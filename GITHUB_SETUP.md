# GitHub Setup

This guide wires AirReview as a GitHub-native PR reviewer.

## 1. Push AirReview To GitHub

Create an empty GitHub repository, then from this repo:

```bash
git remote add origin git@github.com:<owner>/airreview.git
git push -u origin main
```

## 2. Repository Variables

In GitHub repository settings, add these Actions variables:

```text
FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL=<deployment-name>
AIRREVIEW_AGENT_MODE=foundry_agents
FOUNDRY_AGENT_IDS=<comma-separated-agent-ids-or-names-for-evals>
AZURE_CLIENT_ID=<federated-app-client-id>
AZURE_TENANT_ID=<tenant-id>
AZURE_SUBSCRIPTION_ID=<subscription-id>
```

`AIRREVIEW_AGENT_MODE=foundry_agents` is optional. If omitted, AirReview calls the Foundry model endpoint directly.

## 3. Repository Secrets

Preferred: use GitHub OIDC and `azure/login@v2`, not API keys.

Only add this secret if you cannot use OIDC yet:

```text
FOUNDRY_API_KEY=<foundry-api-key>
```

Never store API keys in GitHub variables.

## 4. PR Review Workflow

`.github/workflows/pr-review.yml` runs on every PR open, synchronize, and reopen:

```text
checkout full history
fetch base branch and PR head
install AirReview
run airreview airreview-pr-head --base origin/<base> --output --post-github --fail-on medium
```

The workflow uses:

```text
GITHUB_TOKEN
GITHUB_REPOSITORY
GITHUB_EVENT_PATH
```

It posts one global PR comment for demo reliability. Inline GitHub comments are intentionally out of scope for this MVP.

## 5. Permissions

The workflow needs:

```yaml
permissions:
  contents: read
  pull-requests: read
  issues: write
```

GitHub PR comments are issue comments behind the scenes, hence `issues: write`.
