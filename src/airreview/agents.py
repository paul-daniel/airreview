from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any, Literal

Severity = Literal["low", "medium", "high", "critical"]
Confidence = Literal["low", "medium", "high"]


@dataclass
class Finding:
    file: str
    line: int
    severity: Severity
    category: str
    title: str
    issue: str
    why_it_matters: str
    confidence: Confidence
    end_line: int = 0


@dataclass
class Suggestion:
    finding_title: str
    suggestion: str
    example: str
    test_recommendation: str
    confidence: Confidence


@dataclass
class ReviewResult:
    summary: str
    findings: list[Finding] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    history: dict[str, Any] = field(default_factory=dict)


class JsonAgent:
    def __init__(self, name: str, prompt_file: str, model_client: Any):
        self.name = name
        self.prompt_file = prompt_file
        self.model_client = model_client

    @property
    def instructions(self) -> str:
        return files("airreview.prompts").joinpath(self.prompt_file).read_text(encoding="utf-8")

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        working_payload = dict(payload)
        for attempt in range(1, 4):
            response = self.model_client.complete_json(self.name, self.instructions, working_payload)
            try:
                parsed = parse_json_object(response)
                validate_agent_output(self.name, parsed)
                return parsed
            except Exception as exc:
                last_error = exc
                working_payload["_airreview_retry_instruction"] = (
                    f"Previous attempt {attempt} failed JSON/schema validation: {exc}. "
                    "Return only a valid strict JSON object matching the schema."
                )
                working_payload["_airreview_invalid_output_excerpt"] = response[:1200]
        raise ValueError(f"{self.name} did not return valid JSON after retries: {last_error}")


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("Agent output must be a JSON object.")
        return value
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            value = json.loads(text[start : end + 1])
            if isinstance(value, dict):
                return value
        raise


def validate_agent_output(agent_name: str, payload: dict[str, Any]) -> None:
    required_by_agent = {
        "Review Planning Agent": ("strategy", "chunks", "budget"),
        "Codebase Context Agent": ("relevant_guidelines", "known_smells_to_ignore", "architecture_context", "review_focus"),
        "Codebase Context Worker Agent": (
            "chunk_name",
            "observed_practices",
            "reusable_helpers",
            "testing_patterns",
            "legacy_smell_candidates",
            "bad_practices_not_to_normalize",
        ),
        "Codebase Context Synthesis Agent": (
            "observed_practices",
            "recommended_practices",
            "legacy_smells_to_ignore_in_reviews",
            "objective_bad_practices_not_to_normalize",
            "reusable_helpers",
            "testing_patterns",
            "architecture_patterns",
            "review_guidance",
        ),
        "Branch Review Agent": ("summary", "findings"),
        "Finding Critic Agent": ("accepted_findings", "rejected_findings", "summary"),
        "Fix Suggestion Agent": ("suggestions",),
    }
    for key in required_by_agent.get(agent_name, ()):
        if key not in payload:
            raise ValueError(f"missing key `{key}`")
    if agent_name == "Branch Review Agent" and not isinstance(payload.get("findings"), list):
        raise ValueError("`findings` must be a list")
    if agent_name == "Review Planning Agent" and not isinstance(payload.get("chunks"), list):
        raise ValueError("`chunks` must be a list")
    if agent_name == "Finding Critic Agent" and not isinstance(payload.get("accepted_findings"), list):
        raise ValueError("`accepted_findings` must be a list")
    if agent_name == "Fix Suggestion Agent" and not isinstance(payload.get("suggestions"), list):
        raise ValueError("`suggestions` must be a list")
    if agent_name in {"Codebase Context Worker Agent", "Codebase Context Synthesis Agent"}:
        for key, value in payload.items():
            if key in {"chunk_name", "confidence", "summary"}:
                continue
            if key != "metadata" and not isinstance(value, list):
                raise ValueError(f"`{key}` must be a list")


def findings_from_json(payload: dict[str, Any]) -> list[Finding]:
    findings = []
    for item in payload.get("findings", payload.get("accepted_findings", [])):
        findings.append(
            Finding(
                file=str(item.get("file", "")),
                line=int(item.get("line") or 0),
                severity=_severity(item.get("severity")),
                category=str(item.get("category", "quality")),
                title=str(item.get("title", "Untitled finding")),
                issue=str(item.get("issue", "")),
                why_it_matters=str(item.get("why_it_matters", "")),
                confidence=_confidence(item.get("confidence")),
                end_line=int(item.get("end_line") or 0),
            )
        )
    return findings


def suggestions_from_json(payload: dict[str, Any]) -> list[Suggestion]:
    suggestions = []
    for item in payload.get("suggestions", []):
        suggestions.append(
            Suggestion(
                finding_title=str(item.get("finding_title", "")),
                suggestion=str(item.get("suggestion", "")),
                example=str(item.get("example", "")),
                test_recommendation=str(item.get("test_recommendation", "")),
                confidence=_confidence(item.get("confidence")),
            )
        )
    return suggestions


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, int, str]] = set()
    result: list[Finding] = []
    for finding in findings:
        key = (finding.file, finding.line, finding.title.lower().strip())
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result


def apply_threshold(
    findings: list[Finding], threshold: str, max_findings: int, ignore_low_confidence: bool
) -> list[Finding]:
    weights = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    minimum = weights.get(threshold, 2)
    filtered = [
        finding
        for finding in findings
        if weights.get(finding.severity, 1) >= minimum and not (ignore_low_confidence and finding.confidence == "low")
    ]
    return sorted(filtered, key=lambda item: weights.get(item.severity, 1), reverse=True)[:max_findings]


def _severity(value: object) -> Severity:
    text = str(value or "medium").lower()
    return text if text in {"low", "medium", "high", "critical"} else "medium"  # type: ignore[return-value]


def _confidence(value: object) -> Confidence:
    text = str(value or "medium").lower()
    return text if text in {"low", "medium", "high"} else "medium"  # type: ignore[return-value]
