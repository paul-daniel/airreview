from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

from .agents import Finding, ReviewResult, Suggestion
from .config import airreview_path


def review_dir_for_branch(repo: Path, branch: str) -> Path:
    safe_parts = [part for part in branch.replace("\\", "/").split("/") if part and part not in {".", ".."}]
    if not safe_parts:
        safe_parts = ["detached"]
    return airreview_path(repo) / "reviews" / Path(*safe_parts)


def default_markdown_path(repo: Path, branch: str) -> Path:
    return review_dir_for_branch(repo, branch) / "review.md"


def default_json_path(repo: Path, branch: str) -> Path:
    return review_dir_for_branch(repo, branch) / "review.json"


def load_previous_review(repo: Path, branch: str) -> dict[str, Any]:
    path = default_json_path(repo, branch)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_review_result(path: Path) -> ReviewResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    findings = [
        Finding(
            file=str(item.get("file", "")),
            line=int(item.get("line") or 0),
            end_line=int(item.get("end_line") or 0),
            severity=str(item.get("severity", "medium")),  # type: ignore[arg-type]
            category=str(item.get("category", "quality")),
            title=str(item.get("title", "Untitled finding")),
            issue=str(item.get("issue", "")),
            why_it_matters=str(item.get("why_it_matters", "")),
            confidence=str(item.get("confidence", "medium")),  # type: ignore[arg-type]
        )
        for item in payload.get("findings", [])
        if isinstance(item, dict)
    ]
    suggestions = [
        Suggestion(
            finding_title=str(item.get("finding_title", "")),
            suggestion=str(item.get("suggestion", "")),
            example=str(item.get("example", "")),
            test_recommendation=str(item.get("test_recommendation", "")),
            confidence=str(item.get("confidence", "medium")),  # type: ignore[arg-type]
        )
        for item in payload.get("suggestions", [])
        if isinstance(item, dict)
    ]
    return ReviewResult(
        summary=str(payload.get("summary", "")),
        findings=findings,
        suggestions=suggestions,
        context=payload.get("context", {}) if isinstance(payload.get("context"), dict) else {},
        plan=payload.get("plan", {}) if isinstance(payload.get("plan"), dict) else {},
        history=payload.get("history", {}) if isinstance(payload.get("history"), dict) else {},
    )


def diff_hash(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8", errors="replace")).hexdigest()[:16]


def finding_fingerprint(finding: Finding | dict[str, Any]) -> str:
    item = finding.__dict__ if isinstance(finding, Finding) else finding
    explicit = item.get("fingerprint")
    if explicit:
        return str(explicit)
    parts = [
        _normalize(item.get("file", "")),
        _normalize(item.get("category", "")),
        _normalize(item.get("title", "")),
        _normalize(item.get("issue", "")),
        _normalize(item.get("why_it_matters", "")),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8", errors="replace")).hexdigest()[:16]


def serialize_finding(finding: Finding) -> dict[str, Any]:
    payload = dict(finding.__dict__)
    payload["fingerprint"] = finding_fingerprint(payload)
    return payload


def save_review_json(repo: Path, branch: str, result: ReviewResult, metadata: dict[str, Any]) -> Path:
    path = default_json_path(repo, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata,
        "summary": result.summary,
        "findings": [serialize_finding(finding) for finding in result.findings],
        "suggestions": [suggestion.__dict__ for suggestion in result.suggestions],
        "context": result.context,
        "plan": result.plan,
        "history": result.history,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def compare_findings(previous: dict[str, Any], current: list[Finding]) -> dict[str, Any]:
    previous_findings = previous.get("findings", []) if isinstance(previous, dict) else []
    previous_keys = {finding_fingerprint(item): item for item in previous_findings if isinstance(item, dict)}
    current_keys = {finding_fingerprint(finding): finding for finding in current}
    return {
        "previous_run": bool(previous),
        "new": [serialize_finding(finding) for key, finding in current_keys.items() if key not in previous_keys],
        "still_present": [serialize_finding(finding) for key, finding in current_keys.items() if key in previous_keys],
        "resolved": [item for key, item in previous_keys.items() if key not in current_keys],
    }


def _normalize(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\d+", "<n>", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
