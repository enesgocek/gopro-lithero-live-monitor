"""Real camera quality button, native-size viewer, preset/preview recovery."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QTimer,Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from main import MainWindow
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf8',errors='replace')
app=QApplication([])
window=MainWindow()
window.show()
phase='setup'
started=time.monotonic()
result=None
original_preset=None
failure=False
camera_before=None
local_before={str(path):path.stat().st_size for path in Path('captures').rglob('*') if path.is_file()}

def state_received(state):
    global original_preset
    if original_preset is None:original_preset=state.get('97')
window.gopro.camera_state.connect(state_received)
window.gopro.connection_status.connect(lambda msg:print(msg,flush=True))
window.gopro.quality_ready.connect(lambda capture:save_result(capture))
def save_result(capture):
    global result
    result=capture
    print(json.dumps({'capture_metadata':{key:value for key,value in capture.items() if key!='frame'}},ensure_ascii=False),flush=True)

def tick():
    global phase,failure,camera_before
    if time.monotonic()-started>100:
        print('FAIL: quality workflow timeout',flush=True)
        print('\n'.join(window._log_lines),flush=True)
        failure=True
        timer.stop()
        window.close()
        return
    if phase=='setup':
        phase='preview'
        window.quick_connect()
        window.connection_worker.status.connect(lambda msg:print(msg,flush=True))
        window.connection_worker.error.connect(lambda msg:print(msg,flush=True))
    elif phase=='preview' and window._preview_state=='active' and window._frame is not None and not window._pending and window.quality_photo_button.isEnabled():
        phase='capture'
        camera_before=set(window.gopro.api.media())
        # Windows may prevent a test window from taking keyboard foreground.
        # Exercise the actual connected button without depending on that policy.
        window.quality_photo_button.click()
        assert 'capture' in window._pending,'Quality button did not trigger'
    elif phase=='capture' and result is not None and window._reviews:
        review=window._reviews[-1]
        review.view.fit_image()
        pixmap=review.view.item.pixmap()
        assert (pixmap.width(),pixmap.height())==(result['width'],result['height'])
        review.view.actual_size()
        assert abs(review.view.transform().m11()-1)<.001
        review.view.fit_image()
        assert result['camera_cleaned']
        assert result['kind']=='photo'
        assert (result['width'],result['height'])==(4000,3000)
        assert 'frame' not in result and 'image' not in result and 'original' not in result
        assert set(window.gopro.api.media())==camera_before,'Test clip remained or original media changed'
        assert {str(path):path.stat().st_size for path in Path('captures').rglob('*') if path.is_file()}==local_before
        review.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,False)
        # Reproduce the reported paused-preview state. Closing the review must
        # recover it without clicking the manual preview-start button.
        window.stop_stream()
        review.close()
        assert review.view.scene.items()==[] and review.view.item is None and review.capture=={}
        assert window._reviews==[]
        review.deleteLater()
        phase='resume'
    elif phase=='resume' and window._preview_state=='active' and window.stream_thread and window._frame is not None and 'capture' not in window._pending:
        assert window.gopro.api.state().get('97')==original_preset
        assert not window.gopro.api.state()['10']
        print(json.dumps({'success':True,'trigger':'quality_photo_button','capture':result,'restored_preset':original_preset,'preview_resumed':True,'native_zoom_verified':True,'local_files_created':False,'test_media_deleted':True,'review_pixels_discarded':True,'paused_preview_recovered_on_review_close':True},ensure_ascii=False),flush=True)
        timer.stop()
        if '--leave-open' not in sys.argv:window.close()

timer=QTimer()
def checked_tick():
    global failure
    try:tick()
    except Exception as exc:
        failure=True
        timer.stop()
        print(f'FAIL: {type(exc).__name__}: {exc}',flush=True)
        print('\n'.join(window._log_lines),flush=True)
        window.close()
timer.timeout.connect(checked_tick)
timer.start(200)
app.exec()
sys.exit(1 if failure else 0)
