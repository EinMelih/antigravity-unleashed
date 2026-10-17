"""Help and invalid arguments must never start an installation transaction."""

import ast
import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/repack_and_restart.py"


class RepackCliTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("repack_cli_test_module", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            spec.loader.exec_module(self.module)
        finally:
            sys.path.pop(0)
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        self.entry = compile(ast.Module(body=[tree.body[-1]], type_ignores=[]), str(SCRIPT), "exec")

    def invoke(self, arguments):
        with patch.object(self.module, "main", return_value=0) as install, patch.object(sys, "argv", [str(SCRIPT), *arguments]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            namespace = {**self.module.__dict__, "__name__": "__main__"}
            with self.assertRaises(SystemExit) as result:
                exec(self.entry, namespace)
            return result.exception.code, install.call_count

    def test_help_never_installs(self):
        status, calls = self.invoke(["--help"])
        self.assertEqual(0, status)
        self.assertEqual(0, calls)

    def test_unknown_argument_never_installs(self):
        status, calls = self.invoke(["--unknown-option"])
        self.assertEqual(2, status)
        self.assertEqual(0, calls)

    def test_normal_invocation_still_installs(self):
        self.assertEqual((0, 1), self.invoke([]))


if __name__ == "__main__":
    unittest.main()
