# Azure AI Foundry Demo Runbook

This is the step-by-step runbook for the real demo after the code is pushed to GitHub.

## 1. Prepare Azure

Create or select:

- Azure AI Foundry project;
- model deployment, for example `gpt-5-mini`;
- application registration or managed identity for GitHub OIDC;
- RBAC allowing the identity to use the Foundry project.

Minimum identity guidance:

- local demo: your own Azure CLI login can call Foundry;
- GitHub PR review: GitHub OIDC identity can invoke the Foundry model or agents;
- GenAIOps sync/evals: GitHub OIDC identity can create prompt agent versions and run evaluations.

Keep API keys only as a temporary fallback.

## 2. Configure GitHub

Add repository variables:

```text
FOUNDRY_PROJECT_ENDPOINT
FOUNDRY_MODEL
AIRREVIEW_AGENT_MODE=foundry_agents
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
```

Add this variable after the first agent sync:

```text
FOUNDRY_AGENT_IDS
```

Prefer OIDC. Add `FOUNDRY_API_KEY` only as a temporary fallback secret.

GitHub workflow permissions:

```text
Settings -> Actions -> General -> Workflow permissions -> Read and write
```

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

Expected agents:

```text
airreview-planning-agent
airreview-codebase-context-agent
airreview-branch-review-agent
airreview-finding-critic-agent
airreview-fix-suggestion-agent
```

## 4. Run Evals In Foundry

Trigger:

```text
GitHub Actions > AirReview GenAIOps > Run workflow
```

First run:

- unit tests;
- local deterministic evals;
- Foundry readiness check;
- Foundry prompt agent sync.

Then copy the agent ids from Azure AI Foundry into the GitHub variable `FOUNDRY_AGENT_IDS`.

Second run:

- unit tests;
- local deterministic evals;
- agent sync;
- Foundry evals for quick, pessimistic, security, and coding-complex datasets.

## 5. Review A GitHub PR

Create a PR in a target repo with AirReview installed or in this repo. The PR workflow:

- fetches base and head;
- runs AirReview against the final branch state;
- posts a global PR comment;
- fails when medium/high/critical findings exist.

For the first smoke test, create a small PR in this repository:

```bash
git switch -c feature/demo-pr
printf "\n# temporary demo comment\n" >> README.md
git add README.md
git commit -m "Create demo PR change"
git push -u origin feature/demo-pr
```

Then open a PR from `feature/demo-pr` to `main`.

## 6. What To Show In The Portal

Show:

- Foundry project;
- deployed model;
- AirReview prompt agents;
- evaluation runs and dataset files;
- traces/monitoring where available from the model, agent, and evaluation runs;
- GitHub workflow logs proving GenAIOps automation.

## 7. What Is Still Architecture Target

The current reliable demo keeps Git orchestration in the CLI/GitHub runner. A fully hosted Foundry workflow with GitHub MCP/OpenAPI tools and Foundry IQ knowledge is the enterprise target and can be described from `foundry/workflow-design.md`.

For the presentation, say it like this:

```text
Today: GitHub runner owns Git diff extraction, AirReview orchestrates agents, Foundry hosts the model/agents/evals.
Target: Foundry hosted workflow owns orchestration, GitHub is exposed as a tool, Foundry IQ owns shared codebase knowledge.
```

## 8. Exact Local Commands

Install locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,foundry]"
```

Create the shell alias:

```bash
source scripts/install_alias.sh
```

Run without cloud:

```bash
airreview --base main --mock --output
```

Run with Foundry model or agents:

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL="<deployment-name>"
export AIRREVIEW_AGENT_MODE=foundry_agents
airreview --base main --output
```

Run local deterministic evals:

```bash
airreview eval --output airreview-eval-results.json
```

Dry-run agent sync:

```bash
airreview foundry sync-agents --dry-run
```

Real agent sync:

```bash
az login
airreview foundry sync-agents
```

## 9. What You Must Configure Once

In Azure:

```text
Azure AI Foundry project
Model deployment
Entra app registration or managed identity
Federated credentials for GitHub
RBAC access to the Foundry project
```

In GitHub:

```text
Repository variables from section 2
Workflow read/write permissions
Optional FOUNDRY_API_KEY secret only if OIDC is not ready
```

In local terminal:

```text
.venv installed
airreview alias sourced
az login done
Foundry env vars exported or stored in your shell profile
```
