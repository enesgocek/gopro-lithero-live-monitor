"""Verify whether a res=12 preview request actually changes decoded dimensions."""
from pathlib import Path
import json
import sys
import argparse
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QCoreApplication,QTimer
from camera_api import CameraAPI,CameraError,preview_url
from video_stream import VideoStreamThread
app=QCoreApplication([])
parser=argparse.ArgumentParser()
parser.add_argument('--address',default='10.5.5.9')
parser.add_argument('--output',default='artifacts/resolution-probe.json')
args=parser.parse_args()
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8',errors='replace')
api=CameraAPI(args.address)
if api.state()['10']:
    raise SystemExit('Kamera kayıtta; çözünürlük deneyi yapılmadı.')
report={}
try:
    report['webcam_start_1080']=api.get('gopro/webcam/start',res=12)
except CameraError as exc:
    report['webcam_start_1080']=str(exc)
worker=VideoStreamThread(preview_url(8554),camera_host=urlsplit(api.base_url).hostname)
worker.receiver_ready.connect(lambda:api.get('gopro/camera/stream/start',port=8554,res=12))
worker.start()
finished=False

def close():
    global finished
    if finished:return
    finished=True
    worker.stop()
    worker.wait(4000)
    api.preview(False)
    report['address']=args.address
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    app.quit()
def tick():
    frame=worker.take_frame()
    if frame is not None:
        timer.stop()
        report['preview_requested_res']=12
        report['decoded_dimensions']=[frame.shape[1],frame.shape[0]]
        close()
timer=QTimer()
timer.timeout.connect(tick)
timer.start(20)
QTimer.singleShot(12000,close)
app.exec()
