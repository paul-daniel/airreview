# GitHub Setup

This guide wires AirReview as a GitHub-native PR reviewer.

## 1. Push AirReview To GitHub

The demo repository is:

```text
https://github.com/paul-daniel/airreview.git
```

If you already pushed `codex-foundry-genaiops` to `main`, you are done with this step. Otherwise:

```bash
git remote add origin https://github.com/paul-daniel/airreview.git
git push -u origin codex-foundry-genaiops:main
```

## 2. GitHub Actions Permissions

In GitHub:

```text
Repository Settings
  -> Actions
  -> General
  -> Workflow permissions
```

Select:

```text
Read and write permissions
Allow GitHub Actions to create and approve pull requests: optional
```

AirReview needs permission to create PR review comments. It posts one compact summary plus one comment per finding. Findings attached to changed diff lines are posted inline; findings that cannot be attached to a diff line fall back to individual PR conversation comments.

## 3. Repository Variables

In GitHub repository settings, add these Actions variables:

```text
FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
FOUNDRY_RESOURCE_GROUP=<resource-group>
FOUNDRY_RESOURCE_NAME=<ai-services-or-foundry-resource-name>
FOUNDRY_MODEL=<runtime-fallback-deployment-name>
AIRREVIEW_AGENT_MODE=foundry_agents
AZURE_CLIENT_ID=<federated-app-client-id>
AZURE_TENANT_ID=<tenant-id>
AZURE_SUBSCRIPTION_ID=<subscription-id>
```

`FOUNDRY_MODEL` is still useful as a runtime fallback, but AirReview agent deployments are now declared in `foundry/models.yaml` and connected to agents through `foundry/agents/*.yaml`. `AIRREVIEW_AGENT_MODE=foundry_agents` is optional. If omitted, AirReview calls the Foundry model endpoint directly.

Do not set `FOUNDRY_AGENT_IDS`. The workflow now uses the `name:version` refs returned by `airreview foundry sync-agents`, for example `airreview-planning-agent:3`. The UUID shown under Entra agent identity is not accepted by `microsoft/ai-agent-evals`.

## 4. Repository Secrets

Preferred: use GitHub OIDC and `azure/login@v2`, not API keys.

Only add this secret if you cannot use OIDC yet:

```text
FOUNDRY_API_KEY=<foundry-api-key>
```

Never store API keys in GitHub variables.

## 5. Azure OIDC Setup

Use OIDC for the real demo path:

1. Create a Microsoft Entra app registration or user-assigned managed identity.
2. Add a federated credential for this GitHub repository.
3. Give the identity access to the Azure AI Foundry project.
4. Store the client id, tenant id, and subscription id as GitHub Actions variables.

For the federated credential:

```text
Issuer: https://token.actions.githubusercontent.com
Subject for main pushes: repo:paul-daniel/airreview:ref:refs/heads/main
Subject for PR demos: repo:paul-daniel/airreview:pull_request
Audience: api://AzureADTokenExchange
```

For a stricter production setup, create separate identities for main deployment and PR review.

## 6. PR Review Workflow

`.github/workflows/pr-review.yml` runs on every PR open, synchronize, and reopen:

```text
checkout full history
fetch base branch and PR head
install AirReview
optional Azure OIDC login
run airreview airreview-pr-head --base origin/<base> --output --post-github
```

By default, the workflow fails only if AirReview fails. Add `--fail-on medium` deliberately when you want review findings to become a blocking quality gate.

The workflow uses:

```text
GITHUB_TOKEN
GITHUB_REPOSITORY
GITHUB_EVENT_PATH
```

It posts:

```text
one AirReview summary comment
one inline GitHub review comment per finding when the finding line is commentable
one individual fallback PR conversation comment per finding when GitHub cannot attach the line
```

AirReview keeps a hidden memory block in the summary comment. Reruns skip findings that already have a comment, post only new findings, and mark disappeared fingerprints as resolved in memory.

## 5. Permissions

The workflow needs:

```yaml
permissions:
  contents: read
  pull-requests: write
  issues: write
  id-token: write
```

`id-token: write` is only used when OIDC variables are configured. If you use `FOUNDRY_API_KEY`, the Azure login step is skipped.

## 7. GenAIOps Workflow

`.github/workflows/airreview-genaiops.yml` is separate from PR commenting.

On PRs it runs:

```text
unit tests
local deterministic evals
```

On `main` and manual dispatch it also runs a Foundry readiness check.

If these variables exist:

```text
FOUNDRY_PROJECT_ENDPOINT
FOUNDRY_RESOURCE_GROUP
FOUNDRY_RESOURCE_NAME
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
```

it runs:

```text
Azure OIDC login
airreview foundry sync-models
airreview foundry sync-agents
```

The current demo keeps the Foundry evaluation job visible but disabled for stability. The eval datasets remain versioned under `evals/` and can be re-enabled later.
