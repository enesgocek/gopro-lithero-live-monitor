"""Original JPEG / MP4 decoding adapter; buffers stay in memory."""
import io
import av
import cv2
import numpy as np
from gopro_monitor.domain.errors import CameraError
from gopro_monitor.shared.i18n import tr

class OriginalMediaDecoder:
    def photo(self,source):
        try:image=cv2.imdecode(np.frombuffer(source,np.uint8),cv2.IMREAD_COLOR)
        except cv2.error as exc:raise CameraError(tr('Test fotoğrafı çözümlenemedi.')) from exc
        if image is None:raise CameraError(tr('Test fotoğrafı çözümlenemedi.'))
        return image

    def video(self,source,cancelled=lambda:False):
        try:
            with io.BytesIO(source) as buffer,av.open(buffer) as container:
                first_time=None
                frame=None
                for decoded in container.decode(video=0):
                    if cancelled():raise CameraError(tr('Kadraj kontrolü iptal edildi.'))
                    frame=decoded
                    if first_time is None:first_time=decoded.time or 0
                    if (decoded.time or 0)-first_time>=.8:break
                if frame is None:raise CameraError(tr('Test videosundan görüntü karesi alınamadı.'))
                return frame.to_ndarray(format='bgr24')
        except (av.error.FFmpegError,IndexError) as exc:
            raise CameraError(tr('Test videosundan görüntü karesi alınamadı.')) from exc
