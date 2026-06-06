from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


AIRREVIEW_DIR = ".airreview"
DEFAULT_PROFILE = {
    "profile": "balanced",
    "severity_threshold": "medium",
    "post_mode": "summary",
    "max_findings": 8,
    "suggest_fixes": True,
    "include_tests": True,
    "ignore_low_confidence": True,
    "budget": {
        "max_files_per_chunk": 8,
        "max_diff_chars_per_chunk": 45000,
        "max_chunks": 4,
        "stop_when_budget_exceeded": False,
    },
    "output": {"markdown": True, "console": True},
    "knowledge": {"provider": "local", "auto_init": True},
    "foundry": {"provider": "azure_ai_inference"},
    "azure_devops": {"post_comments": False, "comment_mode": "single_thread"},
}


@dataclass(frozen=True)
class ReviewProfile:
    profile: str
    severity_threshold: str
    post_mode: str
    max_findings: int
    suggest_fixes: bool
    include_tests: bool
    ignore_low_confidence: bool
    max_files_per_chunk: int
    max_diff_chars_per_chunk: int
    max_chunks: int
    stop_when_budget_exceeded: bool
    raw: dict[str, Any]


def airreview_path(repo: Path) -> Path:
    return repo / AIRREVIEW_DIR


def ensure_airreview_dir(repo: Path) -> Path:
    path = airreview_path(repo)
    (path / "generated").mkdir(parents=True, exist_ok=True)
    (path / "runs").mkdir(parents=True, exist_ok=True)
    (path / "reviews").mkdir(parents=True, exist_ok=True)
    gitignore = path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("runs/\nreviews/\n", encoding="utf-8")
    return path


def default_profile_yaml() -> str:
    return yaml.safe_dump(DEFAULT_PROFILE, sort_keys=False)


def write_default_profile(repo: Path, force: bool = False) -> Path:
    root = ensure_airreview_dir(repo)
    profile_path = root / "review_profile.yaml"
    if force or not profile_path.exists():
        profile_path.write_text(default_profile_yaml(), encoding="utf-8")
    return profile_path


def load_review_profile(repo: Path) -> ReviewProfile:
    profile_path = write_default_profile(repo, force=False)
    loaded = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    merged = _deep_merge(DEFAULT_PROFILE, loaded)
    return ReviewProfile(
        profile=str(merged.get("profile", "balanced")),
        severity_threshold=str(merged.get("severity_threshold", "medium")),
        post_mode=str(merged.get("post_mode", "summary")),
        max_findings=int(merged.get("max_findings", 8)),
        suggest_fixes=bool(merged.get("suggest_fixes", True)),
        include_tests=bool(merged.get("include_tests", True)),
        ignore_low_confidence=bool(merged.get("ignore_low_confidence", True)),
        max_files_per_chunk=int(merged.get("budget", {}).get("max_files_per_chunk", 8)),
        max_diff_chars_per_chunk=int(merged.get("budget", {}).get("max_diff_chars_per_chunk", 45000)),
        max_chunks=int(merged.get("budget", {}).get("max_chunks", 4)),
        stop_when_budget_exceeded=bool(merged.get("budget", {}).get("stop_when_budget_exceeded", False)),
        raw=merged,
    )


def init_files(repo: Path, force: bool = False) -> list[Path]:
    root = ensure_airreview_dir(repo)
    written = [write_default_profile(repo, force=force)]
    defaults = {
        "codebase_guidelines.md": (
            "# Codebase Guidelines\n\n"
            "Draft: true\n\n"
            "AirReview will replace this placeholder with a local scan when needed.\n"
        ),
        "known_smells.md": (
            "# Known Smells\n\n"
            "- Add legacy issues that should not be re-reported unless the branch worsens them.\n"
        ),
    }
    for name, content in defaults.items():
        target = root / name
        if force or not target.exists():
            target.write_text(content, encoding="utf-8")
            written.append(target)
    return written


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
