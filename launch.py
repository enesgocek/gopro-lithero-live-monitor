"""Start with explicit trusted import paths, without Python/Qt startup injection."""
import os
from pathlib import Path
import runpy
import sys

def prepare_runtime():
    if not sys.flags.isolated or not sys.flags.no_site:
        raise RuntimeError('Use start.cmd or launch with Python -I -S.')
    root=Path(__file__).resolve().parent
    packages=root/'.venv'/'Lib'/'site-packages'
    if not packages.is_dir():
        raise RuntimeError('Run setup.ps1 to install the verified local dependencies.')
    # Keep only interpreter standard-library paths, this project and its own venv.
    base=Path(sys.base_prefix).resolve()
    standard=[str(base/f'python{sys.version_info.major}{sys.version_info.minor}.zip'),str(base/'DLLs'),str(base/'Lib')]
    sys.path[:]=[*standard,str(root),str(packages)]
    for key in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QT_QPA_FONTDIR','OPENSSL_CONF','OPENSSL_MODULES'):
        os.environ.pop(key,None)
    os.environ['QT_QPA_PLATFORM']='windows'
    if os.name=='nt':
        import ctypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.SetDefaultDllDirectories.argtypes=[ctypes.c_uint32]
        api.SetDefaultDllDirectories.restype=ctypes.c_int
        # System / application / explicitly registered directories, not CWD/PATH.
        if not api.SetDefaultDllDirectories(0x1000):
            raise RuntimeError('Windows could not apply the safe DLL search policy.')
    return root

def main():
    try:
        root=prepare_runtime()
        runpy.run_path(str(root/'main.py'),run_name='__main__')
        return 0
    except Exception:
        message='GoPro LitHero Live Monitor could not start. Run setup.ps1, then use start.cmd. No private error log was saved.'
        if sys.stderr is not None:
            print(message,file=sys.stderr)
        elif os.name=='nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,'GoPro LitHero Live Monitor',0x10)
        return 1

if __name__=='__main__':sys.exit(main())
