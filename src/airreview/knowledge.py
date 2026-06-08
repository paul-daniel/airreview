from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

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


@dataclass(frozen=True)
class PracticeSampleFile:
    path: str
    language: str
    lines: int
    content: str


@dataclass(frozen=True)
class PracticeDiscoveryChunk:
    name: str
    focus: str
    files: list[PracticeSampleFile]


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

    def practice_profile_path(self) -> Path:
        return self.root / "practice_profile.json"

    def load_practice_profile(self) -> dict[str, Any]:
        path = self.practice_profile_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def save_practice_profile(
        self,
        profile: dict[str, Any],
        chunks: list[PracticeDiscoveryChunk],
        worker_results: list[dict[str, Any]],
    ) -> Path:
        ensure_airreview_dir(self.repo)
        profile = dict(profile)
        metadata = dict(profile.get("metadata", {}) if isinstance(profile.get("metadata"), dict) else {})
        metadata.update(
            {
                "provider": "local_agentic_discovery",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "signature": practice_sample_signature(chunks),
                "chunks": [chunk.name for chunk in chunks],
                "sampled_files": sum(len(chunk.files) for chunk in chunks),
                "workers": len(worker_results),
            }
        )
        profile["metadata"] = metadata
        target = self.practice_profile_path()
        target.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
        generated = self.root / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        (generated / "practice_profile.md").write_text(render_practice_profile(profile), encoding="utf-8")
        proposal = render_known_smells_proposal(profile)
        if proposal.strip():
            (generated / "known_smells.proposed.md").write_text(proposal, encoding="utf-8")
        return target

    def needs_practice_discovery(self) -> bool:
        if not self.practice_profile_path().exists():
            return True
        return False


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


def sample_practice_chunks(
    repo: Path,
    changed_files: list[str] | None = None,
    *,
    max_files: int = 40,
    max_files_per_chunk: int = 12,
    max_chars_per_file: int = 3500,
) -> list[PracticeDiscoveryChunk]:
    candidates = practice_candidate_paths(repo, changed_files or [])
    samples: list[PracticeSampleFile] = []
    for path in candidates:
        if len(samples) >= max_files:
            break
        language = SOURCE_EXTENSIONS.get(path.suffix.lower())
        if not language or not path.is_file():
            continue
        rel = str(path.relative_to(repo))
        text = path.read_text(encoding="utf-8", errors="replace")
        samples.append(
            PracticeSampleFile(
                path=rel,
                language=language,
                lines=len(text.splitlines()),
                content=text[:max_chars_per_file],
            )
        )
    grouped: dict[str, list[PracticeSampleFile]] = {}
    for sample in samples:
        grouped.setdefault(practice_group_for_path(sample.path), []).append(sample)
    chunks: list[PracticeDiscoveryChunk] = []
    for name, files in grouped.items():
        for index in range(0, len(files), max_files_per_chunk):
            part = files[index : index + max_files_per_chunk]
            suffix = f"-{index // max_files_per_chunk + 1}" if index else ""
            chunks.append(PracticeDiscoveryChunk(f"{name}{suffix}", focus_for_group(name), part))
    return ensure_minimum_chunks(chunks)


def practice_candidate_paths(repo: Path, changed_files: list[str]) -> list[Path]:
    weighted: list[tuple[int, Path]] = []
    changed = {path for path in changed_files if path}
    for path in repo.rglob("*"):
        rel = path.relative_to(repo)
        if not path.is_file() or _ignored(rel) or path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        rel_text = str(rel)
        weight = 50
        if rel_text in changed:
            weight = 0
        elif is_test_path(rel_text):
            weight = 5
        elif any(part in {"lib", "utils", "helpers", "services", "api", "hooks"} for part in rel.parts):
            weight = 10
        elif any(part in {"features", "components", "pages", "app"} for part in rel.parts):
            weight = 20
        elif rel.name in {"package.json", "pyproject.toml", "requirements.txt", "tsconfig.json"}:
            weight = 2
        weighted.append((weight, path))
    return [path for _, path in sorted(weighted, key=lambda item: (item[0], str(item[1])))]


def practice_group_for_path(path: str) -> str:
    parts = Path(path).parts
    if is_test_path(path):
        return "tests"
    if any(part in {"lib", "utils", "helpers"} for part in parts):
        return "helpers-and-lib"
    if any(part in {"services", "api"} for part in parts):
        return "services-and-api"
    if any(part in {"hooks"} for part in parts):
        return "hooks"
    if any(part in {"features", "components", "pages", "app"} for part in parts):
        return "ui-and-features"
    if Path(path).name in {"package.json", "pyproject.toml", "requirements.txt", "tsconfig.json"}:
        return "config-and-dependencies"
    return "general-code"


def focus_for_group(name: str) -> str:
    return {
        "tests": "testing conventions, assertion style, fixtures, mocks, user-event patterns",
        "helpers-and-lib": "shared helpers, reusable functions, naming, utility patterns to reuse instead of duplicating",
        "services-and-api": "service boundaries, API wrappers, error handling, authorization and data access patterns",
        "hooks": "React hooks patterns, effects, cleanup, data fetching and state conventions",
        "ui-and-features": "feature organization, component naming, props, state and UI interaction patterns",
        "config-and-dependencies": "frameworks, package versions, lint/test tools and dependency conventions",
        "general-code": "general repository conventions and recurring implementation patterns",
    }.get(name, "repository conventions and recurring implementation patterns")


def ensure_minimum_chunks(chunks: list[PracticeDiscoveryChunk]) -> list[PracticeDiscoveryChunk]:
    if len(chunks) != 1 or len(chunks[0].files) < 4:
        return chunks
    files = chunks[0].files
    midpoint = max(1, len(files) // 2)
    return [
        PracticeDiscoveryChunk(f"{chunks[0].name}-a", chunks[0].focus, files[:midpoint]),
        PracticeDiscoveryChunk(f"{chunks[0].name}-b", chunks[0].focus, files[midpoint:]),
    ]


def practice_sample_signature(chunks: list[PracticeDiscoveryChunk]) -> str:
    signature = hashlib.sha256()
    for chunk in chunks:
        signature.update(chunk.name.encode())
        for sample in chunk.files:
            signature.update(sample.path.encode())
            signature.update(sample.content[:1000].encode(errors="ignore"))
    return signature.hexdigest()[:16]


def discovery_chunk_payload(chunk: PracticeDiscoveryChunk) -> dict[str, Any]:
    return {
        "name": chunk.name,
        "focus": chunk.focus,
        "files": [
            {"path": sample.path, "language": sample.language, "lines": sample.lines, "content": sample.content}
            for sample in chunk.files
        ],
    }


def render_practice_profile(profile: dict[str, Any]) -> str:
    lines = ["# AirReview Practice Profile", ""]
    metadata = profile.get("metadata", {}) if isinstance(profile.get("metadata"), dict) else {}
    if metadata:
        lines.append("## Metadata")
        for key in ("generated_at", "signature", "sampled_files", "workers"):
            if key in metadata:
                lines.append(f"- {key}: {metadata[key]}")
        lines.append("")
    sections = [
        ("Observed practices", "observed_practices"),
        ("Recommended practices", "recommended_practices"),
        ("Reusable helpers", "reusable_helpers"),
        ("Testing patterns", "testing_patterns"),
        ("Architecture patterns", "architecture_patterns"),
        ("Legacy smells to ignore in reviews", "legacy_smells_to_ignore_in_reviews"),
        ("Objective bad practices not to normalize", "objective_bad_practices_not_to_normalize"),
        ("Review guidance", "review_guidance"),
    ]
    for title, key in sections:
        values = profile.get(key, [])
        if not isinstance(values, list) or not values:
            continue
        lines.extend([f"## {title}", ""])
        for item in values:
            lines.append(f"- {format_profile_item(item)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_known_smells_proposal(profile: dict[str, Any]) -> str:
    smells = profile.get("legacy_smells_to_ignore_in_reviews", [])
    if not isinstance(smells, list) or not smells:
        return ""
    lines = [
        "# Proposed Known Smells",
        "",
        "These entries were proposed by AirReview practice discovery. Review them before copying to `.airreview/known_smells.md`.",
        "",
    ]
    for item in smells:
        lines.append(f"- {format_profile_item(item)}")
    return "\n".join(lines).rstrip() + "\n"


def format_profile_item(item: Any) -> str:
    if isinstance(item, dict):
        compact = ", ".join(f"{key}: {value}" for key, value in item.items() if value)
        return compact or json.dumps(item, ensure_ascii=False)
    return str(item)


def guidelines_are_draft(path: Path) -> bool:
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8", errors="replace")
    return bool(re.search(r"(?im)^\s*draft\s*:\s*true\s*$", text))


def is_test_path(path: str) -> bool:
    lowered = path.lower()
    return (
        "/test" in lowered
        or lowered.startswith("test")
        or lowered.endswith((".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".spec.ts", ".spec.tsx", "_test.py"))
    )


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
