import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ENTRY = Path(__file__).resolve().parents[1] / 'scripts' / 'geo.py'


class EntryTests(unittest.TestCase):
    def test_empty_entry_declares_github_without_loading_local_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / 'config.json'
            cfg.write_text('existing malformed local config', encoding='utf-8')
            env = dict(os.environ, GEO_ADVISOR_CONFIG=str(cfg), GEO_KB_DB=str(Path(td) / 'unused.sqlite3'))
            run = subprocess.run([sys.executable, '-S', '-B', '-X', 'utf8', str(ENTRY)],
                                 env=env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            result = json.loads(run.stdout)
            self.assertEqual(result['default'], 'github_snapshot')
            self.assertIn('workflow', result['commands'])
            self.assertEqual([p.name for p in Path(td).iterdir()], ['config.json'])

    def test_fresh_standard_library_client_skips_mcp_sqlite_and_optional_models(self):
        # -S removes third-party site packages. Only snapshot I/O is stubbed;
        # the actual entry/parser/client routing and imports are exercised.
        program = r'''
import contextlib, io, json, sys
sys.path.insert(0, sys.argv[1])
blocked = {'mcp', 'onnxruntime', 'numpy', 'tokenizers', 'sqlite3', 'geo_kb', 'geo_mcp', 'geo_vectors', 'geo_workflow_mcp'}
class ForbiddenImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise AssertionError('unexpected dependency: ' + fullname)
sys.meta_path.insert(0, ForbiddenImports())
import geo, geo_remote, geo_snapshot
calls = []
def snapshot_call(self, name, arguments):
    calls.append((name, arguments))
    return {'status': 'ok', 'citations': []}
def forbidden_mcp(*args, **kwargs):
    raise AssertionError('MCP must not be attempted')
geo_snapshot.SnapshotClient.call = snapshot_call
geo_remote.RemoteClient.call = forbidden_mcp
results = []
for args in (['status'], ['ask', '--question', 'GPT喜欢哪些信源'], ['search', '--question', '来源类别']):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = geo.main(args)
    assert code == 0, output.getvalue()
    result = json.loads(output.getvalue())
    assert result['transport']['attempted'] == ['github_snapshot'], result
    results.append(result)
assert not (blocked & set(sys.modules)), blocked & set(sys.modules)
print(json.dumps({'results': results, 'tools': [name for name, _ in calls]}))
'''
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / 'existing-config.json'
            cfg.write_text('not JSON; default must never read this', encoding='utf-8')
            env = dict(os.environ, GEO_ADVISOR_CONFIG=str(cfg), GEO_KB_DB=str(root / 'unused.sqlite3'),
                       GEO_MCP_URL='not a valid URL', LOCALAPPDATA=str(root))
            run = subprocess.run([sys.executable, '-S', '-B', '-X', 'utf8', '-c', program, str(ENTRY.parent)],
                                 env=env, cwd=td, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            result = json.loads(run.stdout)
            self.assertEqual(result['tools'], ['browse_geo_topics', 'ask_geo', 'search_geo'])
            self.assertEqual(list(root.rglob('*.sqlite3')), [])
            self.assertEqual(cfg.read_text(encoding='utf-8'), 'not JSON; default must never read this')
            self.assertEqual([p.name for p in root.iterdir()], ['existing-config.json'])

    def test_local_maintenance_requires_explicit_mode(self):
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GEO_ADVISOR_CONFIG=str(Path(td) / 'absent.json'))
            for command in ('setup', 'build', 'review'):
                with self.subTest(command=command):
                    run = subprocess.run([sys.executable, '-S', '-B', '-X', 'utf8', str(ENTRY), command],
                                         env=env, capture_output=True, text=True, encoding='utf-8')
                    self.assertEqual(run.returncode, 2)
                    self.assertIn('--local', json.loads(run.stdout)['error'])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_workflow_still_routes_to_new_workflow_entry(self):
        run = subprocess.run([sys.executable, '-S', '-B', '-X', 'utf8', str(ENTRY), 'workflow',
                              'plan', '--question', '品牌提及率怎么算', '--today', '2026-11-05'],
                             capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual(json.loads(run.stdout)['understanding']['task'], 'metric_definition')

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
