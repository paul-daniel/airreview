from __future__ import annotations

import os
from pathlib import Path


AGENTS = [
    ("airreview-planning-agent", "src/airreview/prompts/review_planning_agent.md"),
    ("airreview-context-agent", "src/airreview/prompts/codebase_context_agent.md"),
    ("airreview-branch-review-agent", "src/airreview/prompts/branch_review_agent.md"),
    ("airreview-finding-critic-agent", "src/airreview/prompts/finding_critic_agent.md"),
    ("airreview-fix-suggestion-agent", "src/airreview/prompts/fix_suggestion_agent.md"),
]


def main() -> int:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT") or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    model = os.getenv("FOUNDRY_MODEL") or os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not endpoint or not model:
        print("Missing FOUNDRY_PROJECT_ENDPOINT/AZURE_AI_PROJECT_ENDPOINT or FOUNDRY_MODEL/AZURE_AI_MODEL_DEPLOYMENT_NAME.")
        print("Dry-run only. Set env vars to deploy agent prompt versions.")
        return 0
    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import PromptAgentDefinition
        from azure.identity import DefaultAzureCredential
    except Exception as exc:
        print("Missing optional Foundry SDK dependency.")
        print("Install with: pip install '.[foundry]'")
        print(f"Import error: {exc}")
        return 1

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    for agent_name, prompt_path in AGENTS:
        instructions = Path(prompt_path).read_text(encoding="utf-8")
        agent = project.agents.create_version(
            agent_name=agent_name,
            definition=PromptAgentDefinition(model=model, instructions=instructions),
        )
        print(f"Created/updated {agent.name} version {agent.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
