# AirReview

AirReview is a local-first agentic code review CLI for reviewing the final state of a feature branch against its target branch. It is designed to run locally for demos and in Azure DevOps PR pipelines.

The MVP works without Azure by using `--mock`. The enterprise target maps the same architecture to Microsoft Foundry Agent Service, Microsoft Agent Framework hosted workflows, Foundry IQ, and Azure AI Search agentic retrieval.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install ".[dev]"

airreview --mock --output
```

## Use it on any Git repository

Install AirReview once, then run it from any repo:

```bash
cd /path/to/AirReviewer
python -m venv .venv
source .venv/bin/activate
pip install .

cd /path/to/any/git/repo
git checkout -b feature/demo
# make changes, commit them, then run a PR-like local review
airreview --base main --output
```

For a no-cloud smoke test:

```bash
airreview --base main --mock --output
```

If `airreview` is not on your shell yet, install the local alias:

```bash
cd /path/to/AirReviewer
./scripts/install_alias.sh
source ~/.zshrc
```

By default, AirReview behaves like a PR reviewer: it reviews only the committed final state of the source branch against the reference branch. Local uncommitted changes are reviewed only when you explicitly ask for them with `--scope working`, `--scope staged`, or `--scope uncommitted`.

Useful commands:

```bash
airreview --base main
airreview feature/my-branch --base develop --mock --output
airreview --base main --scope working --output review_output.md --mock
airreview --base main --output --fail-on medium
airreview init
airreview init --force
airreview knowledge
airreview doctor
airreview --fetch --output --post-ado
airreview --fetch --output --post-github
airreview foundry sync-agents --dry-run
```

`--output` without a value writes `.airreview/reviews/<branch>/review.md` and a sibling `.airreview/reviews/<branch>/review.json`. If you pass a relative name, for example `--output review_output.md`, AirReview writes `.airreview/reviews/<branch>/review_output.md`. Review artifacts stay under `.airreview/reviews/` and are ignored by Git by default.

On repeated reviews, AirReview reviews the current branch state again and compares the new findings with the previous `.airreview/reviews/<branch>/review.json`:

- `new`: finding was not present in the previous review;
- `still_present`: finding appears to still exist;
- `resolved`: finding existed previously but no longer appears in the current review.

The active report only shows current findings. Resolved findings are summarized in the comparison section.

In CI, use `--fail-on medium` to fail the pipeline when medium, high, or critical findings exist. Low findings pass by default:

```bash
airreview --fetch --output --post-ado --fail-on medium
```

## What AirReview reviews

AirReview reviews the branch as a whole:

1. Detect the source branch.
2. Resolve the reference branch from `--base`, Azure DevOps PR variables, `origin/HEAD`, or common branch names.
3. Resolve `git merge-base <base> <branch>`.
4. In default `--scope branch`, compute `git diff <merge-base>..<branch>` for committed branch changes only.
5. In explicit local scopes, review either the full working tree (`--scope working`), only staged changes (`--scope staged`), or all uncommitted changes (`--scope uncommitted`).
6. Read the final state of changed files from the branch, index, or working tree depending on the selected scope.
7. Run the multi-agent workflow with diff, final files, review profile, and knowledge.

If no files are changed for the selected scope, AirReview exits cleanly without invoking agents.

Ignored folders include `.git`, `node_modules`, `dist`, `build`, `target`, `.venv`, `coverage`, `.next`, `bin`, `obj`, and `vendor`.

## Local knowledge

`airreview init` creates:

```text
.airreview/
├─ codebase_guidelines.md
├─ known_smells.md
├─ review_profile.yaml
├─ index.json
└─ generated/
   └─ codebase_scan.md
```

If guidelines are missing or placeholder-only, AirReview scans a small source sample and generates draft guidelines. Edit them with team rules, accepted patterns, legacy smells to ignore, severity thresholds, and review tone.

## Multi-agent workflow

AirReview uses five logical agents:

- Review Planning Agent: chunks large reviews by budget.
- Codebase Context Agent: extracts relevant guidelines, conventions, known smells, and architecture context.
- Branch Review Agent: analyzes only branch-introduced or branch-aggravated issues.
- Finding Critic Agent: filters noisy, low-confidence, non-local findings.
- Fix Suggestion Agent: turns findings into scoped fixes and test recommendations.

The local workflow is intentionally simple and reliable. It mirrors the sequential multi-agent pattern supported by Microsoft Agent Framework, and the `foundry/` docs explain how to migrate this to hosted workflows.

Run local deterministic evals:

```bash
airreview eval --output airreview-eval-results.json
```

## Foundry and model configuration

Mock mode needs no network:

```bash
airreview --mock --output
```

Foundry-backed mode uses an OpenAI-compatible Foundry Models endpoint:

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL="gpt-5-mini" # deployment name
airreview --output
```

For the GenAIOps control plane, AirReview model deployments are declared in `foundry/models.yaml`. Sync missing deployments from the AirReview repository:

```bash
export FOUNDRY_RESOURCE_GROUP="<resource-group>"
export FOUNDRY_RESOURCE_NAME="<ai-services-or-foundry-resource-name>"
airreview foundry sync-models --dry-run
airreview foundry sync-models
```

Authentication order:

1. `FOUNDRY_API_KEY` or `AZURE_AI_API_KEY`.
2. Azure CLI / managed identity via `DefaultAzureCredential`.

Supported endpoint/model variable aliases:

- `FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_FOUNDRY_ENDPOINT`, `FOUNDRY_ENDPOINT`
- `FOUNDRY_MODEL`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `AZURE_AI_MODEL`

Optional controls:

- `AIRREVIEW_MODEL_API=chat` uses chat completions with JSON mode.
- `AIRREVIEW_MODEL_API=responses` uses the Responses API.
- `AIRREVIEW_MAX_OUTPUT_TOKENS=3000` caps each agent output.

Prefer the Microsoft Foundry project endpoint and deployment name. The package is not hardcoded to the classic Azure OpenAI endpoint.

## Azure DevOps pipeline

The included `.azuredevops/azure-pipelines.yml` runs:

```bash
airreview --fetch --output --post-ado
```

Pipeline requirements:

- Checkout with `fetchDepth: 0`.
- Enable "Allow scripts to access OAuth token".
- Pass `$(System.AccessToken)` as `SYSTEM_ACCESSTOKEN`.
- Run on PR builds so `SYSTEM_PULLREQUEST_*` variables are populated.

The MVP posts one global PR thread. Line-by-line comments are intentionally out of scope for demo reliability.

## GitHub PR review

`.github/workflows/pr-review.yml` reviews every pull request and posts a compact summary plus one comment per finding. AirReview uses inline GitHub review comments when the finding line is present in the PR diff, and falls back to individual PR conversation comments when GitHub cannot attach the line:

```bash
airreview airreview-pr-head --base origin/<base> --output --post-github --fail-on medium
```

See [GITHUB_SETUP.md](GITHUB_SETUP.md) for permissions, variables, and GitHub OIDC setup.

## Foundry agents

AirReview can call either the Foundry model endpoint directly or five prompt agents in Foundry Agent Service.

Sync desired-state model deployments, then prompt agents:

```bash
airreview foundry sync-models --dry-run
airreview foundry sync-models
airreview foundry sync-agents --dry-run
airreview foundry sync-agents
```

Run through Foundry agents:

```bash
export AIRREVIEW_AGENT_MODE=foundry_agents
airreview --base main --output
```

See [GENAIOPS.md](GENAIOPS.md) and [DEMO_FOUNDRY.md](DEMO_FOUNDRY.md).

## GenAIOps

AirReview keeps operational assets versionable:

- prompts in `src/airreview/prompts/`;
- Foundry model desired state in `foundry/models.yaml`;
- Foundry agent manifests in `foundry/agents/`;
- Foundry IQ target architecture in `foundry/knowledge.yaml`;
- evaluation datasets in `evals/*.json`;
- review policy in `.airreview/review_profile.yaml`;
- run traces in `.airreview/runs/<run-id>/trace.json`;
- reproducible Markdown output;
- Azure DevOps pipeline definition;
- environment variables only for Azure/Foundry location and identity;
- local knowledge that can later move to Foundry IQ or Azure AI Search.

This lets teams compare prompt versions, review profile changes, output quality, and roll back through Git.

## Microsoft architecture references

These official docs informed the target architecture:

- [Microsoft Foundry Agent Service overview](https://learn.microsoft.com/azure/foundry/agents/overview)
- [Foundry Agent Service tool catalog](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/tool-catalog?view=foundry)
- [Foundry tools overview](https://learn.microsoft.com/en-us/azure/ai-services/agents/how-to/tools/overview)
- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Create hosted agent workflows in VS Code](https://learn.microsoft.com/ga-ie/azure/foundry/agents/how-to/vs-code-agents-workflow-pro-code?view=foundry)
- [Foundry Models endpoints](https://learn.microsoft.com/en-in/azure/ai-foundry/foundry-models/how-to/inference)
- [Azure AI Search agentic retrieval overview](https://learn.microsoft.com/en-us/azure/search/search-agentic-retrieval-concept)
- [Connect agents to Foundry IQ knowledge bases](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/knowledge-retrieval?preserve-view=true&view=foundry)
- [Azure DevOps PR threads REST API](https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-request-threads/get?view=azure-devops-rest-7.1)

## Out of scope

No web UI, no automatic code changes, no PR-blocking policy, no real Foundry IQ requirement, no fine-tuning, and no fragile line-by-line Azure DevOps comments in this MVP.
