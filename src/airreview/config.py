from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


AIRREVIEW_DIR = ".airreview"
LOCAL_ENV_FILE = ".env"
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
    "github": {"post_comments": False, "comment_mode": "inline_with_summary", "inline_min_severity": "medium"},
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
        gitignore.write_text("runs/\nreviews/\n.env\n", encoding="utf-8")
    else:
        ensure_gitignore_entry(gitignore, ".env")
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
    merged = apply_env_overrides(merged)
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
    env_example = root / ".env.example"
    if force or not env_example.exists():
        env_example.write_text(local_env_example(), encoding="utf-8")
        written.append(env_example)
    return written


def load_local_env(repo: Path) -> list[Path]:
    loaded: list[Path] = []
    for path in local_env_paths(repo):
        if not path.exists():
            continue
        for key, value in parse_env_file(path).items():
            os.environ.setdefault(key, value)
        loaded.append(path)
    return loaded


def local_env_paths(repo: Path) -> list[Path]:
    return [airreview_path(repo) / LOCAL_ENV_FILE]


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = strip_env_value(value.strip())
        if key:
            values[key] = value
    return values


def strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def local_env_example() -> str:
    return "\n".join(
        [
            "# AirReview local Foundry configuration.",
            "# This file is an example. Copy it to `.airreview/.env` and keep `.env` uncommitted.",
            "",
            "FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>",
            "AIRREVIEW_AGENT_MODE=foundry_agents",
            "",
            "# Use either Azure CLI auth (`az login`) or an API key.",
            "# FOUNDRY_API_KEY=<optional-api-key>",
            "",
            "# Optional local throttling controls.",
            "# Local default is AzureCliCredential; CI default is DefaultAzureCredential.",
            "AIRREVIEW_AZURE_CREDENTIAL=auto",
            "AIRREVIEW_MODEL_RETRIES=4",
            "AIRREVIEW_RATE_LIMIT_BACKOFF_SECONDS=12,30,60,90",
            "AIRREVIEW_MODEL_CALL_DELAY_SECONDS=2",
            "AIRREVIEW_MAX_OUTPUT_TOKENS=1800",
            "",
        ]
    )


def ensure_gitignore_entry(path: Path, entry: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if entry not in lines:
        lines.append(entry)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def apply_env_overrides(profile: dict[str, Any]) -> dict[str, Any]:
    result = dict(profile)
    budget = dict(result.get("budget", {}))
    if value := os.getenv("AIRREVIEW_MAX_FINDINGS"):
        result["max_findings"] = int(value)
    if value := os.getenv("AIRREVIEW_SEVERITY_THRESHOLD"):
        result["severity_threshold"] = value
    if value := os.getenv("AIRREVIEW_MAX_FILES_PER_CHUNK"):
        budget["max_files_per_chunk"] = int(value)
    if value := os.getenv("AIRREVIEW_MAX_DIFF_CHARS_PER_CHUNK"):
        budget["max_diff_chars_per_chunk"] = int(value)
    if value := os.getenv("AIRREVIEW_MAX_CHUNKS"):
        budget["max_chunks"] = int(value)
    if value := os.getenv("AIRREVIEW_STOP_WHEN_BUDGET_EXCEEDED"):
        budget["stop_when_budget_exceeded"] = value.lower() in {"1", "true", "yes", "on"}
    result["budget"] = budget
    return result
