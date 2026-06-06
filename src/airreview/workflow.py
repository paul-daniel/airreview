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
from .github import github_context, post_pr_comment as post_github_pr_comment
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

    def run(self, options: RunOptions) -> WorkflowOutput:
        if options.fetch:
            with self.console.status("[cyan]Fetching remotes...[/cyan]", spinner="dots"):
                self.tools.call("git.fetch", fetch, self.repo)
        with self.console.status("[cyan]Collecting branch context...[/cyan]", spinner="dots"):
            branch_context = self.tools.call(
                "git.branch_context",
                collect_branch_context,
                self.repo,
                options.branch,
                options.base,
                options.scope,
            )
        self.trace.branch = branch_context.branch
        self.trace.base = branch_context.base
        self.trace.model = self.model_client.model_name
        previous_review = load_previous_review(self.repo, branch_context.branch)

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
        with self.console.status("[cyan]Checking local knowledge...[/cyan]", spinner="dots"):
            status = self.tools.call("knowledge_status", provider.status)
            if not status.exists:
                status = self.tools.call("knowledge_bootstrap", provider.bootstrap)
            knowledge = self.tools.call("knowledge_load", provider.load)
        self.tools.call("review_profile_load", lambda: self.profile.raw)
        self.tools.call("azure_devops.context", pr_context)
        self.tools.call("github.context", github_context)
        dependency_context = self.tools.call("dependency_context.scan", scan_dependency_context, self.repo)

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
        codebase_context = self._run_agent(context_agent, context_payload)
        review_summaries: list[str] = []
        findings = []
        chunks = normalize_chunks(plan_json, branch_context.changed_files)
        if self.profile.stop_when_budget_exceeded and plan_json.get("budget", {}).get("budget_exceeded"):
            chunks = chunks[: self.profile.max_chunks]
        for chunk in chunks:
            files = [path for path in chunk.get("files", []) if path in branch_context.changed_files]
            if not files:
                continue
            self.console.print(f"[cyan]Reviewing {chunk.get('name', 'chunk')}[/cyan]: {', '.join(files[:8])}")
            review_payload = {
                **context_payload,
                "review_plan": plan_json,
                "current_chunk": chunk,
                "previous_review": previous_review,
                "diff": diff_excerpt_for_files(branch_context.diff, files, self.profile.max_diff_chars_per_chunk),
                "final_files": {path: branch_context.final_files.get(path, "") for path in files},
                "codebase_context": codebase_context,
            }
            review_json = self._run_agent(review_agent, review_payload)
            review_summaries.append(str(review_json.get("summary", "")))
            findings.extend(findings_from_json(review_json))
        findings = dedupe_findings(findings)
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
        findings = apply_threshold(
            findings,
            self.profile.severity_threshold,
            self.profile.max_findings,
            self.profile.ignore_low_confidence,
        )
        history = compare_findings(previous_review, findings)
        line_snippets = build_line_snippets(findings, branch_context.final_files)
        if findings:
            finding_files = sorted({finding.file for finding in findings if finding.file})
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
        else:
            suggestions = []
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
            markdown = build_markdown(branch_context, self.profile, knowledge, result, self.trace)
            self.tools.call("azure_devops_post_pr_comment", post_pr_comment, markdown, options.dry_run)
        if options.post_github:
            markdown = build_markdown(branch_context, self.profile, knowledge, result, self.trace)
            self.tools.call("github_post_pr_comment", post_github_pr_comment, markdown, options.dry_run)
        trace_path = self.trace.write()
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
            markdown_path = self.tools.call("output.markdown", write_markdown, target, markdown)
            self.trace.output_file = str(markdown_path)
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
            with self.console.status(f"[cyan]{agent.name}[/cyan]", spinner="dots"):
                result = agent.run(payload)
            self.trace.record_agent(agent.name, (perf_counter() - start) * 1000, True)
            return result
        except Exception:
            self.trace.record_agent(agent.name, (perf_counter() - start) * 1000, False)
            raise


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
