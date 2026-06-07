from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from rich.prompt import Prompt
from rich.table import Table

from .azure_devops import pr_context
from .config import airreview_path, init_files, load_local_env, load_review_profile
from .git_tools import collect_branch_context, detect_base, ensure_git_repo, ref_exists
from .github import github_context, post_review_comments as post_github_review_comments
from .evals import run_local_evals, write_eval_report
from .foundry_sync import agent_refs, sync_agents, sync_models
from .history import default_json_path, default_markdown_path, load_review_result
from .knowledge import LocalKnowledgeProvider
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
    load_local_env(repo)
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
        if command == "foundry":
            return cmd_foundry(repo, args)
        if command == "github":
            return cmd_github(repo, args)
        return cmd_review(repo, args)
    except Exception as exc:
        error(str(exc))
        return 1


def build_parser(raw_args: list[str]) -> argparse.ArgumentParser:
    if raw_args and raw_args[0] in {"init", "knowledge", "doctor", "eval", "foundry", "github"}:
        parser = argparse.ArgumentParser(prog="airreview", description="Agentic branch code review, local-first.")
        subparsers = parser.add_subparsers(dest="command", required=True)
        init_parser = subparsers.add_parser("init", help="Initialize AirReview configuration and local knowledge.")
        init_parser.add_argument("--force", action="store_true", help="Overwrite AirReview defaults.")
        subparsers.add_parser("knowledge", help="Show local knowledge status.")
        subparsers.add_parser("doctor", help="Check Git, Python, Foundry, and Azure DevOps configuration.")
        eval_parser = subparsers.add_parser("eval", help="Run local AirReview evaluation cases.")
        eval_parser.add_argument("--output", "-o", default="airreview-eval-results.json", help="Write eval JSON report.")
        eval_parser.add_argument("--mock", action="store_true", default=True, help="Use mock model for deterministic evals.")
        foundry_parser = subparsers.add_parser("foundry", help="Foundry GenAIOps commands.")
        foundry_sub = foundry_parser.add_subparsers(dest="foundry_command", required=True)
        models_parser = foundry_sub.add_parser("sync-models", help="Create missing Foundry model deployments from foundry/models.yaml.")
        models_parser.add_argument("--dry-run", action="store_true", help="Show model sync plan without calling Azure.")
        models_parser.add_argument("--prune", action="store_true", help="Delete orphaned airreview-* deployments not declared in foundry/models.yaml.")
        models_parser.add_argument("--output-json", help="Write raw sync results for automation.")
        sync_parser = foundry_sub.add_parser("sync-agents", help="Create/update Foundry prompt agents from manifests.")
        sync_parser.add_argument("--dry-run", action="store_true", help="Show agent sync plan without calling Foundry.")
        sync_parser.add_argument("--output-json", help="Write raw sync results for automation.")
        github_parser = subparsers.add_parser("github", help="GitHub PR integration commands.")
        github_sub = github_parser.add_subparsers(dest="github_command", required=True)
        post_parser = github_sub.add_parser("post", help="Post an already generated AirReview report to a GitHub PR.")
        post_parser.add_argument("branch", nargs="?", help="Reviewed branch. Defaults to current branch.")
        post_parser.add_argument("--base", help="Reference branch used to compute the PR diff.")
        post_parser.add_argument("--scope", choices=["branch", "working", "staged", "uncommitted"], default="branch")
        post_parser.add_argument("--review-json", help="Path to review.json. Defaults to .airreview/reviews/<branch>/review.json.")
        post_parser.add_argument("--markdown", help="Path to review.md. Defaults to .airreview/reviews/<branch>/review.md.")
        post_parser.add_argument("--dry-run", action="store_true", help="Do not post comments; print posting intent only.")
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
    parser.add_argument("--post-github", action="store_true", help="Post GitHub PR review comments, inline when possible.")
    parser.add_argument("--dry-run", action="store_true", help="Do not post to Azure DevOps; record intent only.")
    parser.add_argument("--fail-on", choices=["low", "medium", "high", "critical"], default=None, help="Exit non-zero when findings at this severity or higher exist.")
    parser.add_argument("--verbose", action="store_true", help="Show more progress details while AirReview runs.")
    parser.add_argument("--quiet", action="store_true", help="Hide progress timeline and only render final output.")
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
    agent_mode = _env_any("AIRREVIEW_AGENT_MODE")
    local_env = airreview_path(repo) / ".env"
    table.add_row("Local env file", "ok" if local_env.exists() else "optional", str(local_env) if local_env.exists() else "Use `.airreview/.env` to avoid shell exports")
    table.add_row("Foundry endpoint", "ok" if foundry_endpoint else "missing", foundry_endpoint or "Use --mock or set .env")
    if agent_mode == "foundry_agents":
        table.add_row("Foundry model", "agent mode", "Per-agent deployments are configured by AirReview")
    else:
        table.add_row("Foundry model", "ok" if foundry_model else "missing", foundry_model or "Use --mock or set FOUNDRY_MODEL")
    ado = pr_context()
    table.add_row("Azure DevOps PR", "ok" if ado.is_complete else "optional", "complete" if ado.is_complete else "Only needed for --post-ado")
    gh = github_context()
    table.add_row("GitHub PR", "ok" if gh.is_complete else "optional", "complete" if gh.is_complete else "Only needed for --post-github")
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


def cmd_foundry(repo: Path, args: argparse.Namespace) -> int:
    header()
    if args.foundry_command == "sync-agents":
        rows = sync_agents(repo, dry_run=args.dry_run)
        table = Table(title="Foundry Agent Sync", show_header=True, header_style="bold cyan")
        table.add_column("Agent")
        table.add_column("Model")
        table.add_column("Tools")
        table.add_column("Version")
        table.add_column("Eval ref")
        table.add_column("Mode")
        for row in rows:
            ref = "-"
            if not row.get("dry_run") and row.get("name") and row.get("version"):
                ref = f"{row.get('name')}:{row.get('version')}"
            table.add_row(
                str(row.get("name")),
                str(row.get("model", "-")),
                ", ".join(row.get("tools", [])) or "-",
                str(row.get("version", "-")),
                ref,
                "dry-run" if row.get("dry_run") else "synced",
            )
        console.print(table)
        if args.output_json:
            target = Path(args.output_json)
            if not target.is_absolute():
                target = repo / target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            ok(f"Foundry sync JSON: {target}")
        if not args.dry_run:
            refs = agent_refs(rows)
            if refs:
                ok("Foundry eval refs: " + ",".join(refs))
        return 0
    if args.foundry_command == "sync-models":
        rows = sync_models(repo, dry_run=args.dry_run, prune=args.prune)
        table = Table(title="Foundry Model Sync", show_header=True, header_style="bold cyan")
        table.add_column("Key")
        table.add_column("Deployment")
        table.add_column("Model")
        table.add_column("SKU")
        table.add_column("Capacity")
        table.add_column("Status")
        for row in rows:
            table.add_row(
                str(row.get("key", "-")),
                str(row.get("deployment_name", "-")),
                str(row.get("model", "-")),
                str(row.get("sku", "-")),
                str(row.get("capacity", "-")),
                str(row.get("status", "-")),
            )
        console.print(table)
        if args.output_json:
            target = Path(args.output_json)
            if not target.is_absolute():
                target = repo / target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            ok(f"Foundry model sync JSON: {target}")
        return 0
    raise RuntimeError(f"Unsupported Foundry command: {args.foundry_command}")


def cmd_github(repo: Path, args: argparse.Namespace) -> int:
    header()
    if args.github_command != "post":
        raise RuntimeError(f"Unsupported GitHub command: {args.github_command}")
    ensure_git_repo(repo)
    base = resolve_base(repo, args.base)
    branch_context = collect_branch_context(repo, args.branch, base, args.scope)
    review_json = Path(args.review_json) if args.review_json else default_json_path(repo, branch_context.branch)
    markdown_path = Path(args.markdown) if args.markdown else default_markdown_path(repo, branch_context.branch)
    if not review_json.is_absolute():
        review_json = repo / review_json
    if not markdown_path.is_absolute():
        markdown_path = repo / markdown_path
    if not review_json.exists():
        raise RuntimeError(f"Review JSON not found: {review_json}")
    if not markdown_path.exists():
        raise RuntimeError(f"Markdown report not found: {markdown_path}")
    result = load_review_result(review_json)
    markdown = markdown_path.read_text(encoding="utf-8")
    payload = post_github_review_comments(result, result.suggestions, branch_context.diff, markdown, args.dry_run)
    if payload.get("posted"):
        ok(
            "GitHub comments posted "
            f"({payload.get('new_comments', 0)} new, "
            f"{payload.get('skipped_existing', 0)} already present, "
            f"{payload.get('resolved', 0)} resolved)"
        )
    else:
        ok(
            "GitHub post dry-run: "
            f"{payload.get('inline_comments', 0)} inline, "
            f"{payload.get('fallback_comments', 0)} fallback"
        )
    return 0


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
            post_github=args.post_github,
            dry_run=args.dry_run,
            fail_on=args.fail_on,
            verbose=args.verbose,
            quiet=args.quiet,
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
