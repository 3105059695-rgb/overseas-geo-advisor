import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import geo_remote


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((payload, dict(self.headers)))
        mode = self.server.mode
        if mode == 'http_error':
            self.send_response(503)
            self.end_headers()
            return
        if mode == 'redirect':
            self.send_response(302)
            self.send_header('Location', '/login')
            self.end_headers()
            return
        if mode == 'html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html>Login required</html>')
            return
        if payload['method'] == 'notifications/initialized':
            self.send_response(202)
            self.end_headers()
            return
        if payload['method'] == 'initialize':
            result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fixture', 'version': '1'}}
            if mode == 'unsupported_protocol':
                result['protocolVersion'] = 'unknown-version'
        else:
            data = {'status': 'partial', 'answer_kind': 'evidence_packet', 'citations': [{'document_id': 'doc-1', 'source_version': 'abc', 'line_start': 1, 'line_end': 2}]}
            if mode == 'tool_error':
                data = {'status': 'unavailable', 'error_code': 'data_unavailable', 'citations': []}
            result = {'content': [{'type': 'text', 'text': json.dumps(data)}], 'structuredContent': data, 'isError': mode == 'tool_error'}
        message = {'jsonrpc': '2.0', 'id': payload['id'] if mode != 'wrong_id' else 999, 'result': result}
        if mode == 'rpc_error':
            message = {'jsonrpc': '2.0', 'id': payload['id'], 'error': {'code': -32601, 'message': 'Unknown method'}}
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(message).encode())


@contextlib.contextmanager
def fixture(mode='normal'):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.requests = []
    server.mode = mode
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f'http://127.0.0.1:{server.server_port}/api/mcp'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class RemoteTests(unittest.TestCase):
    def test_handshake_and_query_without_credentials_or_local_database(self):
        with fixture() as (server, url):
            result = geo_remote.RemoteClient(url).call('ask_geo', {'question': '海外信源怎么分？'})
            self.assertEqual(result['answer_kind'], 'evidence_packet')
            self.assertEqual([x[0]['method'] for x in server.requests], ['initialize', 'notifications/initialized', 'tools/call'])
            self.assertEqual(server.requests[-1][0]['params']['arguments']['question'], '海外信源怎么分？')
            for _, headers in server.requests:
                self.assertNotIn('Authorization', headers)
                self.assertIn('application/json', headers['Accept'])

    def test_http_login_redirect_is_not_followed(self):
        with fixture('redirect') as (server, url):
            with self.assertRaises(geo_remote.RemoteError) as raised:
                geo_remote.RemoteClient(url).call('browse_geo_topics', {})
            self.assertEqual(raised.exception.code, 'http_error')
            self.assertEqual(len(server.requests), 1)

    def test_invalid_html_wrong_id_and_protocol_fail_closed(self):
        for mode, code in [('html', 'invalid_response'), ('wrong_id', 'invalid_response'), ('unsupported_protocol', 'invalid_handshake'), ('rpc_error', 'rpc_error')]:
            with self.subTest(mode=mode), fixture(mode) as (_, url):
                with self.assertRaises(geo_remote.RemoteError) as raised:
                    geo_remote.RemoteClient(url).call('browse_geo_topics', {})
                self.assertEqual(raised.exception.code, code)

    def test_failed_tool_remains_unavailable(self):
        with fixture('tool_error') as (_, url):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = geo_remote.main(['--url', url, 'browse'])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())['status'], 'unavailable')

    def test_network_failure_reports_no_lookup(self):
        with patch.object(geo_remote.RemoteClient, 'initialize', side_effect=geo_remote.RemoteError('network_error', '网络未连接')):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = geo_remote.main(['--transport', 'mcp', 'browse'])
            result = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertFalse(result['knowledge_lookup_completed'])
            self.assertEqual(result['citations'], [])

    def test_input_bounds_reject_without_network(self):
        for args in [['search', '--question', '引用', '--limit', '21'], ['ask', '--question', ' '], ['ask', '--question', '引用', '--as-of', '2025-02-30'], ['read', '--document-id', 'd', '--source-version', 'v', '--start-line', '8', '--end-line', '2']]:
            with self.subTest(args=args), patch.object(geo_remote.RemoteClient, 'call') as call, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(geo_remote.main(args), 2)
                call.assert_not_called()

    def test_urls_do_not_allow_credentials_non_https_or_query(self):
        for url in ['http://example.org/mcp', 'https://user:secret@example.org/mcp', 'https://example.org/mcp?key=secret', 'file:///secret', 'https://example.org/mcp#fragment']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                geo_remote.validate_url(url)
        self.assertEqual(geo_remote.validate_url('https://example.org/mcp'), 'https://example.org/mcp')

    def test_fresh_entry_uses_remote_and_creates_no_local_config(self):
        with fixture() as (_, url), tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / 'absent.json'
            env = dict(os.environ, GEO_ADVISOR_CONFIG=str(cfg), GEO_MCP_URL=url)
            env.pop('GEO_KB_DB', None)
            run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT / 'scripts/geo.py'), 'ask', '--question', '海外信源'], env=env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertEqual(json.loads(run.stdout)['status'], 'partial')
            self.assertFalse(cfg.exists())
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_explicit_remote_ignores_existing_local_db(self):
        with fixture() as (_, url), tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / 'local.json'
            cfg.write_text(json.dumps({'db': str(Path(td) / 'not-present.sqlite3')}))
            env = dict(os.environ, GEO_ADVISOR_CONFIG=str(cfg), GEO_MCP_URL=url)
            env.pop('GEO_KB_DB', None)
            run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT / 'scripts/geo.py'), '--remote', 'browse'], env=env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertFalse((Path(td) / 'not-present.sqlite3').exists())

    def test_remote_config_needs_no_network_or_local_setup(self):
        env = dict(os.environ, GEO_MCP_URL='https://example.org/api/mcp')
        run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT / 'scripts/geo.py'), 'remote-config'], env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(run.returncode, 0, run.stderr)
        config = json.loads(run.stdout)['mcpServers']['overseas-geo-advisor']
        self.assertEqual(config, {'type': 'http', 'url': 'https://example.org/api/mcp'})


if __name__ == '__main__':
    unittest.main()
