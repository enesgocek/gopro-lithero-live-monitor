"""Validated Open GoPro HTTP client; local camera requests bypass proxies."""
from gopro_monitor.shared.i18n import tr
from gopro_monitor.domain.errors import CameraError
from gopro_monitor.domain.connection import validate_address,preview_url
import json
import urllib.error
import urllib.request
import re
import time
import io
from pathlib import Path
from urllib.parse import urlencode, urlsplit, quote

class NoCameraRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        raise CameraError(tr('Kamera HTTP yönlendirmeleri engellendi.'))

class CameraAPI:
    def __init__(self, address='10.5.5.9', timeout=3):
        self.base_url = validate_address(address)
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoCameraRedirects())

    def get(self, endpoint, **params):
        url = self.base_url + '/' + endpoint.lstrip('/')
        if params:
            # LIT HERO rejects an encoded directory separator for file deletion.
            safe='/' if endpoint.lstrip('/')=='gopro/media/delete/file' else ''
            url += '?' + urlencode(params,safe=safe)
        try:
            with self.opener.open(url, timeout=self.timeout) as response:
                raw = response.read(1024 * 1024+1)
                if len(raw)>1024*1024:raise CameraError(tr('Kamera yanıtı boyut sınırını aşıyor.'))
        except urllib.error.HTTPError as exc:
            raise CameraError(tr('Kamera komutu reddetti: HTTP {0} ({1}).').format(exc.code,endpoint),http_status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CameraError(tr('Kameraya erişilemiyor. GoPro Wi-Fi bağlantısını ve IP adresini kontrol edin.')) from exc
        try:
            result = json.loads(raw) if raw.strip() else {}
        except (ValueError, UnicodeError) as exc:
            raise CameraError(tr('Kamera geçerli bir JSON yanıtı vermedi.')) from exc
        if not isinstance(result, dict):
            raise CameraError(tr('Beklenmeyen kamera yanıtı.'))
        if result.get('error', 0) != 0:
            raise CameraError(tr('Kamera API hatası: {0} ({1}).').format(result["error"], endpoint))
        return result

    def state(self):
        result = self.get('gopro/camera/state')
        status = result.get('status')
        if not isinstance(status, dict) or '10' not in status:
            raise CameraError(tr('Open GoPro durum yanıtı doğrulanamadı. Firmware sürümünü kontrol edin.'))
        if type(status['10']) not in (int,bool) or status['10'] not in (0,1):
            raise CameraError(tr('Kamera durum verisi geçersiz.'))
        for key in ('13','33','60','96','97'):
            if key in status and (type(status[key]) is not int or not 0<=status[key]<=4294967295):
                raise CameraError(tr('Kamera durum verisi geçersiz.'))
        return status

    def info(self):
        result = self.get('gopro/camera/info')
        if not isinstance(result.get('model_name'), str) or not result['model_name']:
            raise CameraError(tr('Kamera model bilgisi doğrulanamadı.'))
        if re.sub(r'[^A-Z0-9]','',result['model_name'].upper()) not in ('LITHERO','GOPROLITHERO'):
            raise CameraError(tr('Bu uygulama yalnızca GoPro LIT HERO modelini destekler.'))
        return result

    def preview(self, enabled, port=8554):
        return self.get('gopro/camera/stream/' + ('start' if enabled else 'stop'), **({'port': port} if enabled else {}))

    def shutter(self, enabled):
        return self.get('gopro/camera/shutter/' + ('start' if enabled else 'stop'))

    def media(self):
        result=self.get('gopro/media/list')
        if not isinstance(result.get('media'),list):
            raise CameraError(tr('Kamera medya listesi doğrulanamadı.'))
        files={}
        for directory in result['media']:
            if not isinstance(directory,dict) or not isinstance(directory.get('fs'),list):
                raise CameraError(tr('Kamera medya listesi doğrulanamadı.'))
            folder=directory.get('d','')
            for entry in directory.get('fs',[]):
                if not isinstance(entry,dict):raise CameraError(tr('Kamera medya listesi doğrulanamadı.'))
                name=entry.get('n','')
                if isinstance(folder,str) and isinstance(name,str):
                    files[(folder,name)]=entry
        return files

    @staticmethod
    def validate_media_path(folder, name):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',folder) or not re.fullmatch(r'[A-Za-z0-9_-]+\.(MP4|JPG|JPEG)',name,re.IGNORECASE):
            raise CameraError(tr('Kamera medya dosyası yolu geçersiz.'))

    def delete_media(self, folder, name):
        self.validate_media_path(folder,name)
        return self.get('gopro/media/delete/file',path=f'{folder}/{name}')

    def fetch_media_bytes(self, folder, name, cancelled=lambda:False):
        """Transfer a bounded test clip into RAM without creating local files."""
        self.validate_media_path(folder,name)
        resource=f'/videos/DCIM/{quote(folder)}/{quote(name)}'
        parts=urlsplit(self.base_url)
        host=f'[{parts.hostname}]' if ':' in parts.hostname else parts.hostname
        urls=[self.base_url+resource]
        if parts.port!=8080:urls.append(f'http://{host}:8080'+resource)
        response=None
        try:
            for url in urls:
                try:
                    response=self.opener.open(url,timeout=8)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code not in (400,404):raise
            if response is None:raise CameraError(tr('Kamera dosyası aktarılamıyor.'))
            with response,io.BytesIO() as output:
                limit=256*1024*1024
                length=int(response.headers.get('Content-Length',0))
                if length>limit:raise CameraError(tr('Test dosyası beklenenden büyük.'))
                deadline=time.monotonic()+120
                while True:
                    if cancelled():raise CameraError(tr('Görsel aktarımı iptal edildi.'))
                    if time.monotonic()>deadline:raise CameraError(tr('Görsel aktarımı zaman aşımı.'))
                    chunk=response.read(65536)
                    if not chunk:break
                    if output.tell()+len(chunk)>limit:raise CameraError(tr('Test dosyası beklenenden büyük.'))
                    output.write(chunk)
                if not output.tell() or (length and output.tell()!=length):
                    raise CameraError(tr('Medya aktarımı tamamlanmadı.'))
                return output.getvalue()
        except (urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
            raise CameraError(tr('Medya aktarılamadı: {0}.').format(type(exc).__name__)) from exc

    def download_media(self, folder, name, destination, cancelled=lambda:False, progress=lambda value:None):
        self.validate_media_path(folder,name)
        destination=Path(destination)
        if destination.exists():
            raise CameraError(tr('Hedef dosya zaten var; üzerine yazılmadı.'))
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.with_suffix(destination.suffix+'.part')
        resource=f'/videos/DCIM/{quote(folder)}/{quote(name)}'
        parts=urlsplit(self.base_url)
        host=f'[{parts.hostname}]' if ':' in parts.hostname else parts.hostname
        urls=[self.base_url+resource]
        if parts.port!=8080:urls.append(f'http://{host}:8080'+resource)
        response=None
        created=False
        try:
            for url in urls:
                try:
                    response=self.opener.open(url,timeout=8)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code not in (400,404):raise
            if response is None:
                raise CameraError(tr('Kamera dosyası indirilemiyor.'))
            with response,temporary.open('xb') as output:
                created=True
                length=int(response.headers.get('Content-Length',0))
                received=0
                deadline=time.monotonic()+120
                while True:
                    if cancelled():raise CameraError(tr('Görsel indirme iptal edildi.'))
                    if time.monotonic()>deadline:raise CameraError(tr('Görsel indirme zaman aşımı.'))
                    chunk=response.read(65536)
                    if not chunk:break
                    received+=len(chunk)
                    if received>256*1024*1024:raise CameraError(tr('Test dosyası beklenenden büyük.'))
                    output.write(chunk)
                    if length:progress(min(100,int(received*100/length)))
                if not received or (length and received!=length):
                    raise CameraError(tr('Medya indirme tamamlanmadı.'))
            temporary.replace(destination)
            return destination
        except (urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
            raise CameraError(tr('Medya indirilemedi: {0}.').format(type(exc).__name__)) from exc
        finally:
            if created:temporary.unlink(missing_ok=True)
