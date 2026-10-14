"""Camera command use cases; no Qt, HTTP client or media-library dependency."""
from gopro_monitor.domain.connection import preview_url
from gopro_monitor.domain.errors import CameraError
from gopro_monitor.shared.i18n import tr
from gopro_monitor.application.quality_capture import QualityCapture

class CameraSession:
    def __init__(self,api_factory,decoder,emit,prepare_decoder,cancelled):
        self._api_factory=api_factory
        self.decoder=decoder
        self.emit=emit
        self.prepare_decoder=prepare_decoder
        self.cancelled=cancelled
        self.api=None
        self.is_connected=False
        self._preview=False
        self._port=8554

    def _set_connected(self,value):
        self.is_connected=value
        self.emit('connected',value)

    def perform(self, command, argument):
        if command == 'connect':
            self._set_connected(False)
            self._preview = False
            self.emit('connection_status',tr('Kamera bağlantısı denetleniyor…'))
            address, self._port = argument
            self.api = self._api_factory(address)
            info = self.api.info()
            state = self.api.state()
            self.emit('camera_info',info)
            self.emit('camera_state',state)
            self._set_connected(True)
            self.emit('connection_status',tr('Kamera bağlı. Önizlemeyi başlatabilirsiniz.'))
            return
        if not self.is_connected:
            raise CameraError(tr('Önce kameraya bağlanın.'))
        if command == 'start':
            state = self.api.state()
            self.emit('camera_state',state)
            if state.get('55') in (0, False):
                raise CameraError(tr('Kamera bu modda önizlemeye izin vermiyor. Video modunu seçin.'))
            if self._preview:
                self.api.preview(False)
                self._preview = False
            if not self.prepare_decoder(preview_url(self._port)):
                raise CameraError(tr('Görüntü alıcısı açılamadı. UDP portunu kullanan diğer uygulamaları kapatın.'))
            if self.cancelled():
                return
            self.api.preview(True, self._port)
            self._preview = True
            self.emit('stream_url_ready',preview_url(self._port))
            self.emit('connection_status',tr('Önizleme komutu kabul edildi; görüntü bekleniyor…'))
        elif command == 'stop':
            if self._preview:
                self.api.preview(False)
            self._preview = False
            self.emit('preview_stopped')
            self.emit('connection_status',tr('Önizleme durduruldu.'))
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
            self.emit('connection_status',tr('Kayıt komutu kabul edildi; kamera durumu doğrulanıyor…'))
        elif command == 'capture':
            state=self.api.state()
            if state['10']:
                raise CameraError(tr('Kayıt sürüyor. Kadraj kontrolü mevcut kaydı durdurmaz; çekimden önce kullanın.'))
            resume=self._preview
            if self._preview:
                self.api.preview(False)
                self._preview=False
                self.emit('preview_stopped')
            try:
                result=QualityCapture(self.api,lambda text:self.emit('connection_status',text),self.cancelled,decoder=self.decoder).capture(argument)
                self.emit('quality_ready',result)
                self.emit('connection_status',result.get('restore_warning') or result.get('cleanup_warning') or tr('Geçici kadraj hazır: {0} × {1}. Kapatınca silinir.').format(result["width"], result["height"]))
            finally:
                if resume and not self.cancelled():
                    # Let the GUI finish building the native-size viewer before
                    # it starts the decoder and acknowledges receiver readiness.
                    self.emit('resume_preview_requested')
