import json
from pathlib import Path

from airreview.github import github_context


def test_github_context_reads_pull_request_event(tmp_path: Path, monkeypatch) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 42}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    context = github_context()

    assert context.pull_request_number == 42
    assert context.repository == "owner/repo"
    assert context.is_complete
