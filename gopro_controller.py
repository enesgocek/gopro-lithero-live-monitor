"""All camera requests are serialized in one background worker."""
from i18n import tr
import queue
import time
import threading
from PyQt6.QtCore import QThread, pyqtSignal
from camera_api import CameraAPI, CameraError, preview_url
from quality_capture import QualityCapture

class GoProController(QThread):
    connection_status = pyqtSignal(str)
    connected = pyqtSignal(bool)
    camera_info = pyqtSignal(dict)
    camera_state = pyqtSignal(dict)
    stream_url_ready = pyqtSignal(str)
    decoder_requested = pyqtSignal(str)
    preview_stopped = pyqtSignal()
    command_finished = pyqtSignal(str, bool)
    debug_signal = pyqtSignal(str)
    quality_ready = pyqtSignal(dict)
    resume_preview_requested = pyqtSignal()

    def __init__(self, parent=None, api_factory=CameraAPI):
        super().__init__(parent)
        self._commands = queue.Queue()
        self._api_factory = api_factory
        self.api = None
        self.is_connected = False
        self._preview = False
        self._port = 8554
        self._decoder_ready = threading.Event()

    def decoder_ready(self):
        self._decoder_ready.set()

    def connect_camera(self, address, port):
        self._commands.put(('connect', (address, port)))

    def start_stream(self):
        self._commands.put(('start', None))

    def stop_stream(self):
        self._commands.put(('stop', None))

    def set_recording(self, enabled):
        self._commands.put(('record', enabled))

    def capture_quality(self,kind):
        self._commands.put(('capture',kind))

    def shutdown(self):
        self.requestInterruption()
        self._commands.put(('quit', None))

    def _set_connected(self, value):
        self.is_connected = value
        self.connected.emit(value)

    def _perform(self, command, argument):
        if command == 'connect':
            self._set_connected(False)
            self._preview = False
            self.connection_status.emit(tr('Kamera bağlantısı denetleniyor…'))
            address, self._port = argument
            self.api = self._api_factory(address)
            info = self.api.info()
            state = self.api.state()
            self.camera_info.emit(info)
            self.camera_state.emit(state)
            self._set_connected(True)
            self.connection_status.emit(tr('Kamera bağlı. Önizlemeyi başlatabilirsiniz.'))
            return
        if not self.is_connected:
            raise CameraError(tr('Önce kameraya bağlanın.'))
        if command == 'start':
            state = self.api.state()
            self.camera_state.emit(state)
            if state.get('55') in (0, False):
                raise CameraError(tr('Kamera bu modda önizlemeye izin vermiyor. Video modunu seçin.'))
            if self._preview:
                self.api.preview(False)
                self._preview = False
            self._decoder_ready.clear()
            self.decoder_requested.emit(preview_url(self._port))
            if not self._decoder_ready.wait(2):
                raise CameraError(tr('Görüntü alıcısı açılamadı. UDP portunu kullanan diğer uygulamaları kapatın.'))
            if self.isInterruptionRequested():
                return
            self.api.preview(True, self._port)
            self._preview = True
            self.stream_url_ready.emit(preview_url(self._port))
            self.connection_status.emit(tr('Önizleme komutu kabul edildi; görüntü bekleniyor…'))
        elif command == 'stop':
            if self._preview:
                self.api.preview(False)
            self._preview = False
            self.preview_stopped.emit()
            self.connection_status.emit(tr('Önizleme durduruldu.'))
        elif command == 'record':
            state = self.api.state()
            if argument:
                presets=self.api.get('gopro/camera/presets/get')
                active_mode=next((p.get('mode','') for group in presets.get('presetGroupArray',[]) for p in group.get('presetArray',[]) if p.get('id')==state.get('97')),'')
                if state.get('96') != 1000 or 'PHOTO' in active_mode:
                    raise CameraError(tr('Kayıt için kameradan Video modunu seçin.'))
                if state.get('33') not in (None, 0):
                    raise CameraError(tr('SD kart hazır değil. Kameranın SD kart durumunu kontrol edin.'))
            if bool(state['10']) != argument:
                self.api.shutter(argument)
            self.connection_status.emit(tr('Kayıt komutu kabul edildi; kamera durumu doğrulanıyor…'))
        elif command == 'capture':
            state=self.api.state()
            if state['10']:
                raise CameraError(tr('Kayıt sürüyor. Kadraj kontrolü mevcut kaydı durdurmaz; çekimden önce kullanın.'))
            resume=self._preview
            if self._preview:
                self.api.preview(False)
                self._preview=False
                self.preview_stopped.emit()
            try:
                result=QualityCapture(self.api,self.connection_status.emit,self.isInterruptionRequested).capture(argument)
                self.quality_ready.emit(result)
                self.connection_status.emit(result.get('restore_warning') or result.get('cleanup_warning') or tr('Geçici kadraj hazır: {0} × {1}. Kapatınca silinir.').format(result["width"], result["height"]))
            finally:
                if resume and not self.isInterruptionRequested():
                    # Let the GUI finish building the native-size viewer before
                    # it starts the decoder and acknowledges receiver readiness.
                    self.resume_preview_requested.emit()

    def run(self):
        next_poll = 0
        failures = 0
        try:
            while not self.isInterruptionRequested():
                try:
                    command, arg = self._commands.get(timeout=0.15)
                except queue.Empty:
                    command = None
                if command == 'quit':
                    break
                if command:
                    ok = False
                    try:
                        self._perform(command, arg)
                        ok = True
                        failures = 0
                    except CameraError as exc:
                        self.connection_status.emit(str(exc))
                        self.debug_signal.emit(str(exc))
                    except Exception as exc:
                        self.connection_status.emit(tr('Beklenmeyen kamera hatası. Günlüğü inceleyin.'))
                        self.debug_signal.emit(f'{type(exc).__name__}: {exc}')
                    self.command_finished.emit(command, ok)
                    if command in ('connect', 'record','capture'):
                        next_poll = 0
                if self.is_connected and time.monotonic() >= next_poll:
                    try:
                        self.api.get('gopro/camera/keep_alive')
                        state = self.api.state()
                        self.camera_state.emit(state)
                        failures = 0
                        interval = max(2.5, float(state.get('60', 0)) / 1000)
                    except (CameraError, ValueError, TypeError) as exc:
                        failures += 1
                        interval = 2.5
                        self.debug_signal.emit(tr('Durum sorgusu başarısız ({0}/3): {1}').format(failures, exc))
                        if failures >= 3:
                            self._set_connected(False)
                            self._preview = False
                            self.preview_stopped.emit()
                            self.connection_status.emit(tr('Kamera bağlantısı koptu. Wi-Fi ağını kontrol edip yeniden bağlanın.'))
                    next_poll = time.monotonic() + interval
        finally:
            if self.is_connected and self._preview:
                try:
                    self.api.preview(False)
                except CameraError:
                    pass
            self.is_connected = False
