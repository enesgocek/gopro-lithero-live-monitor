"""Check the supported launcher rejects ambient Python/Qt injection."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from launch import prepare_runtime

ROOT=Path(__file__).resolve().parents[1]

class LauncherTests(unittest.TestCase):
    def test_nonisolated_python_is_rejected(self):
        with patch('launch.sys.flags',SimpleNamespace(isolated=0,no_site=0)):
            with self.assertRaisesRegex(RuntimeError,'-I -S'):prepare_runtime()

    @unittest.skipUnless(os.name=='nt','Windows launcher')
    def test_foreign_python_startup_and_qt_plugin_paths_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            private=Path(folder)
            marker=private/'startup-loaded.txt'
            # Harmless sentinel: this file must never be imported or executed.
            (private/'sitecustomize.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("loaded")\n',encoding='utf8')
            environment=dict(os.environ)
            environment.update(PYTHONPATH=str(private),PYTHONSTARTUP=str(private/'sitecustomize.py'),QT_PLUGIN_PATH=str(private),QT_QPA_PLATFORM_PLUGIN_PATH=str(private))
            executable=ROOT/'.venv'/'Scripts'/'python.exe'
            result=subprocess.run([str(executable),'-I','-S',str(ROOT/'launch.py'),'--demo','--smoke-test'],cwd=private,env=environment,capture_output=True,timeout=25)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            self.assertFalse(marker.exists())

if __name__=='__main__':unittest.main()
