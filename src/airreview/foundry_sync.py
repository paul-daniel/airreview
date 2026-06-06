from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AgentManifest:
    name: str
    prompt_file: Path
    model: str
    description: str


def sync_agents(repo: Path, dry_run: bool = False) -> list[dict[str, Any]]:
    manifests = load_agent_manifests(repo)
    if dry_run:
        return [
            {
                "name": manifest.name,
                "model": manifest.model,
                "prompt_file": str(manifest.prompt_file.relative_to(repo)),
                "dry_run": True,
            }
            for manifest in manifests
        ]
    endpoint = first_env("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_FOUNDRY_ENDPOINT")
    if not endpoint:
        raise RuntimeError("Set FOUNDRY_PROJECT_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT before syncing Foundry agents.")
    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import PromptAgentDefinition
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError("Install optional Foundry dependencies with `pip install 'airreview[foundry]'`.") from exc

    results: list[dict[str, Any]] = []
    with DefaultAzureCredential() as credential:
        with AIProjectClient(endpoint=endpoint, credential=credential) as project_client:
            for manifest in manifests:
                instructions = manifest.prompt_file.read_text(encoding="utf-8")
                agent = project_client.agents.create_version(
                    agent_name=manifest.name,
                    definition=PromptAgentDefinition(model=manifest.model, instructions=instructions),
                )
                results.append(
                    {
                        "name": agent.name,
                        "id": getattr(agent, "id", ""),
                        "version": getattr(agent, "version", ""),
                        "model": manifest.model,
                    }
                )
    return results


def load_agent_manifests(repo: Path) -> list[AgentManifest]:
    root = repo / "foundry" / "agents"
    if not root.exists():
        raise RuntimeError("No Foundry agent manifests found. Expected foundry/agents/*.yaml.")
    manifests: list[AgentManifest] = []
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        prompt = repo / str(raw.get("prompt_file", ""))
        if not prompt.exists():
            raise RuntimeError(f"Prompt file not found for {path}: {prompt}")
        model = str(raw.get("model") or "")
        if model.startswith("${") and model.endswith("}"):
            model = os.getenv(model[2:-1], "")
        manifests.append(
            AgentManifest(
                name=str(raw["name"]),
                prompt_file=prompt,
                model=model or first_env("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT_NAME", default="gpt-5-mini"),
                description=str(raw.get("description", "")),
            )
        )
    if not manifests:
        raise RuntimeError("No Foundry agent manifests found. Expected foundry/agents/*.yaml.")
    return manifests


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default
