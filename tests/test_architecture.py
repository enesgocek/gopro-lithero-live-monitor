"""Keep business workflows independent of GUI and concrete adapters."""
import ast
from pathlib import Path
import unittest
from gopro_monitor.domain.errors import CameraError
from gopro_monitor.infrastructure.image_decoder import OriginalMediaDecoder

ROOT=Path(__file__).resolve().parents[1]

class ArchitectureTests(unittest.TestCase):
    def test_domain_and_application_have_no_framework_or_adapter_imports(self):
        banned=('PyQt6','av','cv2','numpy','gopro_monitor.infrastructure','gopro_monitor.presentation')
        for layer in ('domain','application'):
            for path in (ROOT/'src/gopro_monitor'/layer).glob('*.py'):
                for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
                    modules=[item.name for item in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
                    for module in modules:
                        with self.subTest(file=path.name,module=module):
                            self.assertFalse(any(module==prefix or module.startswith(prefix+'.') for prefix in banned))

    def test_preferences_still_use_existing_project_root_file(self):
        from gopro_monitor.infrastructure.connection_store import ConnectionStore
        self.assertEqual(ConnectionStore().path,ROOT/'.connection.json')

    def test_invalid_photo_and_video_data_raise_safe_camera_errors(self):
        decoder=OriginalMediaDecoder()
        for method in (decoder.photo,decoder.video):
            for content in (b'',b'not camera media'):
                with self.subTest(method=method.__name__,content=content),self.assertRaises(CameraError):method(content)

if __name__=='__main__':unittest.main()
