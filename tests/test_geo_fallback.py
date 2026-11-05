"""Routing tests: failures must neither fabricate evidence nor switch custom libraries."""
import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import geo_remote


class SnapshotFailure(Exception):
    def __init__(self, code='snapshot_network_error', message='GitHub unavailable'):
        super().__init__(message)
        self.code = code


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.result = {'status': 'ok', 'counts': {'documents': 977}, 'citations': []}
        self.factory = MagicMock()
        self.factory.return_value.call.return_value = self.result
        fake = SimpleNamespace(SnapshotClient=self.factory, SnapshotError=SnapshotFailure)
        self.modules = patch.dict(sys.modules, {'geo_snapshot': fake})
        self.modules.start()
        self.env = patch.dict('os.environ', {'GEO_MCP_URL': geo_remote.DEFAULT_URL})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.modules.stop()

    def test_successful_mcp_does_not_read_github(self):
        with patch.object(geo_remote.RemoteClient, 'call', return_value=self.result):
            result = geo_remote.KnowledgeClient().call('browse_geo_topics', {})
        self.assertEqual(result['transport']['used'], 'mcp')
        self.assertTrue(result['transport']['mcp_connected'])
        self.factory.assert_not_called()

    def test_http_403_switches_to_snapshot_and_reports_real_channel(self):
        error = geo_remote.RemoteError('http_error', 'HTTP 403', 403)
        with patch.object(geo_remote.RemoteClient, 'call', side_effect=error):
            result = geo_remote.KnowledgeClient().call('browse_geo_topics', {})
        self.assertEqual(result['counts']['documents'], 977)
        self.assertEqual(result['transport']['used'], 'github_snapshot')
        self.assertFalse(result['transport']['mcp_connected'])
        self.assertEqual(result['transport']['fallback_reason']['http_status'], 403)
        self.factory.return_value.call.assert_called_once_with('browse_geo_topics', {})

    def test_network_or_interception_failures_use_same_snapshot_path(self):
        for code in ['network_error', 'invalid_response', 'invalid_handshake']:
            with self.subTest(code=code), patch.object(geo_remote.RemoteClient, 'call', side_effect=geo_remote.RemoteError(code, 'failure')):
                result = geo_remote.KnowledgeClient().call('search_geo', {'question': '信源'})
                self.assertEqual(result['transport']['fallback_reason']['code'], code)
                self.assertEqual(result['transport']['used'], 'github_snapshot')

    def test_tool_unavailability_falls_back_but_invalid_arguments_do_not(self):
        with patch.object(geo_remote.RemoteClient, 'call', return_value={'status':'unavailable','error_code':'knowledge_read_failed'}):
            self.assertEqual(geo_remote.KnowledgeClient().call('browse_geo_topics', {})['transport']['used'], 'github_snapshot')
        self.factory.reset_mock()
        for status in ['error', 'not_found']:
            with self.subTest(status=status), patch.object(geo_remote.RemoteClient, 'call', return_value={'status': status}):
                result = geo_remote.KnowledgeClient().call('read_geo_source', {})
                self.assertEqual(result['status'], status)
                self.assertFalse(result['knowledge_lookup_completed'])
        self.factory.assert_not_called()

    def test_custom_service_is_not_silently_replaced_with_owner_corpus(self):
        with patch.object(geo_remote.RemoteClient, 'call', side_effect=geo_remote.RemoteError('network_error','down')):
            result = geo_remote.KnowledgeClient(url='https://example.org/mcp').call('browse_geo_topics', {})
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('fallback_disabled_reason', result['transport'])
        self.factory.assert_not_called()

    def test_explicit_github_skips_mcp(self):
        with patch.object(geo_remote.RemoteClient, 'call') as mcp:
            result = geo_remote.KnowledgeClient(transport='github').call('browse_geo_topics', {})
        mcp.assert_not_called()
        self.assertEqual(result['transport']['attempted'], ['github_snapshot'])

    def test_explicit_mcp_does_not_hide_failure(self):
        with patch.object(geo_remote.RemoteClient, 'call', side_effect=geo_remote.RemoteError('http_error','403',403)):
            result = geo_remote.KnowledgeClient(transport='mcp').call('browse_geo_topics', {})
        self.assertEqual(result['status'], 'unavailable')
        self.assertFalse(result['transport']['mcp_connected'])
        self.factory.assert_not_called()

    def test_protocol_argument_errors_are_not_reinterpreted_as_connectivity(self):
        with patch.object(geo_remote.RemoteClient, 'call', side_effect=geo_remote.RemoteError('rpc_error','invalid params')):
            result = geo_remote.KnowledgeClient().call('read_geo_source', {})
        self.assertEqual(result['status'], 'unavailable')
        self.factory.assert_not_called()

    def test_all_channels_fail_without_claiming_lookup_completed(self):
        self.factory.return_value.call.side_effect = SnapshotFailure()
        with patch.object(geo_remote.RemoteClient, 'call', side_effect=geo_remote.RemoteError('http_error','403',403)):
            result = geo_remote.KnowledgeClient().call('ask_geo', {'question':'GEO'})
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['citations'], [])
        self.assertEqual(result['answer_markdown'], '')
        self.assertFalse(result['knowledge_lookup_completed'])
        self.assertIsNone(result['transport']['used'])
        self.assertEqual(result['transport']['snapshot_error']['code'], 'snapshot_network_error')

    def test_integrity_failure_does_not_return_candidates(self):
        self.factory.return_value.call.side_effect = SnapshotFailure('integrity_error', 'Hash mismatch')
        result = geo_remote.KnowledgeClient(transport='github').call('browse_geo_topics', {})
        self.assertEqual(result['error_code'], 'integrity_error')
        self.assertFalse(result['knowledge_lookup_completed'])

    def test_cli_transport_reports_used_path(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = geo_remote.main(['--transport','github','--cache-dir','some-cache','status'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['transport']['used'], 'github_snapshot')
        self.factory.assert_called_once_with(timeout=60, cache_dir='some-cache')

    def test_invalid_input_never_reaches_either_network(self):
        with patch.object(geo_remote.RemoteClient, 'call') as mcp, contextlib.redirect_stdout(io.StringIO()):
            code = geo_remote.main(['--transport','auto','search','--question','x','--limit','999'])
        self.assertEqual(code, 2)
        mcp.assert_not_called()
        self.factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
