import contextlib
import hashlib
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from argparse import Namespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "knowledgekit.py"


def load_module() -> types.ModuleType:
    module_name = f"knowledgekit_test_{len([k for k in sys.modules if k.startswith('knowledgekit_test_')])}"
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda *args, **kwargs: {}
    yaml_stub.safe_dump = lambda *args, **kwargs: None
    sys.modules["yaml"] = yaml_stub

    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class KnowledgeKitTests(unittest.TestCase):
    def test_matches_ignore_for_subdir_relative_globs(self) -> None:
        mod = load_module()

        self.assertTrue(mod._matches_ignore(Path("inbox/.obsidian/workspace.json"), [".obsidian/**"]))
        self.assertTrue(mod._matches_ignore(Path("source/.trash/deleted.md"), [".trash/**"]))
        self.assertTrue(mod._matches_ignore(Path("inbox/~$draft.docx"), ["~$*"]))

    def test_record_rejects_output_outside_repo(self) -> None:
        mod = load_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".knowledgekit").mkdir()
            (root / "inbox").mkdir()
            (root / "source").mkdir()
            (root / "inbox" / "doc.txt").write_text("hello", encoding="utf-8")
            (root / "victim.md").write_text("outside", encoding="utf-8")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = mod.cmd_record(
                    root,
                    Namespace(
                        source="inbox/doc.txt",
                        output="../victim.md",
                        converter="test",
                        status="ok",
                        notes="",
                    ),
                )

            self.assertEqual(rc, 2)
            self.assertIn("リポジトリ外", stderr.getvalue())

    def test_scan_and_verify_report_missing_tracked_output(self) -> None:
        mod = load_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".knowledgekit").mkdir()
            (root / "inbox").mkdir()
            (root / "source").mkdir()
            source_path = root / "inbox" / "doc.txt"
            source_path.write_text("hello", encoding="utf-8")
            source_hash = "sha256:" + hashlib.sha256(b"hello").hexdigest()

            mod.load_config = lambda _root: {"ignore": []}
            mod.load_state = lambda _root: mod.State(
                entries=[
                    mod.Entry(
                        source="inbox/doc.txt",
                        source_hash=source_hash,
                        source_mtime="2026-01-01T00:00:00Z",
                        source_size=5,
                        output="source/doc.md",
                        output_hash="sha256:deadbeef",
                        converted_at="2026-01-01T00:00:00Z",
                        converter="test",
                        status="ok",
                    )
                ]
            )

            report = mod.scan(root)
            self.assertEqual(report["summary"]["output_missing"], 1)
            self.assertEqual(report["summary"]["unchanged"], 0)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = mod.cmd_verify(root, None)

            self.assertEqual(rc, 1)
            self.assertIn("不整合 1 件", stderr.getvalue())

    def test_prune_skips_invalid_output_path(self) -> None:
        mod = load_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            root = base / "repo"
            root.mkdir()
            (root / ".knowledgekit").mkdir()
            (root / "source").mkdir()
            outside = base / "victim.md"
            outside.write_text("outside", encoding="utf-8")

            mod.load_config = lambda _root: {"ignore": []}
            mod.load_state = lambda _root: mod.State(
                entries=[
                    mod.Entry(
                        source="inbox/missing.pdf",
                        output="../victim.md",
                        status="ok",
                    )
                ]
            )
            mod.save_state = lambda _root, _state: None

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = mod.cmd_prune(root, Namespace(dry_run=False))

            self.assertEqual(rc, 0)
            self.assertTrue(outside.exists())
            self.assertIn("削除をスキップ", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
