# Azure AI Foundry Demo Runbook

## 1. Prepare Azure

Create or select:

- Azure AI Foundry project;
- model deployment, for example `gpt-5-mini`;
- application registration or managed identity for GitHub OIDC;
- RBAC allowing the identity to use the Foundry project.

## 2. Configure GitHub

Add repository variables:

```text
FOUNDRY_PROJECT_ENDPOINT
FOUNDRY_MODEL
FOUNDRY_AGENT_IDS
AIRREVIEW_AGENT_MODE=foundry_agents
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
```

Prefer OIDC. Add `FOUNDRY_API_KEY` only as a temporary fallback secret.

## 3. Sync Agents

Local dry run:

```bash
airreview foundry sync-agents --dry-run
```

Real sync:

```bash
pip install ".[foundry]"
az login
airreview foundry sync-agents
```

In the Foundry portal, confirm the five AirReview agents exist.

## 4. Run Evals In Foundry

Trigger:

```text
GitHub Actions > AirReview GenAIOps > Run workflow
```

The workflow runs:

- unit tests;
- local deterministic evals;
- agent sync;
- Foundry evals for quick, pessimistic, and security datasets.

## 5. Review A GitHub PR

Create a PR in a target repo with AirReview installed or in this repo. The PR workflow:

- fetches base and head;
- runs AirReview against the final branch state;
- posts a global PR comment;
- fails when medium/high/critical findings exist.

## 6. What To Show In The Portal

Show:

- Foundry project;
- deployed model;
- AirReview prompt agents;
- evaluation runs and dataset files;
- traces/monitoring where available;
- GitHub workflow logs proving GenAIOps automation.

## 7. What Is Still Architecture Target

The current reliable demo keeps Git orchestration in the CLI/GitHub runner. A fully hosted Foundry workflow with GitHub MCP/OpenAPI tools and Foundry IQ knowledge is the enterprise target and can be described from `foundry/workflow-design.md`.
