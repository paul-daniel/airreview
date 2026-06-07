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

- review excellence standards;
- codebase guidelines;
- known smells;
- architecture summaries;
- dependency rules;
- review history.

The current CLI keeps `LocalKnowledgeProvider` as a fallback so PR review stays reliable even when Foundry IQ bootstrap is not configured.

## Foundry IQ MCP tool

AirReview also declares an optional Foundry IQ MCP tool in:

```text
foundry/tools.yaml
```

When the following values are present, `airreview foundry sync-agents` attaches the tool to the agents that can benefit from shared knowledge:

```bash
export AIRREVIEW_FOUNDRY_IQ_MCP_ENDPOINT="https://<search-service>.search.windows.net/knowledgebases/airreview-knowledge/mcp?api-version=2026-05-01-preview"
export AIRREVIEW_FOUNDRY_IQ_CONNECTION_ID="/subscriptions/.../projects/airreview/connections/<foundry-iq-or-search-connection>"
airreview foundry sync-agents
```

If these values are missing, the tool is skipped. This is intentional: local reviews and GitHub PR reviews must keep working while Foundry IQ is being prepared.

The current recommended split is:

| Knowledge | Storage |
| --- | --- |
| PR diff, final changed files, working tree state | Runtime prompt context only |
| Repo-specific guidelines and known smells | Local `.airreview/` now, Foundry IQ later |
| Stable review standards | `foundry/knowledge/review_excellence/`, indexed in Foundry IQ |
| Review history and dedupe memory | Future PR memory layer, not Foundry IQ by default |

## Review excellence knowledge

Versioned source documents live in:

```text
foundry/knowledge/review_excellence/
```

They are intentionally short, original, and demo-friendly. Upload or sync them into your Foundry IQ knowledge base named, for example, `airreview-knowledge`:

- `code_review_principles.md`
- `security_review.md`
- `testing_review.md`
- `performance_review.md`
- `accessibility_review.md`

These documents give the agents a shared standard that is stronger than “copy whatever the repo already does”. The repo conventions still matter, but objectively bad conventions should be challenged when they conflict with security, correctness, accessibility, maintainability, or package documentation.

## Which agents use Foundry IQ?

- Codebase Context Agent: retrieves repository/review standards when local guidelines are missing, generated, or incomplete.
- Branch Review Agent: retrieves standards for security, permissions, accessibility, testing, performance, architecture, and governance-sensitive findings.
- Fix Suggestion Agent: retrieves correction standards when a fix needs security, testing, accessibility, performance, or architecture guidance.

The Planning Agent keeps Context7 only because it should decide scope cheaply. The Finding Critic Agent has no external tool by default so it stays focused on dedupe and evidence quality.
