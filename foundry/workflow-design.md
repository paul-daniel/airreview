# AirReview Hosted Workflow Design

## Workflow

```text
Collect Git context
  -> Codebase Context Agent
  -> Branch Review Agent
  -> Fix Suggestion Agent
  -> Render report
  -> Optional Azure DevOps comment
```

## Agents

### Codebase Context Agent

Inputs:

- branch and base;
- changed files;
- Foundry IQ retrieved knowledge;
- review profile.

Output:

- relevant guidelines;
- known smells to ignore;
- architecture context;
- review focus.

### Branch Review Agent

Inputs:

- diff from merge-base to source branch;
- final file state;
- codebase context;
- review profile.

Output:

- JSON summary;
- localizable findings.

### Fix Suggestion Agent

Inputs:

- findings;
- review profile;
- codebase context.

Output:

- scoped fix recommendations;
- test recommendations.

## Tools

Local tools can become MCP or OpenAPI tools:

- `git_detect_branch`
- `git_detect_base`
- `git_merge_base`
- `git_diff`
- `git_changed_files`
- `git_final_file_state`
- `knowledge_load`
- `azure_devops_pr_context`
- `azure_devops_post_pr_comment`

## Knowledge

The MVP uses `.airreview/`. The enterprise target uses Foundry IQ knowledge bases backed by Azure AI Search agentic retrieval. Knowledge sources can include repository guidelines, architecture docs, ADRs, historical review rules, and accepted legacy-smell lists.

## VS Code Foundry Toolkit path

1. Install Microsoft Foundry Toolkit for Visual Studio Code.
2. Connect to a Microsoft Foundry project.
3. Deploy a model in Foundry Models.
4. Create a hosted agent workflow from the Writer-Reviewer style template.
5. Map AirReview's three agents to workflow participants.
6. Expose Git and Azure DevOps tools through MCP or OpenAPI.
7. Connect a Foundry IQ knowledge base.
8. Test locally with Agent Inspector.
9. Deploy to Foundry Agent Service.
