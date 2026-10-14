"""Optical screen-to-camera benchmark using a changing ArUco marker."""
import argparse
from collections import deque
import json
from pathlib import Path
import statistics
import sys
import time
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import cv2
import numpy as np
from PyQt6.QtCore import Qt,QTimer,QRect
from PyQt6.QtGui import QImage,QPainter,QColor,QFont
from PyQt6.QtWidgets import QApplication,QWidget
from gopro_monitor.infrastructure.camera_api import CameraAPI,preview_url

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds',type=int,default=24)
parser.add_argument('--output',type=Path,default=Path('artifacts/latency.json'))
args=parser.parse_args()
def report_exception(kind,value,tb):
    report=''.join(traceback.format_exception(kind,value,tb))
    args.output.with_suffix('.error.txt').write_text(report,encoding='utf8')
    print(report,file=sys.stderr,flush=True)
    if 'worker' in globals():
        worker.stop()
        worker.wait(6000)
    if 'app' in globals():app.quit()
sys.excepthook=report_exception
from gopro_monitor.infrastructure.video_stream import VideoStreamThread
from urllib.parse import urlsplit
args.output.parent.mkdir(parents=True,exist_ok=True)
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')
app=QApplication([])
issued={}
dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
detector=cv2.aruco.ArucoDetector(dictionary)
started=time.monotonic()
latencies=[]
last_ids=deque(maxlen=20)
last_frame=None
class Pattern(QWidget):
    def __init__(self,screen):
        super().__init__()
        self.setWindowTitle('GoPro gecikme ölçümü — geçici test')
        self.setGeometry(screen.geometry())
        self.image=None
        self.id=0
    def paintEvent(self,event):
        p=QPainter(self)
        p.fillRect(self.rect(),QColor('white'))
        size=min(self.width()//3-100,self.height()//3-80)
        if self.image:
            for row in range(2):
                for column in range(3):
                    x=int((column+.5)*self.width()/3-size/2)
                    y=int((row+.5)*(self.height()-140)/2-size/2)+70
                    p.drawImage(QRect(x,y,size,size),self.image)
        p.setPen(QColor('#111'))
        p.setFont(QFont('Segoe UI',20))
        p.drawText(40,50,'GOPRO · GECİKME TESTİ')
        p.drawText(40,self.height()-35,f'{self.id:03}  /  Test bitince pencere kapanacak')
windows=[Pattern(screen) for screen in app.screens()]
for window in windows:window.showFullScreen()
counter=0
def change_marker():
    global counter
    counter=(counter+1)%100
    marker=cv2.aruco.generateImageMarker(dictionary,counter,720)
    image=QImage(marker.data,720,720,marker.strides[0],QImage.Format.Format_Grayscale8).copy()
    issued[counter]=time.monotonic()
    for window in windows:
        window.id=counter
        window.image=image
        window.update()
marker_timer=QTimer()
marker_timer.timeout.connect(change_marker)
marker_timer.start(80)
change_marker()
api=CameraAPI()
worker=VideoStreamThread(preview_url(8554),camera_host=urlsplit(api.base_url).hostname)
worker.receiver_ready.connect(lambda: api.preview(True,8554))
worker.start()
worker.status_signal.connect(lambda msg: print(msg,flush=True))

def sample():
    global last_frame
    frame=worker.take_frame()
    if frame is not None:
        last_frame=frame
        corners,ids,_=detector.detectMarkers(frame)
        if ids is not None and time.monotonic()-started>6:
            marker_id=int(np.asarray(ids).reshape(-1)[0])
            if marker_id in issued and marker_id not in last_ids:
                latency=(time.monotonic()-issued[marker_id])*1000
                if 0<latency<10000:
                    latencies.append(latency)
                    last_ids.append(marker_id)
    if time.monotonic()-started>=args.seconds:
        timer.stop()
        marker_timer.stop()
        worker.stop()
        worker.wait(6000)
        api.preview(False)
        data={'backend':'direct-pyav','samples':len(latencies),'marker_interval_ms':80,'duration_s':args.seconds,'source_resolution':None if last_frame is None else [last_frame.shape[1],last_frame.shape[0]],'median_ms':round(statistics.median(latencies),1) if latencies else None,'p95_ms':round(sorted(latencies)[int(.95*(len(latencies)-1))],1) if latencies else None,'min_ms':round(min(latencies),1) if latencies else None,'max_ms':round(max(latencies),1) if latencies else None,'notes':'Optical screen-to-camera-to-PC age, includes 0–80 ms marker quantization plus screen refresh/detection; not ICMP ping.'}
        args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(data,ensure_ascii=False),flush=True)
        app.quit()
timer=QTimer()
timer.timeout.connect(sample)
timer.start(15)
app.exec()
