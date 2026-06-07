from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .agents import Finding, ReviewResult, Suggestion
from .history import diff_hash, finding_fingerprint, serialize_finding


AIRREVIEW_MARKER_PREFIX = "<!-- airreview:"
AIRREVIEW_SUMMARY_MARKER = "<!-- airreview:summary -->"
AIRREVIEW_STATE_MARKER = "<!-- airreview:state:v1"


@dataclass(frozen=True)
class GitHubContext:
    repository: str
    server_url: str
    api_url: str
    event_name: str
    event_path: str
    pull_request_number: int | None
    head_sha: str
    token_present: bool

    @property
    def is_pull_request(self) -> bool:
        return bool(self.pull_request_number)

    @property
    def is_complete(self) -> bool:
        return bool(self.repository and self.pull_request_number and self.token_present)


def github_context() -> GitHubContext:
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    event = _event_payload(event_path)
    return GitHubContext(
        repository=os.getenv("GITHUB_REPOSITORY", ""),
        server_url=os.getenv("GITHUB_SERVER_URL", "https://github.com"),
        api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
        event_name=os.getenv("GITHUB_EVENT_NAME", ""),
        event_path=event_path,
        pull_request_number=_pull_request_number_from_payload(event),
        head_sha=_head_sha_from_payload(event),
        token_present=bool(os.getenv("GITHUB_TOKEN")),
    )


def post_pr_comment(markdown: str, dry_run: bool = False) -> dict[str, Any]:
    context = github_context()
    if dry_run:
        return {"posted": False, "dry_run": True, "context_complete": context.is_complete}
    if not context.is_complete:
        raise RuntimeError(
            "GitHub context is incomplete. Run in a pull_request workflow with pull-requests: write permission and GITHUB_TOKEN."
        )
    url = f"{context.api_url.rstrip('/')}/repos/{context.repository}/issues/{context.pull_request_number}/comments"
    response = requests.post(
        url,
        json={"body": markdown},
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"GitHub PR comment failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    return {"posted": True, "status_code": response.status_code, "url": payload.get("html_url")}


def post_review_comments(
    result: ReviewResult,
    suggestions: list[Suggestion],
    diff: str,
    summary_markdown: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Post one GitHub comment per finding, preferring inline PR comments.

    GitHub only accepts inline review comments on lines present in the pull
    request diff. Findings outside those lines fall back to normal PR
    conversation comments so every issue still gets its own comment.
    """
    context = github_context()
    commentable = commentable_lines_from_diff(diff)
    if dry_run:
        inline_count = sum(1 for finding in result.findings if inline_payload_for_finding(context, finding, commentable))
        return {
            "posted": False,
            "dry_run": True,
            "context_complete": context.is_complete,
            "inline_comments": inline_count,
            "fallback_comments": len(result.findings) - inline_count,
            "summary_comment": True,
        }
    if not context.is_complete:
        raise RuntimeError(
            "GitHub context is incomplete. Run in a pull_request workflow with pull-requests: write permission, "
            "issues: write permission, and GITHUB_TOKEN."
        )
    if not context.head_sha:
        raise RuntimeError("GitHub pull request head SHA is missing from the event payload.")

    posted: list[dict[str, Any]] = []
    issue_comments = list_issue_comments(context)
    state = airreview_state_from_comments(issue_comments)
    state.setdefault("version", 1)
    state["repository"] = context.repository
    state["pull_request"] = context.pull_request_number
    state["head_sha"] = context.head_sha
    state["diff_hash"] = diff_hash(diff)
    state_findings = state.setdefault("findings", {})
    if not isinstance(state_findings, dict):
        state_findings = {}
        state["findings"] = state_findings

    current_fingerprints: set[str] = set()
    skipped_existing = 0
    for finding in result.findings:
        fingerprint = finding_fingerprint(finding)
        current_fingerprints.add(fingerprint)
        previous = state_findings.get(fingerprint)
        if isinstance(previous, dict) and previous.get("github_comment_id"):
            previous.update(
                {
                    "status": "open",
                    "last_seen_head_sha": context.head_sha,
                    "file": finding.file,
                    "line": finding.line,
                    "end_line": finding.end_line,
                    "severity": finding.severity,
                    "confidence": finding.confidence,
                }
            )
            skipped_existing += 1
            continue
        suggestion = find_suggestion(finding, suggestions)
        body = finding_comment_body(finding, suggestion, fingerprint)
        inline_payload = inline_payload_for_finding(context, finding, commentable)
        if inline_payload:
            try:
                payload = post_inline_comment(context, {**inline_payload, "body": body})
                posted.append({"kind": "inline", "file": finding.file, "line": finding.line, "url": payload.get("html_url")})
                state_findings[fingerprint] = state_entry_for_finding(finding, fingerprint, context, payload, "inline")
                continue
            except RuntimeError:
                # Fall back to a normal PR comment when GitHub rejects a line
                # because it is no longer commentable on the current diff.
                pass
        payload = post_issue_comment(context, fallback_comment_body(finding, body))
        posted.append({"kind": "fallback", "file": finding.file, "line": finding.line, "url": payload.get("html_url")})
        state_findings[fingerprint] = state_entry_for_finding(finding, fingerprint, context, payload, "fallback")

    resolved_count = 0
    for fingerprint, item in list(state_findings.items()):
        if fingerprint in current_fingerprints or not isinstance(item, dict) or item.get("status") == "resolved":
            continue
        item["status"] = "resolved"
        item["resolved_head_sha"] = context.head_sha
        resolved_count += 1

    summary = upsert_summary_comment(context, issue_comments, summary_body(summary_markdown, result, state))
    posted.append({"kind": "summary", "url": summary.get("html_url")})
    return {
        "posted": True,
        "comments": posted,
        "new_comments": len([item for item in posted if item.get("kind") not in {"summary"}]),
        "skipped_existing": skipped_existing,
        "resolved": resolved_count,
    }


def load_pr_review_state(dry_run: bool = False) -> dict[str, Any]:
    context = github_context()
    if dry_run or not context.is_complete:
        return {}
    return airreview_state_from_comments(list_issue_comments(context))


def commentable_lines_from_diff(diff: str) -> dict[str, set[int]]:
    lines_by_file: dict[str, set[int]] = {}
    current_file = ""
    new_line: int | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current_file = ""
            new_line = None
            continue
        if line.startswith("+++ b/"):
            current_file = line.removeprefix("+++ b/")
            lines_by_file.setdefault(current_file, set())
            continue
        if line.startswith("@@ "):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            new_line = int(match.group(1)) if match else None
            continue
        if not current_file or new_line is None or line.startswith("\\"):
            continue
        if line.startswith("-"):
            continue
        if line.startswith("+") or line.startswith(" "):
            lines_by_file.setdefault(current_file, set()).add(new_line)
            new_line += 1
    return lines_by_file


def inline_payload_for_finding(
    context: GitHubContext, finding: Finding, commentable: dict[str, set[int]]
) -> dict[str, Any] | None:
    if not finding.file or not finding.line or not context.head_sha:
        return None
    lines = commentable.get(finding.file, set())
    end_line = finding.end_line if finding.end_line and finding.end_line >= finding.line else finding.line
    wanted = set(range(finding.line, end_line + 1))
    if not wanted.issubset(lines):
        return None
    payload: dict[str, Any] = {
        "commit_id": context.head_sha,
        "path": finding.file,
        "line": end_line,
        "side": "RIGHT",
    }
    if end_line > finding.line:
        payload["start_line"] = finding.line
        payload["start_side"] = "RIGHT"
    return payload


def cleanup_previous_airreview_comments(context: GitHubContext) -> None:
    for comment in list_issue_comments(context):
        if AIRREVIEW_MARKER_PREFIX in str(comment.get("body", "")):
            delete_url(context, str(comment.get("url", "")))
    for comment in list_pull_review_comments(context):
        if AIRREVIEW_MARKER_PREFIX in str(comment.get("body", "")):
            delete_url(context, str(comment.get("url", "")))


def list_issue_comments(context: GitHubContext) -> list[dict[str, Any]]:
    url = f"{context.api_url.rstrip('/')}/repos/{context.repository}/issues/{context.pull_request_number}/comments"
    return list_response(context, url)


def list_pull_review_comments(context: GitHubContext) -> list[dict[str, Any]]:
    url = f"{context.api_url.rstrip('/')}/repos/{context.repository}/pulls/{context.pull_request_number}/comments"
    return list_response(context, url)


def list_response(context: GitHubContext, url: str) -> list[dict[str, Any]]:
    response = requests.get(url, headers=github_headers(context), timeout=30)
    if response.status_code >= 300:
        raise RuntimeError(f"GitHub list comments failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    return payload if isinstance(payload, list) else []


def post_inline_comment(context: GitHubContext, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{context.api_url.rstrip('/')}/repos/{context.repository}/pulls/{context.pull_request_number}/comments"
    response = requests.post(url, json=payload, headers=github_headers(context), timeout=30)
    if response.status_code >= 300:
        raise RuntimeError(f"GitHub inline review comment failed: {response.status_code} {response.text[:500]}")
    return response.json()


def post_issue_comment(context: GitHubContext, body: str) -> dict[str, Any]:
    url = f"{context.api_url.rstrip('/')}/repos/{context.repository}/issues/{context.pull_request_number}/comments"
    response = requests.post(url, json={"body": body}, headers=github_headers(context), timeout=30)
    if response.status_code >= 300:
        raise RuntimeError(f"GitHub PR comment failed: {response.status_code} {response.text[:500]}")
    return response.json()


def delete_url(context: GitHubContext, url: str) -> None:
    if not url:
        return
    response = requests.delete(url, headers=github_headers(context), timeout=30)
    if response.status_code >= 300 and response.status_code != 404:
        raise RuntimeError(f"GitHub comment cleanup failed: {response.status_code} {response.text[:500]}")


def github_headers(context: GitHubContext) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def airreview_state_from_comments(comments: list[dict[str, Any]]) -> dict[str, Any]:
    for comment in comments:
        state = extract_airreview_state(str(comment.get("body", "")))
        if state:
            return state
    return {"version": 1, "findings": {}}


def extract_airreview_state(body: str) -> dict[str, Any]:
    start = body.find(AIRREVIEW_STATE_MARKER)
    if start < 0:
        return {}
    start = body.find("\n", start)
    if start < 0:
        return {}
    end = body.find("\n-->", start)
    if end < 0:
        return {}
    try:
        payload = json.loads(body[start:end].strip())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def state_entry_for_finding(
    finding: Finding, fingerprint: str, context: GitHubContext, payload: dict[str, Any], kind: str
) -> dict[str, Any]:
    entry = serialize_finding(finding)
    entry.update(
        {
            "fingerprint": fingerprint,
            "status": "open",
            "first_seen_head_sha": context.head_sha,
            "last_seen_head_sha": context.head_sha,
            "github_comment_id": payload.get("id"),
            "github_comment_url": payload.get("html_url"),
            "github_comment_api_url": payload.get("url"),
            "comment_kind": kind,
        }
    )
    return entry


def upsert_summary_comment(context: GitHubContext, comments: list[dict[str, Any]], body: str) -> dict[str, Any]:
    for comment in comments:
        if AIRREVIEW_SUMMARY_MARKER in str(comment.get("body", "")):
            return patch_comment(context, str(comment.get("url", "")), body)
    return post_issue_comment(context, body)


def patch_comment(context: GitHubContext, url: str, body: str) -> dict[str, Any]:
    if not url:
        return post_issue_comment(context, body)
    response = requests.patch(url, json={"body": body}, headers=github_headers(context), timeout=30)
    if response.status_code >= 300:
        raise RuntimeError(f"GitHub summary update failed: {response.status_code} {response.text[:500]}")
    return response.json()


def finding_comment_body(finding: Finding, suggestion: Suggestion | None, fingerprint: str) -> str:
    location = f"{finding.file}:{finding.line}" if finding.line else finding.file or "repository"
    parts = [
        f"<!-- airreview:finding:{fingerprint} -->",
        f"### AirReview: {finding.severity.upper()} - {finding.title}",
        "",
        f"**Location:** `{location}`",
        f"**Category:** `{finding.category}`",
        f"**Confidence:** `{finding.confidence}`",
        "",
        f"**Issue:** {finding.issue}",
        "",
        f"**Why it matters:** {finding.why_it_matters}",
    ]
    if suggestion:
        parts.extend(["", f"**Suggested fix:** {suggestion.suggestion}"])
        if suggestion.example:
            parts.extend(["", "**Suggested code:**", "", *code_block_lines(suggestion.example, finding.file)])
        if has_test_recommendation(suggestion.test_recommendation):
            parts.extend(["", f"**Test:** {suggestion.test_recommendation}"])
    return "\n".join(parts)


def fallback_comment_body(finding: Finding, body: str) -> str:
    if finding.file and finding.line:
        return body + "\n\n_Note: AirReview could not attach this to the exact diff line, so it posted it in the PR conversation._"
    return body


def summary_body(markdown: str, result: ReviewResult, state: dict[str, Any] | None = None) -> str:
    counts: dict[str, int] = {}
    for finding in result.findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    count_text = ", ".join(f"{severity}: {count}" for severity, count in sorted(counts.items())) or "no findings"
    parts = [
        AIRREVIEW_SUMMARY_MARKER,
        "## AirReview summary",
        "",
        result.summary or "Review completed.",
        "",
        f"Findings: {count_text}.",
        memory_summary_line(state),
        "",
        "AirReview posts one comment per new finding and keeps a hidden PR memory to avoid duplicates.",
        "",
        "<details>",
        "<summary>Full Markdown report</summary>",
        "",
        markdown,
        "",
        "</details>",
    ]
    if state is not None:
        parts.extend(
            [
                "",
                f"{AIRREVIEW_STATE_MARKER}",
                json.dumps(state, sort_keys=True, separators=(",", ":")),
                "-->",
            ]
        )
    return "\n".join(parts)


def memory_summary_line(state: dict[str, Any] | None) -> str:
    if state is None:
        return "PR memory: not written."
    findings = state.get("findings", {})
    if not isinstance(findings, dict):
        findings = {}
    open_count = sum(1 for item in findings.values() if isinstance(item, dict) and item.get("status", "open") != "resolved")
    resolved_count = sum(1 for item in findings.values() if isinstance(item, dict) and item.get("status") == "resolved")
    diff = str(state.get("diff_hash", ""))[:8] or "unknown"
    return f"PR memory: {open_count} open, {resolved_count} resolved, diff `{diff}`."


def code_block_lines(text: str, path: str = "") -> list[str]:
    language = language_for_path(path)
    stripped = text.strip()
    if language == "text" and (stripped.startswith(("def ", "class ", "import ", "from ", "return ")) or "pytest" in stripped):
        language = "python"
    elif language == "text" and (stripped.startswith(("const ", "let ", "export ", "function ")) or "=>" in stripped):
        language = "typescript"
    elif language == "text" and stripped.startswith(("{", "[")):
        language = "json"
    return [f"```{language}", text, "```"]


def language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".cs": "csharp",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".json": "json",
    }.get(suffix, "text")


def find_suggestion(finding: Finding, suggestions: list[Suggestion]) -> Suggestion | None:
    for suggestion in suggestions:
        if suggestion.finding_title == finding.title:
            return suggestion
    return None


def has_test_recommendation(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(normalized) and normalized not in {"no test needed", "n/a", "none", "not needed", "aucun test necessaire", "aucun test nécessaire"}


def _event_payload(event_path: str) -> dict[str, Any]:
    if not event_path:
        return {}
    path = Path(event_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _pull_request_number(event_path: str) -> int | None:
    return _pull_request_number_from_payload(_event_payload(event_path))


def _pull_request_number_from_payload(payload: dict[str, Any]) -> int | None:
    number = payload.get("pull_request", {}).get("number") or payload.get("number")
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def _head_sha_from_payload(payload: dict[str, Any]) -> str:
    value = payload.get("pull_request", {}).get("head", {}).get("sha") or os.getenv("GITHUB_SHA") or ""
    return str(value)
