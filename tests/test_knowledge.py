from pathlib import Path

from airreview.knowledge import LocalKnowledgeProvider


def test_bootstrap_generates_local_knowledge(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    provider = LocalKnowledgeProvider(tmp_path)
    status = provider.bootstrap(force=True)
    assert status.exists
    assert status.scanned_files >= 1
    assert "Python" in status.languages
    assert (tmp_path / ".airreview" / "codebase_guidelines.md").exists()
