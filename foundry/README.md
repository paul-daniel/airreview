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
