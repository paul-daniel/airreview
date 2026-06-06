from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from rich.console import Group
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from .agents import Finding, ReviewResult, Suggestion
from .config import ReviewProfile
from .git_tools import BranchContext
from .history import default_markdown_path
from .knowledge import KnowledgeBundle, KnowledgeStatus
from .tracing import RunTrace


console = Console()


def header() -> None:
    title = Text("AirReview", style="bold cyan")
    title.append(" - Agentic Code Reviewer", style="bold white")
    console.print(Panel.fit(title, border_style="cyan"))


def ok(message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def warn(message: str) -> None:
    console.print(f"[yellow]![/yellow] {message}")


def error(message: str) -> None:
    console.print(f"[red]✗[/red] {message}")


def render_repository(context: BranchContext) -> None:
    console.print("\n[bold]Repository[/bold]")
    ok(f"Branch detected: {context.branch}")
    ok(f"Base detected: {context.base}")
    ok(f"Review scope: {context.scope}")
    ok(f"Merge-base resolved: {context.merge_base[:12]}")
    ok(f"Changed files discovered: {len(context.changed_files)}")
    if context.includes_worktree:
        ok("Local changes included by explicit scope")


def render_knowledge(status: KnowledgeStatus, profile: ReviewProfile) -> None:
    console.print("\n[bold]Knowledge[/bold]")
    ok("Local knowledge found" if status.exists else "Local knowledge initialized")
    ok(f"Codebase guidelines loaded ({'generated draft' if status.generated else 'user-provided or existing'})")
    ok(f"Review profile loaded: {profile.profile}")
    if status.languages:
        ok(f"Languages detected: {', '.join(status.languages)}")


def render_tool_summary(trace: RunTrace) -> None:
    console.print("\n[bold]Tool calling[/bold]")
    for tool in trace.tools:
        if tool.ok:
            ok(tool.name)
        else:
            error(tool.name)


def render_agent_summary(trace: RunTrace) -> None:
    console.print("\n[bold]Multi-agent workflow[/bold]")
    if not trace.agents:
        ok("Agents not invoked")
        return
    for agent in trace.agents:
        if agent.ok:
            ok(f"{agent.name} ({agent.duration_ms:.0f} ms)")
        else:
            error(agent.name)


def render_review(result: ReviewResult, suggestions: list[Suggestion]) -> None:
    console.print("\n[bold]Review summary[/bold]")
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Severity")
    table.add_column("File")
    table.add_column("Title")
    table.add_column("Confidence")
    if not result.findings:
        table.add_row("-", "-", "No findings above threshold", "-")
    for finding in result.findings:
        table.add_row(finding.severity, _location(finding), finding.title, finding.confidence)
    console.print(table)
    if result.history.get("previous_run"):
        console.print(
            f"[bold]Previous review[/bold] "
            f"new={len(result.history.get('new', []))}, "
            f"still_present={len(result.history.get('still_present', []))}, "
            f"resolved={len(result.history.get('resolved', []))}"
        )
    for finding in result.findings:
        suggestion = find_suggestion(finding, suggestions)
        snippet = result.context.get("line_snippets", {}).get(_location_key(finding))
        renderables = [
            Text("Issue", style="bold"),
            Text(finding.issue),
            Text(""),
            Text("Why it matters", style="bold"),
            Text(finding.why_it_matters),
            Text(""),
        ]
        link = local_file_link(result.context.get("repo_path"), finding)
        if link:
            renderables.extend([Text("Open file", style="bold"), link, Text("")])
        if snippet:
            renderables.extend([Text("Code context", style="bold"), syntax_from_snippet(snippet), Text("")])
        renderables.extend(
            [
                Text("Suggested fix", style="bold"),
                Text(suggestion.suggestion if suggestion else "Review this location and apply a scoped fix."),
            ]
        )
        if suggestion and suggestion.example:
            renderables.extend([render_suggestion_text(suggestion.example), Text("")])
        else:
            renderables.append(Text(""))
        if suggestion and has_test_recommendation(suggestion.test_recommendation):
            renderables.extend([Text("Test", style="bold"), Text(suggestion.test_recommendation)])
        console.print(Panel(Group(*renderables), title=f"{finding.severity.upper()} - {_location(finding)} - {finding.title}", border_style=_severity_style(finding.severity)))
    console.print(Panel(result.summary or "Review completed.", title="Summary", border_style="green"))
    console.print("[bold]Next steps[/bold]")
    console.print("- Review findings above and apply scoped fixes.")
    console.print("- Commit the Markdown report or attach it to the PR when useful.")


def build_markdown(
    branch_context: BranchContext,
    profile: ReviewProfile,
    knowledge: KnowledgeBundle,
    result: ReviewResult,
    trace: RunTrace,
) -> str:
    lines = [f"# AirReview Report - {branch_context.branch}", ""]
    lines.extend(
        [
            "## Context",
            "",
            f"- Source branch: `{branch_context.branch}`",
            f"- Target branch: `{branch_context.base}`",
            f"- Merge-base: `{branch_context.merge_base}`",
            f"- Review profile: `{profile.profile}`",
            f"- Review scope: `{branch_context.scope}`",
            f"- Changed files: {len(branch_context.changed_files)}",
            f"- Working tree included: `{branch_context.includes_worktree}`",
            "",
            "## Review Plan",
            "",
            f"- Strategy: `{result.plan.get('strategy', 'single_pass')}`",
            f"- Budget exceeded: `{result.plan.get('budget', {}).get('budget_exceeded', False)}`",
            f"- Chunks: {len(result.plan.get('chunks', []))}",
            f"- Skipped files: {len(result.plan.get('skipped_files', []))}",
            "",
            "## Summary",
            "",
            result.summary or "Review completed.",
            "",
        ]
    )
    if result.history.get("previous_run"):
        lines.extend(
            [
                "## Previous Review Comparison",
                "",
                f"- New findings: {len(result.history.get('new', []))}",
                f"- Still present: {len(result.history.get('still_present', []))}",
                f"- Resolved since previous review: {len(result.history.get('resolved', []))}",
                "",
            ]
        )
    lines.extend(["## Findings", ""])
    if not result.findings:
        lines.extend(["No findings above the configured threshold.", ""])
    for finding in result.findings:
        suggestion = find_suggestion(finding, result.suggestions)
        snippet = result.context.get("line_snippets", {}).get(_location_key(finding), "")
        lines.extend(
            [
                f"### {finding.severity.upper()} - {finding.title}",
                "",
                f"- Category: `{finding.category}`",
                f"- Location: `{_location(finding)}`",
                f"- Confidence: `{finding.confidence}`",
                "",
                f"**Issue:** {finding.issue}",
                "",
                f"**Why it matters:** {finding.why_it_matters}",
                "",
            ]
        )
        if snippet:
            language = str(snippet.get("language", "text")) if isinstance(snippet, dict) else "text"
            code = str(snippet.get("code", "")) if isinstance(snippet, dict) else str(snippet)
            start_line = snippet.get("start_line") if isinstance(snippet, dict) else None
            highlight_line = snippet.get("highlight_line") if isinstance(snippet, dict) else None
            line_note = f" lines {start_line}-{start_line + len(code.splitlines()) - 1}" if start_line else ""
            target_note = f"; target line {highlight_line}" if highlight_line else ""
            lines.extend(
                [
                    f"**Code context:** `{finding.file}`{line_note}{target_note}",
                    "",
                    f"```{language}",
                    code,
                    "```",
                    "",
                ]
            )
        lines.extend(
            [
                "**Suggested fix:** "
                + (suggestion.suggestion if suggestion else "Apply a scoped fix at the reported location."),
                "",
            ]
        )
        if suggestion and suggestion.example:
            lines.extend(markdown_example_lines(suggestion.example))
        if suggestion and has_test_recommendation(suggestion.test_recommendation):
            lines.extend(["**Test recommendation:** " + suggestion.test_recommendation, ""])
    lines.extend(
        [
            "## Suggested fixes",
            "",
            *suggestion_lines(result.suggestions),
            "## Knowledge used",
            "",
            f"- Provider: `{knowledge.metadata.get('provider', 'local')}`",
            f"- Generated guidelines: `{knowledge.metadata.get('generated_guidelines', False)}`",
            f"- Languages: `{', '.join(knowledge.metadata.get('languages', [])) or 'unknown'}`",
            f"- Signature: `{knowledge.metadata.get('signature', 'unknown')}`",
            "",
            "## Tools invoked",
            "",
            *[f"- `{tool.name}`: {'ok' if tool.ok else 'failed'} ({tool.duration_ms:.0f} ms)" for tool in trace.tools],
            "",
            "## Next steps",
            "",
            "- Fix high and critical findings first.",
            "- Add tests for behavior-changing fixes.",
            "- Re-run `airreview --mock --output` or the Foundry-backed run before posting.",
            "",
        ]
    )
    return "\n".join(lines)


def write_markdown(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def output_path_for_branch(repo: Path, branch: str, requested: str | bool | None) -> Path | None:
    if requested is None or requested is False:
        return None
    if isinstance(requested, str):
        requested_path = Path(requested)
        if requested_path.is_absolute():
            return requested_path
        if requested_path.parts and requested_path.parts[0] == ".airreview":
            return repo / requested_path
        return default_markdown_path(repo, branch).parent / requested_path
    return default_markdown_path(repo, branch)


def find_suggestion(finding: Finding, suggestions: Iterable[Suggestion]) -> Suggestion | None:
    for suggestion in suggestions:
        if suggestion.finding_title == finding.title:
            return suggestion
    return None


def suggestion_lines(suggestions: list[Suggestion]) -> list[str]:
    if not suggestions:
        return ["No suggestions generated.", ""]
    lines: list[str] = []
    for suggestion in suggestions:
        lines.extend(
            [
                f"### {suggestion.finding_title}",
                "",
                suggestion.suggestion,
                "",
            ]
        )
        if suggestion.example:
            lines.extend(markdown_example_lines(suggestion.example))
        if has_test_recommendation(suggestion.test_recommendation):
            lines.extend([f"- Test: {suggestion.test_recommendation}", ""])
        lines.extend([f"- Confidence: `{suggestion.confidence}`", ""])
    return lines


def _location(finding: Finding) -> str:
    return f"{finding.file}:{finding.line}" if finding.line else finding.file


def _location_key(finding: Finding) -> str:
    return f"{finding.file}:{finding.line}"


def _severity_style(severity: str) -> str:
    return {"critical": "red", "high": "red", "medium": "yellow", "low": "blue"}.get(severity, "white")


def local_file_link(repo_path: object, finding: Finding) -> Text | None:
    if is_ci() or not repo_path or not finding.file:
        return None
    absolute = Path(str(repo_path)) / finding.file
    line = finding.line or 1
    display = f"{finding.file}:{line}"
    vscode_uri = vscode_file_uri(absolute, line)
    text = Text(display, style=f"cyan underline link {vscode_uri}")
    text.append("  ")
    text.append("(Cmd/Ctrl-click)", style="dim")
    return text


def vscode_file_uri(path: Path, line: int) -> str:
    encoded = quote(str(path), safe="/:")
    return f"vscode://file/{encoded}:{line}:1"


def is_ci() -> bool:
    return any(os.getenv(name) for name in ("CI", "TF_BUILD", "GITHUB_ACTIONS", "BUILD_BUILDID"))


def syntax_from_snippet(snippet: dict) -> Syntax:
    code = str(snippet.get("code", ""))
    language = str(snippet.get("language", "text"))
    start_line = int(snippet.get("start_line") or 1)
    highlight_line = int(snippet.get("highlight_line") or start_line)
    return Syntax(
        code,
        language,
        theme="github-dark",
        line_numbers=True,
        start_line=start_line,
        highlight_lines={highlight_line},
        word_wrap=False,
        dedent=False,
    )


def render_suggestion_text(text: str):
    if looks_like_code(text):
        return Syntax(text, infer_language_from_text(text), theme="github-dark", word_wrap=False, dedent=False)
    return Text(text)


def markdown_example_lines(example: str) -> list[str]:
    if not example:
        return []
    if looks_like_code(example):
        language = infer_language_from_text(example)
        return [f"```{language}", example, "```", ""]
    return [example, ""]


def looks_like_code(text: str) -> bool:
    stripped = text.strip()
    code_markers = (
        "def ",
        "class ",
        "return ",
        "const ",
        "let ",
        "var ",
        "=>",
        "{",
        "}",
        "import ",
        "from ",
        "pytest",
        "assert ",
        "if ",
        "for ",
        " = ",
        "TODO(",
    )
    return "\n" in text or stripped.startswith(("#", "//", "export ", "function ")) or any(marker in text for marker in code_markers)


def infer_language_from_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(("def ", "class ", "from ", "import ", "#")) or "pytest" in stripped or "assert " in stripped:
        return "python"
    if stripped.startswith(("const ", "let ", "var ", "function ")) or "=>" in stripped:
        return "typescript"
    if stripped.startswith(("{", "[")):
        return "json"
    return "text"


def has_test_recommendation(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(normalized) and normalized not in {"no test needed", "n/a", "none", "not needed", "aucun test necessaire", "aucun test nécessaire"}
