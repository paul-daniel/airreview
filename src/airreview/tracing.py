from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, TypeVar
from uuid import uuid4

import json

from .config import ensure_airreview_dir

T = TypeVar("T")


@dataclass
class ToolInvocation:
    name: str
    started_at: str
    duration_ms: float
    ok: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentInvocation:
    name: str
    duration_ms: float
    ok: bool


@dataclass
class RunTrace:
    repo: Path
    run_id: str = field(default_factory=lambda: uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    branch: str | None = None
    base: str | None = None
    model: str = "mock"
    output_file: str | None = None
    findings_count: int = 0
    tools: list[ToolInvocation] = field(default_factory=list)
    agents: list[AgentInvocation] = field(default_factory=list)

    def record_tool(self, name: str, duration_ms: float, ok: bool, details: dict[str, Any] | None = None) -> None:
        self.tools.append(
            ToolInvocation(
                name=name,
                started_at=datetime.now(timezone.utc).isoformat(),
                duration_ms=round(duration_ms, 2),
                ok=ok,
                details=details or {},
            )
        )

    def record_agent(self, name: str, duration_ms: float, ok: bool) -> None:
        self.agents.append(AgentInvocation(name=name, duration_ms=round(duration_ms, 2), ok=ok))

    def write(self) -> Path:
        root = ensure_airreview_dir(self.repo)
        run_dir = root / "runs" / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / "trace.json"
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return target

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "branch": self.branch,
            "base": self.base,
            "model": self.model,
            "tools_invoked": [tool.__dict__ for tool in self.tools],
            "agent_durations": [agent.__dict__ for agent in self.agents],
            "output_file": self.output_file,
            "findings_count": self.findings_count,
        }


class ToolRegistry:
    def __init__(self, trace: RunTrace):
        self.trace = trace

    def call(self, name: str, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        start = perf_counter()
        try:
            result = func(*args, **kwargs)
            details = _summarize_result(result)
            self.trace.record_tool(name, (perf_counter() - start) * 1000, True, details)
            return result
        except Exception as exc:
            self.trace.record_tool(name, (perf_counter() - start) * 1000, False, {"error": str(exc)})
            raise


def _summarize_result(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"chars": len(value)}
    if isinstance(value, list):
        return {"items": len(value)}
    if isinstance(value, dict):
        return {"keys": sorted(value.keys())[:12]}
    if hasattr(value, "__dict__"):
        return {"type": type(value).__name__}
    return {"type": type(value).__name__}
