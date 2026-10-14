"""Camera address and preview-port rules, independent of transports and UI."""
import ipaddress
from urllib.parse import urlsplit
from gopro_monitor.domain.errors import CameraError
from gopro_monitor.shared.i18n import tr

def validate_address(address):
    address = address.strip().rstrip('/')
    if '://' not in address:
        address = 'http://' + address
    parts = urlsplit(address)
    try:
        ip = ipaddress.ip_address(parts.hostname or '')
        port = parts.port
    except ValueError as exc:
        raise CameraError(tr('Geçerli bir kamera IP adresi girin.')) from exc
    permitted=any(ip in ipaddress.ip_network(network) for network in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','fc00::/7'))
    if parts.scheme != 'http' or not permitted or parts.username or parts.password or parts.path or parts.query or parts.fragment:
        raise CameraError(tr('Yerel kamera IP adresi gerekiyor (ör. 10.5.5.9).'))
    host = f'[{ip}]' if ip.version == 6 else str(ip)
    return f'http://{host}' + (f':{port}' if port else '')


def preview_url(port):
    return f'udp://0.0.0.0:{port}'
