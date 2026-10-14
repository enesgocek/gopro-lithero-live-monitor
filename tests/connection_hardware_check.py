"""Verify one-click connection, remembered identity and native live frames."""
from pathlib import Path
import sys,time,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from gopro_monitor.presentation.main_window import MainWindow
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf8',errors='replace')
app=QApplication([])
window=MainWindow()
window.show()
if '--fullscreen' in sys.argv:window.toggle_fullscreen()
started=time.monotonic()
failure=False
window.gopro.connection_status.connect(lambda message:print(message,flush=True))
QTimer.singleShot(100,window.quick_connect)

def tick():
    global failure,phase
    if time.monotonic()-started>85:
        failure=True
        print('FAIL: automatic connection timed out\n'+'\n'.join(window._log_lines),flush=True)
        timer.stop()
        window.close()
        return
    if window._preview_state=='active' and window._frame is not None:
        profile=window.connection_store.load()
        assert profile['remember'] and profile['auto_connect']
        assert 'password' not in profile
        height,width=window._frame.shape[:2]
        print(json.dumps({'success':True,'transport':window._transport,'address':window.address.text(),'native_width':width,'native_height':height,'seconds_to_live':round(time.monotonic()-started,3),'windows_profile_reused':window._transport=='Wi-Fi','preferences_saved':True},ensure_ascii=False),flush=True)
        timer.stop()
        if '--leave-open' not in sys.argv:window.close()

timer=QTimer()
timer.timeout.connect(tick)
timer.start(200)
app.exec()
sys.exit(1 if failure else 0)
