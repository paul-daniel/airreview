from pathlib import Path

from airreview.agents import Finding, ReviewResult, Suggestion
from airreview.config import load_review_profile
from airreview.git_tools import BranchContext
from airreview.knowledge import KnowledgeBundle
from airreview.rendering import build_markdown, local_file_link, output_path_for_branch, vscode_file_uri
from airreview.tracing import RunTrace


def test_output_path_auto_uses_branch_name(tmp_path: Path) -> None:
    assert output_path_for_branch(tmp_path, "feature/demo", True) == tmp_path / ".airreview" / "reviews" / "feature" / "demo" / "review.md"


def test_output_path_relative_file_stays_inside_review_folder(tmp_path: Path) -> None:
    assert (
        output_path_for_branch(tmp_path, "feature/demo", "custom.md")
        == tmp_path / ".airreview" / "reviews" / "feature" / "demo" / "custom.md"
    )


def test_output_path_explicit_airreview_path_is_allowed(tmp_path: Path) -> None:
    assert (
        output_path_for_branch(tmp_path, "feature/demo", ".airreview/reviews/manual/review.md")
        == tmp_path / ".airreview" / "reviews" / "manual" / "review.md"
    )


def test_markdown_contains_findings(tmp_path: Path) -> None:
    profile = load_review_profile(tmp_path)
    context = BranchContext("feature/demo", "main", "abc123", ["app.py"], "diff", {"app.py": "x"})
    result = ReviewResult(
        summary="Done",
        findings=[
            Finding(
                file="app.py",
                line=3,
                severity="medium",
                category="testability",
                title="Add regression test",
                issue="Missing test.",
                why_it_matters="Regression risk.",
                confidence="high",
            )
        ],
        suggestions=[
            Suggestion(
                finding_title="Add regression test",
                suggestion="Add a focused test.",
                example="pytest",
                test_recommendation="Unit test",
                confidence="high",
            )
        ],
    )
    knowledge = KnowledgeBundle("", "", "", {"provider": "local", "languages": ["Python"]})
    markdown = build_markdown(context, profile, knowledge, result, RunTrace(tmp_path))
    assert "Add regression test" in markdown
    assert "app.py:3" in markdown


def test_markdown_contains_history_and_snippet(tmp_path: Path) -> None:
    profile = load_review_profile(tmp_path)
    context = BranchContext("feature/demo", "main", "abc123", ["app.py"], "diff", {"app.py": "a\nb\nc\n"})
    finding = Finding(
        file="app.py",
        line=2,
        severity="medium",
        category="quality",
        title="Line issue",
        issue="Problem.",
        why_it_matters="Impact.",
        confidence="high",
    )
    result = ReviewResult(
        summary="Done",
        findings=[finding],
        context={
            "line_snippets": {
                "app.py:2": {
                    "file": "app.py",
                    "code": "a\nb\nc",
                    "language": "python",
                    "start_line": 1,
                    "highlight_line": 2,
                }
            }
        },
        history={"previous_run": True, "new": [finding.__dict__], "still_present": [], "resolved": []},
    )
    knowledge = KnowledgeBundle("", "", "", {"provider": "local"})
    markdown = build_markdown(context, profile, knowledge, result, RunTrace(tmp_path))
    assert "Previous Review Comparison" in markdown
    assert "```python\na\nb\nc\n```" in markdown
    assert "target line 2" in markdown


def test_local_file_link_points_to_vscode_uri(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    finding = Finding(
        file="src/app.py",
        line=7,
        severity="medium",
        category="quality",
        title="Issue",
        issue="Problem.",
        why_it_matters="Impact.",
        confidence="high",
    )
    link = local_file_link(str(tmp_path), finding)
    assert link is not None
    assert "src/app.py:7" in link.plain
    assert "supported terminals" not in link.plain
    assert vscode_file_uri(tmp_path / "src/app.py", 7).startswith("vscode://file/")


def test_markdown_keeps_code_under_suggestion_and_hides_no_test_needed(tmp_path: Path) -> None:
    profile = load_review_profile(tmp_path)
    context = BranchContext("feature/demo", "main", "abc123", ["app.py"], "diff", {"app.py": "x"})
    finding = Finding(
        file="app.py",
        line=2,
        severity="medium",
        category="maintainability",
        title="TODO non assigné et non traqué",
        issue="TODO lacks ownership.",
        why_it_matters="It can be forgotten.",
        confidence="medium",
    )
    result = ReviewResult(
        summary="Done",
        findings=[finding],
        suggestions=[
            Suggestion(
                finding_title=finding.title,
                suggestion="Ajoute un identifiant de ticket ou un assignee dans le commentaire TODO.",
                example="# TODO(PROJECT-123, alice): add product owner validation before production",
                test_recommendation="No test needed",
                confidence="high",
            )
        ],
    )
    knowledge = KnowledgeBundle("", "", "", {"provider": "local"})
    markdown = build_markdown(context, profile, knowledge, result, RunTrace(tmp_path))

    assert "**Suggested fix:** Ajoute un identifiant" in markdown
    assert "```python\n# TODO(PROJECT-123, alice): add product owner validation before production\n```" in markdown
    assert "No test needed" not in markdown
    assert "**Test recommendation:**" not in markdown
