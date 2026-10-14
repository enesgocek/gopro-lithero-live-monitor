"""Direct UDP MPEG-TS decoding without OpenCV's capture queue."""
from i18n import tr
import io
import socket
import threading
import time
from urllib.parse import urlsplit
import av
from PyQt6.QtCore import QThread, pyqtSignal

class StreamTimeout(OSError):
    pass

class UDPReader(io.RawIOBase):
    def __init__(self, port, interrupted, camera_host=None):
        super().__init__()
        self.interrupted = interrupted
        self.camera_host = camera_host
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            self.socket.settimeout(0.15)
            bind_host='127.0.0.1'
            if camera_host:
                # Determine the camera-facing local interface without sending data.
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as route:
                    route.connect((camera_host,9))
                    bind_host=route.getsockname()[0]
            self.socket.bind((bind_host, port))
        except BaseException:
            self.socket.close()
            raise
        self.pending = b''
        self.last_received = time.monotonic()
        self.received = False
        self.packets = 0

    def readable(self):
        return True

    def seekable(self):
        return False

    def read(self, size=-1):
        if self.interrupted():
            return b''
        if not self.pending:
            while not self.interrupted():
                try:
                    packet, sender = self.socket.recvfrom(65535)
                    if self.camera_host and sender[0] != self.camera_host:
                        continue
                    if not packet:
                        continue
                    self.last_received = time.monotonic()
                    self.received = True
                    self.packets += 1
                    self.pending = packet
                    break
                except socket.timeout:
                    limit = 3 if self.received else 8
                    if time.monotonic() - self.last_received > limit:
                        raise StreamTimeout(tr('Kameradan UDP görüntüsü gelmiyor.'))
            if not self.pending:
                return b''
        if size < 0:
            size = len(self.pending)
        result, self.pending = self.pending[:size], self.pending[size:]
        return result

    def close(self):
        self.socket.close()
        super().close()

class VideoStreamThread(QThread):
    status_signal = pyqtSignal(str)
    debug_signal = pyqtSignal(str)
    stream_state = pyqtSignal(str)
    receiver_ready = pyqtSignal()
    metrics = pyqtSignal(dict)

    def __init__(self, url='', parent=None, camera_host=None):
        super().__init__(parent)
        self.stream_url = url
        self.camera_host = camera_host
        self._lock = threading.Lock()
        self._frame = None
        self._frame_time = 0
        self.overwritten_frames = 0

    def take_frame(self):
        with self._lock:
            frame, self._frame = self._frame, None
        return frame

    @property
    def frame_time(self):
        with self._lock:
            return self._frame_time

    def stop(self):
        self.requestInterruption()

    def run(self):
        source = container = None
        active = False
        count = 0
        period = time.monotonic()
        try:
            parsed = urlsplit(self.stream_url)
            if parsed.scheme != 'udp' or not parsed.port:
                raise ValueError(tr('Geçerli UDP önizleme adresi gerekiyor.'))
            self.stream_state.emit('waiting')
            source = UDPReader(parsed.port, self.isInterruptionRequested, self.camera_host)
            # Listener binds before the camera is told to stream, so SPS/PPS is retained.
            self.receiver_ready.emit()
            container = av.open(source, mode='r', format='mpegts', buffer_size=1316, options={
                'probesize': '32768', 'analyzeduration': '0', 'fflags': 'nobuffer',
                'flags': 'low_delay', 'max_delay': '0',
            })
            if not container.streams.video:
                raise ValueError(tr('Akışta video bulunamadı.'))
            stream = container.streams.video[0]
            stream.codec_context.thread_count = 1
            stream.codec_context.thread_type = 'SLICE'
            for packet in container.demux(stream):
                if self.isInterruptionRequested():
                    break
                try:
                    frames = packet.decode()
                except av.error.InvalidDataError:
                    # A damaged UDP picture must not freeze or replay old pictures.
                    continue
                for decoded in frames:
                    if self.isInterruptionRequested():
                        break
                    decode_started = time.perf_counter()
                    frame = decoded.to_ndarray(format='bgr24')
                    now = time.monotonic()
                    with self._lock:
                        if self._frame is not None:
                            self.overwritten_frames += 1
                        self._frame = frame
                        self._frame_time = now
                    count += 1
                    if not active:
                        active = True
                        self.stream_state.emit('active')
                        self.status_signal.emit(tr('Canlı görüntü · düşük gecikme'))
                    if now - period >= 1:
                        self.metrics.emit({'width':decoded.width,'height':decoded.height,
                            'fps':round(count/(now-period),1),
                            'convert_ms':round((time.perf_counter()-decode_started)*1000,2),
                            'overwritten':self.overwritten_frames})
                        count, period = 0, now
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.debug_signal.emit(f'Video: {type(exc).__name__}')
                self.stream_state.emit('failed')
                if isinstance(exc, OSError) and getattr(exc, 'winerror', None) == 10048:
                    self.status_signal.emit(tr('Görüntü portunu başka uygulama kullanıyor. Diğer izleyiciyi kapatın.'))
                else:
                    self.status_signal.emit(tr('Görüntü alınamıyor. Kamera bağlantısını kontrol edip önizlemeyi yeniden başlatın.'))
        finally:
            if container:
                container.close()
            if source:
                source.close()
            with self._lock:
                self._frame = None
            if self.isInterruptionRequested():
                self.stream_state.emit('stopped')
