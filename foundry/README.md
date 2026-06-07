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

## Managed File Search knowledge tool

For the working demo, AirReview uses a managed Foundry File Search vector store attached to the Codebase Context Agent. This matches the index created from the Foundry portal:

```text
Name: airreview_knowledge_index
Type: ManagedAzureSearch
Vector store ID: vs_v06qsV2mw5yTv2OC6sLddzIF
```

Set the vector store ID before syncing agents:

```text
AIRREVIEW_FILE_SEARCH_VECTOR_STORE_ID=vs_v06qsV2mw5yTv2OC6sLddzIF
```

AirReview declares this tool in:

```text
foundry/tools.yaml
```

The tool is optional. If this value is missing, `airreview foundry sync-agents` skips the File Search tool and keeps the agents usable.

Only the Codebase Context Agent uses File Search by default. Some Foundry agent/model combinations do not expose File Search. The downstream Branch Review and Fix Suggestion agents receive the retrieved standards through the orchestrated context instead of calling File Search directly.

The current recommended split is:

| Knowledge | Storage |
| --- | --- |
| PR diff, final changed files, working tree state | Runtime prompt context only |
| Repo-specific guidelines and known smells | Local `.airreview/` now, search-backed later |
| Stable review standards | Managed File Search vector store `vs_v06qsV2mw5yTv2OC6sLddzIF` |
| Review history and dedupe memory | Future PR memory layer, not the search index by default |

## Foundry IQ target

`foundry/knowledge.yaml` describes the longer-term enterprise knowledge layer. The PR diff remains runtime context, while stable repository knowledge can move to Foundry IQ or Azure AI Search:

- review excellence standards;
- codebase guidelines;
- known smells;
- architecture summaries;
- dependency rules;
- review history.

The current CLI keeps `LocalKnowledgeProvider` as a fallback so PR review stays reliable even when Foundry IQ bootstrap is not configured.

## Review excellence knowledge

Versioned source documents live in:

```text
foundry/knowledge/review_excellence/
```

They are intentionally short, original, and demo-friendly. Upload or sync them into `airreview_knowledge_index`:

- `code_review_principles.md`
- `security_review.md`
- `testing_review.md`
- `performance_review.md`
- `accessibility_review.md`

These documents give the agents a shared standard that is stronger than “copy whatever the repo already does”. The repo conventions still matter, but objectively bad conventions should be challenged when they conflict with security, correctness, accessibility, maintainability, or package documentation.

## Which agents use search grounding?

- Codebase Context Agent: retrieves repository/review standards when local guidelines are missing, generated, or incomplete.
- Branch Review Agent: receives the retrieved standards through `codebase_context`.
- Fix Suggestion Agent: receives the retrieved standards through `codebase_context`.

The Planning Agent keeps Context7 only because it should decide scope cheaply. The Finding Critic Agent has no external tool by default so it stays focused on dedupe and evidence quality.
