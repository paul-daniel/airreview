import json

from airreview.models import MockModelClient, normalize_openai_base_url


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
