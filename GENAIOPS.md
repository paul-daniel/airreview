# AirReview GenAIOps

AirReview is designed so prompt, agent, evaluation, and pipeline changes are versioned together.

## Versioned Assets

```text
src/airreview/prompts/*.md        Prompt instructions
foundry/agents/*.yaml            Foundry prompt agent manifests
evals/*.json                     Foundry evaluation datasets
.github/workflows/*.yml          CI, PR review, Foundry eval workflows
.airreview/review_profile.yaml   Review policy template
```

## Push To Main Flow

```text
developer changes AirReview
git push
GitHub Actions runs unit tests and local evals
GitHub logs into Azure with OIDC
airreview foundry sync-agents
microsoft/ai-agent-evals runs quick, pessimistic, security, and coding-complex suites using the synced agent `name:version` refs
results are visible in Azure AI Foundry
```

## Pull Request Flow

```text
developer opens or updates a PR
AirReview PR Review workflow fetches base and head
airreview reviews the final branch state
one GitHub PR comment is posted
the check fails on medium/high/critical findings
AirReview GenAIOps workflow runs tests and deterministic evals without posting a second comment
```

## Foundry Agent Sync

Dry run:

```bash
airreview foundry sync-agents --dry-run
```

Real sync:

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL="<deployment-name>"
az login
pip install ".[foundry]"
airreview foundry sync-agents
```

The command creates a new version of each prompt agent:

```text
airreview-planning-agent
airreview-codebase-context-agent
airreview-branch-review-agent
airreview-finding-critic-agent
airreview-fix-suggestion-agent
```

The GitHub workflow does not need manual `FOUNDRY_AGENT_IDS`. The sync step exports refs such as `airreview-planning-agent:3`, which is the format expected by `microsoft/ai-agent-evals`. Do not use the Entra identity UUIDs shown in the portal.

## Foundry Agent Runtime

To make AirReview call Foundry agents instead of the model directly:

```bash
export AIRREVIEW_AGENT_MODE=foundry_agents
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL="<deployment-name>"
airreview --base main --output
```

## Evaluation Suites

```text
evals/airreview_quality_smoke.json
evals/airreview_pessimistic_smoke.json
evals/airreview_security_smoke.json
evals/airreview_coding_smoke.json
```

The GitHub workflow keeps the Foundry evaluation job visible, but temporarily disables execution of `microsoft/ai-agent-evals@v3-beta` for demo stability. The larger datasets remain in `evals/airreview_quality_quick.json`, `evals/airreview_quality_pessimistic.json`, `evals/airreview_security_guardrails.json`, and `evals/airreview_coding_complex.json` for manual or future scheduled evaluations.

Quick quality checks normal review behavior. Pessimistic checks false positives, prompt injection, huge diffs, and uncertainty. Security guardrails check redaction, PII, secrets, and unsafe suggestions. Coding complex evaluates code-level review ability with realistic snippets, cross-file reasoning, package context, missing-file findings, and contextual fix suggestions.

Foundry evals are currently an observability target in this demo workflow rather than a blocking check. The PR review quality gate remains the blocking check.

## Current Reality

Reliable today:

- GitHub PR comment workflow.
- Direct Foundry model calls.
- Foundry prompt agent sync.
- Foundry agent evaluations through `microsoft/ai-agent-evals@v3-beta`.
- Local traces in `.airreview/runs`.

Preview / architecture target:

- Full hosted multi-agent workflow entirely visible as a single Foundry workflow.
- GitHub and Git tools exposed to hosted agents through MCP/OpenAPI.
- Foundry IQ-backed repository knowledge replacing local `.airreview` knowledge.
