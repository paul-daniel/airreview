# AirReview - comprendre le code sans se perdre

Ce guide est fait pour expliquer AirReview a l'oral. Il ne cherche pas a faire une doc parfaite. Il explique simplement ce qui se passe dans le code, dans quel ordre, et quels fichiers regarder si quelqu'un pose une question.

## L'image mentale

AirReview fait 4 choses:

1. Il regarde Git pour savoir quoi reviewer.
2. Il prepare du contexte utile pour les agents.
3. Il appelle les agents Foundry dans un ordre precis.
4. Il transforme le resultat en affichage terminal, rapport et commentaires GitHub.

Donc le plus important a comprendre:

```text
CLI -> Git context -> Knowledge -> Agents -> Resultat -> GitHub/Markdown/Trace
```

## Quand tu tapes `airreview --output`

Le point d'entree est dans [src/airreview/cli.py](/Users/pauldaniel/Documents/AirReviewer/src/airreview/cli.py).

La fonction importante est `cmd_review`.

Extrait simplifie:

```python
def cmd_review(repo, args):
    ensure_git_repo(repo)
    base = resolve_base(repo, args.base)
    profile = load_review_profile(repo)
    trace = RunTrace(repo=repo)
    model = build_model_client(mock=args.mock)
    workflow = AirReviewWorkflow(repo, profile, model, trace)
    output = workflow.run(RunOptions(...))
    render_review(output.result, output.result.suggestions)
```

Explication simple:

- `ensure_git_repo`: verifie qu'on est dans un repo Git.
- `resolve_base`: trouve la branche de reference, par exemple `origin/main`.
- `load_review_profile`: charge le niveau de review, les budgets, le max findings.
- `RunTrace`: prepare le fichier de trace.
- `build_model_client`: choisit si on utilise le mock, un modele Foundry, ou les agents Foundry.
- `AirReviewWorkflow.run`: fait la vraie review.
- `render_review`: affiche le resultat.

Phrase a dire:

> Le CLI ne review pas lui-meme. Il prepare les options, choisit le client modele, puis donne tout a `AirReviewWorkflow`.

## Comment AirReview sait quelle branche reviewer

Le code est dans [src/airreview/git_tools.py](/Users/pauldaniel/Documents/AirReviewer/src/airreview/git_tools.py).

La fonction centrale est `collect_branch_context`.

Elle construit un objet `BranchContext`:

```python
@dataclass(frozen=True)
class BranchContext:
    branch: str
    base: str
    merge_base: str
    changed_files: list[str]
    diff: str
    final_files: dict[str, str]
```

Ca veut dire:

- `branch`: la branche source;
- `base`: la branche de reference;
- `merge_base`: le point commun entre les deux branches;
- `changed_files`: les fichiers modifies;
- `diff`: le diff entre la base et la branche;
- `final_files`: le contenu final des fichiers modifies.

Pourquoi c'est important:

AirReview ne review pas seulement un commit. Il review la branche comme GitHub la verrait dans une PR.

En mode normal:

```python
mb = merge_base(repo, base_ref, source)
files = changed_files(repo, mb, source)
branch_diff = diff(repo, mb, source)
final_files = {path: final_file_state(repo, source, path) for path in files[:30]}
```

Traduction:

> On calcule le merge-base, on liste les fichiers changes depuis ce merge-base, on prend le diff, et on lit le contenu final des fichiers. C'est ce contexte qui part aux agents.

## Comment les changements non commites sont geres

Par defaut, AirReview utilise:

```text
--scope branch
```

Donc il review seulement la branche committee par rapport a la base.

Si on veut inclure le travail local, il faut demander explicitement:

```bash
airreview --scope working --output
airreview --scope staged --output
airreview --scope uncommitted --output
```

Pourquoi:

> En pipeline, on veut review l'etat de la PR. En local, on peut choisir de reviewer aussi le travail non committe, mais ce n'est pas le comportement par defaut.

## Comment le modele est choisi

Le code est dans [src/airreview/models.py](/Users/pauldaniel/Documents/AirReviewer/src/airreview/models.py).

La fonction importante:

```python
def build_model_client(mock: bool) -> ModelClient:
    if mock:
        return MockModelClient()
    if first_env("AIRREVIEW_AGENT_MODE").lower() == "foundry_agents":
        return FoundryAgentClient()
    return FoundryModelClient()
```

Il y a trois cas:

1. `--mock`: pas de cloud, reponse deterministe.
2. `AIRREVIEW_AGENT_MODE=foundry_agents`: on appelle les agents deployes dans Foundry.
3. Sinon: on appelle directement un modele Foundry.

Pour la demo Foundry, le mode important est:

```text
AIRREVIEW_AGENT_MODE=foundry_agents
```

Phrase a dire:

> Le workflow ne sait pas vraiment quel backend il utilise. Il appelle un `ModelClient`. Derriere, ce client peut etre un mock, un modele direct ou des agents Foundry.

## Comment AirReview appelle un agent Foundry

Toujours dans [src/airreview/models.py](/Users/pauldaniel/Documents/AirReviewer/src/airreview/models.py).

En mode agents Foundry, AirReview utilise `FoundryAgentClient`.

Il y a une table de correspondance:

```python
self.agent_names = {
    "Review Planning Agent": "airreview-planning-agent",
    "Codebase Context Agent": "airreview-codebase-context-agent",
    "Branch Review Agent": "airreview-branch-review-agent",
    "Finding Critic Agent": "airreview-finding-critic-agent",
    "Fix Suggestion Agent": "airreview-fix-suggestion-agent",
}
```

Et une autre pour les modeles/deployments:

```python
self.agent_models = {
    "Review Planning Agent": "airreview-planning-mini",
    "Codebase Context Agent": "airreview-context-mini",
    "Branch Review Agent": "airreview-review-codex",
    "Finding Critic Agent": "airreview-critic-mini",
    "Fix Suggestion Agent": "airreview-fix-codex",
}
```

Quand le workflow appelle par exemple le Branch Review Agent, AirReview envoie une requete a Foundry avec:

```python
{
    "model": "airreview-review-codex",
    "input": user_content,
    "agent_reference": {
        "name": "airreview-branch-review-agent",
        "type": "agent_reference"
    },
}
```

Point important:

> Le modele est celui du deployment associe a l'agent. Le nom de l'agent dit a Foundry quel prompt et quels tools utiliser.

## Comment un agent est cree dans Foundry

Les agents sont declares dans:

```text
foundry/agents/*.yaml
```

Exemple:

```yaml
name: airreview-branch-review-agent
description: Reviews final branch state against the reference branch.
model_key: branch_review
prompt_file: src/airreview/prompts/branch_review_agent.md
tools:
  - context7_docs
```

Ca veut dire:

- l'agent s'appelle `airreview-branch-review-agent`;
- il utilise le modele declare sous `branch_review`;
- ses instructions viennent du prompt Markdown;
- il a acces au tool `context7_docs`.

Le code qui lit ce fichier est dans `foundry_sync.py`:

```python
def load_agent_manifests(repo):
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        prompt = repo / raw["prompt_file"]
        model_key = raw["model_key"]
        model = models_by_key[model_key].deployment_name
        manifests.append(AgentManifest(...))
```

Ensuite la creation Foundry se fait ici:

```python
agent = project_client.agents.create_version(
    agent_name=manifest.name,
    definition=PromptAgentDefinition(
        model=manifest.model,
        instructions=instructions,
        tools=tools or None,
    ),
)
```

Traduction:

> La pipeline lit les YAML du repo, lit les prompts Markdown, construit une definition d'agent, puis publie une nouvelle version dans Foundry.

Ce point est important pour la demo:

> Le portail Foundry n'est pas la source de verite. Le repo est la source de verite. Foundry recoit les versions publiees.

## Comment les modeles sont bootstrapes

Les modeles attendus sont declares dans:

```text
foundry/models.yaml
```

Exemple:

```yaml
branch_review:
  deployment_name: airreview-review-codex
  model: gpt-5-codex
  model_version: auto
  sku: GlobalStandard
  capacity: 10
```

Ca veut dire:

> Pour l'agent de review principale, on veut un deployment Foundry/Azure OpenAI appele `airreview-review-codex`, base sur `gpt-5-codex`.

Le code qui bootstrap les modeles est dans `sync_models`.

Il fait:

1. lire `foundry/models.yaml`;
2. lister les deployments deja existants;
3. si le deployment existe, ne rien recreer;
4. si le deployment manque, resoudre la version du modele;
5. creer le deployment avec Azure CLI.

Extrait simplifie:

```python
existing = list_model_deployments(resource_group, resource_name)

for manifest in manifests:
    if manifest.deployment_name in existing:
        status = "exists"
    else:
        resolved_manifest = resolve_model_version(...)
        create_model_deployment(resource_group, resource_name, resolved_manifest)
```

La creation appelle Azure CLI:

```python
az cognitiveservices account deployment create \
  --deployment-name airreview-review-codex \
  --model-name gpt-5-codex \
  --model-version <version> \
  --sku-name GlobalStandard \
  --sku-capacity 10
```

Phrase a dire:

> On ne redeploie pas les modeles a chaque PR. On les declare dans le repo, et la pipeline GenAIOps cree seulement ceux qui manquent.

## Comment les tools sont attaches

Les tools sont declares dans:

```text
foundry/tools.yaml
```

Exemple Context7:

```yaml
context7_docs:
  type: mcp
  server_url: https://mcp.context7.com/mcp
  project_connection_id: ${AIRREVIEW_CONTEXT7_CONNECTION_ID}
  allowed_tools:
    - resolve-library-id
    - query-docs
```

Exemple File Search:

```yaml
airreview_file_search_knowledge:
  type: file_search
  vector_store_ids:
    - ${AIRREVIEW_FILE_SEARCH_VECTOR_STORE_ID}
  optional: true
```

Puis les agents choisissent quels tools ils utilisent.

Exemples:

- Branch Review Agent utilise Context7.
- Fix Suggestion Agent utilise Context7.
- Codebase Context Agent peut utiliser File Search.

Pourquoi:

> On ne donne pas tous les tools a tous les agents. On donne seulement ce qui est utile pour leur mission.

## Comment le workflow multi-agent marche

Le code principal est dans [src/airreview/workflow.py](/Users/pauldaniel/Documents/AirReviewer/src/airreview/workflow.py).

Il cree les agents comme ca:

```python
planner_agent = JsonAgent("Review Planning Agent", "review_planning_agent.md", self.model_client)
context_agent = JsonAgent("Codebase Context Agent", "codebase_context_agent.md", self.model_client)
review_agent = JsonAgent("Branch Review Agent", "branch_review_agent.md", self.model_client)
critic_agent = JsonAgent("Finding Critic Agent", "finding_critic_agent.md", self.model_client)
fix_agent = JsonAgent("Fix Suggestion Agent", "fix_suggestion_agent.md", self.model_client)
```

Ces `JsonAgent` sont des wrappers locaux.

Ils font deux choses:

- charger le prompt local;
- appeler `model_client.complete_json(...)`.

Le modele ou l'agent Foundry est derriere `model_client`.

Donc:

```text
JsonAgent local -> ModelClient -> Foundry Agent
```

Pourquoi garder un wrapper local si Foundry a deja des agents ?

> Parce que le CLI doit rester capable de tourner en mock, en modele direct, ou avec Foundry. Le wrapper local garde le workflow stable, peu importe le backend.

## L'ordre exact des agents

Dans `workflow.py`, l'ordre est:

### 1. Review Planning Agent

Il recoit:

- fichiers changes;
- taille du diff;
- budget du profil.

Il retourne:

- single pass ou chunks;
- liste des chunks;
- fichiers eventuellement skipped.

### 2. Codebase Context Agent

Il recoit:

- guidelines locales;
- known smells;
- scan du repo;
- dependances.

Il retourne:

- regles pertinentes;
- dettes a ignorer;
- contexte architecture;
- focus de review.

### 3. Branch Review Agent

Il tourne pour chaque chunk.

Il recoit:

- diff du chunk;
- fichiers finaux du chunk;
- contexte codebase;
- dependances;
- review precedente.

Il retourne des findings candidats.

### 4. Finding Critic Agent

Il recoit tous les findings candidats.

Il rejette:

- bruit;
- doublons;
- findings hors scope;
- low confidence;
- dette historique.

Il retourne les findings acceptes.

### 5. Fix Suggestion Agent

Il recoit seulement les findings acceptes.

Il retourne:

- suggestion;
- exemple de code;
- test recommande.

## Pourquoi les agents retournent du JSON

Le code est dans [src/airreview/agents.py](/Users/pauldaniel/Documents/AirReviewer/src/airreview/agents.py).

`JsonAgent.run` fait:

```python
response = self.model_client.complete_json(...)
parsed = parse_json_object(response)
validate_agent_output(self.name, parsed)
```

Si le JSON est invalide, AirReview retente avec une instruction:

```python
working_payload["_airreview_retry_instruction"] = (
    "Previous attempt failed JSON/schema validation..."
)
```

Pourquoi:

> On ne veut pas afficher un gros bloc texte. On veut des donnees structurees pour pouvoir faire une table, des panels, un Markdown et des commentaires GitHub.

## Comment AirReview evite les doublons en PR

Le code est dans [src/airreview/github.py](/Users/pauldaniel/Documents/AirReviewer/src/airreview/github.py).

Chaque finding a un fingerprint:

```python
fingerprint = finding_fingerprint(finding)
```

AirReview stocke ensuite l'etat dans un commentaire summary:

```text
<!-- airreview:state:v1
{ ... json cache ... }
-->
```

Au prochain run:

1. AirReview lit les commentaires de la PR.
2. Il retrouve le commentaire summary.
3. Il lit le JSON cache.
4. Il sait quels findings ont deja ete postes.
5. Il ne reposte pas les memes commentaires.

Phrase a dire:

> La memoire n'est pas sur le disque du runner, parce que le runner disparait. Elle est stockee dans la PR elle-meme, dans un commentaire cache.

## Comment AirReview poste les commentaires GitHub

Toujours dans `github.py`.

Pour chaque finding:

- si la ligne existe dans le diff GitHub, AirReview poste un commentaire inline;
- sinon il poste un commentaire normal dans la conversation PR.

Pourquoi le fallback existe:

> GitHub n'autorise pas les commentaires inline sur toutes les lignes. Il faut que la ligne soit commentable dans le diff de la PR.

## Comment la pipeline GenAIOps marche

Le workflow est dans:

```text
.github/workflows/airreview-genaiops.yml
```

Il y a 4 jobs.

### 1. `test-evaluate`

Ce job:

- checkout le repo;
- installe AirReview;
- lance les tests unitaires;
- lance les evals locales deterministes;
- upload le rapport d'eval.

Ce job sert a verifier que le code AirReview marche avant de toucher Foundry.

### 2. `foundry-readiness`

Ce job verifie si les variables Foundry existent.

Exemples:

- `FOUNDRY_PROJECT_ENDPOINT`;
- `FOUNDRY_RESOURCE_GROUP`;
- `FOUNDRY_RESOURCE_NAME`;
- `AIRREVIEW_CONTEXT7_CONNECTION_ID`;
- `AZURE_CLIENT_ID`;
- `AZURE_TENANT_ID`;
- `AZURE_SUBSCRIPTION_ID`.

Si une variable manque, la sync Foundry est skippee proprement.

Pourquoi:

> On veut que les tests puissent tourner meme si Foundry n'est pas configure.

### 3. `foundry-sync`

Ce job:

- se connecte a Azure avec OIDC;
- installe AirReview avec extras Foundry;
- lance `airreview foundry sync-models`;
- lance `airreview foundry sync-agents`;
- exporte les references agents.

Commandes importantes:

```bash
airreview foundry sync-models --output-json foundry-model-sync.json
airreview foundry sync-agents --output-json foundry-agent-sync.json
```

### 4. `foundry-agent-evals`

Pour le moment, ce job affiche que les evaluations Foundry sont desactivees pour stabilite demo.

Pourquoi:

> Les evals Foundry preview avaient tendance a rester bloquees ou a renvoyer des 404 de polling. On garde les agents synchronises, mais on ne bloque pas la demo sur ce point.

## Comment la pipeline PR review marche

Dans le repo applicatif, le workflow ressemble a:

```bash
airreview airreview-pr-head \
  --base origin/${{ github.base_ref }} \
  --output \
  --post-github
```

Explication:

- `airreview-pr-head` est la branche PR fetch par GitHub Actions;
- `--base origin/main` ou autre base donne la branche cible;
- `--output` ecrit le rapport Markdown/JSON;
- `--post-github` poste les commentaires dans la PR.

## Difference entre repo AirReview et repo applicatif

Repo AirReview:

- contient le code du produit;
- contient les prompts;
- contient les manifests Foundry;
- contient les pipelines GenAIOps;
- synchronise les agents/modeles/tools.

Repo applicatif:

- installe AirReview;
- lance AirReview sur ses PR;
- n'a pas besoin de savoir comment les agents sont deployes.

Phrase a dire:

> Le repo applicatif consomme AirReview. Le repo AirReview gouverne la solution.

## Les endroits ou le code est reutilise

### `ModelClient`

Le workflow appelle toujours:

```python
model_client.complete_json(...)
```

Peu importe le backend.

Ca permet:

- mock local;
- modele direct;
- agents Foundry.

### `JsonAgent`

Tous les agents passent par le meme wrapper:

```python
JsonAgent(name, prompt_file, model_client)
```

Ca permet:

- charger les prompts depuis `src/airreview/prompts`;
- valider le JSON;
- retry si JSON invalide.

### `BranchContext`

Tout le workflow utilise le meme objet Git:

```python
BranchContext(...)
```

Ca evite de recalculer partout la branche, la base, le diff et les fichiers finaux.

### `ReviewResult`

Le resultat final est le meme pour:

- affichage terminal;
- Markdown;
- JSON;
- GitHub comments.

## Les limites actuelles a assumer

Oui, le code peut etre mieux structure.

Les gros fichiers qui meriteraient un refactor:

- `workflow.py`;
- `github.py`;
- `foundry_sync.py`;
- `rendering.py`.

Mais pour la demo, ils ont un avantage:

> La logique est explicite et facile a suivre dans un seul fichier par domaine.

Ce qu'on ferait plus tard:

- separer `workflow.py` en contexte, agents, outputs, publication;
- separer `github.py` en API client, memoire PR, commentaires;
- separer `foundry_sync.py` en model sync, agent sync, tool builder.

## Version courte pour l'oral

> Quand on lance AirReview, le CLI detecte la branche et la base, calcule le diff final, lit les fichiers modifies, charge la knowledge locale et les dependances, puis appelle un workflow de cinq agents. Un agent planifie, un agent prepare le contexte repo, un agent review les chunks, un critic filtre le bruit, et un agent propose les fixes. Les prompts, modeles et tools sont versionnes dans le repo AirReview, puis synchronises vers Foundry par la pipeline GenAIOps. En PR, AirReview poste un commentaire par finding et garde une memoire cachee dans la PR pour eviter les doublons.

