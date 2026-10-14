"""Exercise popup lifetimes, repeated actions, reconnects and language data."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import numpy as np
from PyQt6.QtCore import QPoint,Qt,QCoreApplication,QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from gopro_monitor.presentation.main_window import MainWindow
from gopro_monitor.shared.i18n import set_language

APP=QApplication.instance() or QApplication([])

class UiWorkflowTests(unittest.TestCase):
    def window(self,demo=True):
        folder=tempfile.TemporaryDirectory()
        window=MainWindow(demo=demo,settings_path=Path(folder.name)/'settings.json')
        window.render_timer.stop()
        window.show()
        QTest.qWait(30)
        def cleanup():
            for combo in (window.language_combo,window.device_combo):combo.hidePopup()
            window.stream_thread=None
            window.connection_worker=None
            window._workers=[]
            window.close()
            for _ in range(100):
                if not window.gopro.isRunning():break
                QTest.qWait(20)
            window.close()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            folder.cleanup()
            set_language('en')
        self.addCleanup(cleanup)
        return window

    def fullscreen(self,window):
        window.toggle_fullscreen()
        QTest.qWait(30)
        window.update_edge_panels(QPoint(1,300))

    def test_language_popup_survives_pointer_leaving_panel_and_selects_turkish(self):
        window=self.window()
        self.fullscreen(window)
        window.language_combo.showPopup()
        QTest.qWait(30)
        self.assertIsNotNone(APP.activePopupWidget())
        window.update_edge_panels(QPoint(window.width()//2,window.height()//2))
        QTest.qWait(300)
        self.assertTrue(window.left_panel.isVisible())
        self.assertIsNotNone(APP.activePopupWidget())
        view=window.language_combo.view()
        index=window.language_combo.model().index(1,0)
        QTest.mouseMove(view.viewport(),view.visualRect(index).center())
        QTest.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,pos=view.visualRect(index).center())
        self.assertEqual(window.language_combo.currentData(),'tr')
        self.assertEqual(window.connect_button.text(),'Tek tuşla bağlan')
        QTest.mouseMove(window.video_label,QPoint(window.width()//2,window.height()//2))
        window.update_edge_panels(QPoint(window.width()//2,window.height()//2))
        QTest.qWait(300)
        self.assertFalse(window.left_panel.isVisible())

    def test_device_popup_is_protected_and_escape_closes_only_popup(self):
        window=self.window()
        self.fullscreen(window)
        window.setup_toggle.setChecked(True)
        window.device_combo.addItem('GoPro Test','02:00:00:00:00:01')
        window.device_combo.showPopup()
        QTest.qWait(30)
        window.hide_edge_panels()
        self.assertTrue(window.left_panel.isVisible())
        window.escape()
        self.assertIsNone(APP.activePopupWidget())
        self.assertTrue(window._focus_mode)

    def test_clicked_drawer_stays_available_until_clicking_background(self):
        window=self.window()
        self.fullscreen(window)
        window.hide_edge_panels()
        window.toggle_connection_panel()
        window.update_edge_panels(QPoint(window.width()-250,30))
        window.hide_edge_panels()
        self.assertTrue(window.left_panel.isVisible())
        QTest.mouseClick(window.video_label,Qt.MouseButton.LeftButton,pos=QPoint(window.width()//2,window.height()//2))
        self.assertFalse(window.left_panel.isVisible())

    def test_network_identity_is_not_translated_with_interface(self):
        window=self.window()
        window.on_connection_profile_ready({'ssid':'GoPro Ready Tam ekran'})
        window.language_combo.setCurrentIndex(window.language_combo.findData('tr'))
        self.assertIn('GoPro Ready Tam ekran',window.ssid_label.text())
        window.language_combo.setCurrentIndex(window.language_combo.findData('en'))
        self.assertIn('GoPro Ready Tam ekran',window.ssid_label.text())

    def test_manual_discovery_saves_original_bluetooth_name_for_reconnect(self):
        window=self.window(demo=False)
        window.device_combo.clear()
        window.on_devices([('GoPro Test Camera','02:00:00:00:00:01')])
        window.save_connection_profile()
        self.assertEqual(window.connection_profile['device_name'],'GoPro Test Camera')
        self.assertEqual(window.connection_profile['device'],'02:00:00:00:00:01')

    def test_repeated_fullscreen_resize_and_display_options_preserve_source_pixels(self):
        window=self.window()
        frame=np.zeros((120,160,3),np.uint8)
        frame[0,0]=(20,80,150)
        window._frame=frame
        for _ in range(10):
            window.toggle_fullscreen()
            QTest.qWait(5)
            window.mirror.setChecked(not window.mirror.isChecked())
            window.fill_toggle.setChecked(not window.fill_toggle.isChecked())
            window.display_frame()
            self.assertIs(window._frame,frame)
            self.assertEqual(tuple(frame[0,0]),(20,80,150))
            window.escape()
            window.resize(960,720)
            APP.processEvents()
            self.assertFalse(window._focus_mode)
            self.assertTrue(window.gopro.isRunning())

    def test_replacing_and_closing_many_reviews_releases_every_frame(self):
        import weakref
        window=self.window()
        for _ in range(15):
            capture={'kind':'photo','width':160,'height':120,'frame':np.zeros((120,160,3),np.uint8)}
            reference=weakref.ref(capture['frame'])
            window.on_quality_ready(capture)
            self.assertIsNone(reference())
            self.assertEqual(len(window._reviews),1)
            review=window._reviews[0]
            review.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,False)
            review.view.actual_size()
            for factor in (200,.00001,1.2):
                review.view.zoom(factor)
                self.assertGreaterEqual(review.view.transform().m11(),.05)
                self.assertLessEqual(review.view.transform().m11(),8)
            review.close()
            self.assertEqual(review.view.scene.items(),[])
            self.assertEqual(review.capture,{})
            self.assertEqual(window._reviews,[])
            review.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_retry_uses_existing_bluetooth_maintenance_instead_of_ignoring_click(self):
        window=self.window(demo=False)
        window.connection_worker=Mock()
        window.connection_worker.isRunning.return_value=True
        window.connection_worker.maintaining_ble=True
        window.gopro.connect_camera=Mock()
        window.quick_connect()
        window.gopro.connect_camera.assert_called_once()
        self.assertIn('connect',window._pending)

    def test_advanced_connect_cannot_interrupt_capture(self):
        window=self.window(demo=False)
        window._pending.add('capture')
        window.gopro.connect_camera=Mock()
        window.connect_camera()
        window.gopro.connect_camera.assert_not_called()

    def test_repeated_record_and_start_commands_are_not_queued(self):
        window=self.window(demo=False)
        window._connected=True
        window._recording=False
        window.gopro.set_recording=Mock()
        window.toggle_recording()
        window.toggle_recording()
        window.gopro.set_recording.assert_called_once_with(True)
        window._pending.clear()
        window.gopro.start_stream=Mock()
        window.start_stream()
        window.start_stream()
        window.gopro.start_stream.assert_called_once()

    def test_many_language_switches_preserve_frame_and_recording_timer(self):
        window=self.window(demo=False)
        window._connected=True
        window.on_camera_state({'10':1,'13':75,'33':0,'70':80})
        window._frame=np.zeros((12,16,3),np.uint8)
        frame=window._frame
        for _ in range(15):
            for code in ('tr','en'):
                window.language_combo.setCurrentIndex(window.language_combo.findData(code))
                self.assertIs(window._frame,frame)
                self.assertIn('01:15',window.record_badge.text())
                self.assertTrue(window._recording)
        self.assertEqual(window.record_badge.text(),'● SD RECORDING: 01:15')

if __name__=='__main__':unittest.main()
