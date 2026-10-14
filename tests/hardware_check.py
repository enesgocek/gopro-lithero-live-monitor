"""Explicit hardware test. --record-test creates and cleans a short SD video."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from PyQt6.QtCore import QTimer,QPoint
from PyQt6.QtWidgets import QApplication
from gopro_monitor.presentation.main_window import MainWindow
from gopro_monitor.application.quality_capture import QualityCapture
from gopro_monitor.infrastructure.image_decoder import OriginalMediaDecoder

for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):
        stream.reconfigure(encoding='utf-8',errors='replace')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--record-test',action='store_true')
parser.add_argument('--leave-open',action='store_true')
parser.add_argument('--fullscreen-check',action='store_true')
parser.add_argument('--screenshots',action='store_true',help='Explicitly save private camera screenshots under artifacts/')
args=parser.parse_args()
app=QApplication([])
window=MainWindow()
window.show()
if args.screenshots:Path('artifacts').mkdir(exist_ok=True)
started=time.monotonic()
phase='connect'
record_started=0
owned_recording=False
recording_frame=False
exit_code=1
media_before=None

def screenshot(name):
    if args.screenshots:window.grab().save(str(Path('artifacts')/name))

def finish(ok, message):
    global exit_code,phase
    if media_before is not None:
        try:
            capture=QualityCapture(window.gopro.api,decoder=OriginalMediaDecoder())
            files=capture.ready_media(cancellable=False)
            new=[key for key in files if key not in media_before and key[1].upper().endswith('.MP4')]
            if not window.gopro.api.state()['10'] and len(new)==1:
                window.gopro.api.delete_media(*new[0])
                assert set(capture.ready_media(cancellable=False))==media_before
            else:
                ok=False
                message+=' New test file could not be safely cleaned.'
        except Exception:
            ok=False
            message+=' Test cleanup could not be verified.'
    print(json.dumps({'success':ok,'message':message},ensure_ascii=False),flush=True)
    exit_code=0 if ok else 1
    timer.stop()
    phase='finished'
    if not args.leave_open:
        window.close()

def check_fullscreen():
    if not args.fullscreen_check:
        return
    window.toggle_fullscreen()
    app.processEvents()
    window.edge_hint.hide()
    window.hide_edge_panels()
    assert window._focus_mode and not window.top_bar.isVisible()
    assert not window.left_panel.isVisible() and not window.right_panel.isVisible()
    assert window.video_label.size()==window.surface.size()
    screenshot('minimal-fullscreen.png')
    for name,point,panel in [('left',QPoint(1,250),window.left_panel),
                             ('top',QPoint(window.surface.width()//2,1),window.top_bar),
                             ('right',QPoint(window.surface.width()-1,250),window.right_panel)]:
        window.update_edge_panels(point)
        assert panel.isVisible()
        screenshot(f'minimal-{name}-panel.png')
    window.hide_edge_panels()
    print('Gerçek görüntü: saf tam ekran ve sol/üst/sağ paneller doğrulandı.',flush=True)

def tick():
    global phase,record_started,owned_recording,recording_frame,media_before
    now=time.monotonic()
    if now-started>75:
        if owned_recording:
            window.gopro.set_recording(False)
        finish(False,'Donanım testi zaman aşımı.')
        return
    if phase=='connect':
        phase='preview'
        window.quick_connect()
    elif phase=='preview' and window._preview_state=='active' and window._frame is not None:
        if not args.record_test:
            screenshot('live-app.png')
            check_fullscreen()
            finish(True,'Gerçek görüntü masaüstü arayüzünde gösterildi.')
        elif window._recording:
            finish(False,'Kamera zaten kayıtta; mevcut kayda müdahale edilmedi.')
        else:
            phase='record-start'
            media_before=set(window.gopro.api.media())
            owned_recording=True
            window.toggle_recording()
    elif phase=='record-start' and window._recording:
        phase='recording'
        record_started=now
    elif phase=='recording':
        if now-record_started>3 and now-window._last_frame_time<1 and window._preview_state=='active':
            recording_frame=True
        if now-record_started>6:
            screenshot('recording-app.png')
            window.toggle_recording()
            phase='record-stop'
    elif phase=='record-stop' and window._recording is False:
        owned_recording=False
        screenshot('live-app.png')
        check_fullscreen()
        finish(recording_frame,'SD kaydı başlatıldı/durduruldu; kayıt sırasında canlı görüntü doğrulandı.' if recording_frame else 'SD kayıt kontrolü çalıştı, kayıt sırasında görüntü doğrulanamadı.')

timer=QTimer()
timer.timeout.connect(tick)
timer.start(200)
app.exec()
sys.exit(exit_code)
