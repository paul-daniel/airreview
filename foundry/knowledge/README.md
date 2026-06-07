# AirReview Knowledge

This folder contains versioned knowledge sources for AirReview grounding.

Use two source groups:

- `review_excellence/`: stable review standards used across repositories.
- `repository_knowledge/`: templates and generated repository-specific summaries.

Do not place secrets, private code dumps, or full proprietary source trees here. The PR diff remains runtime context. The search index should contain stable guidance that multiple agents can retrieve when needed.

## Demo Path: Managed File Search

For the working demo, use the managed Foundry File Search index:

```text
Name: airreview_knowledge_index
Type: ManagedAzureSearch
Vector store ID: vs_v06qsV2mw5yTv2OC6sLddzIF
```

Attach it to the Codebase Context Agent through the native File Search tool.

AirReview expects these values when syncing agents:

```bash
AIRREVIEW_FILE_SEARCH_VECTOR_STORE_ID=vs_v06qsV2mw5yTv2OC6sLddzIF
```

The tool is declared in:

```text
foundry/tools.yaml
```

Agents using the vector store:

- `airreview-codebase-context-agent`

The Branch Review and Fix Suggestion agents consume the retrieved standards via the orchestrated `codebase_context`. They do not get File Search directly because some Foundry agent/model combinations do not support the tool.

## Recommended Upload Documents

Upload compact AirReview-owned documents first:

- `review_excellence/code_review_principles.md`
- `review_excellence/security_review.md`
- `review_excellence/testing_review.md`
- `review_excellence/performance_review.md`
- `review_excellence/accessibility_review.md`

For a richer demo, also upload the local document pack generated in:

```text
foundry/knowledge/document_upload/
```

That folder is ignored by Git because it contains local upload artifacts and public external PDFs.

## Future Path: Foundry IQ

Foundry IQ remains a valid enterprise target for shared knowledge bases. For this demo, managed File Search is simpler and easier to keep versioned through AirReview agent manifests.
