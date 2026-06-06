from __future__ import annotations

import json
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
        plan=payload.get("plan", {}) if isinstance(payload.get("plan"), dict) else {},
    )


def save_review_json(repo: Path, branch: str, result: ReviewResult, metadata: dict[str, Any]) -> Path:
    path = default_json_path(repo, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata,
        "summary": result.summary,
        "findings": [finding.__dict__ for finding in result.findings],
        "suggestions": [suggestion.__dict__ for suggestion in result.suggestions],
        "plan": result.plan,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def compare_findings(previous: dict[str, Any], current: list[Finding]) -> dict[str, Any]:
    previous_findings = previous.get("findings", []) if isinstance(previous, dict) else []
    previous_keys = {_finding_key(item): item for item in previous_findings if isinstance(item, dict)}
    current_keys = {_finding_key(finding.__dict__): finding for finding in current}
    return {
        "previous_run": bool(previous),
        "new": [finding.__dict__ for key, finding in current_keys.items() if key not in previous_keys],
        "still_present": [finding.__dict__ for key, finding in current_keys.items() if key in previous_keys],
        "resolved": [item for key, item in previous_keys.items() if key not in current_keys],
    }


def _finding_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("file", "")),
            str(item.get("line", 0)),
            str(item.get("title", "")).strip().lower(),
        ]
    )
