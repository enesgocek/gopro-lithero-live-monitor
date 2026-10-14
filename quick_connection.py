"""One-button saved WLAN / BLE setup, without storing application secrets."""
from i18n import tr
import asyncio
import sys
import time
from PyQt6.QtCore import QThread,pyqtSignal
from camera_api import CameraAPI,CameraError
from wifi_connect import ensure_wifi,current_ssid

class QuickConnectionWorker(QThread):
    status=pyqtSignal(str)
    ready=pyqtSignal(dict)
    profile_ready=pyqtSignal(dict)
    error=pyqtSignal(str)

    def __init__(self,profile,parent=None,force_ble=False,api_factory=CameraAPI):
        super().__init__(parent)
        self.profile=dict(profile)
        self.force_ble=force_ble
        self.api_factory=api_factory
        self.maintaining_ble=False
        self._loop=self._task=None

    def stop(self):
        self.requestInterruption()
        if self._loop and self._task and not self._loop.is_closed():
            try:self._loop.call_soon_threadsafe(self._task.cancel)
            except RuntimeError:pass

    def probe(self,address,transport):
        if self.isInterruptionRequested():return None
        try:
            api=self.api_factory(address,timeout=.8)
            info=api.info()
            if not any(name in info['model_name'].upper() for name in ('HERO','MAX','MISSION')):return None
            api.state()
            return {'address':address,'transport':transport}
        except CameraError:return None

    def run(self):
        try:asyncio.run(self._run())
        except asyncio.CancelledError:pass
        except Exception:
            # Avoid reflecting credentials from OS / Bluetooth exceptions.
            self.error.emit(tr('Otomatik bağlantı kurulamadı. Kamerayı açık tutup Quik eşleştirme ekranını açın ve yeniden bağlanın.'))
        finally:
            self._loop=self._task=None
            self.maintaining_ble=False

    async def emit_ready(self,result,ssid=''):
        if self.isInterruptionRequested():return
        if ssid:
            self.profile['ssid']=ssid
            self.profile_ready.emit({key:self.profile.get(key,'') for key in ('device','device_name','ssid')})
        self.ready.emit(result)

    async def wait_http(self,address,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline and not self.isInterruptionRequested():
            result=await asyncio.to_thread(self.probe,address,'Wi-Fi')
            if result:return result
            await asyncio.sleep(.25)
        return None

    async def _run(self):
        self._loop=asyncio.get_running_loop()
        self._task=asyncio.current_task()
        if self.isInterruptionRequested():return
        if not self.force_ble:
            self.status.emit(tr('Hazır kamera Wi-Fi bağlantısı aranıyor…'))
            address=self.profile.get('address','10.5.5.9')
            result=await asyncio.to_thread(self.probe,address,'Wi-Fi')
            if result:
                ssid=await asyncio.to_thread(current_ssid)
                await self.emit_ready(result,ssid if ssid.startswith('GoPro') else '')
                return
            if self.profile.get('ssid'):
                self.status.emit(tr('Kayıtlı Windows kamera ağına bağlanılıyor…'))
                try:
                    await asyncio.to_thread(ensure_wifi,self.profile['ssid'])
                    result=await self.wait_http(address,2)
                    if result:
                        await self.emit_ready(result,self.profile['ssid'])
                        return
                except (RuntimeError,OSError):pass
        if sys.platform=='win32':
            from bleak.backends.winrt.util import uninitialize_sta
            uninitialize_sta()
        from bleak import BleakClient,BleakScanner
        from ble_setup import BLESession,SERVICE
        async def wireless(device,name):
            self.status.emit(tr('Hatırlanan kamera hazırlanıyor…'))
            async with BleakClient(device,timeout=20) as client:
                if sys.platform=='win32':await client.pair()
                session=BLESession(client)
                ssid,password=await session.prepare()
                self.profile.update(device=device,device_name=name,ssid=ssid)
                self.profile_ready.emit({key:self.profile[key] for key in ('device','device_name','ssid')})
                self.status.emit(tr('Kamera ağına otomatik bağlanılıyor…'))
                await asyncio.to_thread(ensure_wifi,ssid,password,False,self.isInterruptionRequested)
                address=self.profile.get('address','10.5.5.9')
                result=await self.wait_http(address,6)
                if result is None:
                    # Camera reset may have changed its password; refresh only
                    # its own WLAN profile using the freshly read BLE secret.
                    await asyncio.to_thread(ensure_wifi,ssid,password,True,self.isInterruptionRequested)
                    result=await self.wait_http(address,10)
                # empty credential default / reference release, not a secret.
                password=''  # nosec B105
                if result is None:raise RuntimeError('Camera network unavailable')
                self.maintaining_ble=True
                await self.emit_ready(result,ssid)
                while client.is_connected and not self.isInterruptionRequested():
                    await session.keep_alive()
                    await asyncio.sleep(3)
                if not self.isInterruptionRequested():raise RuntimeError('BLE connection dropped')
        if self.profile.get('device'):
            try:
                await wireless(self.profile['device'],self.profile.get('device_name','GoPro'))
                return
            except asyncio.CancelledError:raise
            except Exception:
                if self.maintaining_ble or self.isInterruptionRequested():raise
        self.status.emit(tr('İlk bağlantı için GoPro otomatik aranıyor…'))
        devices=await BleakScanner.discover(timeout=8,return_adv=True)
        found=[device for device,adv in devices.values() if SERVICE in adv.service_uuids or 'gopro' in (device.name or adv.local_name or '').lower()]
        matching=[d for d in found if d.name==self.profile.get('device_name')]
        candidates=matching or found
        if len(candidates)!=1:
            self.error.emit(tr('Tek kamera belirlenemedi. Bluetooth / Wi-Fi kurulumu bölümünden kameranızı seçin.'))
            return
        device=candidates[0]
        await wireless(device.address,device.name or 'GoPro')
