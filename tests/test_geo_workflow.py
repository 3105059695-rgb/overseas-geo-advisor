"""Public workflow must not inherit a maintainer's old local configuration."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from geo_workflow import main, load


class WorkflowEntryTests(unittest.TestCase):
    def test_implicit_environment_config_cannot_redirect_public_default(self):
        with patch.dict(os.environ, {"GEO_WORKFLOW_CONFIG": "missing-private-maintainer-config.json"}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["plan", "--question", "Claude 和 Grok 的信源？"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["version"], "0.5.0")

    def test_windows_bom_json_and_explicit_missing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.json"
            path.write_text('{"keywords":["Claude"]}', encoding="utf-8-sig")
            self.assertEqual(load(path)["keywords"], ["Claude"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--config", str(path.with_name("missing.json")), "plan", "--question", "Claude"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "error")


if __name__ == "__main__":
    unittest.main()
