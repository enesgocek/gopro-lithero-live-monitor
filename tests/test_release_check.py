"""Publication gate rejects accidental personal data and unapproved paths."""
import unittest
from tools.release_check import inspect_text,valid_path

class ReleaseCheckTests(unittest.TestCase):
    def test_private_paths_cannot_enter_release(self):
        for name in ('.connection.json','backups/main.py','artifacts/log.txt','captures/frame.jpg','RESTORATION.md','private.pem','notebook.ipynb','../outside.py'):
            with self.subTest(name=name):self.assertFalse(valid_path(name))

    def test_known_local_identity_is_detected_without_echoing_it(self):
        findings=inspect_text('Camera: synthetic-private-camera','README.md',('synthetic-private-camera',))
        self.assertEqual(findings,['local camera identity'])

    def test_synthetic_fixture_is_allowed_but_source_credential_is_blocked(self):
        text="password='synthetic-passphrase'"
        self.assertEqual(inspect_text(text,'tests/example.py'),[])
        self.assertIn('literal credential',inspect_text(text,'main.py'))

    def test_sample_device_address_is_only_a_nonsecret_fixture(self):
        self.assertEqual(inspect_text('02:00:00:00:00:01','tests/example.py'),[])

if __name__=='__main__':unittest.main()
