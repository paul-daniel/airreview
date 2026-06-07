from airreview.config import ensure_airreview_dir, load_local_env, load_review_profile, parse_env_file


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


def test_parse_env_file_supports_export_and_quotes(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # comment
        export FOUNDRY_PROJECT_ENDPOINT="https://example"
        AIRREVIEW_AGENT_MODE=foundry_agents
        FOUNDRY_API_KEY='secret value'
        """,
        encoding="utf-8",
    )

    values = parse_env_file(env_file)

    assert values["FOUNDRY_PROJECT_ENDPOINT"] == "https://example"
    assert values["AIRREVIEW_AGENT_MODE"] == "foundry_agents"
    assert values["FOUNDRY_API_KEY"] == "secret value"


def test_load_local_env_reads_airreview_env_without_overriding_existing(tmp_path, monkeypatch) -> None:
    airreview_dir = ensure_airreview_dir(tmp_path)
    (airreview_dir / ".env").write_text(
        "FOUNDRY_PROJECT_ENDPOINT=https://from-file\nAIRREVIEW_AGENT_MODE=foundry_agents\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://already-exported")
    monkeypatch.delenv("AIRREVIEW_AGENT_MODE", raising=False)

    loaded = load_local_env(tmp_path)

    assert loaded == [airreview_dir / ".env"]
    assert __import__("os").environ["FOUNDRY_PROJECT_ENDPOINT"] == "https://already-exported"
    assert __import__("os").environ["AIRREVIEW_AGENT_MODE"] == "foundry_agents"
    assert ".env" in (airreview_dir / ".gitignore").read_text(encoding="utf-8")
