import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import urllib.error
import av
import cv2
import numpy as np
from PyQt6.QtCore import Qt,QCoreApplication,QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from camera_api import CameraAPI,CameraError
from quality_capture import QualityCapture
from quality_review import QualityReview

APP=QApplication.instance() or QApplication([])

class FakeCamera:
    def __init__(self,fixture,photo=False):
        self.fixture=fixture
        self.photo=photo
        self.recording=False
        self.preset=5
        self.fresh=False
        self.calls=[]
        self.fail_download=False
    def state(self):
        return {'10':int(self.recording),'8':0,'33':0,'96':1001 if self.preset==65536 else 1000,'97':self.preset,'60':500}
    def media(self):
        before={('100GOPRO','GOPR0001.JPG'):{'n':'GOPR0001.JPG'}}
        if self.fresh:before[('100GOPRO','GOPR0002.JPG' if self.photo else 'GX010002.MP4')]={}
        return before
    def get(self,path,**params):
        self.calls.append((path,params))
        if path.endswith('presets/get'):
            return {'presetGroupArray':[{'presetArray':[{'id':65536,'mode':'FLAT_MODE_PHOTO_SINGLE'}]}]}
        if path.endswith('presets/load'):self.preset=params['id']
        return {}
    def shutter(self,enabled):
        self.calls.append(('shutter',enabled))
        if self.preset==65536:
            self.fresh=True
        else:
            self.recording=enabled
            if not enabled:self.fresh=True
    def fetch_media_bytes(self,folder,name,*args):
        if self.fail_download:raise CameraError('download failed')
        return self.fixture.read_bytes()
    def delete_media(self,folder,name):
        self.calls.append(('delete',(folder,name)))
        expected='GOPR0002.JPG' if self.photo else 'GX010002.MP4'
        if (folder,name)!=('100GOPRO',expected):raise AssertionError('Wrong media deletion')
        self.fresh=False

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.jpg=self.root/'source.jpg'
        cv2.imwrite(str(self.jpg),np.full((300,400,3),170,np.uint8))
        self.camera=FakeCamera(self.jpg)
        self.capture=QualityCapture(self.camera)
        self.capture.pause=Mock()

    def test_existing_recording_is_never_stopped(self):
        self.camera.recording=True
        with self.assertRaisesRegex(CameraError,'Recording is active'):
            self.capture.capture('video')
        self.assertEqual(self.camera.calls,[])
        self.assertTrue(self.camera.recording)

    def test_ambiguous_new_media_is_not_mistaken_for_requested_clip(self):
        self.capture.api.media=Mock(return_value={('100GOPRO','GX010002.MP4'):{},('100GOPRO','GX010003.MP4'):{}})
        with self.assertRaisesRegex(CameraError,'Multiple new'):
            self.capture.new_media({}, {'.MP4'})

    def video_fixture(self):
        video=self.root/'original.mp4'
        with av.open(str(video),'w') as output:
            stream=output.add_stream('libx264',rate=10)
            stream.width,stream.height=640,360
            stream.pix_fmt='yuv420p'
            for _ in range(12):
                frame=av.VideoFrame.from_ndarray(np.full((360,640,3),120,np.uint8),format='bgr24')
                for packet in stream.encode(frame):output.mux(packet)
            for packet in stream.encode():output.mux(packet)
        return video

    def test_video_frame_is_decoded_from_original_mp4(self):
        video=self.video_fixture()
        self.camera.fixture=video
        self.camera.photo=False
        before=set(self.root.rglob('*'))
        result=self.capture.capture('video')
        self.assertEqual((result['width'],result['height']),(640,360))
        self.assertEqual(result['frame'].shape,(360,640,3))
        self.assertEqual(set(self.root.rglob('*')),before)
        self.assertNotIn('image',result)
        self.assertNotIn('original',result)
        self.assertTrue(result['camera_cleaned'])
        self.assertEqual([c for c in self.camera.calls if c[0]=='delete'],[('delete',('100GOPRO','GX010002.MP4'))])
        self.assertIn(('100GOPRO','GOPR0001.JPG'),self.camera.media())
        self.assertEqual(self.camera.preset,5)
        self.assertFalse(self.camera.recording)

    def test_cleanup_failure_warns_without_losing_memory_frame(self):
        self.camera.fixture=self.video_fixture()
        self.camera.delete_media=Mock(side_effect=CameraError('camera disconnected'))
        result=self.capture.capture('video')
        self.assertEqual(result['frame'].shape,(360,640,3))
        self.assertFalse(result['camera_cleaned'])
        self.assertIn('camera disconnected',result['cleanup_warning'])
        self.assertIn(('100GOPRO','GOPR0001.JPG'),self.camera.media())

    def test_failed_transfer_still_removes_only_new_test_clip(self):
        self.camera.fail_download=True
        with self.assertRaisesRegex(CameraError,'download failed'):
            self.capture.capture('video')
        self.assertEqual([c for c in self.camera.calls if c[0]=='delete'],[('delete',('100GOPRO','GX010002.MP4'))])
        self.assertIn(('100GOPRO','GOPR0001.JPG'),self.camera.media())

    def test_ambiguous_capture_does_not_delete_any_media(self):
        original_media=self.camera.media
        def ambiguous_media():
            files=original_media()
            if self.camera.fresh:files[('100GOPRO','GX010003.MP4')]={}
            return files
        self.camera.media=ambiguous_media
        with self.assertRaisesRegex(CameraError,'Multiple new'):
            self.capture.capture('video')
        self.assertFalse(any(c[0]=='delete' for c in self.camera.calls))

    def test_cancellation_stops_only_owned_test_recording(self):
        def cancel_after_start(seconds):
            raise CameraError('cancelled')
        self.capture.pause=cancel_after_start
        with self.assertRaisesRegex(CameraError,'cancelled'):
            self.capture.capture('video')
        self.assertEqual([c for c in self.camera.calls if c[0]=='shutter'],[('shutter',True),('shutter',False)])
        self.assertFalse(self.camera.recording)

class PhotoCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        fixture=self.root/'original.jpg'
        cv2.imwrite(str(fixture),np.full((300,400,3),150,np.uint8))
        self.camera=FakeCamera(fixture,photo=True)
        self.capture=QualityCapture(self.camera)
        self.capture.pause=Mock()
        self.capture.load_preset=Mock(side_effect=lambda preset,**kwargs:self.camera.get('gopro/camera/presets/load',id=preset))

    def test_photo_uses_native_jpeg_without_video_and_restores_original_preset(self):
        before=set(self.root.rglob('*'))
        result=self.capture.capture('photo')
        self.assertEqual(result['frame'].shape,(300,400,3))
        self.assertEqual(result['kind'],'photo')
        self.assertTrue(result['camera_cleaned'])
        self.assertEqual(self.camera.preset,5)
        self.assertEqual(set(self.root.rglob('*')),before)
        self.assertEqual([call for call in self.camera.calls if call[0]=='shutter'],[('shutter',True)])
        self.assertIn(('delete',('100GOPRO','GOPR0002.JPG')),self.camera.calls)

    def test_photo_media_waits_out_camera_busy_response(self):
        original=self.camera.media
        def media():
            if self.camera.fresh and not getattr(self.camera,'busy_reported',False):
                self.camera.busy_reported=True
                raise CameraError('busy',http_status=503)
            return original()
        self.camera.media=media
        self.assertTrue(self.capture.capture('photo')['camera_cleaned'])
        self.capture.pause.assert_any_call(.2)

    def test_failed_photo_transfer_cleans_new_jpeg_and_restores_video(self):
        self.camera.fail_download=True
        with self.assertRaisesRegex(CameraError,'download failed'):self.capture.capture('photo')
        self.assertEqual(self.camera.preset,5)
        self.assertIn(('delete',('100GOPRO','GOPR0002.JPG')),self.camera.calls)
        self.assertFalse(any(call==('shutter',False) for call in self.camera.calls))

    def test_existing_recording_is_never_switched_or_stopped(self):
        self.camera.recording=True
        with self.assertRaisesRegex(CameraError,'Recording is active'):self.capture.capture('photo')
        self.assertEqual(self.camera.calls,[])

    def test_photo_preset_in_video_group_cannot_start_a_video_test(self):
        self.camera.preset=65536
        state=self.camera.state()
        state['96']=1000
        self.camera.state=Mock(return_value=state)
        with self.assertRaisesRegex(CameraError,'Select Video'):self.capture.capture('video')
        self.assertFalse(any(call[0]=='shutter' for call in self.camera.calls))

    def test_preset_transition_waits_for_stable_ready_state(self):
        import itertools
        capture=QualityCapture(self.camera)
        capture.pause=Mock()
        self.camera.state=Mock(side_effect=[{'97':5,'8':1,'10':0}]+[{'97':65536,'8':0,'10':0}]*10)
        with patch('quality_capture.time.monotonic',side_effect=itertools.count(0,.1)):
            capture.load_preset(65536)
        self.assertGreaterEqual(self.camera.state.call_count,4)
        self.assertEqual(self.camera.preset,65536)

class BinaryResponse(io.BytesIO):
    def __init__(self,data,length=None):
        super().__init__(data)
        self.headers={'Content-Length':str(len(data) if length is None else length)}

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'image.JPG'
        self.api=CameraAPI()
    def test_incomplete_download_is_not_published(self):
        self.api.opener.open=Mock(return_value=BinaryResponse(b'abc',length=20))
        with self.assertRaises(CameraError):self.api.download_media('100GOPRO','GOPR0001.JPG',self.path)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.with_suffix('.JPG.part').exists())
    def test_invalid_camera_filename_cannot_escape_destination(self):
        with self.assertRaises(CameraError):self.api.download_media('100GOPRO','../bad.JPG',self.path)
        self.assertFalse(self.path.exists())
    def test_download_uses_camera_media_port_when_required(self):
        self.api.opener.open=Mock(side_effect=[urllib.error.HTTPError('url',404,'not found',{},None),BinaryResponse(b'abc')])
        self.api.download_media('100GOPRO','GOPR0001.JPG',self.path)
        self.assertEqual(self.path.read_bytes(),b'abc')
        self.assertEqual(self.api.opener.open.call_args.args[0],'http://10.5.5.9:8080/videos/DCIM/100GOPRO/GOPR0001.JPG')
    def test_existing_partial_file_is_not_deleted(self):
        partial=self.path.with_suffix('.JPG.part')
        partial.write_bytes(b'previous download')
        self.api.opener.open=Mock(return_value=BinaryResponse(b'abc'))
        with self.assertRaises(CameraError):self.api.download_media('100GOPRO','GOPR0001.JPG',self.path)
        self.assertEqual(partial.read_bytes(),b'previous download')

    def test_memory_transfer_never_creates_a_local_file(self):
        self.api.opener.open=Mock(return_value=BinaryResponse(b'abc'))
        self.assertEqual(self.api.fetch_media_bytes('100GOPRO','GX010002.MP4'),b'abc')
        self.assertEqual(list(self.path.parent.iterdir()),[])

    def test_memory_transfer_rejects_partial_data(self):
        self.api.opener.open=Mock(return_value=BinaryResponse(b'abc',length=20))
        with self.assertRaises(CameraError):self.api.fetch_media_bytes('100GOPRO','GX010002.MP4')

    def test_delete_uses_exact_file_path_and_rejects_traversal(self):
        response=BinaryResponse(b'{}')
        self.api.opener.open=Mock(return_value=response)
        self.api.delete_media('100GOPRO','GX010002.MP4')
        self.assertEqual(self.api.opener.open.call_args.args[0],'http://10.5.5.9/gopro/media/delete/file?path=100GOPRO/GX010002.MP4')
        with self.assertRaises(CameraError):self.api.delete_media('../100GOPRO','GX010002.MP4')

class ReviewLifetimeTests(unittest.TestCase):
    def window(self):
        from main import MainWindow
        window=MainWindow(demo=True)
        def cleanup():
            window.close()
            deadline=__import__('time').monotonic()+3
            while window.gopro.isRunning() and __import__('time').monotonic()<deadline:QTest.qWait(20)
            window.close()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.addCleanup(cleanup)
        return window

    def review(self):
        capture={'kind':'video','width':320,'height':180,'frame':np.full((180,320,3),(20,80,150),np.uint8),'camera_cleaned':True}
        review=QualityReview(capture)
        review.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,False)
        review.show()
        APP.processEvents()
        def cleanup():
            review.close()
            review.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.addCleanup(cleanup)
        return review

    def test_close_discards_native_pixels_and_metadata(self):
        review=self.review()
        image=review.view.item.pixmap().toImage()
        self.assertEqual((image.width(),image.height()),(320,180))
        self.assertEqual(image.pixelColor(0,0).getRgb()[:3],(150,80,20))
        review.close()
        self.assertEqual(review.view.scene.items(),[])
        self.assertIsNone(review.view.item)
        self.assertEqual(review.capture,{})

    def test_escape_discards_native_pixels(self):
        review=self.review()
        QTest.keyClick(review,Qt.Key.Key_Escape)
        self.assertTrue(review._discarded)
        self.assertEqual(review.view.scene.items(),[])

    def test_main_window_does_not_retain_closed_capture(self):
        import weakref
        from main import MainWindow
        window=MainWindow(demo=True)
        capture={'kind':'video','width':320,'height':180,'frame':np.zeros((180,320,3),np.uint8)}
        frame_ref=weakref.ref(capture['frame'])
        try:
            window.on_quality_ready(capture)
            self.assertNotIn('frame',capture)
            self.assertIsNone(frame_ref())
            window._reviews[0].close()
            self.assertEqual(window._reviews,[])
            self.assertFalse(hasattr(window,'_last_capture'))
        finally:
            window.close()
            deadline=__import__('time').monotonic()+3
            while window.gopro.isRunning() and __import__('time').monotonic()<deadline:
                QTest.qWait(20)
            window.close()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_review_close_waits_for_capture_then_restarts_preview(self):
        window=self.window()
        window.demo=False
        window._connected=True
        window.gopro.start_stream=Mock()
        window._pending.add('capture')
        capture={'kind':'photo','width':320,'height':180,'frame':np.zeros((180,320,3),np.uint8)}
        window.on_quality_ready(capture)
        window._reviews[0].close()
        self.assertTrue(window._return_to_live)
        window.check_return_to_live()
        window.gopro.start_stream.assert_not_called()
        window.on_command_finished('capture',True)
        window.check_return_to_live()
        window.gopro.start_stream.assert_called_once()
        self.assertIn('start',window._pending)
        window.check_return_to_live()
        window.gopro.start_stream.assert_called_once()

    def test_review_close_preserves_an_already_healthy_live_stream(self):
        import time
        window=self.window()
        window.demo=False
        window._connected=True
        window.gopro.start_stream=Mock()
        window.stream_thread=Mock()
        window.stream_thread.isRunning.return_value=True
        window._preview_state='active'
        window._frame=np.zeros((12,16,3),np.uint8)
        window._last_frame_time=time.monotonic()
        window.request_return_to_live()
        window.check_return_to_live()
        window.gopro.start_stream.assert_not_called()
        self.assertFalse(window._return_to_live)
        window.stream_thread=None

if __name__=='__main__':unittest.main()
