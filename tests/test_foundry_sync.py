from pathlib import Path

from airreview.foundry_sync import (
    agent_refs,
    build_foundry_tools,
    load_agent_manifests,
    load_model_manifests,
    load_tool_manifests,
    sync_agents,
    sync_models,
)


def test_load_foundry_agent_manifests() -> None:
    repo = Path(__file__).resolve().parents[1]
    manifests = load_agent_manifests(repo)

    assert {manifest.name for manifest in manifests} == {
        "airreview-planning-agent",
        "airreview-codebase-context-agent",
        "airreview-codebase-context-worker-agent",
        "airreview-codebase-context-synthesis-agent",
        "airreview-branch-review-agent",
        "airreview-finding-critic-agent",
        "airreview-fix-suggestion-agent",
    }
    assert {manifest.model for manifest in manifests} == {
        "airreview-planning-mini",
        "airreview-context-mini",
        "airreview-context-worker-mini",
        "airreview-context-synthesis-mini",
        "airreview-review-codex",
        "airreview-critic-mini",
        "airreview-fix-codex",
    }
    tools_by_agent = {manifest.name: manifest.tools for manifest in manifests}
    assert tools_by_agent["airreview-planning-agent"] == ()
    assert tools_by_agent["airreview-branch-review-agent"] == ("context7_docs",)
    assert tools_by_agent["airreview-fix-suggestion-agent"] == ("context7_docs",)
    assert tools_by_agent["airreview-codebase-context-agent"] == ("airreview_file_search_knowledge",)
    assert tools_by_agent["airreview-codebase-context-worker-agent"] == ("airreview_file_search_knowledge",)
    assert tools_by_agent["airreview-codebase-context-synthesis-agent"] == ("airreview_file_search_knowledge",)
    assert tools_by_agent["airreview-finding-critic-agent"] == ()


def test_load_foundry_tool_manifests(monkeypatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    connection_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/res/projects/proj/connections/context7"
    monkeypatch.setenv("AIRREVIEW_CONTEXT7_CONNECTION_ID", connection_id)

    monkeypatch.setenv("AIRREVIEW_FILE_SEARCH_VECTOR_STORE_ID", "vs_v06qsV2mw5yTv2OC6sLddzIF")

    manifests = load_tool_manifests(repo)

    assert len(manifests) == 2
    manifest = next(item for item in manifests if item.key == "context7_docs")
    assert manifest.key == "context7_docs"
    assert manifest.type == "mcp"
    assert manifest.server_label == "context7"
    assert manifest.server_url == "https://mcp.context7.com/mcp"
    assert manifest.project_connection_id == connection_id
    assert manifest.require_approval == "never"
    assert manifest.allowed_tools == ("resolve-library-id", "query-docs")
    search_manifest = next(item for item in manifests if item.key == "airreview_file_search_knowledge")
    assert search_manifest.optional is True
    assert search_manifest.type == "file_search"
    assert search_manifest.vector_store_ids == ("vs_v06qsV2mw5yTv2OC6sLddzIF",)
    assert search_manifest.max_num_results == 5


def test_load_foundry_model_manifests() -> None:
    repo = Path(__file__).resolve().parents[1]
    manifests = load_model_manifests(repo)

    assert {manifest.key for manifest in manifests} == {
        "planning",
        "codebase_context",
        "codebase_context_worker",
        "codebase_context_synthesis",
        "branch_review",
        "finding_critic",
        "fix_suggestion",
    }
    assert any(manifest.deployment_name == "airreview-review-codex" for manifest in manifests)
    assert all(manifest.model_version == "auto" for manifest in manifests)


def test_sync_agents_dry_run() -> None:
    repo = Path(__file__).resolve().parents[1]
    rows = sync_agents(repo, dry_run=True)

    assert len(rows) == 7
    assert all(row["dry_run"] for row in rows)
    assert any(
        row["name"] == "airreview-branch-review-agent"
        and row["tools"] == ["context7_docs"]
        for row in rows
    )
    assert any(
        row["name"] == "airreview-codebase-context-agent"
        and row["tools"] == ["airreview_file_search_knowledge"]
        for row in rows
    )


def test_sync_models_dry_run() -> None:
    repo = Path(__file__).resolve().parents[1]
    rows = sync_models(repo, dry_run=True)

    assert len(rows) == 7
    assert all(row["status"] == "would_create" for row in rows)


def test_agent_refs_use_name_and_version() -> None:
    rows = [
        {"name": "airreview-planning-agent", "version": "1"},
        {"name": "airreview-branch-review-agent", "version": "2"},
    ]

    assert agent_refs(rows) == ["airreview-planning-agent:1", "airreview-branch-review-agent:2"]


def test_build_foundry_mcp_tool(monkeypatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    connection_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/res/projects/proj/connections/context7"
    monkeypatch.setenv("AIRREVIEW_CONTEXT7_CONNECTION_ID", connection_id)
    monkeypatch.delenv("AIRREVIEW_FILE_SEARCH_VECTOR_STORE_ID", raising=False)
    agent = next(manifest for manifest in load_agent_manifests(repo) if manifest.name == "airreview-branch-review-agent")
    tools_by_key = {manifest.key: manifest for manifest in load_tool_manifests(repo)}

    class FakeMCPTool:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    tools = build_foundry_tools(FakeMCPTool, agent, tools_by_key)

    assert len(tools) == 1
    assert tools[0].kwargs == {
        "server_label": "context7",
        "server_url": "https://mcp.context7.com/mcp",
        "require_approval": "never",
        "project_connection_id": connection_id,
        "allowed_tools": ["resolve-library-id", "query-docs"],
    }


def test_optional_file_search_tool_is_skipped_without_env(monkeypatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("AIRREVIEW_FILE_SEARCH_VECTOR_STORE_ID", raising=False)
    agent = next(manifest for manifest in load_agent_manifests(repo) if manifest.name == "airreview-codebase-context-agent")
    tools_by_key = {manifest.key: manifest for manifest in load_tool_manifests(repo)}

    class FakeMCPTool:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    assert build_foundry_tools(FakeMCPTool, agent, tools_by_key) == []


def test_optional_file_search_tool_builds_with_env(monkeypatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("AIRREVIEW_FILE_SEARCH_VECTOR_STORE_ID", "vs_v06qsV2mw5yTv2OC6sLddzIF")
    agent = next(manifest for manifest in load_agent_manifests(repo) if manifest.name == "airreview-codebase-context-agent")
    tools_by_key = {manifest.key: manifest for manifest in load_tool_manifests(repo)}

    class FakeMCPTool:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeFileSearchTool:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    tools = build_foundry_tools(
        FakeMCPTool,
        agent,
        tools_by_key,
        file_search_tool_cls=FakeFileSearchTool,
    )

    assert len(tools) == 1
    assert tools[0].kwargs == {
        "vector_store_ids": ["vs_v06qsV2mw5yTv2OC6sLddzIF"],
        "max_num_results": 5,
    }


def test_sync_models_resolves_auto_model_version(monkeypatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    calls: list[list[str]] = []

    def fake_run_az_json(args: list[str]):
        calls.append(args)
        if args[:3] == ["cognitiveservices", "account", "deployment"] and args[3] == "list":
            return []
        if args[:3] == ["cognitiveservices", "account", "show"]:
            return {"location": "eastus"}
        if args[:3] == ["cognitiveservices", "model", "list"]:
            return [
                {"name": "gpt-4.1-mini", "version": "2025-04-14", "format": "OpenAI"},
                {"name": "gpt-5-codex", "version": "2025-08-07", "format": "OpenAI"},
            ]
        if args[:4] == ["cognitiveservices", "account", "deployment", "create"]:
            return {}
        return {}

    monkeypatch.setenv("FOUNDRY_RESOURCE_GROUP", "rg")
    monkeypatch.setenv("FOUNDRY_RESOURCE_NAME", "resource")
    monkeypatch.setattr("airreview.foundry_sync.run_az_json", fake_run_az_json)

    rows = sync_models(repo)

    assert len(rows) == 7
    assert all(row["status"] == "created" for row in rows)
    create_calls = [call for call in calls if call[:4] == ["cognitiveservices", "account", "deployment", "create"]]
    assert len(create_calls) == 7
    assert all("--model-version" in call for call in create_calls)
