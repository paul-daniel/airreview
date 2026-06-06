# AirReview and Microsoft Foundry

The MVP orchestrates locally for demo reliability. The target enterprise version maps directly to Microsoft Foundry Agent Service and Microsoft Agent Framework hosted workflows.

## Target components

- Microsoft Foundry Agent Service for hosted prompt, workflow, or hosted agents.
- Microsoft Agent Framework for pro-code multi-agent orchestration.
- Foundry Models endpoint for model inference.
- Foundry IQ, powered by Azure AI Search agentic retrieval, for shared project knowledge.
- MCP or OpenAPI tools for Git and Azure DevOps capabilities.
- Application Insights and Foundry tracing for operations.

## Local to hosted mapping

| Local MVP | Foundry target |
| --- | --- |
| `LocalKnowledgeProvider` | Foundry IQ knowledge base |
| `MockModelClient` | Foundry Models deployment |
| `AirReviewWorkflow` | Hosted workflow or Agent Framework sequential workflow |
| Python tool functions | MCP/OpenAPI tools |
| `.airreview/runs` trace | Foundry tracing and App Insights |
| Azure DevOps REST poster | Azure DevOps MCP or OpenAPI tool |

## Why local first

The Saturday demo must run without cloud setup. Local mock mode proves the experience, shape of the data, review policy, traceability, and pipeline ergonomics. Foundry becomes the deployment and shared knowledge layer, not a demo blocker.

## Prompt agent manifests

Model desired state lives in:

```text
foundry/models.yaml
```

Sync missing AirReview model deployments with:

```bash
airreview foundry sync-models --dry-run
airreview foundry sync-models
```

Versioned manifests live in:

```text
foundry/agents/*.yaml
```

Sync them with:

```bash
airreview foundry sync-agents --dry-run
airreview foundry sync-agents
```

When `AIRREVIEW_AGENT_MODE=foundry_agents`, the CLI calls these Foundry prompt agents instead of calling the model deployment directly.

## Context7 MCP tool

AirReview declares the Context7 remote MCP tool in:

```text
foundry/tools.yaml
```

The planning, branch review, and fix suggestion agents reference this tool in their agent manifests. The sync command attaches it when creating the next Foundry agent version:

```bash
export AIRREVIEW_CONTEXT7_CONNECTION_ID="/subscriptions/.../projects/airreview/connections/context7"
airreview foundry sync-agents
```

Use Context7 for documentation-sensitive decisions only:

- API deprecations;
- package/framework version behavior;
- recommended APIs or migration guidance;
- code suggestions that must match the installed dependency version.

Do not use it for obvious diff-local findings such as hardcoded secrets, removed tests, missing cleanup, or fail-open authorization.

## Foundry IQ target

`foundry/knowledge.yaml` describes the intended enterprise knowledge layer. The PR diff remains runtime context, while stable repository knowledge can move to Foundry IQ:

- codebase guidelines;
- known smells;
- architecture summaries;
- dependency rules;
- review history.

The current CLI keeps `LocalKnowledgeProvider` as a fallback so PR review stays reliable even when Foundry IQ bootstrap is not configured.
