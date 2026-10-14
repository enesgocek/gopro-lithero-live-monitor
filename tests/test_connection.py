import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch,AsyncMock
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QCoreApplication,QEvent
from connection_store import ConnectionStore
from quick_connection import QuickConnectionWorker
from wifi_connect import ensure_wifi,current_ssid

APP=QApplication.instance() or QApplication([])

class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=ConnectionStore(Path(self.temp.name)/'connection.json')

    def test_remembers_camera_but_never_serializes_password(self):
        profile={'device':'02:00:00:00:00:01','device_name':'GoPro Test','ssid':'GoPro TestCamera','password':'test-secret','port':8556,'auto_connect':True}
        self.store.save(profile)
        restored=self.store.load()
        self.assertEqual(restored['device'],profile['device'])
        self.assertEqual(restored['ssid'],profile['ssid'])
        self.assertEqual(restored['port'],8556)
        self.assertNotIn('password',restored)
        self.assertNotIn('test-secret',self.store.path.read_text(encoding='utf8'))

    def test_forget_clears_camera_identity_and_startup_autoconnect(self):
        self.store.save({'remember':False,'device':'02:00:00:00:00:01','ssid':'GoPro TestCamera','auto_connect':True})
        profile=self.store.load()
        self.assertEqual((profile['device'],profile['ssid']),('',''))
        self.assertFalse(profile['auto_connect'])

    def test_corrupt_settings_are_recoverable_and_invalid_endpoint_not_used(self):
        self.store.path.write_text('{broken',encoding='utf8')
        self.assertEqual(self.store.load()['port'],8554)
        self.store.save({'address':'https://outside.example','port':80,'device':'not an address'})
        profile=self.store.load()
        self.assertEqual(profile['device'],'')
        self.assertEqual(profile['port'],8554)
        self.assertIn('10.5.5.9',profile['address'])

class SavedWifiTests(unittest.TestCase):
    def test_existing_windows_profile_does_not_need_password_or_xml(self):
        with patch('wifi_connect.current_ssid',return_value=''),patch('wifi_connect.netsh',return_value=subprocess.CompletedProcess([],0)),patch('wifi_connect.install_profile') as temp:
            ensure_wifi('GoPro TestCamera')
            temp.assert_not_called()
            from wifi_connect import netsh
            self.assertEqual(netsh.call_args.args,('connect','name=GoPro TestCamera','ssid=GoPro TestCamera'))

    def test_current_camera_network_is_preserved_without_reconnect(self):
        with patch('wifi_connect.current_ssid',return_value='GoPro TestCamera'),patch('wifi_connect.netsh') as commands:
            ensure_wifi('GoPro TestCamera')
            commands.assert_not_called()

    def test_current_ssid_parser_does_not_confuse_bssid(self):
        output=b' BSSID : aa:bb:cc:dd:ee:ff\r\n SSID : GoPro TestCamera\r\n Signal : 99%'
        with patch('wifi_connect.netsh',return_value=subprocess.CompletedProcess([],0,stdout=output)):
            self.assertEqual(current_ssid(),'GoPro TestCamera')

    def test_missing_profile_requires_ble_secret_without_empty_profile_write(self):
        with patch('wifi_connect.current_ssid',return_value=''),patch('wifi_connect.netsh',return_value=subprocess.CompletedProcess([],1)),patch('wifi_connect.install_profile') as temp:
            with self.assertRaisesRegex(RuntimeError,'Bluetooth'):ensure_wifi('GoPro TestCamera')
            temp.assert_not_called()

class DiscoveryTests(unittest.TestCase):
    def test_remembered_bluetooth_device_skips_full_scan(self):
        profile={'address':'10.5.5.9','device':'02:00:00:00:00:01','device_name':'GoPro Test','ssid':'GoPro TestCamera'}
        worker=QuickConnectionWorker(profile,force_ble=True)
        stopped=[False]
        worker.isInterruptionRequested=lambda:stopped[0]
        worker.ready.connect(lambda result:stopped.__setitem__(0,True))
        worker.wait_http=AsyncMock(return_value={'address':'10.5.5.9','transport':'Wi-Fi'})
        client=Mock()
        client.pair=AsyncMock()
        client.is_connected=True
        context=Mock()
        context.__aenter__=AsyncMock(return_value=client)
        context.__aexit__=AsyncMock(return_value=False)
        session=Mock()
        session.prepare=AsyncMock(return_value=('GoPro TestCamera','unit-test-secret'))
        session.keep_alive=AsyncMock()
        with patch('bleak.BleakClient',return_value=context) as connect,patch('bleak.BleakScanner.discover') as scan,patch('ble_setup.BLESession',return_value=session),patch('bleak.backends.winrt.util.uninitialize_sta'),patch('quick_connection.ensure_wifi'):
            asyncio.run(worker._run())
        scan.assert_not_called()
        connect.assert_called_once_with(profile['device'],timeout=20)

    def test_ready_wifi_avoids_bluetooth_scan_and_preserves_saved_profile(self):
        worker=QuickConnectionWorker({'address':'10.5.5.9','device':'02:00:00:00:00:01','ssid':'GoPro TestCamera'})
        worker.probe=Mock(return_value={'address':'10.5.5.9','transport':'Wi-Fi'})
        profiles=[]
        worker.profile_ready.connect(profiles.append)
        with patch('quick_connection.current_ssid',return_value='GoPro TestCamera'),patch('bleak.BleakScanner.discover') as scan:
            asyncio.run(worker._run())
        scan.assert_not_called()
        self.assertEqual(profiles[0]['device'],'02:00:00:00:00:01')

class ConnectionUiTests(unittest.TestCase):
    def test_short_lived_discovery_worker_still_starts_preview_after_connect(self):
        from main import MainWindow
        temp=tempfile.TemporaryDirectory()
        window=MainWindow(demo=True,settings_path=Path(temp.name)/'settings.json')
        window.demo=False
        window._quick_connecting=True
        window.gopro.connect_camera=Mock()
        try:
            window.on_quick_connection_ready({'address':'10.5.5.9','transport':'Wi-Fi'})
            # Fast discovery may finish before the controller validates HTTP.
            window._quick_connecting=False
            window.on_connected(True)
            self.assertTrue(window._return_to_live)
            window.gopro.connect_camera.assert_called_once()
        finally:
            window.close()
            for _ in range(100):
                if not window.gopro.isRunning():break
                QTest.qWait(20)
            window.close()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            temp.cleanup()

if __name__=='__main__':unittest.main()
