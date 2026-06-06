import subprocess
from pathlib import Path

from airreview.git_tools import collect_branch_context, detect_base


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def test_collect_branch_context_reviews_final_branch_state(tmp_path: Path) -> None:
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "app.py").write_text("def handler():\n    return True\n", encoding="utf-8")
    git(tmp_path, "add", "app.py")
    git(tmp_path, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "initial")
    git(tmp_path, "checkout", "-b", "feature/demo")
    (tmp_path / "app.py").write_text("def handler():\n    # TODO: owner\n    return True\n", encoding="utf-8")
    git(tmp_path, "add", "app.py")
    git(tmp_path, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "feature")

    assert detect_base(tmp_path) == "main"
    context = collect_branch_context(tmp_path)

    assert context.branch == "feature/demo"
    assert context.base == "main"
    assert context.changed_files == ["app.py"]
    assert "# TODO: owner" in context.final_files["app.py"]
    assert context.scope == "branch"
    assert not context.includes_worktree


def test_collect_branch_context_branch_scope_ignores_uncommitted_and_untracked_files(tmp_path: Path) -> None:
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "app.py").write_text("def handler():\n    return True\n", encoding="utf-8")
    git(tmp_path, "add", "app.py")
    git(tmp_path, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "initial")
    git(tmp_path, "checkout", "-b", "feature/demo")
    (tmp_path / "app.py").write_text("def handler():\n    return False\n", encoding="utf-8")
    (tmp_path / "new_module.py").write_text("def new_feature():\n    return 'ok'\n", encoding="utf-8")

    context = collect_branch_context(tmp_path)

    assert context.scope == "branch"
    assert not context.includes_worktree
    assert context.changed_files == []


def test_collect_branch_context_working_scope_includes_uncommitted_and_untracked_files(tmp_path: Path) -> None:
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "app.py").write_text("def handler():\n    return True\n", encoding="utf-8")
    git(tmp_path, "add", "app.py")
    git(tmp_path, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "initial")
    git(tmp_path, "checkout", "-b", "feature/demo")
    (tmp_path / "app.py").write_text("def handler():\n    return False\n", encoding="utf-8")
    (tmp_path / "new_module.py").write_text("def new_feature():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("noise\n", encoding="utf-8")

    context = collect_branch_context(tmp_path, scope="working")

    assert context.scope == "working"
    assert context.includes_worktree
    assert "app.py" in context.changed_files
    assert "new_module.py" in context.changed_files
    assert ".DS_Store" not in context.changed_files
    assert "return False" in context.final_files["app.py"]
    assert "new file mode" in context.diff


def test_collect_branch_context_staged_scope_only_reviews_index(tmp_path: Path) -> None:
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "app.py").write_text("def handler():\n    return True\n", encoding="utf-8")
    git(tmp_path, "add", "app.py")
    git(tmp_path, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "initial")
    git(tmp_path, "checkout", "-b", "feature/demo")
    (tmp_path / "app.py").write_text("def handler():\n    return False\n", encoding="utf-8")
    git(tmp_path, "add", "app.py")
    (tmp_path / "app.py").write_text("def handler():\n    return 'unstaged'\n", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("x = 1\n", encoding="utf-8")

    context = collect_branch_context(tmp_path, scope="staged")

    assert context.scope == "staged"
    assert context.changed_files == ["app.py"]
    assert "return False" in context.final_files["app.py"]
    assert "unstaged" not in context.final_files["app.py"]
    assert "untracked.py" not in context.changed_files
