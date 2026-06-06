from airreview.config import load_review_profile


def test_review_profile_env_overrides_budget(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIRREVIEW_MAX_FINDINGS", "5")
    monkeypatch.setenv("AIRREVIEW_MAX_FILES_PER_CHUNK", "3")
    monkeypatch.setenv("AIRREVIEW_MAX_DIFF_CHARS_PER_CHUNK", "12000")
    monkeypatch.setenv("AIRREVIEW_MAX_CHUNKS", "2")
    monkeypatch.setenv("AIRREVIEW_STOP_WHEN_BUDGET_EXCEEDED", "true")

    profile = load_review_profile(tmp_path)

    assert profile.max_findings == 5
    assert profile.max_files_per_chunk == 3
    assert profile.max_diff_chars_per_chunk == 12000
    assert profile.max_chunks == 2
    assert profile.stop_when_budget_exceeded is True
