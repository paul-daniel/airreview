# AirReview Demo Manual

This document is the end-to-end setup guide for demonstrating AirReview as an Azure AI Foundry GenAIOps use case.

The demo story:

> Code reviews slow teams down. AirReview shifts review left for developers, then runs an agentic review pipeline in parallel with build and tests. Azure AI Foundry becomes the control plane for models, agents, knowledge, traces, evaluations, and guardrails.

## 0. What You Will Show

You will show three layers:

1. **Local developer review**
   - A developer creates a branch.
   - The developer changes code.
   - The developer runs AirReview before pushing.
   - AirReview reviews the final branch state, including staged, unstaged, and untracked files.

2. **Pipeline review**
   - A PR triggers a pipeline.
   - Build/test can run in parallel.
   - AirReview runs as another quality signal.
   - It reviews the full branch, not one commit.
   - It can post a global PR comment.

3. **Azure AI Foundry GenAIOps**
   - Model deployment is managed in Foundry.
   - Agents are versioned from prompts.
   - Foundry IQ is the target knowledge layer.
   - Evals run from CI.
   - Traces and evaluation results become the operational feedback loop.
   - Guardrails protect quality, cost, JSON validity, confidence, and posting.

## 1. Prerequisites

Local machine:

- Git
- Python 3.10+
- Azure CLI if you want keyless Foundry auth
- Access to GitHub and/or Azure DevOps
- Access to an Azure AI Foundry project in the **new** portal

Recommended:

- VS Code
- Microsoft Foundry Toolkit for VS Code
- An Azure subscription where you can create or use an Azure AI Foundry project

## 2. Repositories

You need two repos for a clean demo.

### Repo 1: AirReview product repo

This is the repo containing the AirReview tool:

```bash
/Users/pauldaniel/Documents/AirReviewer
```

This repo is where you version:

- CLI code;
- prompts;
- eval datasets;
- pipelines;
- Foundry deployment notes/scripts;
- docs.

### Repo 2: Demo target repo

This is a separate repo that AirReview reviews.

Suggested location:

```bash
/Users/pauldaniel/Documents/AirReviewDemoRepo
```

This repo simulates a normal application repo with a feature branch and intentional issues.

## 3. Install AirReview Locally

From the AirReview product repo:

```bash
cd /Users/pauldaniel/Documents/AirReviewer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install ".[dev]"
python -m pytest
airreview doctor
```

Important: for using AirReview from any other repo, install it normally, not only editable:

```bash
pip install .
```

The command you can use from any repo is:

```bash
/Users/pauldaniel/Documents/AirReviewer/.venv/bin/airreview
```

Install the shell alias so you can simply type `airreview` from any repo:

```bash
cd /Users/pauldaniel/Documents/AirReviewer
./scripts/install_alias.sh
source ~/.zshrc
```

## 4. Configure Foundry Model Access

AirReview supports two auth styles.

### Option A: Azure CLI / managed identity

Use this for best-practice local demos when your user has access to the Foundry project.

```bash
az login
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL="<deployment-name>"
```

### Option B: API key

Use this only for demo convenience. Do not commit keys.

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL="<deployment-name>"
export FOUNDRY_API_KEY="<key>"
```

Supported aliases:

```bash
AZURE_AI_PROJECT_ENDPOINT
AZURE_AI_FOUNDRY_ENDPOINT
FOUNDRY_ENDPOINT
AZURE_AI_MODEL_DEPLOYMENT_NAME
AZURE_AI_MODEL
AZURE_AI_API_KEY
```

Optional model controls:

```bash
export AIRREVIEW_MODEL_API=chat
export AIRREVIEW_MAX_OUTPUT_TOKENS=3000
```

Use `--mock` only for deterministic no-cloud smoke tests.

## 5. Create the Demo Target Repo

Create the repo:

```bash
cd /Users/pauldaniel/Documents
mkdir AirReviewDemoRepo
cd AirReviewDemoRepo
git init -b main
```

Create a tiny app:

```bash
cat > app.py <<'PY'
def can_access(user):
    return user.get("role") == "admin"
PY

cat > test_app.py <<'PY'
from app import can_access

def test_admin_can_access():
    assert can_access({"role": "admin"})
PY

git add .
git commit -m "Initial app"
```

Create a feature branch with intentional issues:

```bash
git checkout -b feature/foundry-demo-review

cat > app.py <<'PY'
def can_access(user):
    # TODO: add product owner validation before production
    return user.get("role") in ["admin", "support"]
PY

cat > settings.py <<'PY'
API_KEY = "demo-secret-key"
PY
```

Notice: do not commit the changes yet. This first local smoke test uses an explicit local scope to prove AirReview can review staged, unstaged, and untracked files without pretending they are already part of the PR.

## 6. Local Smoke Test

Run mock mode first:

```bash
airreview --base main --scope working --mock --output
```

Expected:

- branch detected;
- base detected;
- review scope shown as `working`;
- local changes included because the scope requested them;
- local knowledge auto-created;
- five-agent flow visible:
  - Review Planning Agent;
  - Codebase Context Agent;
  - Branch Review Agent;
  - Finding Critic Agent;
  - Fix Suggestion Agent;
- Markdown report generated;
- report written by default to `.airreview/reviews/<branch>/review.md`;
- relative custom report names also stay under `.airreview/reviews/<branch>/`;
- structured comparison state written to `.airreview/reviews/<branch>/review.json`;
- trace JSON generated in `.airreview/runs/`.

Then run real Foundry mode:

```bash
airreview --base main --scope working --output
```

If env vars are correct, the model call goes through Foundry. If not, `airreview doctor` tells what is missing.

For a PR-like local review, commit the feature changes and run the default branch scope:

```bash
git add app.py settings.py
git commit -m "Add foundry demo review changes"
airreview --base main --mock --output
```

In this mode AirReview ignores unstaged and untracked files. This is the same conceptual scope used in CI.

### Re-running a Review

When you run another review on the same branch, AirReview does not blindly append old comments. Locally, it stores a structured result here:

```text
.airreview/reviews/<branch>/review.json
```

If the diff hash is unchanged, AirReview reuses that cached result and avoids another model call. If the diff changed, it reviews the new branch state and compares current findings with the previous review.

The report shows:

- new findings;
- findings still present;
- findings resolved since the previous review.

In GitHub PR mode, AirReview also stores a hidden memory block inside its summary comment. That lets a later workflow run skip already-posted findings, keep one comment per new issue, and avoid another agent run when the PR diff is exactly the same.

The current findings remain the source of truth. Resolved findings are summarized but not kept as active issues.

### Pipeline Pass/Fail

For the demo PR pipeline, use:

```bash
airreview --fetch --output --post-ado
```

This means:

- source and target branches are detected from PR variables;
- review scope defaults to `branch`;
- review findings are posted but do not fail the job by default;
- the job fails only if AirReview itself fails or the surrounding build/test pipeline fails;
- normal build/test failures still fail as usual.

Add `--fail-on medium` only when you intentionally want AirReview to become a blocking quality gate.

## 7. Local GenAIOps Evals

From the AirReview product repo:

```bash
cd /Users/pauldaniel/Documents/AirReviewer
source .venv/bin/activate
airreview eval --output airreview-eval-results.json
```

This runs deterministic evaluation cases:

- secret-like literal should be flagged;
- introduced TODO should be flagged.

This is a local version of the GenAIOps quality gate.

## 8. GitHub Setup

If AirReview is hosted on GitHub, use:

```text
.github/workflows/airreview-genaiops.yml
```

The workflow does:

- checkout;
- install AirReview;
- unit tests;
- local evals;
- optional Foundry agent evaluation.

### GitHub variables

In GitHub:

```text
Settings -> Secrets and variables -> Actions -> Variables
```

Add:

```text
FOUNDRY_PROJECT_ENDPOINT
FOUNDRY_MODEL
FOUNDRY_AGENT_IDS
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
```

Use variables for non-secrets. Use secrets for sensitive values.

### Best-practice auth

Prefer GitHub OIDC to Azure instead of storing credentials.

High-level steps:

1. Create an Entra ID app registration or managed identity for CI.
2. Configure federated credentials for your GitHub repo/environment.
3. Grant this identity access to the Azure AI Foundry project.
4. Use `azure/login@v2` with OIDC.

For quick demo only, you can use `FOUNDRY_API_KEY`, but that is less clean.

## 9. Azure DevOps Setup

If AirReview runs inside Azure DevOps, use:

```text
.azuredevops/azure-pipelines.yml
```

Important settings:

- checkout uses `fetchDepth: 0`;
- `System.AccessToken` is passed to the script;
- enable **Allow scripts to access OAuth token**;
- pipeline runs on PRs.

### Azure DevOps variables

In your pipeline library or pipeline variables:

```text
FOUNDRY_PROJECT_ENDPOINT
FOUNDRY_MODEL
FOUNDRY_API_KEY
FOUNDRY_AGENT_IDS
```

Mark API keys as secret.

### Permissions for PR posting

For posting comments, AirReview uses:

```text
SYSTEM_ACCESSTOKEN
SYSTEM_COLLECTIONURI
SYSTEM_TEAMPROJECT
BUILD_REPOSITORY_ID
SYSTEM_PULLREQUEST_PULLREQUESTID
```

Azure DevOps provides these in PR builds.

You must:

1. Enable `Allow scripts to access OAuth token`.
2. Ensure the build service identity has permission to contribute to pull request threads/comments.
3. Use `--post-ado` only in PR pipelines.

## 10. Azure AI Foundry Setup

In the new Azure AI Foundry portal:

1. Create or select a Foundry project.
2. Deploy a model from Foundry Models.
3. Copy the project endpoint.
4. Copy the deployment name.
5. Add your local user or CI identity with appropriate role access.
6. Optional: create a Foundry IQ knowledge base.
7. Optional: create Foundry Agent Service agents from the AirReview prompts.
8. Optional: configure evaluations and run them from GitHub/Azure DevOps.

### Roles / access

For local user:

- ability to access the Foundry project;
- ability to invoke model deployment;
- ability to read knowledge sources if using Foundry IQ.

For CI identity:

- least privilege needed to invoke model/evals;
- permission to create/update agents only if pipeline deploys agent versions;
- permission to write evaluation results/traces if configured.

Avoid giving broad subscription Owner rights for the demo.

## 11. Foundry Agent Mapping

AirReview local agents map to Foundry agents:

```text
Review Planning Agent       -> airreview-planning-agent
Codebase Context Agent      -> airreview-context-agent
Branch Review Agent         -> airreview-branch-review-agent
Finding Critic Agent        -> airreview-finding-critic-agent
Fix Suggestion Agent        -> airreview-fix-suggestion-agent
```

For now, AirReview can call a Foundry model directly. The target demo architecture is:

```text
CLI / Pipeline
  -> normalized ReviewRequest
  -> Foundry hosted workflow / agents
  -> Foundry IQ knowledge
  -> traces + evals + guardrails
  -> Markdown / PR comment
```

## 12. Foundry IQ Setup Story

For the demo, local knowledge is in:

```text
.airreview/codebase_guidelines.md
.airreview/known_smells.md
.airreview/generated/codebase_scan.md
```

Enterprise target:

1. Upload guidelines, ADRs, review rules, known smells, examples.
2. Index them in Foundry IQ / Azure AI Search.
3. Connect agents to the knowledge base.
4. Require citations for knowledge-grounded answers.

Talk track:

> The model knows programming. Foundry IQ gives it our project-specific memory.

## 13. Guardrails

AirReview has app-level guardrails:

- JSON schema validation;
- 3 retry attempts for invalid model output;
- severity threshold;
- max findings;
- confidence filtering;
- review budget / chunks;
- no PR post unless requested;
- dry-run support;
- local traces;
- Markdown report.

Foundry-level guardrails:

- model safety filters;
- agent/tool policies;
- managed identity access;
- knowledge source access control;
- evaluation gates;
- tracing/monitoring.

## 14. Suggested Demo Script

### Step 1: Show the pain

Explain:

> Code reviews are slow, and generic assistants lack project context.

### Step 2: Show local shift-left

```bash
cd /Users/pauldaniel/Documents/AirReviewDemoRepo
airreview --mock --output
```

Explain:

> The developer gets feedback before pushing.

### Step 3: Show Foundry model mode

```bash
export FOUNDRY_PROJECT_ENDPOINT="..."
export FOUNDRY_MODEL="..."
airreview --output
```

Explain:

> Same CLI, now backed by Foundry model deployment.

### Step 4: Show GenAIOps evals

```bash
cd /Users/pauldaniel/Documents/AirReviewer
airreview eval --output airreview-eval-results.json
```

Explain:

> Prompt and agent changes are evaluated before release.

### Step 5: Show pipelines

Show:

```text
.github/workflows/airreview-genaiops.yml
.azuredevops/azure-pipelines.yml
```

Explain:

> AirReview can run on GitHub or Azure DevOps because it is a CLI quality gate.

### Step 6: Show Foundry target

Show:

```text
foundry/agents.md
foundry/workflow-design.md
foundry/deploy_foundry.py
```

Explain:

> Foundry becomes the control plane for agents, knowledge, traces, evals, and guardrails.

## 15. Troubleshooting

### `ModuleNotFoundError: airreview`

Reinstall the package inside the AirReview venv:

```bash
cd /Users/pauldaniel/Documents/AirReviewer
source .venv/bin/activate
pip install . --force-reinstall --no-deps
```

### Foundry endpoint missing

Run:

```bash
airreview doctor
```

Set:

```bash
export FOUNDRY_PROJECT_ENDPOINT="..."
export FOUNDRY_MODEL="..."
```

### PR comment does not post

Check:

- PR build, not normal branch build;
- `SYSTEM_ACCESSTOKEN` exists;
- OAuth token access enabled;
- build service has PR comment permission;
- command includes `--post-ado`.

### Review too large / timeouts

Tune `.airreview/review_profile.yaml`:

```yaml
budget:
  max_files_per_chunk: 6
  max_diff_chars_per_chunk: 30000
  max_chunks: 3
  stop_when_budget_exceeded: false
```

## 16. What Is Real Today vs Target

Real today:

- local CLI;
- real Foundry model invocation;
- five logical agents;
- local knowledge;
- local evals;
- GitHub/Azure DevOps pipeline templates;
- PR posting via Azure DevOps REST;
- traces as JSON.

Target / next step:

- Foundry hosted agent versions;
- Foundry hosted workflow;
- Foundry IQ real knowledge retrieval;
- Foundry portal traces;
- Foundry evaluation dashboards;
- platform guardrails.

This distinction is important and honest for the demo.
