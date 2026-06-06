# AirReview GenAIOps

AirReview is designed so prompt, agent, evaluation, and pipeline changes are versioned together.

## Versioned Assets

```text
src/airreview/prompts/*.md        Prompt instructions
foundry/agents/*.yaml            Foundry prompt agent manifests
evals/*.jsonl                    Evaluation datasets
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
microsoft/ai-agent-evals runs quick, pessimistic, and security suites
results are visible in Azure AI Foundry
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
evals/airreview_quality.quick.jsonl
evals/airreview_quality.pessimistic.jsonl
evals/airreview_security.guardrails.jsonl
```

Quick quality checks normal review behavior. Pessimistic checks false positives, prompt injection, huge diffs, and uncertainty. Security guardrails check redaction, PII, secrets, and unsafe suggestions.

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
