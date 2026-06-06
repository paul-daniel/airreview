from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import ReviewResult
from .config import load_review_profile
from .git_tools import run_git
from .models import MockModelClient, build_model_client
from .workflow import AirReviewWorkflow, RunOptions
from .tracing import RunTrace


@dataclass
class EvalCase:
    name: str
    files: dict[str, str]
    changed_files: dict[str, str]
    expected_titles: list[str]


DEFAULT_EVALS = [
    EvalCase(
        name="secret_literal_is_flagged",
        files={"app.py": "def handler():\n    return True\n"},
        changed_files={"settings.py": 'API_KEY = "demo-secret-key"\n'},
        expected_titles=["Possible secret-like value introduced"],
    ),
    EvalCase(
        name="todo_is_flagged_when_introduced",
        files={"app.py": "def handler():\n    return True\n"},
        changed_files={"app.py": "def handler():\n    # TODO: add owner before prod\n    return True\n"},
        expected_titles=["New TODO needs an owner or follow-up"],
    ),
]


def run_local_evals(repo: Path, mock: bool = True) -> dict[str, Any]:
    results = []
    for case in DEFAULT_EVALS:
        result = run_eval_case(case, mock=mock)
        results.append(result)
    passed = sum(1 for item in results if item["passed"])
    return {"passed": passed, "total": len(results), "cases": results}


def run_eval_case(case: EvalCase, mock: bool = True) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"airreview-eval-{case.name}-") as tmp:
        repo = Path(tmp)
        run_git(repo, ["init", "-b", "main"])
        for path, content in case.files.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        run_git(repo, ["add", "."])
        run_git(repo, ["-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "initial"])
        run_git(repo, ["checkout", "-b", "feature/eval"])
        for path, content in case.changed_files.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        run_git(repo, ["add", "."])
        run_git(repo, ["-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "eval feature"])
        profile = load_review_profile(repo)
        model = MockModelClient() if mock else build_model_client(mock=False)
        trace = RunTrace(repo=repo)
        output = AirReviewWorkflow(repo, profile, model, trace).run(RunOptions(output=False, mock=mock))
        return score_case(case, output.result)


def score_case(case: EvalCase, result: ReviewResult) -> dict[str, Any]:
    titles = [finding.title for finding in result.findings]
    missing = [title for title in case.expected_titles if title not in titles]
    return {
        "name": case.name,
        "passed": not missing,
        "expected_titles": case.expected_titles,
        "actual_titles": titles,
        "missing_titles": missing,
        "findings_count": len(result.findings),
    }


def write_eval_report(path: Path, result: dict[str, Any]) -> Path:
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path
