from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


IGNORED_DIRS = {
    ".git",
    ".airreview",
    ".DS_Store",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    ".venv",
    "coverage",
    ".next",
    "bin",
    "obj",
    "vendor",
}


ReviewScope = Literal["branch", "working", "staged", "uncommitted"]


@dataclass(frozen=True)
class BranchContext:
    branch: str
    base: str
    merge_base: str
    changed_files: list[str]
    diff: str
    final_files: dict[str, str]
    scope: ReviewScope = "branch"
    includes_worktree: bool = False


def run_git(repo: Path, args: list[str], check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def ensure_git_repo(repo: Path) -> None:
    run_git(repo, ["rev-parse", "--is-inside-work-tree"])


def fetch(repo: Path) -> None:
    run_git(repo, ["fetch", "--all", "--prune"], check=True)


def detect_branch(repo: Path, explicit_branch: str | None = None) -> str:
    if explicit_branch:
        return normalize_ref(explicit_branch)
    env_branch = os.getenv("SYSTEM_PULLREQUEST_SOURCEBRANCH")
    if env_branch:
        return normalize_ref(env_branch)
    branch = run_git(repo, ["branch", "--show-current"], check=False)
    if branch:
        return branch
    return run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])


def detect_base(repo: Path, explicit_base: str | None = None) -> str:
    if explicit_base:
        return normalize_ref(explicit_base, prefer_remote=False)

    ado_target = os.getenv("SYSTEM_PULLREQUEST_TARGETBRANCH")
    if ado_target:
        return normalize_ref(ado_target, prefer_remote=True)

    origin_head = run_git(repo, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], check=False)
    if origin_head:
        return origin_head

    for candidate in ("origin/main", "origin/master", "main", "master"):
        if ref_exists(repo, candidate):
            return candidate
    raise RuntimeError("Unable to detect a base branch. Set SYSTEM_PULLREQUEST_TARGETBRANCH or create origin/main.")


def normalize_ref(ref: str, prefer_remote: bool = False) -> str:
    cleaned = ref.removeprefix("refs/heads/").removeprefix("refs/remotes/")
    if prefer_remote and not cleaned.startswith("origin/"):
        return f"origin/{cleaned}"
    return cleaned


def ref_exists(repo: Path, ref: str) -> bool:
    run_git(repo, ["rev-parse", "--verify", "--quiet", ref], check=False)
    proc = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=repo, capture_output=True)
    return proc.returncode == 0


def merge_base(repo: Path, base: str, branch: str) -> str:
    return run_git(repo, ["merge-base", base, branch])


def diff(repo: Path, merge_base_sha: str, branch: str) -> str:
    return run_git(repo, ["diff", f"{merge_base_sha}..{branch}", "--", *pathspec_excludes()])


def diff_worktree(repo: Path, merge_base_sha: str) -> str:
    tracked_diff = run_git(repo, ["diff", merge_base_sha, "--", *pathspec_excludes()])
    untracked = untracked_files(repo)
    if not untracked:
        return tracked_diff
    additions = ["\n# Untracked files included by AirReview\n"]
    for path in untracked[:30]:
        content = final_file_state(repo, "HEAD", path, prefer_worktree=True)
        additions.append(f"\ndiff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n")
        additions.extend(f"+{line}\n" for line in content.splitlines()[:400])
        if len(content.splitlines()) > 400:
            additions.append("+[airreview truncated untracked file]\n")
    return tracked_diff + "".join(additions)


def diff_staged(repo: Path) -> str:
    return run_git(repo, ["diff", "--cached", "--", *pathspec_excludes()])


def diff_uncommitted(repo: Path) -> str:
    tracked_diff = run_git(repo, ["diff", "HEAD", "--", *pathspec_excludes()])
    untracked = untracked_files(repo)
    if not untracked:
        return tracked_diff
    additions = ["\n# Untracked files included by AirReview\n"]
    for path in untracked[:30]:
        content = final_file_state(repo, "HEAD", path, prefer_worktree=True)
        additions.append(f"\ndiff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n")
        additions.extend(f"+{line}\n" for line in content.splitlines()[:400])
        if len(content.splitlines()) > 400:
            additions.append("+[airreview truncated untracked file]\n")
    return tracked_diff + "".join(additions)


def changed_files(repo: Path, merge_base_sha: str, branch: str) -> list[str]:
    output = run_git(repo, ["diff", "--name-only", f"{merge_base_sha}..{branch}", "--", *pathspec_excludes()])
    return [path for path in output.splitlines() if path and not is_ignored(path)]


def changed_files_staged(repo: Path) -> list[str]:
    output = run_git(repo, ["diff", "--cached", "--name-only", "--", *pathspec_excludes()])
    return [path for path in output.splitlines() if path and not is_ignored(path)]


def changed_files_uncommitted(repo: Path) -> list[str]:
    output = run_git(repo, ["diff", "--name-only", "HEAD", "--", *pathspec_excludes()])
    files = [path for path in output.splitlines() if path and not is_ignored(path)]
    return sorted(set(files + untracked_files(repo)))


def changed_files_worktree(repo: Path, merge_base_sha: str) -> list[str]:
    output = run_git(repo, ["diff", "--name-only", merge_base_sha, "--", *pathspec_excludes()])
    files = [path for path in output.splitlines() if path and not is_ignored(path)]
    return sorted(set(files + untracked_files(repo)))


def final_file_state(repo: Path, branch: str, path: str, prefer_worktree: bool = False) -> str:
    if is_ignored(path):
        return ""
    current = repo / path
    if prefer_worktree and current.exists() and current.is_file():
        return truncate(current.read_text(encoding="utf-8", errors="replace"))
    content = run_git(repo, ["show", f"{branch}:{path}"], check=False)
    if content:
        return truncate(content)
    if current.exists() and current.is_file():
        return truncate(current.read_text(encoding="utf-8", errors="replace"))
    return ""


def final_file_state_staged(repo: Path, path: str) -> str:
    if is_ignored(path):
        return ""
    content = run_git(repo, ["show", f":{path}"], check=False)
    if content:
        return truncate(content)
    return ""


def collect_branch_context(
    repo: Path,
    branch: str | None = None,
    base: str | None = None,
    scope: ReviewScope = "branch",
) -> BranchContext:
    source = detect_branch(repo, branch)
    if not has_commits(repo):
        files = working_tree_files(repo)
        final_files = {
            path: truncate((repo / path).read_text(encoding="utf-8", errors="replace"))
            for path in files[:30]
            if (repo / path).is_file()
        }
        return BranchContext(
            branch=source,
            base="unborn",
            merge_base="unborn",
            changed_files=files,
            diff="Repository has no commits yet; reviewing the current working tree as initial branch state.",
            final_files=final_files,
            scope="working",
            includes_worktree=True,
        )
    base_ref = detect_base(repo, base)
    if not ref_exists(repo, source):
        raise RuntimeError(f"Source branch or ref does not exist: {source}")
    if not ref_exists(repo, base_ref):
        raise RuntimeError(f"Reference branch or ref does not exist: {base_ref}")
    if scope not in {"branch", "working", "staged", "uncommitted"}:
        raise RuntimeError(f"Unsupported review scope: {scope}")

    if scope == "branch":
        mb = merge_base(repo, base_ref, source)
        files = changed_files(repo, mb, source)
        final_files = {path: final_file_state(repo, source, path) for path in files[:30]}
        branch_diff = diff(repo, mb, source)
        return BranchContext(
            branch=source,
            base=base_ref,
            merge_base=mb,
            changed_files=files,
            diff=branch_diff,
            final_files=final_files,
            scope=scope,
            includes_worktree=False,
        )

    require_current_scope(repo, source, scope)
    if scope == "working":
        mb = merge_base(repo, base_ref, source)
        files = changed_files_worktree(repo, mb)
        final_files = {path: final_file_state(repo, source, path, prefer_worktree=True) for path in files[:30]}
        branch_diff = diff_worktree(repo, mb)
        return BranchContext(source, base_ref, mb, files, branch_diff, final_files, scope=scope, includes_worktree=True)

    head = head_sha(repo)
    if scope == "staged":
        files = changed_files_staged(repo)
        final_files = {path: final_file_state_staged(repo, path) for path in files[:30]}
        return BranchContext(source, base_ref, head, files, diff_staged(repo), final_files, scope=scope, includes_worktree=True)

    files = changed_files_uncommitted(repo)
    final_files = {path: final_file_state(repo, source, path, prefer_worktree=True) for path in files[:30]}
    return BranchContext(source, base_ref, head, files, diff_uncommitted(repo), final_files, scope=scope, includes_worktree=True)


def has_commits(repo: Path) -> bool:
    proc = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo, capture_output=True)
    return proc.returncode == 0


def current_branch(repo: Path) -> str:
    return run_git(repo, ["branch", "--show-current"], check=False)


def head_sha(repo: Path) -> str:
    return run_git(repo, ["rev-parse", "HEAD"])


def require_current_scope(repo: Path, source: str, scope: str) -> None:
    current = current_branch(repo)
    if source != current:
        raise RuntimeError(f"`--scope {scope}` can only review the checked-out branch. Current branch is {current}.")


def untracked_files(repo: Path) -> list[str]:
    output = run_git(repo, ["ls-files", "--others", "--exclude-standard"], check=False)
    return sorted(path for path in output.splitlines() if path and not is_ignored(path))


def working_tree_files(repo: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(repo.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(repo))
            if not is_ignored(rel):
                files.append(rel)
    return files


def pathspec_excludes() -> list[str]:
    return [".", *[f":(exclude){name}/**" for name in sorted(IGNORED_DIRS)]]


def is_ignored(path: str) -> bool:
    parts = Path(path).parts
    return any(part in IGNORED_DIRS for part in parts)


def truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[airreview truncated file state]\n"
