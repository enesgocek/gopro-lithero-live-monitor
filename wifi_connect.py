"""Explicit Windows camera Wi-Fi connection; secrets are never printed."""
from i18n import tr
import os
from pathlib import Path
# fixed Windows executable; no shell is used.
import subprocess  # nosec B404
import ctypes
from ctypes import wintypes
import re
# constructs escaped XML; never parses input.
import xml.etree.ElementTree as ET  # nosec B405
from PyQt6.QtCore import QThread, pyqtSignal

NS = 'http://www.microsoft.com/networking/WLAN/profile/v1'

def netsh(*arguments):
    executable=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'netsh.exe')
    # argument list; SSID is validated, shell=False.
    return subprocess.run([executable,'wlan',*arguments],capture_output=True,timeout=12,  # nosec B603
                          creationflags=subprocess.CREATE_NO_WINDOW)

def current_ssid():
    if os.name!='nt':return ''
    try:
        output=netsh('show','interfaces').stdout.decode('utf8',errors='replace')
        match=re.search(r'^\s*SSID\s*:\s*(.*?)\s*$',output,re.MULTILINE)
        return match.group(1) if match else ''
    except (OSError,subprocess.SubprocessError):return ''

def install_profile(ssid,password):
    """Pass XML in memory to Windows; never create a plaintext credential file."""
    if os.name!='nt':raise RuntimeError(tr('Wi-Fi ağını işletim sisteminizin ağ menüsünden seçin.'))
    if not isinstance(password,str) or not 8<=len(password)<=63 or any(ord(c)<32 or ord(c)>126 for c in password):
        raise RuntimeError(tr('Geçersiz kamera Wi-Fi parolası.'))
    class GUID(ctypes.Structure):
        _fields_=[('data1',wintypes.DWORD),('data2',wintypes.WORD),('data3',wintypes.WORD),('data4',ctypes.c_ubyte*8)]
    class Interface(ctypes.Structure):
        _fields_=[('guid',GUID),('description',wintypes.WCHAR*256),('state',wintypes.DWORD)]
    class ListHeader(ctypes.Structure):
        _fields_=[('count',wintypes.DWORD),('index',wintypes.DWORD)]
    dll=ctypes.WinDLL('wlanapi.dll',use_last_error=True)
    dll.WlanOpenHandle.argtypes=[wintypes.DWORD,ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.HANDLE)]
    dll.WlanEnumInterfaces.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
    dll.WlanSetProfile.argtypes=[wintypes.HANDLE,ctypes.POINTER(GUID),wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.BOOL,ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD)]
    dll.WlanFreeMemory.argtypes=[ctypes.c_void_p]
    dll.WlanCloseHandle.argtypes=[wintypes.HANDLE,ctypes.c_void_p]
    handle=wintypes.HANDLE()
    version=wintypes.DWORD()
    memory=ctypes.c_void_p()
    xml=None
    if dll.WlanOpenHandle(2,None,ctypes.byref(version),ctypes.byref(handle)):
        raise RuntimeError(tr('Windows WLAN API kullanılamıyor.'))
    try:
        if dll.WlanEnumInterfaces(handle,None,ctypes.byref(memory)):
            raise RuntimeError(tr('Windows Wi-Fi bağdaştırıcıları bulunamadı.'))
        count=ctypes.cast(memory,ctypes.POINTER(ListHeader)).contents.count
        if not 1<=count<=64:raise RuntimeError(tr('Kullanılabilir Wi-Fi bağdaştırıcısı yok.'))
        interfaces=(Interface*count).from_address(memory.value+ctypes.sizeof(ListHeader))
        ready=[interface for interface in interfaces if interface.state!=0]
        if not ready:raise RuntimeError(tr('Kullanılabilir Wi-Fi bağdaştırıcısı yok.'))
        selected=next((interface for interface in ready if interface.state==1),ready[0])
        xml=ctypes.create_unicode_buffer(profile_xml(ssid,password).decode('utf8'))
        reason=wintypes.DWORD()
        # WLAN_PROFILE_USER (2) scopes the encrypted Windows profile to this user.
        code=dll.WlanSetProfile(handle,ctypes.byref(selected.guid),2,xml,None,True,None,ctypes.byref(reason))
        if code:raise RuntimeError(tr('Windows kamera Wi-Fi profilini kaydedemedi.'))
    finally:
        if xml is not None:ctypes.memset(ctypes.addressof(xml),0,ctypes.sizeof(xml))
        if memory:dll.WlanFreeMemory(memory)
        dll.WlanCloseHandle(handle,None)

# empty credential default / reference release, not a secret.
def ensure_wifi(ssid,password='',update_profile=False,cancelled=lambda:False):  # nosec B107
    if os.name!='nt':raise RuntimeError(tr('Wi-Fi ağını işletim sisteminizin ağ menüsünden seçin.'))
    if not isinstance(ssid,str) or not ssid or len(ssid.encode('utf8'))>32 or any(ord(c)<32 for c in ssid):
        raise RuntimeError(tr('Geçersiz kamera ağ adı.'))
    if cancelled():raise RuntimeError(tr('Wi-Fi bağlantısı iptal edildi.'))
    if not update_profile and current_ssid()==ssid:return
    exists=netsh('show','profile',f'name={ssid}').returncode==0
    if not exists or update_profile:
        if not password:raise RuntimeError(tr('Kayıtlı kamera profili bulunamadı; Bluetooth ile ağ hazırlanmalı.'))
        install_profile(ssid,password)
    if cancelled():raise RuntimeError(tr('Wi-Fi bağlantısı iptal edildi.'))
    if netsh('connect',f'name={ssid}',f'ssid={ssid}').returncode:
        raise RuntimeError(tr('Windows kamera ağına bağlantıyı başlatamadı.'))

def profile_xml(ssid, password):
    ET.register_namespace('', NS)
    root = ET.Element(f'{{{NS}}}WLANProfile')
    def add(parent, tag, value=None):
        element = ET.SubElement(parent, f'{{{NS}}}{tag}')
        if value is not None:
            element.text = value
        return element
    add(root, 'name', ssid)
    config = add(root, 'SSIDConfig')
    network = add(config, 'SSID')
    add(network, 'hex', ssid.encode('utf-8').hex().upper())
    add(network, 'name', ssid)
    add(root, 'connectionType', 'ESS')
    add(root, 'connectionMode', 'manual')
    security = add(add(root, 'MSM'), 'security')
    auth = add(security, 'authEncryption')
    add(auth, 'authentication', 'WPA2PSK')
    add(auth, 'encryption', 'AES')
    add(auth, 'useOneX', 'false')
    key = add(security, 'sharedKey')
    add(key, 'keyType', 'passPhrase')
    add(key, 'protected', 'false')
    add(key, 'keyMaterial', password)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)

class WifiConnectWorker(QThread):
    completed = pyqtSignal(bool, str)
    # empty credential default / reference release, not a secret.
    def __init__(self, ssid, password='', parent=None):  # nosec B107
        super().__init__(parent)
        self.ssid, self.password = ssid, password

    def run(self):
        if os.name != 'nt':
            self.completed.emit(False, tr('Wi-Fi ağını işletim sisteminizin ağ menüsünden seçin.'))
            return
        try:
            ensure_wifi(self.ssid,self.password,cancelled=self.isInterruptionRequested)
            self.completed.emit(True, tr('Windows’a Wi-Fi bağlantı isteği gönderildi. Birkaç saniye sonra Kameraya Bağlan’a basın.'))
        except Exception:
            self.completed.emit(False,tr('Windows kamera ağına bağlantıyı başlatamadı.'))
        finally:
            # empty credential default / reference release, not a secret.
            self.password = ''  # nosec B105
