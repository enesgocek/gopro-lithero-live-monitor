import asyncio
import json
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error
import numpy as np
from PyQt6.QtWidgets import QApplication
from camera_api import CameraAPI, CameraError, validate_address
from gopro_controller import GoProController
from ble_setup import PacketAssembler, BLESession, BLECommandError
from video_stream import VideoStreamThread
from wifi_connect import profile_xml

APP = QApplication.instance() or QApplication([])

class Response:
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, *args):
        return self.data

class APITests(unittest.TestCase):
    def api(self, data):
        api = CameraAPI()
        api.opener.open = Mock(return_value=Response(data))
        return api

    def test_camera_json_error_is_failure(self):
        with self.assertRaises(CameraError):
            self.api(b'{"error": 2}').preview(True)

    def test_invalid_state_cannot_mark_camera_connected(self):
        for data in [b'{}', b'{"status": []}', b'<html>login</html>', b'[]']:
            with self.subTest(data=data), self.assertRaises(CameraError):
                self.api(data).state()

    def test_http_rejection_is_actionable(self):
        api = self.api(b'{}')
        api.opener.open.side_effect = urllib.error.HTTPError('url', 404, 'missing', {}, None)
        with self.assertRaisesRegex(CameraError, 'HTTP 404'):
            api.preview(True)

    def test_preview_request_uses_selected_port(self):
        api = self.api(b'{}')
        api.preview(True, 8560)
        self.assertEqual(api.opener.open.call_args.args[0], 'http://10.5.5.9/gopro/camera/stream/start?port=8560')

    def test_invalid_camera_address_is_rejected(self):
        for address in ['example.org','http://10.5.5.9/path','https://10.5.5.9','10.5.5.9:bad','http://user:pass@10.5.5.9']:
            with self.subTest(address=address), self.assertRaises(CameraError):
                validate_address(address)

class FakeAPI:
    def __init__(self, address=''):
        self.status = {'10':0, '55':1, '96':1000, '33':0}
        self.calls = []
        self.fail_preview = False
    def info(self):
        return {'model_name':'LIT HERO','firmware_version':'H25.03.02.10.00'}
    def state(self):
        return dict(self.status)
    def get(self, path):
        self.calls.append(path)
        return {}
    def preview(self, enabled, port=8554):
        self.calls.append(('preview',enabled,port))
        if self.fail_preview:
            raise CameraError('preview rejected')
    def shutter(self, enabled):
        self.calls.append(('shutter', enabled))
        self.status['10'] = int(enabled)

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = GoProController(api_factory=FakeAPI)
        self.controller.decoder_requested.connect(lambda url:self.controller.decoder_ready())
        self.controller._perform('connect', ('10.5.5.9',8554))
        self.urls = []
        self.controller.stream_url_ready.connect(self.urls.append)

    def test_failed_stream_never_emits_ready(self):
        self.controller.api.fail_preview = True
        with self.assertRaises(CameraError):
            self.controller._perform('start',None)
        self.assertEqual(self.urls, [])
        self.assertFalse(self.controller._preview)

    def test_preview_preserves_existing_recording(self):
        self.controller.api.status['10'] = 1
        self.controller._perform('start',None)
        self.controller._perform('stop',None)
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='shutter' for c in self.controller.api.calls))
        self.assertEqual(self.controller.api.status['10'],1)

    def test_photo_mode_cannot_accidentally_take_photo(self):
        self.controller.api.status['96'] = 1001
        with self.assertRaisesRegex(CameraError, 'Video'):
            self.controller._perform('record',True)
        self.assertNotIn(('shutter',True),self.controller.api.calls)

    def test_lit_photo_preset_in_video_group_cannot_start_recording(self):
        self.controller.api.status.update({'96':1000,'97':65536})
        self.controller.api.get=Mock(return_value={'presetGroupArray':[{'presetArray':[{'id':65536,'mode':'FLAT_MODE_PHOTO_SINGLE'}]}]})
        with self.assertRaisesRegex(CameraError,'Video'):
            self.controller._perform('record',True)
        self.assertNotIn(('shutter',True),self.controller.api.calls)

    def test_sd_error_prevents_start(self):
        self.controller.api.status['33'] = 2
        with self.assertRaisesRegex(CameraError,'SD card'):
            self.controller._perform('record',True)

    def test_shutdown_never_stops_recording(self):
        self.controller.api.status['10'] = 1
        self.controller._preview = True
        self.controller.start()
        self.controller.shutdown()
        self.assertTrue(self.controller.wait(2000))
        self.assertEqual(self.controller.api.status['10'],1)
        self.assertNotIn(('shutter',False),self.controller.api.calls)

    def test_connection_failure_can_be_retried(self):
        events = []
        self.controller.command_finished.connect(lambda command,ok:events.append((command,ok)))
        self.controller._api_factory = Mock(side_effect=[CameraError('unreachable'), FakeAPI()])
        self.controller.start()
        self.controller.connect_camera('10.5.5.9',8554)
        self.controller.connect_camera('10.5.5.9',8554)
        deadline = time.monotonic() + 2
        while len(events)<2 and time.monotonic()<deadline:
            APP.processEvents()
            time.sleep(.01)
        self.controller.shutdown()
        self.assertTrue(self.controller.wait(2000))
        self.assertEqual(events,[('connect',False),('connect',True)])

class BluetoothTests(unittest.TestCase):
    def test_fragmented_hardware_info(self):
        parser = PacketAssembler()
        payload = bytes([0x3c,0]) + bytes(range(50))
        self.assertIsNone(parser.feed(bytes([0x20,len(payload)])+payload[:18]))
        self.assertIsNone(parser.feed(bytes([0x80])+payload[18:37]))
        self.assertEqual(parser.feed(bytes([0x81])+payload[37:]), payload)

    def test_bad_continuation_does_not_create_false_success(self):
        parser = PacketAssembler()
        parser.feed(bytes([0x20,30])+b'a'*18)
        self.assertIsNone(parser.feed(bytes([0x81])+b'b'*12))

    def test_lit_hero_optional_analytics_rejection_is_tolerated(self):
        class Session(BLESession):
            async def subscribe(self):
                pass
            async def exchange(self,channel,payload,timeout=5):
                if payload[0]==0x50:
                    raise BLECommandError(0x50,2)
                if payload[0]==0x13:
                    return bytes([0x13,0,69,1,1])
                return bytes([payload[0],0])
        client = Mock()
        async def read(key):
            return b'GoPro Test' if '0002-' in key else b'password'
        client.read_gatt_char = read
        self.assertEqual(asyncio.run(Session(client).prepare()), ('GoPro Test','password'))

    def test_wifi_xml_escapes_camera_credentials(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(profile_xml('GoPro & Test', '<abc&123>'))
        self.assertEqual(next(e.text for e in root.iter() if e.tag.endswith('keyMaterial')), '<abc&123>')

class VideoTests(unittest.TestCase):
    def test_stop_restart_and_mailbox_release(self):
        containers = []
        readers=[]
        class Reader:
            def __init__(self,*args):
                self.closed=False
                readers.append(self)
            def close(self):self.closed=True
        class Frame:
            width,height=16,12
            def to_ndarray(self,**kwargs):return np.ones((12,16,3),dtype=np.uint8)
        class Packet:
            def decode(self):return [Frame()]
        class Container:
            def __init__(self):
                self.released = False
                self.streams=Mock()
                self.streams.video=[Mock()]
                containers.append(self)
            def demux(self,*args):
                while True:
                    time.sleep(.01)
                    yield Packet()
            def close(self):
                self.released = True
        with patch('video_stream.UDPReader',Reader),patch('video_stream.av.open',side_effect=lambda *a,**kw:Container()):
            for _ in range(2):
                worker = VideoStreamThread('udp://0.0.0.0:8554')
                worker.start()
                frame=None
                deadline=time.monotonic()+2
                try:
                    while frame is None and time.monotonic()<deadline:
                        frame=worker.take_frame()
                        time.sleep(.01)
                finally:
                    worker.stop()
                    self.assertTrue(worker.wait(1000))
                self.assertIsNotNone(frame)
                self.assertEqual(frame.shape,(12,16,3))
        self.assertTrue(all(c.released for c in containers))
        self.assertTrue(all(r.closed for r in readers))

    def test_failed_open_releases_decoder(self):
        source=Mock()
        worker = VideoStreamThread('udp://0.0.0.0:8554')
        with patch('video_stream.UDPReader',return_value=source),patch('video_stream.av.open',side_effect=ValueError('broken header')):
            worker.run()
        source.close.assert_called_once()
        self.assertIsNone(worker.take_frame())

    def test_udp_reads_preserve_datagram_bytes_and_cancel(self):
        import socket
        from video_stream import UDPReader
        cancelled=False
        reader=UDPReader(0,lambda:cancelled,camera_host='127.0.0.1')
        sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            sender.sendto(b'abcdef',('127.0.0.1',reader.socket.getsockname()[1]))
            self.assertEqual(reader.read(2),b'ab')
            self.assertEqual(reader.read(5),b'cdef')
            cancelled=True
            self.assertEqual(reader.read(5),b'')
        finally:
            reader.close()
            sender.close()

class LifecycleTests(unittest.TestCase):
    def test_bluetooth_cancel_before_start_returns_without_scan(self):
        from ble_setup import BluetoothWorker
        worker = BluetoothWorker()
        worker.requestInterruption()
        # QThread resets interruption at start; stop inside an active worker is
        # separately exercised by the GUI hardware test. This covers cancellation.
        async def cancelled():
            worker.isInterruptionRequested = lambda: True
            await worker._run()
        asyncio.run(cancelled())

    def test_finished_decoder_does_not_accumulate_frame_workers(self):
        from main import MainWindow
        window = MainWindow()
        worker = VideoStreamThread('udp://0.0.0.0:8554',window)
        window.stream_thread = worker
        window._workers.append(worker)
        window.worker_finished(worker)
        self.assertIsNone(window.stream_thread)
        self.assertEqual(window._workers,[])
        window.close()
        deadline = time.monotonic()+3
        while window.gopro.isRunning() and time.monotonic()<deadline:
            APP.processEvents()
            time.sleep(.01)
        APP.processEvents()
        self.assertFalse(window.gopro.isRunning())
        window.finish_close()
        APP.processEvents()

    def test_fullscreen_panels_follow_edges_and_preserve_session(self):
        from main import MainWindow
        from PyQt6.QtCore import QPoint
        window=MainWindow(demo=True)
        window.show()
        APP.processEvents()
        window.toggle_fullscreen()
        APP.processEvents()
        self.assertTrue(window._focus_mode)
        self.assertFalse(window.top_bar.isVisible())
        self.assertFalse(window.left_panel.isVisible())
        self.assertFalse(window.right_panel.isVisible())
        window.update_edge_panels(QPoint(1,250))
        self.assertTrue(window.left_panel.isVisible())
        window.update_edge_panels(QPoint(150,250))
        self.assertTrue(window.left_panel.isVisible())
        window.update_edge_panels(QPoint(window.surface.width()//2,1))
        self.assertTrue(window.top_bar.isVisible())
        window.update_edge_panels(QPoint(window.surface.width()-1,250))
        self.assertTrue(window.right_panel.isVisible())
        window.update_edge_panels(QPoint(window.surface.width()//2,window.surface.height()//2))
        window.hide_edge_panels()
        self.assertFalse(window.right_panel.isVisible())
        window.escape()
        APP.processEvents()
        self.assertFalse(window._focus_mode)
        self.assertTrue(window.gopro.isRunning())
        window.close()
        deadline=time.monotonic()+3
        while window.gopro.isRunning() and time.monotonic()<deadline:
            APP.processEvents()
            time.sleep(.01)
        APP.processEvents()
        self.assertFalse(window.gopro.isRunning())
        window.finish_close()
        APP.processEvents()

def tearDownModule():
    from PyQt6.QtCore import QEvent
    APP.closeAllWindows()
    for widget in APP.topLevelWidgets():widget.deleteLater()
    APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    APP.processEvents()

if __name__ == '__main__':
    unittest.main()
