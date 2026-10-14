"""Remember camera identity; Windows WLAN profiles own all stored passwords."""
import json
import re
from pathlib import Path
from camera_api import validate_address,CameraError

DEFAULTS={'remember':True,'auto_connect':True,'device':'','device_name':'','ssid':'','address':'10.5.5.9','port':8554,'language':'en'}

class ConnectionStore:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(__file__).resolve().parent/'.connection.json'

    @staticmethod
    def validated(data):
        result=dict(DEFAULTS)
        if data.get('language') in ('en','tr'):result['language']=data['language']
        for key in ('remember','auto_connect'):
            if isinstance(data.get(key),bool):result[key]=data[key]
        device=data.get('device','')
        if isinstance(device,str) and re.fullmatch(r'([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',device):result['device']=device.upper()
        for key,limit in (('device_name',128),('ssid',32)):
            value=data.get(key,'')
            if isinstance(value,str) and len(value.encode('utf8'))<=limit and not any(ord(c)<32 for c in value):result[key]=value
        try:result['address']=validate_address(data.get('address',DEFAULTS['address']))
        except (CameraError,AttributeError,TypeError):pass
        port=data.get('port')
        if type(port) is int and 1024<=port<=65535:result['port']=port
        if not result['remember']:
            result.update(device='',device_name='',ssid='',auto_connect=False)
        return result

    def load(self):
        try:
            if self.path.stat().st_size>16384:return dict(DEFAULTS)
            data=json.loads(self.path.read_text(encoding='utf8'))
            return self.validated(data) if isinstance(data,dict) else dict(DEFAULTS)
        except (OSError,ValueError):return dict(DEFAULTS)

    def save(self,data):
        safe=self.validated(data)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(safe,ensure_ascii=False,indent=2),encoding='utf8')
            temporary.replace(self.path)
        finally:temporary.unlink(missing_ok=True)
        return safe
