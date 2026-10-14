"""Inspect native photos or video frames in RAM, clean only owned test media."""
from i18n import tr
import io
from pathlib import Path
import time
import av
import cv2
import numpy as np
from camera_api import CameraError

class QualityCapture:
    def __init__(self,api,status=lambda text:None,cancelled=lambda:False):
        self.api=api
        self.status=status
        self.cancelled=cancelled

    def pause(self,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if self.cancelled():raise CameraError(tr('Kadraj kontrolü iptal edildi.'))
            time.sleep(min(.1,max(0,deadline-time.monotonic())))

    def wait_idle(self,timeout=12):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if self.cancelled():raise CameraError(tr('Kadraj kontrolü iptal edildi.'))
            state=self.api.state()
            if not state.get('10') and not state.get('8'):
                return state
            self.pause(max(.5,float(state.get('60',500))/1000))
        raise CameraError(tr('Kamera çekimi zamanında tamamlayamadı.'))

    def wait_encoding(self,wanted,timeout=12,retry_stop=False):
        deadline=time.monotonic()+timeout
        last_stop=time.monotonic()
        while time.monotonic()<deadline:
            if self.cancelled():raise CameraError(tr('Kadraj kontrolü iptal edildi.'))
            state=self.api.state()
            if bool(state['10'])==wanted:return state
            if retry_stop and time.monotonic()-last_stop>2:
                self.api.shutter(False)
                last_stop=time.monotonic()
            self.api.get('gopro/camera/keep_alive')
            self.pause(max(.5,float(state.get('60',500))/1000))
        raise CameraError(tr('Test kaydının başlangıç/bitiş durumu doğrulanamadı.'))

    def new_media(self,before,extensions,timeout=18):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:files=self.api.media()
            except CameraError as exc:
                if exc.http_status!=503:raise
                self.pause(.2)
                continue
            matches=[key for key in files if key not in before and Path(key[1]).suffix.upper() in extensions]
            if len(matches)==1:return matches[0]
            if len(matches)>1:raise CameraError(tr('Birden fazla yeni çekim bulundu; yanlış görsel seçilmedi.'))
            self.api.get('gopro/camera/keep_alive')
            self.pause(.2)
        raise CameraError(tr('Yeni çekim dosyası bulunamadı. SD kartı kontrol edin.'))

    def ready_media(self,cancellable=True,timeout=12):
        deadline=time.monotonic()+timeout
        while True:
            try:return self.api.media()
            except CameraError as exc:
                if exc.http_status!=503 or time.monotonic()>=deadline:raise
                self.pause(.2) if cancellable else time.sleep(.2)

    def load_preset(self,preset,cancellable=True,timeout=12):
        self.api.get('gopro/camera/presets/load',id=preset)
        deadline=time.monotonic()+timeout
        ready_since=None
        while time.monotonic()<deadline:
            state=self.api.state()
            now=time.monotonic()
            if state.get('97')==preset and not state.get('8') and not state['10']:
                if ready_since is None:ready_since=now
                if now-ready_since>=.5:return
            else:ready_since=None
            self.pause(.1) if cancellable else time.sleep(.1)
        raise CameraError(tr('Kamera modu zamanında hazır olmadı.'))

    def capture(self,kind):
        if kind not in ('photo','video'):raise CameraError(tr('Geçersiz kadraj kontrolü türü.'))
        state=self.api.state()
        if state['10']:
            raise CameraError(tr('Kayıt sürüyor. Kadraj kontrolünü çekimden önce kullanın; mevcut kayıt durdurulmadı.'))
        if state.get('33')!=0 or state.get('8'):
            raise CameraError(tr('Kamera veya SD kart hazır değil.'))
        if kind=='video' and state.get('96')!=1000:
            raise CameraError(tr('Video karesi için kamerada Video modunu seçin.'))
        original_preset=state.get('97')
        presets=self.api.get('gopro/camera/presets/get')
        available=[p for group in presets.get('presetGroupArray',[]) for p in group.get('presetArray',[])]
        active_mode=next((p.get('mode','') for p in available if p.get('id')==original_preset),'')
        if kind=='video' and 'PHOTO' in active_mode:
            raise CameraError(tr('Video karesi için kamerada Video modunu seçin.'))
        photo_preset=None
        if kind=='photo':
            if not isinstance(original_preset,int):raise CameraError(tr('Mevcut video ayarı doğrulanamadı.'))
            ids=[p['id'] for p in available if p.get('mode')=='FLAT_MODE_PHOTO_SINGLE' and isinstance(p.get('id'),int)]
            if not ids:raise CameraError(tr('Kamerada tek fotoğraf modu bulunamadı; Video karesi seçeneğini kullanın.'))
            photo_preset=ids[0]
        before=self.ready_media()
        owned_recording=False
        requested=False
        media_key=None
        result=None
        preset_changed=False
        extensions={'.JPG','.JPEG'} if kind=='photo' else {'.MP4'}
        started=time.monotonic()
        try:
            if kind=='photo':
                self.status(tr('Fotoğraf modu hazırlanıyor…'))
                preset_changed=photo_preset!=original_preset
                if preset_changed:self.load_preset(photo_preset)
                self.status(tr('12 MP test fotoğrafı çekiliyor…'))
                requested=True
                self.api.shutter(True)
            else:
                self.status(tr('Kadraj testi: yaklaşık 2 saniyelik video çekiliyor…'))
                owned_recording=True
                requested=True
                self.api.shutter(True)
                self.wait_encoding(True)
                self.pause(2)
                self.api.shutter(False)
                self.wait_encoding(False,retry_stop=True)
                owned_recording=False
                self.wait_idle()
            folder,name=self.new_media(before,extensions)
            media_key=(folder,name)
            self.status(tr('Orijinal çekim geçici olarak belleğe aktarılıyor…'))
            source=self.api.fetch_media_bytes(folder,name,self.cancelled)
            source_bytes=len(source)
            if kind=='photo':
                image=cv2.imdecode(np.frombuffer(source,np.uint8),cv2.IMREAD_COLOR)
                del source
                if image is None:raise CameraError(tr('Test fotoğrafı çözümlenemedi.'))
            else:
                self.status(tr('Videonun yüksek çözünürlüklü karesi hazırlanıyor…'))
                with io.BytesIO(source) as buffer,av.open(buffer) as container:
                    del source
                    first_time=None
                    frame=None
                    for decoded in container.decode(video=0):
                        if self.cancelled():raise CameraError(tr('Kadraj kontrolü iptal edildi.'))
                        frame=decoded
                        if first_time is None:first_time=decoded.time or 0
                        if (decoded.time or 0)-first_time>=.8:break
                    if frame is None:raise CameraError(tr('Test videosundan görüntü karesi alınamadı.'))
                    image=frame.to_ndarray(format='bgr24')
            height,width=image.shape[:2]
            result={'kind':kind,'frame':image,
                    'width':width,'height':height,'camera_folder':folder,'camera_file':name,
                    'preset':original_preset,'camera_cleaned':False,
                    'source_bytes':source_bytes,
                    'quality':(tr('Orijinal fotoğraf') if kind=='photo' else tr('Orijinal video karesi'))+tr(' · yalnızca bellekte · kapatınca silinir.')}
            return result
        finally:
            # Cancellation still completes cleanup, but never stops a pre-existing recording.
            if owned_recording:
                try:
                    deadline=time.monotonic()+12
                    while True:
                        self.api.shutter(False)
                        if not self.api.state()['10']:break
                        if time.monotonic()>=deadline:raise CameraError(tr('Test kaydı hâlâ sürüyor.'))
                        time.sleep(2)
                except CameraError as exc:self.status(tr('Test kaydı durumu belirsiz; kamerayı kontrol edin. {0}').format(exc))
            if requested:
                try:
                    # The exact before/after difference is the only deletion authority.
                    # Do not use delete-last, delete-all, or delete-group endpoints.
                    deadline=time.monotonic()+12
                    while True:
                        cleanup_state=self.api.state()
                        if not cleanup_state.get('8') and not cleanup_state['10']:break
                        if time.monotonic()>=deadline:raise CameraError(tr('Kamera test dosyasını kapatamadı.'))
                        time.sleep(.2)
                    if self.api.state()['10']:raise CameraError(tr('Kamera kayıtta; test dosyası silinmedi.'))
                    files=self.ready_media(cancellable=False)
                    if media_key is None:
                        matches=[key for key in files if key not in before and Path(key[1]).suffix.upper() in extensions]
                        if len(matches)>1:raise CameraError(tr('Yeni test dosyası kesin belirlenemedi; dosyalar silinmedi.'))
                        if matches:media_key=matches[0]
                    if media_key is not None:
                        if media_key in before:raise CameraError(tr('Mevcut kayıt silinmedi.'))
                        if media_key in files:self.api.delete_media(*media_key)
                        if media_key in self.ready_media(cancellable=False):raise CameraError(tr('SD karttaki test dosyası silinemedi.'))
                    if result is not None:result['camera_cleaned']=True
                except CameraError as exc:
                    warning=tr('Test çekimi kamerada kalmış olabilir: {0}').format(exc)
                    if result is not None:result['cleanup_warning']=warning
                    self.status(warning)
            if preset_changed:
                try:self.load_preset(original_preset,cancellable=False)
                except CameraError as exc:
                    warning=tr('Video ayarı geri yüklenemedi: {0}').format(exc)
                    if result is not None:result['restore_warning']=warning
                    self.status(warning)
            if result is not None:result['elapsed_s']=round(time.monotonic()-started,3)
