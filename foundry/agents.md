# AirReview Agents for Azure AI Foundry

This folder documents how the local AirReview agents map to Azure AI Foundry Agent Service.

## Agent Versions

Target agents:

- `airreview-planning-agent`
- `airreview-context-agent`
- `airreview-branch-review-agent`
- `airreview-finding-critic-agent`
- `airreview-fix-suggestion-agent`

Each version should record:

- prompt file path;
- git commit SHA;
- model deployment name;
- knowledge provider;
- evaluation score;
- release notes.

## Tool Mapping

Local tools can be exposed as MCP/OpenAPI tools later:

- `git_detect_branch`
- `git_detect_base`
- `git_merge_base`
- `git_diff`
- `git_changed_files`
- `git_final_file_state`
- `knowledge_load`
- `azure_devops_pr_context`
- `azure_devops_post_pr_comment`

For the demo, the CLI collects Git context locally and calls Foundry model/agents. Enterprise target: hosted workflow receives a normalized `ReviewRequest`.

## Knowledge Mapping

Local MVP:

- `.airreview/codebase_guidelines.md`
- `.airreview/known_smells.md`
- `.airreview/generated/codebase_scan.md`

Foundry target:

- Foundry IQ knowledge base backed by Azure AI Search.
- Agents retrieve project rules, known smells, ADRs, security rules, examples of good reviews, and accepted patterns.

## Observability Mapping

Local MVP:

- `.airreview/runs/<run-id>/trace.json`

Foundry target:

- Foundry traces / OpenTelemetry spans;
- model/tool latency;
- token/cost metadata;
- eval result per agent/workflow;
- PR metadata correlation.
