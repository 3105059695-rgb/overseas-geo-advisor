import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ENTRY = Path(__file__).resolve().parents[1] / 'scripts' / 'geo.py'


class EntryTests(unittest.TestCase):
    def test_setup_connects_sources_without_mutating_them(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = root / 'vault'
            vault.mkdir()
            original = '# 来源分类\n\n自有网站与第三方网站需要分别记录。\n'
            source = vault / 'source.md'
            source.write_text(original, encoding='utf-8')
            cfg = root / 'settings' / 'config.json'
            command = [sys.executable, '-B', '-X', 'utf8', str(ENTRY), '--config', str(cfg)]
            setup = subprocess.run(command + ['setup', '--vault', str(vault), '--data-dir', str(root / 'data')], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(setup.returncode, 0, setup.stderr + setup.stdout)
            self.assertEqual(json.loads(setup.stdout)['status'], 'configured')
            self.assertEqual(source.read_text(encoding='utf-8'), original)
            result = subprocess.run(command + ['search', '--question', '来源分类'], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['citations'])
            old_config = cfg.read_bytes()
            other = root / 'other'
            other.mkdir()
            refused = subprocess.run(command + ['setup', '--vault', str(other)], capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(cfg.read_bytes(), old_config)

    def test_unconfigured_command_fails_without_creating_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / 'not-created.json'
            result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ENTRY), '--config', str(cfg), 'ask', '--question', '海外信源'], capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['status'], 'unavailable')
            self.assertFalse(cfg.exists())


if __name__ == '__main__':
    unittest.main()
