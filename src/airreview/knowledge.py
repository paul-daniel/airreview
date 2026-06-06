from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .config import airreview_path, ensure_airreview_dir, init_files
from .git_tools import IGNORED_DIRS, detect_branch


SOURCE_EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".cs": "C#",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".md": "Markdown",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
}


@dataclass(frozen=True)
class KnowledgeStatus:
    exists: bool
    generated: bool
    scanned_files: int
    languages: list[str]
    index_path: Path
    guidelines_path: Path


@dataclass(frozen=True)
class KnowledgeBundle:
    guidelines: str
    known_smells: str
    generated_scan: str
    metadata: dict


class KnowledgeProvider(Protocol):
    def status(self) -> KnowledgeStatus:
        ...

    def bootstrap(self, force: bool = False) -> KnowledgeStatus:
        ...

    def load(self) -> KnowledgeBundle:
        ...


class LocalKnowledgeProvider:
    def __init__(self, repo: Path):
        self.repo = repo
        self.root = airreview_path(repo)

    def status(self) -> KnowledgeStatus:
        index_path = self.root / "index.json"
        guidelines_path = self.root / "codebase_guidelines.md"
        if not index_path.exists():
            return KnowledgeStatus(False, False, 0, [], index_path, guidelines_path)
        metadata = json.loads(index_path.read_text(encoding="utf-8"))
        return KnowledgeStatus(
            exists=True,
            generated=bool(metadata.get("generated_guidelines")),
            scanned_files=int(metadata.get("scanned_files", 0)),
            languages=list(metadata.get("languages", [])),
            index_path=index_path,
            guidelines_path=guidelines_path,
        )

    def bootstrap(self, force: bool = False) -> KnowledgeStatus:
        init_files(self.repo, force=False)
        ensure_airreview_dir(self.repo)
        guidelines_path = self.root / "codebase_guidelines.md"
        should_generate = force or _is_placeholder(guidelines_path)
        scan = scan_codebase(self.repo)
        generated = should_generate
        if should_generate:
            guidelines_path.write_text(render_generated_guidelines(scan), encoding="utf-8")
        known_smells = self.root / "known_smells.md"
        if not known_smells.exists():
            known_smells.write_text("# Known Smells\n\n- No known smells documented yet.\n", encoding="utf-8")
        generated_path = self.root / "generated" / "codebase_scan.md"
        generated_path.write_text(render_scan(scan), encoding="utf-8")
        metadata = {
            "repo_name": self.repo.name,
            "branch": _safe_branch(self.repo),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scanned_files": len(scan["files"]),
            "languages": sorted(scan["languages"]),
            "signature": scan["signature"],
            "generated_guidelines": generated,
            "provider": "local",
        }
        (self.root / "index.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return self.status()

    def load(self) -> KnowledgeBundle:
        if not self.status().exists or _is_placeholder(self.root / "codebase_guidelines.md"):
            self.bootstrap(force=False)
        metadata_path = self.root / "index.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        return KnowledgeBundle(
            guidelines=_read(self.root / "codebase_guidelines.md"),
            known_smells=_read(self.root / "known_smells.md"),
            generated_scan=_read(self.root / "generated" / "codebase_scan.md"),
            metadata=metadata,
        )


class FutureFoundryIQKnowledgeProvider:
    def __init__(self, repo: Path):
        self.repo = repo

    def status(self) -> KnowledgeStatus:
        raise NotImplementedError("Foundry IQ provider is a documented enterprise target, not enabled in the MVP.")

    def bootstrap(self, force: bool = False) -> KnowledgeStatus:
        raise NotImplementedError("Use LocalKnowledgeProvider for the MVP.")

    def load(self) -> KnowledgeBundle:
        raise NotImplementedError("Use LocalKnowledgeProvider for the MVP.")


def scan_codebase(repo: Path, max_files: int = 80) -> dict:
    files: list[dict[str, str | int]] = []
    languages: set[str] = set()
    signature = hashlib.sha256()
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo)
        if not path.is_file() or _ignored(rel):
            continue
        language = SOURCE_EXTENSIONS.get(path.suffix.lower())
        if not language:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        snippet = "\n".join(lines[:80])
        files.append({"path": str(rel), "language": language, "lines": len(lines), "snippet": snippet[:4000]})
        languages.add(language)
        signature.update(str(rel).encode())
        signature.update(snippet[:1000].encode(errors="ignore"))
        if len(files) >= max_files:
            break
    return {"files": files, "languages": languages, "signature": signature.hexdigest()[:16]}


def render_generated_guidelines(scan: dict) -> str:
    languages = ", ".join(sorted(scan["languages"])) or "unknown"
    common_roots = sorted({Path(item["path"]).parts[0] for item in scan["files"] if Path(item["path"]).parts})
    roots = ", ".join(common_roots[:10]) or "not enough files yet"
    return (
        "# Codebase Guidelines\n\n"
        "Draft: true\n\n"
        "Generated by AirReview local bootstrap. Replace or edit these notes with team-approved rules.\n\n"
        "## Repository Shape\n\n"
        f"- Detected languages: {languages}.\n"
        f"- Notable top-level areas: {roots}.\n"
        "- Prefer conventions already present in nearby files over generic advice.\n"
        "- Review final branch state against the merge-base, not an isolated commit.\n\n"
        "## Review Rules\n\n"
        "- Prioritize issues introduced or aggravated by the branch.\n"
        "- Avoid re-reporting legacy smells unless the change makes them worse.\n"
        "- Prefer concrete, localizable, actionable findings with clear severity.\n"
        "- Ask for tests when behavior, security, or regression risk changes.\n"
    )


def render_scan(scan: dict) -> str:
    lines = ["# AirReview Codebase Scan", ""]
    lines.append(f"- Files scanned: {len(scan['files'])}")
    lines.append(f"- Languages: {', '.join(sorted(scan['languages'])) or 'unknown'}")
    lines.append(f"- Signature: {scan['signature']}")
    lines.append("")
    lines.append("## Sampled Files")
    for item in scan["files"]:
        lines.append(f"- {item['path']} ({item['language']}, {item['lines']} lines)")
    return "\n".join(lines) + "\n"


def _is_placeholder(path: Path) -> bool:
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8", errors="replace").strip().lower()
    return not text or "airreview will replace this placeholder" in text or len(text) < 80


def _ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _safe_branch(repo: Path) -> str:
    try:
        return detect_branch(repo)
    except Exception:
        return "unknown"
