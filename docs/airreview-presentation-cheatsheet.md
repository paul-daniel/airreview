# AirReview - fiche simple pour questions/reponses

Cette fiche est volontairement courte. Elle sert pendant la presentation.

## Pitch simple

AirReview aide a reviewer une PR avant ou pendant la pipeline.

Il ne regarde pas juste un fichier au hasard. Il reconstruit le contexte de la PR:

- branche source;
- branche cible;
- merge-base;
- diff final;
- fichiers modifies;
- contenu final des fichiers;
- regles du repo;
- dependances;
- review precedente si elle existe.

Ensuite il donne ce contexte a plusieurs agents Foundry.

## En une phrase

> AirReview transforme une PR en contexte structure, puis utilise des agents Foundry specialises pour produire une review utile, lisible et postable dans GitHub.

## Pourquoi on a fait ca

Le probleme: les reviews peuvent bloquer les livraisons quand les reviewers obligatoires sont peu nombreux ou deja occupes.

AirReview ne remplace pas le reviewer humain.

Il prepare le travail:

- detecte des erreurs tot;
- reduit les allers-retours;
- donne des commentaires contextualises;
- aide a livrer une PR plus propre.

## Ce qui se passe quand on lance `airreview`

1. `cli.py` lit la commande.
2. `git_tools.py` calcule la branche, la base, le diff et les fichiers finaux.
3. `knowledge.py` charge ou cree `.airreview`.
4. `dependencies.py` lit les packages du repo.
5. `workflow.py` appelle les agents.
6. `rendering.py` affiche la review.
7. `github.py` poste les commentaires si on est en PR.

## Les agents

### Review Planning Agent

Il ne review pas le code.

Il decide comment couper la PR en morceaux pour eviter un prompt trop gros.

### Codebase Context Agent

Il prepare le contexte du repo:

- conventions;
- architecture;
- dettes connues;
- points d'attention.

### Branch Review Agent

Il fait la vraie review.

Il cherche:

- bugs;
- securite;
- tests manquants;
- problemes de logique;
- mauvais usage de packages;
- performance;
- code trop complique.

### Finding Critic Agent

Il filtre le bruit.

Il rejette les commentaires trop vagues, les doublons et les faux positifs.

### Fix Suggestion Agent

Il propose comment corriger.

Il peut donner un extrait de code, mais AirReview n'applique pas automatiquement le patch.

## Comment un modele est bootstrap

Les modeles sont declares dans:

```text
foundry/models.yaml
```

Exemple:

```yaml
branch_review:
  deployment_name: airreview-review-codex
  model: gpt-5-codex
  model_version: auto
```

La pipeline lance:

```bash
airreview foundry sync-models
```

Ce que ca fait:

1. liste les deployments existants;
2. regarde ceux qui manquent;
3. cree seulement les modeles manquants.

## Comment un agent est cree

Les agents sont declares dans:

```text
foundry/agents/*.yaml
```

Exemple:

```yaml
name: airreview-branch-review-agent
model_key: branch_review
prompt_file: src/airreview/prompts/branch_review_agent.md
tools:
  - context7_docs
```

La pipeline lance:

```bash
airreview foundry sync-agents
```

Ce que ca fait:

1. lit le YAML de l'agent;
2. lit le prompt Markdown;
3. trouve le deployment modele;
4. ajoute les tools;
5. publie une nouvelle version de l'agent dans Foundry.

## Comment le CLI appelle un agent Foundry

Le code envoie a Foundry:

```json
{
  "model": "airreview-review-codex",
  "agent_reference": {
    "name": "airreview-branch-review-agent",
    "type": "agent_reference"
  },
  "input": "contexte de review..."
}
```

Donc:

- le modele vient du deployment;
- le prompt et les tools viennent de l'agent Foundry;
- le contexte vient du CLI AirReview.

## Pourquoi garder un CLI

Foundry ne sait pas tout seul:

- quelle branche comparer;
- quel merge-base utiliser;
- quels fichiers ont change;
- comment poster exactement les commentaires GitHub;
- comment eviter les doublons dans une PR.

Le CLI fait cette partie "engineering".

Foundry fait la partie "agents, modeles, tools, traces".

## Comment la pipeline GenAIOps marche

Dans le repo AirReview:

```text
.github/workflows/airreview-genaiops.yml
```

Elle fait:

1. tests unitaires;
2. evals locales deterministes;
3. verification des variables Foundry;
4. login Azure avec OIDC;
5. sync des modeles;
6. sync des agents;
7. preparation des references agents pour evals.

Pour l'instant, les evals Foundry live sont desactivees pour eviter de bloquer la demo sur une API preview instable.

## Comment la pipeline PR marche dans le repo applicatif

Elle lance:

```bash
airreview airreview-pr-head \
  --base origin/main \
  --output \
  --post-github
```

AirReview review la branche de PR contre `origin/main`, ecrit le rapport, puis poste les commentaires.

## Comment AirReview evite les doublons

AirReview met un identifiant stable sur chaque finding.

Puis il garde une petite memoire cachee dans le commentaire summary de la PR.

Au prochain run, il relit cette memoire et evite de reposter le meme commentaire.

## Pourquoi les commentaires ne sont pas toujours inline

GitHub accepte un commentaire inline seulement sur une ligne presente dans le diff.

Si la ligne n'est pas commentable, AirReview poste un commentaire normal dans la PR.

## Ou sont les fichiers importants

```text
src/airreview/cli.py          # commande airreview
src/airreview/workflow.py     # orchestration de la review
src/airreview/git_tools.py    # branche, base, diff
src/airreview/models.py       # appel mock / modele / agent Foundry
src/airreview/agents.py       # JSON strict et schemas
src/airreview/github.py       # commentaires PR et memoire
src/airreview/foundry_sync.py # sync modeles, agents, tools
foundry/models.yaml           # modeles voulus
foundry/agents/*.yaml         # agents voulus
foundry/tools.yaml            # tools voulus
src/airreview/prompts/*.md    # prompts versionnes
```

## Questions probables

### Pourquoi plusieurs agents ?

Parce que chaque agent a un role plus simple. C'est plus controlable, plus observable, et ca reduit le bruit.

### Pourquoi JSON strict ?

Parce qu'on veut transformer la reponse en table, panels, Markdown et commentaires GitHub. Un gros texte libre serait dur a exploiter.

### Pourquoi Context7 ?

Pour verifier la documentation d'une librairie ou d'une version quand le finding depend d'une API recente ou depreciee.

### Pourquoi File Search ?

Pour donner aux agents des standards de review partages, par exemple securite, tests, accessibilite ou performance.

### Pourquoi le repo est la source de verite ?

Parce que les prompts, modeles, agents et tools doivent etre versionnes. Si on change tout a la main dans Foundry, on perd le controle Git.

### Est-ce que ca modifie le code ?

Non. AirReview propose des corrections, mais ne modifie pas automatiquement le repository.

### Est-ce que ca peut bloquer la PR ?

Aujourd'hui, on prefere que la pipeline fail seulement si AirReview echoue techniquement. Les findings sont postes pour aider le dev, pas pour casser la demo.

### Le code est-il parfaitement structure ?

Non. `workflow.py`, `github.py` et `foundry_sync.py` sont trop gros. Pour le MVP, on a privilegie une logique visible et fiable. Pour une v2, on les decouperait.

