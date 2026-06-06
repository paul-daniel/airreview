import json
import sys
from types import SimpleNamespace

from airreview.models import FoundryAgentClient, MockModelClient, RetryPolicy, call_with_retry, normalize_openai_base_url


def test_normalize_openai_base_url_appends_openai_v1() -> None:
    assert (
        normalize_openai_base_url("https://example.services.ai.azure.com/api/projects/proj")
        == "https://example.services.ai.azure.com/api/projects/proj/openai/v1"
    )


def test_normalize_openai_base_url_keeps_existing_openai_v1() -> None:
    assert normalize_openai_base_url("https://example/openai/v1") == "https://example/openai/v1"


def test_mock_fix_suggestion_uses_final_file_shape() -> None:
    payload = {
        "findings": [
            {
                "file": "app.py",
                "line": 3,
                "title": "New TODO needs an owner or follow-up",
                "confidence": "high",
            }
        ],
        "final_files": {
            "app.py": (
                "def can_access(user):\n"
                "    # TODO: add product owner validation before production\n"
                "    return user.get(\"role\") in [\"admin\", \"support\"]\n"
            )
        },
    }

    result = json.loads(MockModelClient().complete_json("Fix Suggestion Agent", "", payload))
    example = result["suggestions"][0]["example"]

    assert "def can_access(user):" in example
    assert 'user.get("role")' in example
    assert "user.role" not in example
    assert "resource" not in example
    assert "product_access_approved" not in example
    assert "return False" in example


def test_foundry_agent_client_uses_agent_reference(monkeypatch) -> None:
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text='{"ok": true}')

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/proj")
    monkeypatch.setenv("FOUNDRY_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    result = FoundryAgentClient().complete_json("Branch Review Agent", "system prompt", {"x": 1})

    assert json.loads(result) == {"ok": True}
    assert calls
    assert "instructions" not in calls[0]
    assert calls[0]["model"] == "airreview-review-codex"
    assert calls[0]["extra_body"] == {
        "agent_reference": {"name": "airreview-branch-review-agent", "type": "agent_reference"}
    }
    assert "runtime_instructions" in calls[0]["input"]


def test_rate_limit_retry_retries_429(monkeypatch) -> None:
    attempts = {"count": 0}
    sleeps = []

    class RateLimitError(Exception):
        status_code = 429

    def flaky_call():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RateLimitError("rate_limit_exceeded")
        return {"ok": True}

    monkeypatch.setattr("airreview.models.time.sleep", lambda seconds: sleeps.append(seconds))

    result = call_with_retry(flaky_call, RetryPolicy(2, [0.1], 0), "test agent")

    assert result == {"ok": True}
    assert attempts["count"] == 2
    assert sleeps == [0.1]
