import json
from types import SimpleNamespace
from pathlib import Path

from airreview.agents import Finding, ReviewResult, Suggestion
from airreview.github import commentable_lines_from_diff, github_context, post_review_comments
from airreview.history import finding_fingerprint, load_review_result


def test_github_context_reads_pull_request_event(tmp_path: Path, monkeypatch) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 42, "head": {"sha": "abc123"}}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    context = github_context()

    assert context.pull_request_number == 42
    assert context.head_sha == "abc123"
    assert context.repository == "owner/repo"
    assert context.is_complete


def test_commentable_lines_from_diff_tracks_right_side_lines() -> None:
    diff = """diff --git a/src/app.ts b/src/app.ts
--- a/src/app.ts
+++ b/src/app.ts
@@ -1,3 +1,4 @@
 export function run() {
+  console.log("debug")
   return true
 }
"""

    lines = commentable_lines_from_diff(diff)

    assert lines["src/app.ts"] == {1, 2, 3, 4}


def test_post_review_comments_uses_inline_and_fallback(monkeypatch, tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 7, "head": {"sha": "head-sha"}}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    calls = []

    def fake_get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: [], text="")

    def fake_post(url, json=None, **kwargs):
        calls.append(("POST", url, json, kwargs))
        return SimpleNamespace(status_code=201, json=lambda: {"html_url": url, "url": url}, text="")

    def fake_delete(url, **kwargs):
        calls.append(("DELETE", url, kwargs))
        return SimpleNamespace(status_code=204, json=lambda: {}, text="")

    monkeypatch.setattr("airreview.github.requests.get", fake_get)
    monkeypatch.setattr("airreview.github.requests.post", fake_post)
    monkeypatch.setattr("airreview.github.requests.delete", fake_delete)
    result = ReviewResult(
        summary="Two findings.",
        findings=[
            Finding(
                file="src/app.ts",
                line=2,
                severity="high",
                category="security",
                title="Debug logging leaks data",
                issue="Debug log prints sensitive data.",
                why_it_matters="Logs can leak customer data.",
                confidence="high",
            ),
            Finding(
                file="src/missing-test.ts",
                line=99,
                severity="medium",
                category="testability",
                title="Missing regression test",
                issue="No changed diff line can host this comment.",
                why_it_matters="The issue still needs a separate PR comment.",
                confidence="medium",
            ),
        ],
        suggestions=[
            Suggestion(
                finding_title="Debug logging leaks data",
                suggestion="Remove the debug log before merge.",
                example='return sanitize(value)',
                test_recommendation="No test needed",
                confidence="high",
            )
        ],
    )
    diff = """diff --git a/src/app.ts b/src/app.ts
--- a/src/app.ts
+++ b/src/app.ts
@@ -1,2 +1,2 @@
 export function run() {
+  console.log(secret)
"""

    posted = post_review_comments(result, result.suggestions, diff, "# report")

    assert posted["posted"] is True
    post_urls = [call[1] for call in calls if call[0] == "POST"]
    assert any("/pulls/7/comments" in url for url in post_urls)
    assert sum("/issues/7/comments" in url for url in post_urls) == 2


def test_post_review_comments_skips_existing_finding_from_pr_state(monkeypatch, tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 8, "head": {"sha": "new-head"}}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    finding = Finding(
        file="src/app.ts",
        line=2,
        severity="high",
        category="security",
        title="Debug logging leaks data",
        issue="Debug log prints sensitive data.",
        why_it_matters="Logs can leak customer data.",
        confidence="high",
    )
    fingerprint = finding_fingerprint(finding)
    summary_body = "\n".join(
        [
            "<!-- airreview:summary -->",
            "<!-- airreview:state:v1",
            json.dumps(
                {
                    "version": 1,
                    "findings": {
                        fingerprint: {
                            "fingerprint": fingerprint,
                            "github_comment_id": 123,
                            "status": "open",
                        }
                    },
                }
            ),
            "-->",
        ]
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        return SimpleNamespace(
            status_code=200,
            json=lambda: [{"body": summary_body, "url": "https://api.github.test/comments/summary"}],
            text="",
        )

    def fake_post(url, json=None, **kwargs):
        calls.append(("POST", url, json, kwargs))
        return SimpleNamespace(status_code=201, json=lambda: {"html_url": url, "url": url, "id": 777}, text="")

    def fake_patch(url, json=None, **kwargs):
        calls.append(("PATCH", url, json, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"html_url": url, "url": url, "id": 1}, text="")

    monkeypatch.setattr("airreview.github.requests.get", fake_get)
    monkeypatch.setattr("airreview.github.requests.post", fake_post)
    monkeypatch.setattr("airreview.github.requests.patch", fake_patch)

    result = ReviewResult(summary="One finding.", findings=[finding])
    diff = """diff --git a/src/app.ts b/src/app.ts
--- a/src/app.ts
+++ b/src/app.ts
@@ -1,2 +1,2 @@
 export function run() {
+  console.log(secret)
"""

    posted = post_review_comments(result, [], diff, "# report")

    assert posted["skipped_existing"] == 1
    assert posted["new_comments"] == 0
    assert not [call for call in calls if call[0] == "POST"]
    assert [call for call in calls if call[0] == "PATCH"]


def test_load_review_result_from_saved_json(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    path.write_text(
        """{
          "summary": "Reviewed branch.",
          "findings": [
            {
              "file": "src/app.ts",
              "line": 4,
              "end_line": 6,
              "severity": "high",
              "category": "security",
              "title": "Unsafe access",
              "issue": "Problem",
              "why_it_matters": "Impact",
              "confidence": "high"
            }
          ],
          "suggestions": [
            {
              "finding_title": "Unsafe access",
              "suggestion": "Tighten the guard.",
              "example": "return false;",
              "test_recommendation": "Add a denial test.",
              "confidence": "high"
            }
          ],
          "plan": {"strategy": "single_pass"}
        }""",
        encoding="utf-8",
    )

    result = load_review_result(path)

    assert result.summary == "Reviewed branch."
    assert result.findings[0].file == "src/app.ts"
    assert result.findings[0].end_line == 6
    assert result.suggestions[0].finding_title == "Unsafe access"
    assert result.plan["strategy"] == "single_pass"
