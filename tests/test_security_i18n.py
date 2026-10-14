"""Regression coverage for privacy boundaries and runtime language switching."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from PyQt6.QtCore import QCoreApplication,QEvent,Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QLabel
from camera_api import CameraAPI,CameraError,NoCameraRedirects,validate_address
from connection_store import ConnectionStore
from i18n import language,set_language,tr
from monitor_ui import VideoCanvas
from privacy import redact
from wifi_connect import ensure_wifi

APP=QApplication.instance() or QApplication([])

class SecurityTests(unittest.TestCase):
    def test_camera_address_rejects_public_loopback_and_metadata_networks(self):
        for address in ('8.8.8.8','127.0.0.1','169.254.169.254','0.0.0.0','[::1]','[2001:db8::1]'):
            with self.subTest(address=address),self.assertRaises(CameraError):validate_address(address)

    def test_redirects_cannot_leave_the_camera(self):
        with self.assertRaises(CameraError):NoCameraRedirects().redirect_request(None,None,302,'',{},'https://example.com')

    def test_oversized_json_is_rejected_before_parsing(self):
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.read.return_value=b' '* (1024*1024+1)
        api=CameraAPI()
        api.opener.open=Mock(return_value=response)
        with self.assertRaises(CameraError):api.info()

    def test_other_camera_models_are_rejected(self):
        api=CameraAPI()
        api.get=Mock(return_value={'model_name':'HERO13 Black'})
        with self.assertRaises(CameraError):api.info()

    def test_profile_setup_uses_memory_api_without_plaintext_file(self):
        with patch('wifi_connect.current_ssid',return_value=''),patch('wifi_connect.netsh',side_effect=[subprocess.CompletedProcess([],1),subprocess.CompletedProcess([],0)]),patch('wifi_connect.install_profile') as native,patch('builtins.open') as disk:
            ensure_wifi('GoPro TestCamera','synthetic-passphrase')
            native.assert_called_once_with('GoPro TestCamera','synthetic-passphrase')
            disk.assert_not_called()

    def test_logs_redact_device_and_supplied_credentials(self):
        message='02:00:00:00:00:01 synthetic-passphrase private-ssid'
        result=redact(message,('synthetic-passphrase','private-ssid'))
        for sensitive in message.split():self.assertNotIn(sensitive,result)

class LanguageTests(unittest.TestCase):
    def setUp(self):
        set_language('en')
        self.addCleanup(lambda:set_language('en'))

    def test_first_launch_is_english_and_language_is_validated(self):
        self.assertEqual(ConnectionStore.validated({})['language'],'en')
        self.assertEqual(ConnectionStore.validated({'language':'unknown'})['language'],'en')
        self.assertEqual(tr('Tek tuşla bağlan'),'Connect camera')

    def test_language_switch_preserves_camera_and_current_frame(self):
        from main import MainWindow
        with tempfile.TemporaryDirectory() as folder:
            window=MainWindow(demo=False,settings_path=Path(folder)/'settings.json')
            try:
                window._connected=True
                window._frame=np.zeros((12,16,3),np.uint8)
                pixels=window._frame
                window.gopro.connect_camera=Mock()
                self.assertEqual(window.connect_button.text(),'Connect camera')
                window.language_combo.setCurrentIndex(window.language_combo.findData('tr'))
                self.assertEqual(window.connect_button.text(),'Tek tuşla bağlan')
                self.assertIs(window._frame,pixels)
                self.assertTrue(window._connected)
                self.assertEqual(json.loads(window.connection_store.path.read_text())['language'],'tr')
                window.language_combo.setCurrentIndex(window.language_combo.findData('en'))
                self.assertEqual(window.connect_button.text(),'Connect camera')
                window.gopro.connect_camera.assert_not_called()
                for label in window.findChildren(QLabel):self.assertEqual(label.textFormat(),Qt.TextFormat.PlainText)
            finally:
                window.close()
                for _ in range(100):
                    if not window.gopro.isRunning():break
                    QTest.qWait(20)
                window.close()
                QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_canvas_bgr_path_preserves_colors_and_owns_pixels(self):
        pixels=np.full((12,16,3),(20,80,150),np.uint8)
        canvas=VideoCanvas()
        canvas.set_frame(pixels)
        pixels[:]=0
        self.assertEqual(canvas.image.pixelColor(0,0).getRgb()[:3],(150,80,20))

if __name__=='__main__':unittest.main()
