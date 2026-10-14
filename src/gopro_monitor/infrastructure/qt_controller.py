"""All camera requests are serialized in one background worker."""
from gopro_monitor.shared.i18n import tr
import queue
import time
import threading
from PyQt6.QtCore import QThread, pyqtSignal
from gopro_monitor.infrastructure.camera_api import CameraAPI, CameraError
from gopro_monitor.application.camera_session import CameraSession
from gopro_monitor.infrastructure.image_decoder import OriginalMediaDecoder

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
        self._decoder_ready = threading.Event()
        self._session=CameraSession(api_factory,OriginalMediaDecoder(),self._emit_event,self._prepare_decoder,self.isInterruptionRequested)

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

    @property
    def api(self):return self._session.api

    @property
    def is_connected(self):return self._session.is_connected

    @is_connected.setter
    def is_connected(self,value):self._session.is_connected=value

    @property
    def _preview(self):return self._session._preview

    @_preview.setter
    def _preview(self,value):self._session._preview=value

    def _set_connected(self,value):self._session._set_connected(value)

    def _perform(self,command,argument):self._session.perform(command,argument)

    def _prepare_decoder(self,url):
        self._decoder_ready.clear()
        self.decoder_requested.emit(url)
        return self._decoder_ready.wait(2)

    def _emit_event(self,topic,*arguments):
        getattr(self,topic).emit(*arguments)

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
