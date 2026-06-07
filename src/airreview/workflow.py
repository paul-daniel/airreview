from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from rich.console import Console

from .agents import (
    JsonAgent,
    ReviewResult,
    apply_threshold,
    dedupe_findings,
    findings_from_json,
    suggestions_from_json,
)
from .azure_devops import post_pr_comment, pr_context
from .config import ReviewProfile
from .dependencies import scan_dependency_context
from .git_tools import BranchContext, collect_branch_context, fetch
from .github import github_context, post_review_comments as post_github_review_comments
from .history import compare_findings, load_previous_review, save_review_json
from .knowledge import KnowledgeBundle, LocalKnowledgeProvider
from .models import ModelClient
from .rendering import build_markdown, output_path_for_branch, write_markdown
from .tracing import RunTrace, ToolRegistry


@dataclass
class RunOptions:
    branch: str | None = None
    base: str | None = None
    scope: str = "branch"
    output: str | bool | None = None
    mock: bool = False
    fetch: bool = False
    post_ado: bool = False
    post_github: bool = False
    dry_run: bool = False
    fail_on: str | None = None
    verbose: bool = False
    quiet: bool = False


@dataclass
class WorkflowOutput:
    branch_context: BranchContext
    knowledge: KnowledgeBundle
    result: ReviewResult
    markdown_path: Path | None
    trace_path: Path
    should_fail: bool = False


class AirReviewWorkflow:
    def __init__(self, repo: Path, profile: ReviewProfile, model_client: ModelClient, trace: RunTrace):
        self.repo = repo
        self.profile = profile
        self.model_client = model_client
        self.trace = trace
        self.tools = ToolRegistry(trace)
        self.console = Console()
        self.verbose = False
        self.quiet = False

    def run(self, options: RunOptions) -> WorkflowOutput:
        self.verbose = options.verbose
        self.quiet = options.quiet
        if options.fetch:
            self._progress("Fetching remotes before review")
            with self.console.status("[cyan]Fetching remotes...[/cyan]", spinner="dots"):
                self.tools.call("git.fetch", fetch, self.repo)
            self._progress("Remotes fetched")
        self._progress("Collecting Git branch context")
        with self.console.status("[cyan]Collecting branch context...[/cyan]", spinner="dots"):
            branch_context = self.tools.call(
                "git.branch_context",
                collect_branch_context,
                self.repo,
                options.branch,
                options.base,
                options.scope,
            )
        self._progress(
            f"Branch context ready: {branch_context.branch} -> {branch_context.base}, "
            f"{len(branch_context.changed_files)} changed file(s)"
        )
        self._progress(f"Merge-base: {branch_context.merge_base}", detail=True)
        self._progress(f"Diff size: {len(branch_context.diff):,} chars", detail=True)
        self.trace.branch = branch_context.branch
        self.trace.base = branch_context.base
        self.trace.model = self.model_client.model_name
        previous_review = load_previous_review(self.repo, branch_context.branch)
        if previous_review:
            self._progress("Previous AirReview result found for comparison")

        if not branch_context.changed_files:
            knowledge = KnowledgeBundle("", "", "", {"provider": "local", "skipped": True})
            result = ReviewResult(
                summary=(
                    f"No changed files found for scope `{branch_context.scope}` between "
                    f"`{branch_context.branch}` and `{branch_context.base}`. Agents were not invoked."
                ),
                findings=[],
                suggestions=[],
                context={"repo_path": str(self.repo), "line_snippets": {}},
                plan={"strategy": "no_changes", "chunks": [], "budget": {"budget_exceeded": False}},
                history=compare_findings(previous_review, []),
            )
            markdown_path = self._write_outputs_if_requested(branch_context, knowledge, result, options)
            trace_path = self.trace.write()
            return WorkflowOutput(branch_context, knowledge, result, markdown_path, trace_path, should_fail=False)

        provider = LocalKnowledgeProvider(self.repo)
        self._progress("Loading local AirReview knowledge")
        with self.console.status("[cyan]Checking local knowledge...[/cyan]", spinner="dots"):
            status = self.tools.call("knowledge_status", provider.status)
            if not status.exists:
                self._progress("Local knowledge missing; bootstrapping repository scan")
                status = self.tools.call("knowledge_bootstrap", provider.bootstrap)
            knowledge = self.tools.call("knowledge_load", provider.load)
        self._progress(
            f"Knowledge ready: {status.scanned_files} scanned file(s), "
            f"{', '.join(status.languages) or 'unknown language'}"
        )
        self.tools.call("review_profile_load", lambda: self.profile.raw)
        self.tools.call("azure_devops.context", pr_context)
        self.tools.call("github.context", github_context)
        dependency_context = self.tools.call("dependency_context.scan", scan_dependency_context, self.repo)
        self._progress(dependency_summary(dependency_context), detail=True)

        planner_agent = JsonAgent("Review Planning Agent", "review_planning_agent.md", self.model_client)
        context_agent = JsonAgent("Codebase Context Agent", "codebase_context_agent.md", self.model_client)
        review_agent = JsonAgent("Branch Review Agent", "branch_review_agent.md", self.model_client)
        critic_agent = JsonAgent("Finding Critic Agent", "finding_critic_agent.md", self.model_client)
        fix_agent = JsonAgent("Fix Suggestion Agent", "fix_suggestion_agent.md", self.model_client)

        context_payload = {
            "branch": branch_context.branch,
            "base": branch_context.base,
            "changed_files": branch_context.changed_files,
            "includes_worktree": branch_context.includes_worktree,
            "knowledge": {
                "guidelines": knowledge.guidelines,
                "known_smells": knowledge.known_smells,
                "generated_scan": knowledge.generated_scan,
                "metadata": knowledge.metadata,
            },
            "review_profile": self.profile.raw,
            "dependency_context": dependency_context,
        }
        plan_json = self._run_agent(
            planner_agent,
            {
                **context_payload,
                "diff_size": len(branch_context.diff),
                "final_file_count": len(branch_context.final_files),
            },
        )
        chunks = normalize_chunks(plan_json, branch_context.changed_files)
        self._progress(
            f"Review plan: {plan_json.get('strategy', 'single_pass')} with {len(chunks)} chunk(s)"
        )
        budget = plan_json.get("budget", {})
        if isinstance(budget, dict) and budget.get("budget_exceeded"):
            self._progress("Review budget exceeded; remaining files will be skipped or capped by profile")
        codebase_context = self._run_agent(context_agent, context_payload)
        focus_count = len(codebase_context.get("review_focus", [])) if isinstance(codebase_context.get("review_focus"), list) else 0
        self._progress(f"Codebase context ready: {focus_count} review focus item(s)", detail=True)
        review_summaries: list[str] = []
        findings = []
        if self.profile.stop_when_budget_exceeded and plan_json.get("budget", {}).get("budget_exceeded"):
            chunks = chunks[: self.profile.max_chunks]
        for index, chunk in enumerate(chunks, start=1):
            files = [path for path in chunk.get("files", []) if path in branch_context.changed_files]
            if not files:
                continue
            chunk_name = str(chunk.get("name", f"chunk-{index}"))
            self._progress(
                f"Reviewing {chunk_name} ({index}/{len(chunks)}): {', '.join(files[:8])}"
                + ("..." if len(files) > 8 else "")
            )
            review_payload = {
                **context_payload,
                "review_plan": plan_json,
                "current_chunk": chunk,
                "previous_review": previous_review,
                "diff": diff_excerpt_for_files(branch_context.diff, files, self.profile.max_diff_chars_per_chunk),
                "final_files": {path: branch_context.final_files.get(path, "") for path in files},
                "codebase_context": codebase_context,
            }
            self._progress(
                f"{chunk_name} context: {len(review_payload['diff']):,} diff chars, "
                f"{len(review_payload['final_files'])} final file(s)",
                detail=True,
            )
            review_json = self._run_agent(review_agent, review_payload)
            review_summaries.append(str(review_json.get("summary", "")))
            chunk_findings = findings_from_json(review_json)
            findings.extend(chunk_findings)
            self._progress(f"{chunk_name} produced {len(chunk_findings)} candidate finding(s)")
        findings = dedupe_findings(findings)
        self._progress(f"Candidate findings after de-duplication: {len(findings)}")
        critic_json = self._run_agent(
            critic_agent,
            {
                "findings": [finding.__dict__ for finding in findings],
                "changed_files": branch_context.changed_files,
                "codebase_context": codebase_context,
                "review_profile": self.profile.raw,
            },
        )
        findings = findings_from_json(critic_json)
        rejected = critic_json.get("rejected_findings", [])
        rejected_count = len(rejected) if isinstance(rejected, list) else 0
        self._progress(f"Finding critic accepted {len(findings)} finding(s), rejected {rejected_count}")
        findings = apply_threshold(
            findings,
            self.profile.severity_threshold,
            self.profile.max_findings,
            self.profile.ignore_low_confidence,
        )
        self._progress(f"Findings after profile threshold: {len(findings)}")
        history = compare_findings(previous_review, findings)
        if history.get("previous_run"):
            self._progress(
                f"Previous review comparison: {len(history.get('new', []))} new, "
                f"{len(history.get('still_present', []))} still present, "
                f"{len(history.get('resolved', []))} resolved"
            )
        line_snippets = build_line_snippets(findings, branch_context.final_files)
        if findings:
            finding_files = sorted({finding.file for finding in findings if finding.file})
            self._progress(f"Preparing fix suggestions for {len(findings)} finding(s)")
            fix_json = self._run_agent(
                fix_agent,
                {
                    "branch": branch_context.branch,
                    "base": branch_context.base,
                    "scope": branch_context.scope,
                    "changed_files": branch_context.changed_files,
                    "findings": [finding.__dict__ for finding in findings],
                    "history": history,
                    "review_profile": self.profile.raw,
                    "codebase_context": codebase_context,
                    "dependency_context": dependency_context,
                    "code_context": line_snippets,
                    "final_files": {
                        path: branch_context.final_files.get(path, "")
                        for path in finding_files
                        if branch_context.final_files.get(path)
                    },
                    "diff": diff_excerpt_for_files(
                        branch_context.diff,
                        finding_files,
                        self.profile.max_diff_chars_per_chunk,
                    ),
                },
            )
            suggestions = suggestions_from_json(fix_json)
            self._progress(f"Fix suggestions ready: {len(suggestions)}")
        else:
            suggestions = []
            self._progress("No accepted findings; skipping fix suggestion agent")
        result = ReviewResult(
            summary=summarize_review(plan_json, review_summaries, critic_json),
            findings=findings,
            suggestions=suggestions,
            context={
                **codebase_context,
                "repo_path": str(self.repo),
                "line_snippets": line_snippets,
            },
            plan=plan_json,
            history=history,
        )
        self.trace.findings_count = len(findings)

        markdown_path = self._write_outputs_if_requested(branch_context, knowledge, result, options)
        if options.post_ado:
            self._progress("Posting Azure DevOps PR comment")
            markdown = build_markdown(branch_context, self.profile, knowledge, result, self.trace)
            self.tools.call("azure_devops_post_pr_comment", post_pr_comment, markdown, options.dry_run)
        if options.post_github:
            self._progress("Posting GitHub PR comments")
            markdown = build_markdown(branch_context, self.profile, knowledge, result, self.trace)
            self.tools.call(
                "github_post_review_comments",
                post_github_review_comments,
                result,
                result.suggestions,
                branch_context.diff,
                markdown,
                options.dry_run,
            )
        trace_path = self.trace.write()
        self._progress(f"Trace written: {trace_path}", detail=True)
        return WorkflowOutput(branch_context, knowledge, result, markdown_path, trace_path, should_fail=should_fail(result, options.fail_on))

    def _write_outputs_if_requested(
        self,
        branch_context: BranchContext,
        knowledge: KnowledgeBundle,
        result: ReviewResult,
        options: RunOptions,
    ) -> Path | None:
        markdown_path = None
        markdown = build_markdown(branch_context, self.profile, knowledge, result, self.trace)
        target = output_path_for_branch(self.repo, branch_context.branch, options.output)
        if target:
            self._progress(f"Writing Markdown report to {target}", detail=True)
            markdown_path = self.tools.call("output.markdown", write_markdown, target, markdown)
            self.trace.output_file = str(markdown_path)
            self._progress("Saving structured review JSON", detail=True)
            self.tools.call(
                "output.review_json",
                save_review_json,
                self.repo,
                branch_context.branch,
                result,
                {
                    "branch": branch_context.branch,
                    "base": branch_context.base,
                    "merge_base": branch_context.merge_base,
                    "scope": branch_context.scope,
                    "model": self.model_client.model_name,
                    "markdown_path": str(markdown_path),
                },
            )
        return markdown_path

    def _run_agent(self, agent: JsonAgent, payload: dict) -> dict:
        start = perf_counter()
        try:
            self._progress(f"{agent.name} started using {model_for_agent(self.model_client, agent.name)}")
            with self.console.status(f"[cyan]{agent.name}[/cyan]", spinner="dots"):
                result = agent.run(payload)
            duration_ms = (perf_counter() - start) * 1000
            self.trace.record_agent(agent.name, duration_ms, True)
            self._progress(f"{agent.name} completed in {duration_ms:.0f} ms")
            return result
        except Exception:
            duration_ms = (perf_counter() - start) * 1000
            self.trace.record_agent(agent.name, duration_ms, False)
            self._progress(f"{agent.name} failed after {duration_ms:.0f} ms")
            raise

    def _progress(self, message: str, detail: bool = False) -> None:
        if self.quiet or (detail and not self.verbose):
            return
        prefix = "[dim]•[/dim]" if detail else "[cyan]→[/cyan]"
        self.console.print(f"{prefix} {message}")


def normalize_chunks(plan: dict, changed_files: list[str]) -> list[dict]:
    chunks = plan.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        return [{"name": "full-review", "files": changed_files}]
    return chunks


def diff_excerpt_for_files(diff: str, files: list[str], limit: int) -> str:
    if len(diff) <= limit:
        return diff
    selected: list[str] = []
    current: list[str] = []
    include = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if current and include:
                selected.extend(current)
            current = [line]
            include = any(f"a/{path}" in line or f"b/{path}" in line for path in files)
        else:
            current.append(line)
    if current and include:
        selected.extend(current)
    excerpt = "\n".join(selected)
    if not excerpt:
        excerpt = diff[:limit]
    return excerpt[:limit] + ("\n[airreview diff excerpt truncated]\n" if len(excerpt) > limit else "")


def summarize_review(plan: dict, summaries: list[str], critic_json: dict) -> str:
    strategy = plan.get("strategy", "single_pass")
    budget = plan.get("budget", {})
    exceeded = " budget exceeded" if budget.get("budget_exceeded") else ""
    accepted = len(critic_json.get("accepted_findings", []))
    return f"Reviewed branch with {strategy}{exceeded}; accepted {accepted} finding(s)."


def should_fail(result: ReviewResult, fail_on: str | None) -> bool:
    if not fail_on:
        return False
    weights = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    minimum = weights.get(fail_on, 2)
    return any(weights.get(finding.severity, 1) >= minimum for finding in result.findings)


def model_for_agent(model_client: ModelClient, agent_name: str) -> str:
    agent_models = getattr(model_client, "agent_models", None)
    if isinstance(agent_models, dict):
        return str(agent_models.get(agent_name) or model_client.model_name)
    return model_client.model_name


def dependency_summary(context: dict) -> str:
    dependencies = context.get("dependencies", {})
    dev_dependencies = context.get("dev_dependencies", {})
    total = len(dependencies) + len(dev_dependencies) if isinstance(dependencies, dict) and isinstance(dev_dependencies, dict) else 0
    manifests = context.get("package_manifests", [])
    manifest_text = ", ".join(manifests) if isinstance(manifests, list) and manifests else "no dependency manifest"
    package_manager = context.get("package_manager", "unknown")
    return f"Dependency context: {total} package(s), {manifest_text}, package manager {package_manager}"


def build_line_snippets(findings: list, final_files: dict[str, str], radius: int = 2) -> dict[str, dict]:
    snippets: dict[str, dict] = {}
    for finding in findings:
        if not finding.line or finding.file not in final_files:
            continue
        lines = final_files[finding.file].splitlines()
        if not lines:
            continue
        start = max(1, finding.line - radius)
        end = min(len(lines), finding.line + radius)
        code = "\n".join(lines[start - 1 : end])
        snippets[f"{finding.file}:{finding.line}"] = {
            "file": finding.file,
            "code": code,
            "language": language_for_path(finding.file),
            "start_line": start,
            "highlight_line": finding.line,
        }
    return snippets


def language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".cs": "csharp",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".json": "json",
        ".toml": "toml",
        ".md": "markdown",
        ".sh": "bash",
        ".sql": "sql",
        ".html": "html",
        ".css": "css",
    }.get(suffix, "text")
