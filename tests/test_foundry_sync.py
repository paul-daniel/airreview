from pathlib import Path

from airreview.foundry_sync import agent_refs, load_agent_manifests, load_model_manifests, sync_agents, sync_models


def test_load_foundry_agent_manifests() -> None:
    repo = Path(__file__).resolve().parents[1]
    manifests = load_agent_manifests(repo)

    assert {manifest.name for manifest in manifests} == {
        "airreview-planning-agent",
        "airreview-codebase-context-agent",
        "airreview-branch-review-agent",
        "airreview-finding-critic-agent",
        "airreview-fix-suggestion-agent",
    }
    assert {manifest.model for manifest in manifests} == {
        "airreview-planning-mini",
        "airreview-context-mini",
        "airreview-review-codex",
        "airreview-critic-mini",
        "airreview-fix-codex",
    }


def test_load_foundry_model_manifests() -> None:
    repo = Path(__file__).resolve().parents[1]
    manifests = load_model_manifests(repo)

    assert {manifest.key for manifest in manifests} == {
        "planning",
        "codebase_context",
        "branch_review",
        "finding_critic",
        "fix_suggestion",
    }
    assert any(manifest.deployment_name == "airreview-review-codex" for manifest in manifests)


def test_sync_agents_dry_run() -> None:
    repo = Path(__file__).resolve().parents[1]
    rows = sync_agents(repo, dry_run=True)

    assert len(rows) == 5
    assert all(row["dry_run"] for row in rows)


def test_sync_models_dry_run() -> None:
    repo = Path(__file__).resolve().parents[1]
    rows = sync_models(repo, dry_run=True)

    assert len(rows) == 5
    assert all(row["status"] == "would_create" for row in rows)


def test_agent_refs_use_name_and_version() -> None:
    rows = [
        {"name": "airreview-planning-agent", "version": "1"},
        {"name": "airreview-branch-review-agent", "version": "2"},
    ]

    assert agent_refs(rows) == ["airreview-planning-agent:1", "airreview-branch-review-agent:2"]
