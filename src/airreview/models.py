from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any


class ModelClient(ABC):
    model_name: str
    provider_name: str = "unknown"

    @abstractmethod
    def complete_json(self, agent_name: str, instructions: str, payload: dict[str, Any]) -> str:
        ...


class MockModelClient(ModelClient):
    model_name = "mock"
    provider_name = "mock"

    def complete_json(self, agent_name: str, instructions: str, payload: dict[str, Any]) -> str:
        if agent_name == "Review Planning Agent":
            files = payload.get("changed_files", [])
            budget = payload.get("review_profile", {}).get("budget", {})
            chunk_size = int(budget.get("max_files_per_chunk", 8))
            max_chunks = int(budget.get("max_chunks", 4))
            chunks = [
                {"name": f"chunk-{index + 1}", "files": files[index * chunk_size : (index + 1) * chunk_size]}
                for index in range(min(max_chunks, max(1, (len(files) + chunk_size - 1) // chunk_size)))
            ]
            return json.dumps(
                {
                    "strategy": "chunked" if len(chunks) > 1 else "single_pass",
                    "chunks": chunks,
                    "skipped_files": files[chunk_size * max_chunks :],
                    "budget": {
                        "max_files_per_chunk": chunk_size,
                        "max_chunks": max_chunks,
                        "budget_exceeded": len(files) > chunk_size * max_chunks,
                    },
                    "rationale": "Mock planner groups files by configured budget to keep review cost bounded.",
                }
            )
        if agent_name == "Codebase Context Agent":
            return json.dumps(
                {
                    "relevant_guidelines": [
                        "Review the final branch state against the merge-base.",
                        "Prefer project-specific conventions over generic style advice.",
                        "Only report legacy smells when the branch introduces or worsens them.",
                    ],
                    "known_smells_to_ignore": ["Placeholder or draft knowledge entries are not review findings."],
                    "architecture_context": _architecture_context(payload),
                    "review_focus": ["changed behavior", "missing tests", "security-sensitive diffs", "configuration drift"],
                }
            )
        if agent_name == "Branch Review Agent":
            return json.dumps(_mock_review(payload))
        if agent_name == "Finding Critic Agent":
            findings = payload.get("findings", [])
            accepted = [item for item in findings if item.get("file") and item.get("confidence") != "low"]
            return json.dumps(
                {
                    "summary": f"Accepted {len(accepted)} finding(s); rejected {len(findings) - len(accepted)} noisy finding(s).",
                    "accepted_findings": accepted,
                    "rejected_findings": [
                        {
                            "title": item.get("title", "Finding"),
                            "reason": "Missing location or low confidence.",
                        }
                        for item in findings
                        if item not in accepted
                    ],
                }
            )
        if agent_name == "Fix Suggestion Agent":
            findings = payload.get("findings", [])
            return json.dumps(
                {
                    "suggestions": [
                        _mock_suggestion(item, payload)
                        for item in findings
                    ]
                }
            )
        return "{}"


class FoundryModelClient(ModelClient):
    def __init__(self) -> None:
        self.provider_name = "foundry"
        self.endpoint = first_env(
            "FOUNDRY_PROJECT_ENDPOINT",
            "AZURE_AI_PROJECT_ENDPOINT",
            "AZURE_AI_FOUNDRY_ENDPOINT",
            "FOUNDRY_ENDPOINT",
        )
        self.model_name = first_env(
            "FOUNDRY_MODEL",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME",
            "AZURE_AI_MODEL",
            default="gpt-5-mini",
        )
        self.api_key = first_env("FOUNDRY_API_KEY", "AZURE_AI_API_KEY")
        self.max_output_tokens = int(first_env("AIRREVIEW_MAX_OUTPUT_TOKENS", default="3000"))
        self.use_responses_api = first_env("AIRREVIEW_MODEL_API", default="chat").lower() == "responses"
        if not self.endpoint:
            raise RuntimeError(
                "Foundry endpoint is required outside --mock. Set FOUNDRY_PROJECT_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT "
                "to your Microsoft Foundry project endpoint."
            )

    def complete_json(self, agent_name: str, instructions: str, payload: dict[str, Any]) -> str:
        from openai import OpenAI

        base_url = normalize_openai_base_url(self.endpoint)
        api_key: str | Any
        if self.api_key:
            api_key = self.api_key
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
            api_key = token_provider()
        client = OpenAI(base_url=base_url, api_key=api_key)
        user_content = json.dumps(
            {
                "agent": agent_name,
                "payload": payload,
                "requirement": "Return only a strict JSON object matching the requested schema. No prose, no Markdown.",
            },
            ensure_ascii=False,
        )
        if self.use_responses_api:
            response = client.responses.create(
                model=self.model_name,
                instructions=instructions,
                input=user_content,
                max_output_tokens=self.max_output_tokens,
            )
            return response.output_text or "{}"
        response = self._chat_completion(client, instructions, user_content)
        return response.choices[0].message.content or "{}"

    def _chat_completion(self, client: Any, instructions: str, user_content: str) -> Any:
        base_kwargs = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_content},
            ],
        }
        attempts = [
            {"response_format": {"type": "json_object"}, "max_completion_tokens": self.max_output_tokens},
            {"response_format": {"type": "json_object"}, "max_tokens": self.max_output_tokens},
            {"max_completion_tokens": self.max_output_tokens},
            {"max_tokens": self.max_output_tokens},
            {},
        ]
        last_error: Exception | None = None
        for extra in attempts:
            try:
                return client.chat.completions.create(**base_kwargs, **extra)
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                if not any(token in message for token in ("response_format", "json", "max_tokens", "max_completion_tokens")):
                    raise
        raise RuntimeError(f"Foundry chat completion failed after compatibility fallbacks: {last_error}")


class FoundryAgentClient(ModelClient):
    provider_name = "foundry_agents"

    def __init__(self) -> None:
        self.endpoint = first_env(
            "FOUNDRY_PROJECT_ENDPOINT",
            "AZURE_AI_PROJECT_ENDPOINT",
            "AZURE_AI_FOUNDRY_ENDPOINT",
            "FOUNDRY_ENDPOINT",
        )
        self.model_name = "foundry-agent-service"
        self.api_key = first_env("FOUNDRY_API_KEY", "AZURE_AI_API_KEY")
        if not self.endpoint:
            raise RuntimeError("Foundry project endpoint is required for AIRREVIEW_AGENT_MODE=foundry_agents.")
        self.agent_names = {
            "Review Planning Agent": first_env("AIRREVIEW_FOUNDRY_PLANNING_AGENT", default="airreview-planning-agent"),
            "Codebase Context Agent": first_env("AIRREVIEW_FOUNDRY_CONTEXT_AGENT", default="airreview-codebase-context-agent"),
            "Branch Review Agent": first_env("AIRREVIEW_FOUNDRY_REVIEW_AGENT", default="airreview-branch-review-agent"),
            "Finding Critic Agent": first_env("AIRREVIEW_FOUNDRY_CRITIC_AGENT", default="airreview-finding-critic-agent"),
            "Fix Suggestion Agent": first_env("AIRREVIEW_FOUNDRY_FIX_AGENT", default="airreview-fix-suggestion-agent"),
        }

    def complete_json(self, agent_name: str, instructions: str, payload: dict[str, Any]) -> str:
        from openai import OpenAI

        base_url = normalize_openai_base_url(self.endpoint)
        api_key: str | Any
        if self.api_key:
            api_key = self.api_key
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
            api_key = token_provider()
        client = OpenAI(base_url=base_url, api_key=api_key)
        foundry_agent_name = self.agent_names.get(agent_name)
        if not foundry_agent_name:
            raise RuntimeError(f"No Foundry agent mapping configured for {agent_name}.")
        user_content = json.dumps(
            {
                "agent": agent_name,
                "payload": payload,
                "requirement": "Return only a strict JSON object matching the requested schema. No prose, no Markdown.",
            },
            ensure_ascii=False,
        )
        response = client.responses.create(
            model=first_env("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT_NAME", "AZURE_AI_MODEL", default="gpt-5-mini"),
            instructions=instructions,
            input=user_content,
            extra_body={"agent": {"name": foundry_agent_name, "type": "agent_reference"}},
        )
        return response.output_text or "{}"


def build_model_client(mock: bool) -> ModelClient:
    if mock:
        return MockModelClient()
    if first_env("AIRREVIEW_AGENT_MODE").lower() == "foundry_agents":
        return FoundryAgentClient()
    return FoundryModelClient()


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def normalize_openai_base_url(endpoint: str) -> str:
    cleaned = endpoint.rstrip("/")
    if cleaned.endswith("/openai/v1"):
        return cleaned
    return cleaned + "/openai/v1"


def _architecture_context(payload: dict[str, Any]) -> list[str]:
    metadata = payload.get("knowledge", {}).get("metadata", {})
    languages = ", ".join(metadata.get("languages", [])) or "unknown"
    return [f"Detected languages from local knowledge: {languages}.", "Use changed file context before generic inference."]


def _mock_review(payload: dict[str, Any]) -> dict[str, Any]:
    changed_files = payload.get("changed_files", [])
    diff = payload.get("diff", "")
    findings: list[dict[str, Any]] = []
    for path in changed_files:
        final = payload.get("final_files", {}).get(path, "")
        lowered = final.lower()
        if _contains_literal_secret(final):
            findings.append(
                {
                    "file": path,
                    "line": _line_for(final, ("password", "api_key", "secret")),
                    "severity": "high",
                    "category": "security",
                    "title": "Possible secret-like value introduced",
                    "issue": "The final file state contains an assignment that looks like a credential or secret.",
                    "why_it_matters": "Secrets in source can leak through Git history and pipeline logs.",
                    "confidence": "high",
                }
            )
        if "todo" in lowered and re.search(r"(?im)^\+.*todo", diff):
            findings.append(
                {
                    "file": path,
                    "line": _line_for(final, ("todo",)),
                    "severity": "medium",
                    "category": "maintainability",
                    "title": "New TODO needs an owner or follow-up",
                    "issue": "The branch appears to introduce a TODO without making the review expectation explicit.",
                    "why_it_matters": "Unowned TODOs become ambiguous review debt and are easy to lose after merge.",
                    "confidence": "medium",
                }
            )
    if not findings and changed_files:
        first = changed_files[0]
        findings.append(
            {
                "file": first,
                "line": 1,
                "severity": "medium",
                "category": "testability",
                "title": "Confirm branch behavior with a focused regression test",
                "issue": "The mock reviewer did not find a concrete bug, but changed branch behavior should be covered by a focused test for demo confidence.",
                "why_it_matters": "A small regression test makes the branch review reproducible and gives the pipeline a durable signal.",
                "confidence": "medium",
            }
        )
    return {
        "summary": f"Reviewed {len(changed_files)} changed file(s) against the target branch using local knowledge.",
        "findings": findings[:4],
    }


def _line_for(text: str, needles: tuple[str, ...]) -> int:
    for index, line in enumerate(text.splitlines(), start=1):
        if any(needle in line.lower() for needle in needles):
            return index
    return 1


def _contains_literal_secret(text: str) -> bool:
    pattern = re.compile(
        r"(?i)\b(password|api[_-]?key|secret|token)\b\s*=\s*['\"][^'\"]*(secret|key|token|password)[^'\"]*['\"]"
    )
    return bool(pattern.search(text))


def _mock_suggestion(item: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, str]:
    title = str(item.get("title", "Finding"))
    file = str(item.get("file", ""))
    final_file = str((payload or {}).get("final_files", {}).get(file, ""))
    if "secret" in title.lower():
        return {
            "finding_title": title,
            "suggestion": f"Remove the literal secret from `{file}` and read it from environment or a managed secret store.",
            "example": "import os\n\nAPI_KEY = os.environ[\"APP_API_KEY\"]",
            "test_recommendation": "Add a configuration test that fails when APP_API_KEY is missing and never asserts the secret value itself.",
            "confidence": str(item.get("confidence", "medium")),
        }
    if "todo" in title.lower():
        return {
            "finding_title": title,
            "suggestion": f"Replace the unowned TODO in `{file}` with implemented validation or a tracked follow-up identifier.",
            "example": _contextual_access_example(final_file),
            "test_recommendation": "Add tests for admin, support, inactive support, and unknown roles.",
            "confidence": str(item.get("confidence", "medium")),
        }
    if "regression test" in title.lower() or "test" in title.lower():
        return {
            "finding_title": title,
            "suggestion": f"Add a focused regression test near the existing tests for `{file}`.",
            "example": "def test_support_user_requires_active_status():\n    assert not can_access({\"role\": \"support\", \"status\": \"disabled\"})",
            "test_recommendation": "Cover the changed branch behavior with one failing-before/passing-after test.",
            "confidence": str(item.get("confidence", "medium")),
        }
    return {
        "finding_title": title,
        "suggestion": f"Apply a scoped fix in `{file}` and prefer the simplest API offered by the installed packages.",
        "example": "Keep the change local; avoid broad rewrites unless the package API requires it.",
        "test_recommendation": "Add or update a focused test when behavior changes.",
        "confidence": str(item.get("confidence", "medium")),
    }


def _contextual_access_example(final_file: str) -> str:
    if "def can_access(user):" in final_file and 'user.get("role")' in final_file:
        return (
            "def can_access(user):\n"
            "    if user.get(\"role\") == \"support\":\n"
            "        # TODO(PROJECT-123): allow support only after product-owner validation exists.\n"
            "        return False\n"
            "    return user.get(\"role\") == \"admin\""
        )
    return (
        "def can_access(user):\n"
        "    allowed_roles = {\"admin\", \"support\"}\n"
        "    return user.get(\"role\") in allowed_roles and user.get(\"status\") == \"active\""
    )
