from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from rich.prompt import Prompt
from rich.table import Table

from .azure_devops import pr_context
from .config import init_files, load_review_profile
from .git_tools import detect_base, ensure_git_repo, ref_exists
from .knowledge import LocalKnowledgeProvider
from .evals import run_local_evals, write_eval_report
from .models import build_model_client
from .rendering import (
    console,
    error,
    header,
    ok,
    render_agent_summary,
    render_knowledge,
    render_repository,
    render_review,
    render_tool_summary,
    warn,
)
from .tracing import RunTrace
from .workflow import AirReviewWorkflow, RunOptions


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(raw_args)
    args = parser.parse_args(raw_args)
    repo = Path.cwd()
    command = args.command
    try:
        if command == "init":
            return cmd_init(repo, force=args.force)
        if command == "knowledge":
            return cmd_knowledge(repo)
        if command == "doctor":
            return cmd_doctor(repo)
        if command == "eval":
            return cmd_eval(repo, output=args.output, mock=args.mock)
        return cmd_review(repo, args)
    except Exception as exc:
        error(str(exc))
        return 1


def build_parser(raw_args: list[str]) -> argparse.ArgumentParser:
    if raw_args and raw_args[0] in {"init", "knowledge", "doctor", "eval"}:
        parser = argparse.ArgumentParser(prog="airreview", description="Agentic branch code review, local-first.")
        subparsers = parser.add_subparsers(dest="command", required=True)
        init_parser = subparsers.add_parser("init", help="Initialize AirReview configuration and local knowledge.")
        init_parser.add_argument("--force", action="store_true", help="Overwrite AirReview defaults.")
        subparsers.add_parser("knowledge", help="Show local knowledge status.")
        subparsers.add_parser("doctor", help="Check Git, Python, Foundry, and Azure DevOps configuration.")
        eval_parser = subparsers.add_parser("eval", help="Run local AirReview evaluation cases.")
        eval_parser.add_argument("--output", "-o", default="airreview-eval-results.json", help="Write eval JSON report.")
        eval_parser.add_argument("--mock", action="store_true", default=True, help="Use mock model for deterministic evals.")
        return parser
    parser = argparse.ArgumentParser(prog="airreview", description="Agentic branch code review, local-first.")
    parser.set_defaults(command=None)
    parser.add_argument("branch", nargs="?", help="Feature branch to review. Defaults to current branch.")
    parser.add_argument("--base", help="Reference branch to review against, for example main, develop, or origin/main.")
    parser.add_argument(
        "--scope",
        choices=["branch", "working", "staged", "uncommitted"],
        default="branch",
        help="Review scope. Default: branch commits only. Use working/staged/uncommitted explicitly for local changes.",
    )
    parser.add_argument("--output", "-o", nargs="?", const=True, default=None, help="Write Markdown report. Optional path.")
    parser.add_argument("--mock", action="store_true", help="Use deterministic local model output.")
    parser.add_argument("--fetch", action="store_true", help="Fetch remotes before computing branch diff.")
    parser.add_argument("--post-ado", action="store_true", help="Post a global Azure DevOps PR comment.")
    parser.add_argument("--dry-run", action="store_true", help="Do not post to Azure DevOps; record intent only.")
    parser.add_argument("--fail-on", choices=["low", "medium", "high", "critical"], default=None, help="Exit non-zero when findings at this severity or higher exist.")
    return parser


def cmd_init(repo: Path, force: bool = False) -> int:
    header()
    ensure_git_repo(repo)
    paths = init_files(repo, force=force)
    status = LocalKnowledgeProvider(repo).bootstrap(force=force)
    for path in paths:
        ok(f"Initialized {path.relative_to(repo)}")
    ok(f"Knowledge indexed: {status.scanned_files} files")
    return 0


def cmd_knowledge(repo: Path) -> int:
    header()
    ensure_git_repo(repo)
    provider = LocalKnowledgeProvider(repo)
    status = provider.status()
    if not status.exists:
        warn("Local knowledge has not been initialized yet. Run `airreview init` or `airreview --mock`.")
    table = Table(title="Local Knowledge", show_header=True, header_style="bold cyan")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Exists", str(status.exists))
    table.add_row("Guidelines", str(status.guidelines_path))
    table.add_row("Generated", str(status.generated))
    table.add_row("Scanned files", str(status.scanned_files))
    table.add_row("Languages", ", ".join(status.languages) or "-")
    table.add_row("Index", str(status.index_path))
    console.print(table)
    return 0


def cmd_doctor(repo: Path) -> int:
    header()
    table = Table(title="Doctor", show_header=True, header_style="bold cyan")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Notes")
    git_ok = shutil.which("git") is not None
    table.add_row("Git", "ok" if git_ok else "missing", shutil.which("git") or "Install Git")
    table.add_row("Python", "ok", sys.version.split()[0])
    try:
        ensure_git_repo(repo)
        table.add_row("Repository", "ok", str(repo))
    except Exception as exc:
        table.add_row("Repository", "warning", str(exc))
    profile = load_review_profile(repo)
    table.add_row("Review profile", "ok", profile.profile)
    foundry_endpoint = _env_any(
        "FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_ENDPOINT",
        "FOUNDRY_ENDPOINT",
    )
    foundry_model = _env_any("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT_NAME", "AZURE_AI_MODEL")
    table.add_row("Foundry endpoint", "ok" if foundry_endpoint else "missing", foundry_endpoint or "Use --mock or set .env")
    table.add_row("Foundry model", "ok" if foundry_model else "missing", foundry_model or "Use --mock or set FOUNDRY_MODEL")
    ado = pr_context()
    table.add_row("Azure DevOps PR", "ok" if ado.is_complete else "optional", "complete" if ado.is_complete else "Only needed for --post-ado")
    console.print(table)
    return 0


def cmd_eval(repo: Path, output: str, mock: bool = True) -> int:
    header()
    result = run_local_evals(repo, mock=mock)
    target = Path(output)
    if not target.is_absolute():
        target = repo / target
    write_eval_report(target, result)
    table = Table(title="AirReview Evaluations", show_header=True, header_style="bold cyan")
    table.add_column("Case")
    table.add_column("Status")
    table.add_column("Findings")
    for case in result["cases"]:
        table.add_row(case["name"], "pass" if case["passed"] else "fail", str(case["findings_count"]))
    console.print(table)
    ok(f"Eval score: {result['passed']}/{result['total']}")
    ok(f"Eval report: {target}")
    return 0 if result["passed"] == result["total"] else 1


def cmd_review(repo: Path, args: argparse.Namespace) -> int:
    header()
    ensure_git_repo(repo)
    base = resolve_base(repo, args.base)
    profile = load_review_profile(repo)
    trace = RunTrace(repo=repo)
    model = build_model_client(mock=args.mock)
    workflow = AirReviewWorkflow(repo, profile, model, trace)
    output = workflow.run(
        RunOptions(
            branch=args.branch,
            base=base,
            scope=args.scope,
            output=args.output,
            mock=args.mock,
            fetch=args.fetch,
            post_ado=args.post_ado,
            dry_run=args.dry_run,
            fail_on=args.fail_on,
        )
    )
    render_repository(output.branch_context)
    render_knowledge(LocalKnowledgeProvider(repo).status(), profile)
    render_tool_summary(trace)
    render_agent_summary(trace)
    render_review(output.result, output.result.suggestions)
    if output.markdown_path:
        ok(f"Markdown report: {output.markdown_path}")
    ok(f"Trace: {output.trace_path}")
    if output.should_fail:
        error(f"Failing because review findings meet --fail-on {args.fail_on}")
        return 2
    return 0


def resolve_base(repo: Path, explicit_base: str | None) -> str | None:
    if explicit_base:
        if not ref_exists(repo, explicit_base):
            raise RuntimeError(f"Reference branch or ref does not exist: {explicit_base}")
        return explicit_base
    context = pr_context()
    if context.target_branch:
        return None
    detected = detect_base(repo)
    if is_interactive_local():
        answer = Prompt.ask("Reference branch", default=detected)
        if not ref_exists(repo, answer):
            raise RuntimeError(f"Reference branch or ref does not exist: {answer}")
        return answer
    return detected


def is_interactive_local() -> bool:
    import os

    if any(os.getenv(name) for name in ("CI", "TF_BUILD", "GITHUB_ACTIONS", "BUILD_BUILDID")):
        return False
    return sys.stdin.isatty()


def _env_any(*names: str) -> str:
    import os

    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
