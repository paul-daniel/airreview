from __future__ import annotations

import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
from .git_tools import BranchContext, collect_branch_context, fetch, run_git
from .github import github_context, load_pr_review_state, post_review_comments as post_github_review_comments
from .history import compare_findings, default_json_path, diff_hash, load_previous_review, load_review_result, save_review_json
from .knowledge import KnowledgeBundle, LocalKnowledgeProvider, discovery_chunk_payload, sample_practice_chunks
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
        current_diff_hash = diff_hash(branch_context.diff)
        current_head_sha = git_head_for_ref(self.repo, branch_context.branch)
        previous_review = load_previous_review(self.repo, branch_context.branch)
        github_state: dict = {}
        github_pr_context = github_context()
        github_memory_enabled = github_pr_context.is_complete and not options.dry_run
        if github_memory_enabled:
            self._progress("Checking GitHub PR memory for previous AirReview state")
            try:
                github_state = self.tools.call("github_state.load", load_pr_review_state, options.dry_run)
            except Exception as exc:
                self._progress(f"GitHub PR memory unavailable before review: {exc}", detail=True)
            github_previous = previous_review_from_github_state(github_state)
            if github_previous and not previous_review:
                previous_review = github_previous
                self._progress("Previous AirReview state loaded from GitHub PR memory")
        elif options.post_github:
            self._progress("GitHub PR memory unavailable before review: missing PR context or token", detail=True)
        if previous_review:
            self._progress("Previous AirReview result found for comparison")
            metadata = previous_review.get("metadata", {}) if isinstance(previous_review.get("metadata"), dict) else {}
            local_review_path = default_json_path(self.repo, branch_context.branch)
            if metadata.get("diff_hash") == current_diff_hash and local_review_path.exists():
                self._progress("Diff unchanged since previous AirReview run; reusing cached review result")
                result = load_review_result(local_review_path)
                knowledge = KnowledgeBundle("", "", "", {"provider": "local", "cache_hit": True})
                markdown_path = self._write_outputs_if_requested(
                    branch_context,
                    knowledge,
                    result,
                    options,
                    extra_metadata={
                        "head_sha": current_head_sha,
                        "diff_hash": current_diff_hash,
                        "cache_hit": True,
                    },
                )
                if options.post_github:
                    self._progress("Posting cached GitHub PR comments with duplicate protection")
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
                if options.post_ado:
                    self._progress("Posting cached Azure DevOps PR comment")
                    markdown = build_markdown(branch_context, self.profile, knowledge, result, self.trace)
                    self.tools.call("azure_devops_post_pr_comment", post_pr_comment, markdown, options.dry_run)
                trace_path = self.trace.write()
                self._progress(f"Trace written: {trace_path}", detail=True)
                return WorkflowOutput(
                    branch_context,
                    knowledge,
                    result,
                    markdown_path,
                    trace_path,
                    should_fail=should_fail(result, options.fail_on),
                )
            if github_state.get("diff_hash") == current_diff_hash:
                self._progress("GitHub PR memory matches this diff; skipping agent calls")
                findings = findings_from_json({"findings": github_previous.get("findings", [])}) if github_previous else []
                result = ReviewResult(
                    summary="Diff unchanged since previous AirReview PR review; agents were not invoked.",
                    findings=findings,
                    suggestions=[],
                    context={"repo_path": str(self.repo), "line_snippets": build_line_snippets(findings, branch_context.final_files)},
                    plan={"strategy": "github_pr_memory_cache", "chunks": [], "budget": {"budget_exceeded": False}},
                    history=compare_findings(previous_review, findings),
                )
                knowledge = KnowledgeBundle("", "", "", {"provider": "local", "cache_hit": True, "source": "github_pr_memory"})
                markdown_path = self._write_outputs_if_requested(
                    branch_context,
                    knowledge,
                    result,
                    options,
                    extra_metadata={
                        "head_sha": current_head_sha,
                        "diff_hash": current_diff_hash,
                        "cache_hit": True,
                        "cache_source": "github_pr_memory",
                    },
                )
                if options.post_github:
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
                return WorkflowOutput(
                    branch_context,
                    knowledge,
                    result,
                    markdown_path,
                    trace_path,
                    should_fail=should_fail(result, options.fail_on),
                )

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
            markdown_path = self._write_outputs_if_requested(
                branch_context,
                knowledge,
                result,
                options,
                extra_metadata={"head_sha": current_head_sha, "diff_hash": current_diff_hash},
            )
            trace_path = self.trace.write()
            return WorkflowOutput(branch_context, knowledge, result, markdown_path, trace_path, should_fail=False)

        review_files = branch_context.changed_files
        if options.post_github and github_state:
            previous_head_sha = str(github_state.get("head_sha", ""))
            incremental_files = files_changed_since_previous_review(
                self.repo,
                previous_head_sha,
                current_head_sha,
                branch_context.changed_files,
            )
            if incremental_files and len(incremental_files) < len(branch_context.changed_files):
                review_files = incremental_files
                self._progress(
                    f"Incremental PR review: focusing on {len(review_files)} file(s) changed since previous AirReview run"
                )

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
        context_worker_agent = JsonAgent("Codebase Context Worker Agent", "codebase_context_agent.md", self.model_client)
        context_synthesis_agent = JsonAgent("Codebase Context Synthesis Agent", "codebase_context_agent.md", self.model_client)
        context_agent = JsonAgent("Codebase Context Agent", "codebase_context_agent.md", self.model_client)
        review_agent = JsonAgent("Branch Review Agent", "branch_review_agent.md", self.model_client)
        critic_agent = JsonAgent("Finding Critic Agent", "finding_critic_agent.md", self.model_client)
        fix_agent = JsonAgent("Fix Suggestion Agent", "fix_suggestion_agent.md", self.model_client)

        context_payload = {
            "branch": branch_context.branch,
            "base": branch_context.base,
            "changed_files": review_files,
            "all_changed_files": branch_context.changed_files,
            "incremental_review": {
                "enabled": review_files != branch_context.changed_files,
                "review_files": review_files,
                "total_pr_files": len(branch_context.changed_files),
            },
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
        practice_profile = self._ensure_practice_profile(
            provider,
            context_worker_agent,
            context_synthesis_agent,
            branch_context,
            knowledge,
            dependency_context,
        )
        if practice_profile:
            context_payload["practice_profile"] = practice_profile
            self._progress("Practice profile loaded for review context")
        plan_json = self._run_agent(
            planner_agent,
            {
                **context_payload,
                "diff_size": len(branch_context.diff),
                "final_file_count": len(review_files),
            },
        )
        chunks = normalize_chunks(plan_json, review_files)
        self._progress(
            f"Review plan: {plan_json.get('strategy', 'single_pass')} with {len(chunks)} chunk(s)"
        )
        budget = plan_json.get("budget", {})
        if isinstance(budget, dict) and budget.get("budget_exceeded"):
            self._progress("Review budget exceeded; remaining files will be skipped or capped by profile")
        context_payload["mode"] = "select_review_context"
        codebase_context = self._run_agent(context_agent, context_payload)
        focus_count = len(codebase_context.get("review_focus", [])) if isinstance(codebase_context.get("review_focus"), list) else 0
        self._progress(f"Codebase context ready: {focus_count} review focus item(s)", detail=True)
        review_summaries: list[str] = []
        findings = []
        if self.profile.stop_when_budget_exceeded and plan_json.get("budget", {}).get("budget_exceeded"):
            chunks = chunks[: self.profile.max_chunks]
        for index, chunk in enumerate(chunks, start=1):
            files = [path for path in chunk.get("files", []) if path in review_files]
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
                "changed_files": review_files,
                "all_changed_files": branch_context.changed_files,
                "incremental_review": {
                    "enabled": review_files != branch_context.changed_files,
                    "review_files": review_files,
                    "total_pr_files": len(branch_context.changed_files),
                },
                "previous_review": previous_review,
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
                    "changed_files": review_files,
                    "all_changed_files": branch_context.changed_files,
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

        markdown_path = self._write_outputs_if_requested(
            branch_context,
            knowledge,
            result,
            options,
            extra_metadata={"head_sha": current_head_sha, "diff_hash": current_diff_hash},
        )
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
        extra_metadata: dict | None = None,
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
                    **(extra_metadata or {}),
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

    def _run_agent_plain(self, agent: JsonAgent, payload: dict, display_name: str) -> dict:
        start = perf_counter()
        try:
            self._progress(f"{display_name} started using {model_for_agent(self.model_client, agent.name)}")
            result = agent.run(payload)
            duration_ms = (perf_counter() - start) * 1000
            self.trace.record_agent(display_name, duration_ms, True)
            self._progress(f"{display_name} completed in {duration_ms:.0f} ms")
            return result
        except Exception:
            duration_ms = (perf_counter() - start) * 1000
            self.trace.record_agent(display_name, duration_ms, False)
            self._progress(f"{display_name} failed after {duration_ms:.0f} ms")
            raise

    def _ensure_practice_profile(
        self,
        provider: LocalKnowledgeProvider,
        worker_agent: JsonAgent,
        synthesis_agent: JsonAgent,
        branch_context: BranchContext,
        knowledge: KnowledgeBundle,
        dependency_context: dict,
    ) -> dict:
        mode = os.getenv("AIRREVIEW_PRACTICE_DISCOVERY", "auto").strip().lower()
        if mode in {"0", "false", "off", "disabled"}:
            return provider.load_practice_profile()
        profile = provider.load_practice_profile()
        should_discover = mode in {"1", "true", "force", "refresh"} or provider.needs_practice_discovery()
        if profile and not should_discover:
            return profile
        try:
            return self._discover_practice_profile(
                provider,
                worker_agent,
                synthesis_agent,
                branch_context,
                knowledge,
                dependency_context,
            )
        except Exception as exc:
            self._progress(f"Practice discovery unavailable; continuing with existing knowledge: {exc}")
            return profile

    def _discover_practice_profile(
        self,
        provider: LocalKnowledgeProvider,
        worker_agent: JsonAgent,
        synthesis_agent: JsonAgent,
        branch_context: BranchContext,
        knowledge: KnowledgeBundle,
        dependency_context: dict,
    ) -> dict:
        self._progress("Discovering codebase practices with parallel context workers")
        chunks = sample_practice_chunks(
            self.repo,
            branch_context.changed_files,
            max_files=int(os.getenv("AIRREVIEW_PRACTICE_MAX_FILES", "40")),
            max_files_per_chunk=int(os.getenv("AIRREVIEW_PRACTICE_MAX_FILES_PER_CHUNK", "12")),
            max_chars_per_file=int(os.getenv("AIRREVIEW_PRACTICE_MAX_CHARS_PER_FILE", "3500")),
        )
        max_chunks = int(os.getenv("AIRREVIEW_PRACTICE_MAX_CHUNKS", "2"))
        if max_chunks > 0:
            chunks = chunks[:max_chunks]
        if not chunks:
            self._progress("Practice discovery skipped: no representative source files found")
            return provider.load_practice_profile()
        max_workers = max(1, min(int(os.getenv("AIRREVIEW_PRACTICE_MAX_PARALLEL_WORKERS", "2")), len(chunks)))
        self._progress(f"Practice discovery plan: {len(chunks)} chunk(s), {max_workers} parallel worker(s)")
        worker_results: list[dict] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending = {}
            for index, chunk in enumerate(chunks, start=1):
                display_name = f"Codebase Context Worker Agent - {chunk.name}"
                files = ", ".join(sample.path for sample in chunk.files[:6])
                self._progress(f"{display_name} analyzing {len(chunk.files)} file(s): {files}")
                payload = {
                    "mode": "discover_practices_chunk",
                    "branch": branch_context.branch,
                    "base": branch_context.base,
                    "chunk": discovery_chunk_payload(chunk),
                    "knowledge": {
                        "guidelines": knowledge.guidelines,
                        "known_smells": knowledge.known_smells,
                        "generated_scan": knowledge.generated_scan,
                        "metadata": knowledge.metadata,
                    },
                    "dependency_context": dependency_context,
                    "review_profile": self.profile.raw,
                    "worker_index": index,
                    "worker_count": len(chunks),
                }
                future = executor.submit(self._run_agent_plain, worker_agent, payload, display_name)
                pending[future] = chunk.name
            while pending:
                done, _ = wait(pending, timeout=12, return_when=FIRST_COMPLETED)
                if not done:
                    running = ", ".join(sorted(pending.values()))
                    self._progress(f"Practice discovery workers still running: {running}")
                    continue
                for future in done:
                    chunk_name = pending.pop(future)
                    result = future.result()
                    worker_results.append(result)
                    observed = result.get("observed_practices", [])
                    observed_count = len(observed) if isinstance(observed, list) else 0
                    self._progress(f"Practice worker {chunk_name} returned {observed_count} observed practice(s)")
        synthesis_payload = {
            "mode": "synthesize_practice_profile",
            "branch": branch_context.branch,
            "base": branch_context.base,
            "worker_results": worker_results,
            "chunks": [discovery_chunk_payload(chunk) for chunk in chunks],
            "knowledge": {
                "guidelines": knowledge.guidelines,
                "known_smells": knowledge.known_smells,
                "generated_scan": knowledge.generated_scan,
                "metadata": knowledge.metadata,
            },
            "dependency_context": dependency_context,
            "review_profile": self.profile.raw,
        }
        profile = self._run_agent(synthesis_agent, synthesis_payload)
        path = provider.save_practice_profile(profile, chunks, worker_results)
        self.tools.call("knowledge.practice_profile_save", lambda: str(path))
        self._progress(f"Practice profile saved: {path}", detail=True)
        return profile

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


def git_head_for_ref(repo: Path, ref: str) -> str:
    return run_git(repo, ["rev-parse", ref], check=False) or run_git(repo, ["rev-parse", "HEAD"], check=False)


def files_changed_since_previous_review(
    repo: Path,
    previous_head_sha: str,
    current_head_sha: str,
    allowed_files: list[str],
) -> list[str]:
    if not previous_head_sha or not current_head_sha or previous_head_sha == current_head_sha:
        return []
    output = run_git(repo, ["diff", "--name-only", f"{previous_head_sha}..{current_head_sha}", "--"], check=False)
    if not output:
        return []
    allowed = set(allowed_files)
    return [path for path in output.splitlines() if path in allowed]


def previous_review_from_github_state(state: dict) -> dict:
    findings = state.get("findings", {}) if isinstance(state, dict) else {}
    if not isinstance(findings, dict):
        return {}
    open_findings = [
        item
        for item in findings.values()
        if isinstance(item, dict) and item.get("status", "open") != "resolved"
    ]
    if not open_findings and not state.get("diff_hash"):
        return {}
    return {
        "metadata": {
            "source": "github_pr_memory",
            "diff_hash": state.get("diff_hash", ""),
            "head_sha": state.get("head_sha", ""),
        },
        "findings": open_findings,
    }


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
