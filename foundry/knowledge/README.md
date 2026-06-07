# AirReview Knowledge

This folder contains versioned knowledge sources for AirReview grounding.

Use two source groups:

- `review_excellence/`: stable review standards used across repositories.
- `repository_knowledge/`: templates and generated repository-specific summaries.

Do not place secrets, private code dumps, or full proprietary source trees here. The PR diff remains runtime context. The search index should contain stable guidance that multiple agents can retrieve when needed.

## Demo Path: Azure AI Search Index

For the working demo, use an Azure AI Search index:

```text
airreview_knowledge_index
```

Attach it to Foundry agents through the native Azure AI Search / file search tool.

AirReview expects these values when syncing agents:

```bash
AIRREVIEW_SEARCH_CONNECTION_NAME=airreview-search
AIRREVIEW_SEARCH_INDEX_NAME=airreview_knowledge_index
```

If your project connection is known by ID rather than name, set:

```bash
AIRREVIEW_SEARCH_PROJECT_CONNECTION_ID=/subscriptions/.../projects/airreview/connections/airreview-search
```

The tool is declared in:

```text
foundry/tools.yaml
```

Agents using the index:

- `airreview-codebase-context-agent`
- `airreview-branch-review-agent`
- `airreview-fix-suggestion-agent`

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

Foundry IQ remains a valid enterprise target for shared knowledge bases. For this demo, Azure AI Search direct tooling is simpler and easier to keep versioned through AirReview agent manifests.

