# AirReview Foundry IQ Knowledge

This folder contains versioned knowledge that can be synced into Foundry IQ / Azure AI Search.

Use two source groups:

- `review_excellence/`: stable review standards used across repositories.
- `repository_knowledge/`: templates and generated repository-specific summaries.

Do not place secrets, private code dumps, or full proprietary source trees here. The PR diff remains runtime context. Foundry IQ should contain stable guidance that multiple agents can retrieve when needed.

## Target Foundry IQ Sources

Suggested knowledge source names:

- `airreview-review-excellence`
- `airreview-repository-knowledge`

Suggested knowledge base name:

- `airreview-knowledge`

The resulting Azure AI Search MCP endpoint should look like:

```text
https://<search-service>.search.windows.net/knowledgebases/airreview-knowledge/mcp?api-version=2026-05-01-preview
```

Set these variables before `airreview foundry sync-agents` if you want agents to include the Foundry IQ MCP tool:

```bash
AIRREVIEW_FOUNDRY_IQ_MCP_ENDPOINT=https://<search-service>.search.windows.net/knowledgebases/airreview-knowledge/mcp?api-version=2026-05-01-preview
AIRREVIEW_FOUNDRY_IQ_CONNECTION_ID=<project-connection-name-or-id>
```

## Portal setup checklist

1. Create or reuse an Azure AI Search service.
2. Create a knowledge base, for example `airreview-knowledge`.
3. Add knowledge sources for `review_excellence/` and, later, repository-specific guidelines.
4. In the Microsoft Foundry project, create a RemoteTool project connection that targets:

```text
https://<search-service>.search.windows.net/knowledgebases/airreview-knowledge/mcp?api-version=2026-05-01-preview
```

5. Grant the Foundry project managed identity read access to Azure AI Search, typically `Search Index Data Reader`.
6. Use `ProjectManagedIdentity` authentication for production-style demos when possible. Key-based auth is acceptable only for a quick controlled demo.

Microsoft documents this integration as a Foundry Agent Service MCP connection to an Azure AI Search knowledge base. The exposed MCP tool is currently:

```text
knowledge_base_retrieve
```
