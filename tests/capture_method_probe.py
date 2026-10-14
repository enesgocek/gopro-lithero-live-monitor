"""Compare native photo/video framing methods on an idle camera, RAM only."""
from pathlib import Path
import sys
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from gopro_monitor.infrastructure.camera_api import CameraAPI,CameraError
from gopro_monitor.application.quality_capture import QualityCapture
from gopro_monitor.infrastructure.image_decoder import OriginalMediaDecoder

def report(value):
    print(json.dumps(value,ensure_ascii=False),flush=True)

def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf8',errors='replace')
    api=CameraAPI()
    if api.state()['10']:raise CameraError('Existing recording preserved')
    before=set(api.media())
    preset=api.state()['97']
    for kind in ('photo','video'):
        capture=QualityCapture(api,lambda msg:report({'stage':msg}),decoder=OriginalMediaDecoder()).capture(kind)
        report({'method':kind,'width':capture['width'],'height':capture['height'],'elapsed_s':capture['elapsed_s'],'bytes':capture['source_bytes'],'cleaned':capture['camera_cleaned'],'restored_preset':api.state()['97']})
        assert capture['camera_cleaned'] and not capture.get('restore_warning')
        assert api.state()['97']==preset
        assert set(api.media())==before
        del capture

if __name__=='__main__':main()
