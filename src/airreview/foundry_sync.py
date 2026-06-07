from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AgentManifest:
    name: str
    prompt_file: Path
    model: str
    description: str
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelDeploymentManifest:
    key: str
    deployment_name: str
    model_name: str
    model_version: str
    model_format: str
    sku_name: str
    sku_capacity: int


@dataclass(frozen=True)
class ToolManifest:
    key: str
    type: str
    description: str
    server_label: str
    server_url: str
    require_approval: str
    project_connection_id: str
    connection_name: str
    allowed_tools: tuple[str, ...]
    index_name: str = ""
    query_type: str = "simple"
    top_k: int = 5
    filter: str = ""
    optional: bool = False


def sync_models(repo: Path, dry_run: bool = False, prune: bool = False) -> list[dict[str, Any]]:
    manifests = load_model_manifests(repo)
    resource_group = first_env("FOUNDRY_RESOURCE_GROUP", "AZURE_AI_RESOURCE_GROUP")
    resource_name = first_env("FOUNDRY_RESOURCE_NAME", "AZURE_AI_RESOURCE_NAME", "FOUNDRY_ACCOUNT_NAME")
    if dry_run:
        existing: dict[str, Any] = {}
    else:
        if not resource_group or not resource_name:
            raise RuntimeError(
                "Set FOUNDRY_RESOURCE_GROUP and FOUNDRY_RESOURCE_NAME before syncing model deployments."
            )
        existing = list_model_deployments(resource_group, resource_name)
    rows: list[dict[str, Any]] = []
    desired_names = {manifest.deployment_name for manifest in manifests}
    for manifest in manifests:
        current = existing.get(manifest.deployment_name)
        if current:
            rows.append(
                {
                    "key": manifest.key,
                    "deployment_name": manifest.deployment_name,
                    "model": manifest.model_name,
                    "sku": manifest.sku_name,
                    "capacity": manifest.sku_capacity,
                    "status": "exists",
                    "dry_run": dry_run,
                }
            )
            continue
        resolved_manifest = manifest
        if not dry_run:
            resolved_manifest = resolve_model_version(resource_group, resource_name, manifest)
        if not dry_run:
            create_model_deployment(resource_group, resource_name, resolved_manifest)
        rows.append(
            {
                "key": manifest.key,
                "deployment_name": manifest.deployment_name,
                "model": manifest.model_name,
                "model_version": resolved_manifest.model_version,
                "sku": manifest.sku_name,
                "capacity": manifest.sku_capacity,
                "status": "would_create" if dry_run else "created",
                "dry_run": dry_run,
            }
        )
    orphaned = [
        name
        for name in sorted(existing)
        if name.startswith("airreview-") and name not in desired_names
    ]
    for name in orphaned:
        status = "orphaned"
        if prune and not dry_run:
            delete_model_deployment(resource_group, resource_name, name)
            status = "deleted"
        rows.append({"deployment_name": name, "status": status, "dry_run": dry_run})
    return rows


def sync_agents(repo: Path, dry_run: bool = False) -> list[dict[str, Any]]:
    manifests = load_agent_manifests(repo)
    if dry_run:
        return [
            {
                "name": manifest.name,
                "model": manifest.model,
                "prompt_file": str(manifest.prompt_file.relative_to(repo)),
                "tools": list(manifest.tools),
                "dry_run": True,
            }
            for manifest in manifests
        ]
    endpoint = first_env("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_FOUNDRY_ENDPOINT")
    if not endpoint:
        raise RuntimeError("Set FOUNDRY_PROJECT_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT before syncing Foundry agents.")
    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import AISearchIndexResource
        from azure.ai.projects.models import AzureAISearchQueryType
        from azure.ai.projects.models import AzureAISearchToolResource
        from azure.ai.projects.models import MCPTool
        from azure.ai.projects.models import PromptAgentDefinition
        from azure.identity import DefaultAzureCredential
        try:
            from azure.ai.projects.models import AzureAISearchAgentTool as AzureAISearchToolClass
        except ImportError:
            from azure.ai.projects.models import AzureAISearchTool as AzureAISearchToolClass
    except ImportError as exc:
        raise RuntimeError(
            "Install optional Foundry dependencies with `pip install 'airreview[foundry]'`. "
            f"Import error: {exc}"
        ) from exc

    tool_manifests = {manifest.key: manifest for manifest in load_tool_manifests(repo, optional=True)}
    results: list[dict[str, Any]] = []
    with DefaultAzureCredential() as credential:
        with AIProjectClient(endpoint=endpoint, credential=credential) as project_client:
            for manifest in manifests:
                instructions = manifest.prompt_file.read_text(encoding="utf-8")
                tools = build_foundry_tools(
                    MCPTool,
                    manifest,
                    tool_manifests,
                    azure_ai_search_tool_cls=AzureAISearchToolClass,
                    azure_ai_search_resource_cls=AzureAISearchToolResource,
                    ai_search_index_resource_cls=AISearchIndexResource,
                    query_type_cls=AzureAISearchQueryType,
                    connection_resolver=lambda name: project_client.connections.get(connection_name=name).id,
                )
                agent = project_client.agents.create_version(
                    agent_name=manifest.name,
                    definition=PromptAgentDefinition(
                        model=manifest.model,
                        instructions=instructions,
                        tools=tools or None,
                    ),
                )
                results.append(
                    {
                        "name": agent.name,
                        "id": getattr(agent, "id", ""),
                        "version": getattr(agent, "version", ""),
                        "model": manifest.model,
                        "tools": list(manifest.tools),
                    }
                )
    return results


def agent_refs(rows: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for row in rows:
        if row.get("dry_run"):
            continue
        name = str(row.get("name") or "").strip()
        version = str(row.get("version") or "").strip()
        if not name or not version or version == "-":
            raise RuntimeError(f"Cannot build Foundry eval agent ref from sync result: {row}")
        refs.append(f"{name}:{version}")
    return refs


def load_agent_manifests(repo: Path) -> list[AgentManifest]:
    root = repo / "foundry" / "agents"
    models_by_key = {manifest.key: manifest for manifest in load_model_manifests(repo, optional=True)}
    if not root.exists():
        raise RuntimeError("No Foundry agent manifests found. Expected foundry/agents/*.yaml.")
    manifests: list[AgentManifest] = []
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        prompt = repo / str(raw.get("prompt_file", ""))
        if not prompt.exists():
            raise RuntimeError(f"Prompt file not found for {path}: {prompt}")
        model = str(raw.get("model") or "")
        model_key = str(raw.get("model_key") or "")
        if model_key:
            model_manifest = models_by_key.get(model_key)
            if not model_manifest:
                raise RuntimeError(f"Unknown model_key `{model_key}` in {path}.")
            model = model_manifest.deployment_name
        if model.startswith("${") and model.endswith("}"):
            model = os.getenv(model[2:-1], "")
        raw_tools = raw.get("tools", [])
        if raw_tools is None:
            raw_tools = []
        if not isinstance(raw_tools, list):
            raise RuntimeError(f"`tools` in {path} must be a list.")
        manifests.append(
            AgentManifest(
                name=str(raw["name"]),
                prompt_file=prompt,
                model=model or first_env("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT_NAME", default="gpt-5-mini"),
                description=str(raw.get("description", "")),
                tools=tuple(str(tool) for tool in raw_tools),
            )
        )
    if not manifests:
        raise RuntimeError("No Foundry agent manifests found. Expected foundry/agents/*.yaml.")
    return manifests


def load_tool_manifests(repo: Path, optional: bool = False) -> list[ToolManifest]:
    path = repo / "foundry" / "tools.yaml"
    if not path.exists():
        if optional:
            return []
        raise RuntimeError("No Foundry tool manifest found. Expected foundry/tools.yaml.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("tools", {})
    if not isinstance(entries, dict):
        raise RuntimeError("foundry/tools.yaml must contain a `tools` map.")
    manifests: list[ToolManifest] = []
    for key, value in entries.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"Tool manifest `{key}` must be an object.")
        allowed_tools = value.get("allowed_tools") or []
        if not isinstance(allowed_tools, list):
            raise RuntimeError(f"`allowed_tools` in tool manifest `{key}` must be a list.")
        manifests.append(
            ToolManifest(
                key=str(key),
                type=str(value.get("type") or "mcp"),
                description=str(value.get("description") or ""),
                server_label=str(value.get("server_label") or key),
                server_url=expand_env(str(value.get("server_url") or "")),
                require_approval=str(value.get("require_approval") or "never"),
                project_connection_id=expand_env(str(value.get("project_connection_id") or "")),
                connection_name=expand_env(str(value.get("connection_name") or "")),
                allowed_tools=tuple(str(tool) for tool in allowed_tools),
                index_name=expand_env(str(value.get("index_name") or "")),
                query_type=str(value.get("query_type") or "simple"),
                top_k=int(value.get("top_k") or 5),
                filter=str(value.get("filter") or ""),
                optional=bool(value.get("optional", False)),
            )
        )
    for manifest in manifests:
        if manifest.type not in {"mcp", "azure_ai_search"}:
            raise RuntimeError(f"Unsupported Foundry tool type `{manifest.type}` for `{manifest.key}`.")
        if manifest.type == "mcp" and not manifest.server_url and not manifest.optional:
            raise RuntimeError(f"Tool manifest `{manifest.key}` needs server_url.")
        if manifest.type == "azure_ai_search" and not manifest.index_name and not manifest.optional:
            raise RuntimeError(f"Tool manifest `{manifest.key}` needs index_name.")
        if (
            manifest.type == "azure_ai_search"
            and not manifest.project_connection_id
            and not manifest.connection_name
            and not manifest.optional
        ):
            raise RuntimeError(f"Tool manifest `{manifest.key}` needs project_connection_id or connection_name.")
    return manifests


def build_foundry_tools(
    mcp_tool_cls: Any,
    agent: AgentManifest,
    tools_by_key: dict[str, ToolManifest],
    *,
    azure_ai_search_tool_cls: Any | None = None,
    azure_ai_search_resource_cls: Any | None = None,
    ai_search_index_resource_cls: Any | None = None,
    query_type_cls: Any | None = None,
    connection_resolver: Any | None = None,
) -> list[Any]:
    foundry_tools: list[Any] = []
    for key in agent.tools:
        manifest = tools_by_key.get(key)
        if not manifest:
            raise RuntimeError(f"Agent `{agent.name}` references unknown Foundry tool `{key}`.")
        if manifest.type == "mcp" and manifest.optional and (not manifest.server_url or not manifest.project_connection_id):
            continue
        if manifest.type == "azure_ai_search" and manifest.optional and (
            not manifest.index_name or (not manifest.project_connection_id and not manifest.connection_name)
        ):
            continue
        if manifest.type == "azure_ai_search":
            foundry_tools.append(
                build_azure_ai_search_tool(
                    manifest,
                    azure_ai_search_tool_cls=azure_ai_search_tool_cls,
                    azure_ai_search_resource_cls=azure_ai_search_resource_cls,
                    ai_search_index_resource_cls=ai_search_index_resource_cls,
                    query_type_cls=query_type_cls,
                    connection_resolver=connection_resolver,
                )
            )
            continue
        kwargs: dict[str, Any] = {
            "server_label": manifest.server_label,
            "server_url": manifest.server_url,
            "require_approval": manifest.require_approval,
        }
        if manifest.project_connection_id:
            kwargs["project_connection_id"] = manifest.project_connection_id
        if manifest.allowed_tools:
            kwargs["allowed_tools"] = list(manifest.allowed_tools)
        try:
            foundry_tools.append(mcp_tool_cls(**kwargs))
        except TypeError as exc:
            raise RuntimeError(
                f"The installed azure-ai-projects SDK does not support the MCP tool fields used by `{key}`. "
                "Upgrade with `pip install --upgrade 'airreview[foundry]'`."
            ) from exc
    return foundry_tools


def build_azure_ai_search_tool(
    manifest: ToolManifest,
    *,
    azure_ai_search_tool_cls: Any | None,
    azure_ai_search_resource_cls: Any | None,
    ai_search_index_resource_cls: Any | None,
    query_type_cls: Any | None,
    connection_resolver: Any | None,
) -> Any:
    if not azure_ai_search_tool_cls or not azure_ai_search_resource_cls or not ai_search_index_resource_cls:
        raise RuntimeError("The installed azure-ai-projects SDK does not expose Azure AI Search agent tools.")
    connection_id = manifest.project_connection_id
    if not connection_id and manifest.connection_name:
        if not connection_resolver:
            raise RuntimeError(f"Tool manifest `{manifest.key}` needs a project_connection_id in dry construction.")
        connection_id = str(connection_resolver(manifest.connection_name))
    if not connection_id:
        raise RuntimeError(f"Tool manifest `{manifest.key}` needs project_connection_id or connection_name.")
    query_type: Any = manifest.query_type
    if query_type_cls:
        query_type = getattr(query_type_cls, manifest.query_type.upper(), manifest.query_type)
    index_kwargs: dict[str, Any] = {
        "project_connection_id": connection_id,
        "index_name": manifest.index_name,
        "query_type": query_type,
        "top_k": manifest.top_k,
    }
    if manifest.filter:
        index_kwargs["filter"] = manifest.filter
    try:
        index = ai_search_index_resource_cls(**index_kwargs)
        resource = azure_ai_search_resource_cls(indexes=[index])
        return azure_ai_search_tool_cls(azure_ai_search=resource)
    except TypeError as exc:
        raise RuntimeError(
            f"The installed azure-ai-projects SDK does not support the Azure AI Search tool fields used by `{manifest.key}`. "
            "Upgrade with `pip install --upgrade 'airreview[foundry]'`."
        ) from exc


def load_model_manifests(repo: Path, optional: bool = False) -> list[ModelDeploymentManifest]:
    path = repo / "foundry" / "models.yaml"
    if not path.exists():
        if optional:
            return []
        raise RuntimeError("No Foundry model manifest found. Expected foundry/models.yaml.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("models", {})
    if not isinstance(entries, dict) or not entries:
        raise RuntimeError("foundry/models.yaml must contain a non-empty `models` map.")
    manifests: list[ModelDeploymentManifest] = []
    for key, value in entries.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"Model manifest `{key}` must be an object.")
        manifests.append(
            ModelDeploymentManifest(
                key=str(key),
                deployment_name=str(value.get("deployment_name") or f"airreview-{key}"),
                model_name=str(value.get("model") or value.get("model_name") or ""),
                model_version=str(value.get("model_version") or "auto"),
                model_format=str(value.get("model_format") or "OpenAI"),
                sku_name=str(value.get("sku") or value.get("sku_name") or "GlobalStandard"),
                sku_capacity=int(value.get("capacity") or value.get("sku_capacity") or 10),
            )
        )
    for manifest in manifests:
        if not manifest.deployment_name or not manifest.model_name:
            raise RuntimeError(f"Model manifest `{manifest.key}` needs deployment_name and model.")
    return manifests


def list_model_deployments(resource_group: str, resource_name: str) -> dict[str, Any]:
    payload = run_az_json(
        [
            "cognitiveservices",
            "account",
            "deployment",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            resource_name,
        ]
    )
    if not isinstance(payload, list):
        return {}
    return {str(item.get("name")): item for item in payload if item.get("name")}


def resolve_model_version(resource_group: str, resource_name: str, manifest: ModelDeploymentManifest) -> ModelDeploymentManifest:
    if manifest.model_version and manifest.model_version.lower() != "auto":
        return manifest
    location = account_location(resource_group, resource_name)
    models = list_models(location)
    version = choose_model_version(models, manifest)
    if not version:
        raise RuntimeError(
            f"Could not resolve a model version for `{manifest.model_name}` in Azure region `{location}`. "
            "Set `model_version` explicitly in foundry/models.yaml, or choose a model available in that region."
        )
    return replace(manifest, model_version=version)


def account_location(resource_group: str, resource_name: str) -> str:
    payload = run_az_json(
        [
            "cognitiveservices",
            "account",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            resource_name,
        ]
    )
    location = str(payload.get("location") or "").strip() if isinstance(payload, dict) else ""
    if not location:
        raise RuntimeError(f"Could not resolve Azure region for Cognitive Services account `{resource_name}`.")
    return location


def list_models(location: str) -> list[dict[str, Any]]:
    payload = run_az_json(["cognitiveservices", "model", "list", "--location", location])
    return payload if isinstance(payload, list) else []


def choose_model_version(models: list[dict[str, Any]], manifest: ModelDeploymentManifest) -> str:
    candidates = [
        item
        for item in models
        if model_field(item, "name").lower() == manifest.model_name.lower()
        and (not model_field(item, "format") or model_field(item, "format").lower() == manifest.model_format.lower())
    ]
    versions = sorted({model_field(item, "version") for item in candidates if model_field(item, "version")})
    return versions[-1] if versions else ""


def model_field(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if value:
        return str(value)
    for nested_key in ("model", "properties"):
        nested = item.get(nested_key)
        if isinstance(nested, dict) and nested.get(key):
            return str(nested[key])
    return ""


def create_model_deployment(resource_group: str, resource_name: str, manifest: ModelDeploymentManifest) -> None:
    args = [
        "cognitiveservices",
        "account",
        "deployment",
        "create",
        "--resource-group",
        resource_group,
        "--name",
        resource_name,
        "--deployment-name",
        manifest.deployment_name,
        "--model-name",
        manifest.model_name,
        "--model-format",
        manifest.model_format,
        "--sku-name",
        manifest.sku_name,
        "--sku-capacity",
        str(manifest.sku_capacity),
        "--model-version",
        manifest.model_version,
    ]
    run_az_json(args)


def delete_model_deployment(resource_group: str, resource_name: str, deployment_name: str) -> None:
    run_az_json(
        [
            "cognitiveservices",
            "account",
            "deployment",
            "delete",
            "--resource-group",
            resource_group,
            "--name",
            resource_name,
            "--deployment-name",
            deployment_name,
            "--yes",
        ]
    )


def run_az_json(args: list[str]) -> Any:
    proc = subprocess.run(["az", *args, "-o", "json"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"az {' '.join(args)} failed")
    if not proc.stdout.strip():
        return {}
    return yaml.safe_load(proc.stdout)


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def expand_env(value: str) -> str:
    value = value.strip()
    if value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    return value
