"""GoPro BLE setup using the documented TLV protocol, without a model-specific SDK."""
from gopro_monitor.shared.i18n import tr
import asyncio
import sys
from PyQt6.QtCore import QThread, pyqtSignal

SERVICE = '0000fea6-0000-1000-8000-00805f9b34fb'
class BLECommandError(RuntimeError):
    def __init__(self, command, status):
        self.command, self.status = command, status
        super().__init__(tr('Bluetooth komutu reddedildi: 0x{0:02x}, kod {1}').format(command, status))

def uuid(suffix):
    return f'b5f9{suffix}-aa8d-11e3-9046-0002a5d5c51b'

class PacketAssembler:
    def __init__(self):
        self.buffer = bytearray()
        self.expected = 0
        self.counter = 0

    def feed(self, packet):
        if not packet:
            return None
        header = packet[0]
        if header & 0x80:
            if not self.expected or (header & 15) != self.counter:
                self.expected = 0
                return None
            self.counter = (self.counter + 1) % 16
            self.buffer.extend(packet[1:])
        else:
            kind = (header >> 5) & 3
            offset = (1, 2, 3, 0)[kind]
            if not offset or len(packet) < offset:
                return None
            self.expected = ((header & 31) << 8 | packet[1]) if kind == 1 else (int.from_bytes(packet[1:3], 'big') if kind == 2 else header & 31)
            self.buffer = bytearray(packet[offset:])
            self.counter = 0
        if self.expected and len(self.buffer) >= self.expected:
            message = bytes(self.buffer[:self.expected])
            self.expected = 0
            return message
        return None

class BLESession:
    def __init__(self, client):
        self.client = client
        self.pending = {}
        self.assemblers = {}

    async def subscribe(self):
        for service in self.client.services:
            for characteristic in service.characteristics:
                if 'notify' in characteristic.properties:
                    key = characteristic.uuid.lower()
                    self.assemblers[key] = PacketAssembler()
                    def callback(sender, packet, key=key):
                        message = self.assemblers[key].feed(packet)
                        if message and len(message) >= 2:
                            future = self.pending.get((key, message[0]))
                            if future and not future.done():
                                future.set_result(message)
                    await self.client.start_notify(characteristic, callback)

    async def exchange(self, channel, payload, timeout=5):
        write_uuid = uuid(channel)
        response_uuid = uuid(f'{int(channel, 16) + 1:04x}')
        key = (response_uuid, payload[0])
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            # Extended 13-bit headers are recommended even for short requests.
            framed = bytes([0x20 | (len(payload) >> 8), len(payload) & 255]) + payload
            await self.client.write_gatt_char(write_uuid, framed, response=True)
            message = await asyncio.wait_for(future, timeout)
            if message[1] != 0:
                raise BLECommandError(payload[0], message[1])
            return message
        finally:
            self.pending.pop(key, None)

    async def prepare(self):
        await self.subscribe()
        for attempt in range(8):
            try:
                await self.exchange('0072', bytes([0x3c]))
                break
            except (TimeoutError, RuntimeError):
                if attempt == 7:
                    raise RuntimeError(tr('Kamera Bluetooth kontrolü hazır değil.'))
                await asyncio.sleep(1)
        await self.exchange('0072', bytes([0x17, 1, 1]))
        for _ in range(15):
            result = await self.exchange('0076', bytes([0x13, 69]))
            if len(result) >= 5 and result[2] == 69 and int.from_bytes(result[4:4+result[3]], 'big') == 1:
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError(tr('Kamera Wi-Fi ağı zamanında hazır olmadı.'))
        ssid = bytes(await self.client.read_gatt_char(uuid('0002'))).decode('utf-8').rstrip('\x00')
        password = bytes(await self.client.read_gatt_char(uuid('0003'))).decode('utf-8').rstrip('\x00')
        return ssid, password

    async def keep_alive(self):
        # Documented SDK heartbeat: LED setting 91, special value 66.
        await self.exchange('0074', bytes([91, 1, 66]))

class BluetoothWorker(QThread):
    status = pyqtSignal(str)
    devices_found = pyqtSignal(list)
    wifi_ready = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, device=None, parent=None):
        super().__init__(parent)
        self.device = device
        self._loop = self._task = None

    def stop(self):
        self.requestInterruption()
        loop, task = self._loop, self._task
        if loop and task and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def run(self):
        try:
            asyncio.run(self._run())
        except asyncio.CancelledError:
            pass
        except Exception:
            self.error.emit(tr('Kamera Bluetooth kontrolü hazır değil.'))
        finally:
            self._loop = self._task = None

    async def _run(self):
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        if self.isInterruptionRequested():
            return
        from bleak import BleakClient, BleakScanner
        if sys.platform == 'win32':
            from bleak.backends.winrt.util import uninitialize_sta
            uninitialize_sta()
        if self.device is None:
            self.status.emit(tr('GoPro Bluetooth cihazları aranıyor…'))
            items = await BleakScanner.discover(timeout=8, return_adv=True)
            found = [(d.name or a.local_name or 'GoPro', d.address) for d,a in items.values() if SERVICE in a.service_uuids or 'gopro' in (d.name or a.local_name or '').lower()]
            self.devices_found.emit(found)
            return
        self.status.emit(tr('GoPro Bluetooth bağlantısı kuruluyor…'))
        async with BleakClient(self.device, timeout=25) as client:
            if sys.platform == 'win32':
                await client.pair()
            session = BLESession(client)
            ssid, password = await session.prepare()
            if self.isInterruptionRequested():
                return
            self.wifi_ready.emit(ssid, password)
            self.status.emit(tr('Kamera Wi-Fi ağı hazır. Windows’u bu ağa bağlayın.'))
            while client.is_connected and not self.isInterruptionRequested():
                await session.keep_alive()
                for _ in range(15):
                    if self.isInterruptionRequested():
                        return
                    await asyncio.sleep(0.2)
            if not self.isInterruptionRequested():
                raise RuntimeError(tr('Bluetooth bağlantısı kesildi; Wi-Fi önizlemesinin durumunu kontrol edin.'))
