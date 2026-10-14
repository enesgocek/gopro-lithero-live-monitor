"""Read-only, redacted local camera diagnostics. No snapshots or analytics."""
import argparse
import asyncio
import json
import sys
from camera_api import CameraAPI
from privacy import redact

async def scan(show_identifiers=False):
    from bleak import BleakScanner
    if sys.platform=='win32':
        from bleak.backends.winrt.util import uninitialize_sta
        uninitialize_sta()
    from ble_setup import SERVICE
    devices=await BleakScanner.discover(timeout=8,return_adv=True)
    found=[(device,adv) for device,adv in devices.values() if SERVICE in adv.service_uuids or 'gopro' in (device.name or adv.local_name or '').lower()]
    result=[]
    for number,(device,adv) in enumerate(found,1):
        item={'index':number,'name':redact(device.name or adv.local_name or 'GoPro')}
        if show_identifiers:item.update(name=device.name or adv.local_name,address=device.address)
        result.append(item)
    print(json.dumps(result,ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan',action='store_true',help='Read-only Bluetooth scan')
    parser.add_argument('--show-identifiers',action='store_true',help='Show private Bluetooth names and addresses; do not share this output')
    parser.add_argument('--ip',default='10.5.5.9')
    args=parser.parse_args()
    try:
        if args.scan:asyncio.run(scan(args.show_identifiers))
        else:
            api=CameraAPI(args.ip)
            info,state=api.info(),api.state()
            print(json.dumps({'model':info['model_name'],'firmware':info.get('firmware_version'),'recording':bool(state['10']),'preview_available':state.get('55'),'battery':state.get('70'),'sd_status':state.get('33')},ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f'Diagnostic failed: {type(exc).__name__}. Check camera power, Wi-Fi and pairing.',file=sys.stderr)
        return 1

if __name__=='__main__':
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf8')
    sys.exit(main())
