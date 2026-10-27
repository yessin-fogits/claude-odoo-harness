# claude-odoo-harness

Un harness [Claude Code](https://claude.com/claude-code) pour les projets Odoo, basé sur
[Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/fr/).

> 🇬🇧 [English version](README.md)

Le harness est le système de travail autour du modèle. Il rend Claude fiable sur les
projets Odoo longs : l'état vit dans le dépôt, une seule fonctionnalité est faite à la
fois, et seul le harness peut déclarer une fonctionnalité terminée, après une vraie
vérification.

## Installation

Un plugin par version d'Odoo, tous dans cette marketplace :

| Odoo | Plugin | Branche |
|---|---|---|
| 17.0 | `odoo-harness-17` | [`17.0`](../../tree/17.0) |
| 18.0 | `odoo-harness-18` | [`18.0`](../../tree/18.0) |
| 19.0 | `odoo-harness-19` | [`19.0`](../../tree/19.0) |
| 20.0 | `odoo-harness-20` | [`20.0`](../../tree/20.0) |

```
/plugin marketplace add yessin-fogits/claude-odoo-harness@main
/plugin install odoo-harness-20@odoo-harness
```

Ensuite, dans votre dépôt Odoo, lancez `/odoo-harness-20:init` (avec le numéro de votre
version). Il installe les fichiers du harness et suit les 4 étapes d'initialisation :

1. **Environnement exécutable** : Docker Compose (Odoo, PostgreSQL), une base de test
   jetable, vos modules installés (`harness/init.sh`).
2. **Cadre de test vérifiable** : un test qui passe à chaque niveau (unitaire, intégration, e2e).
3. **Document de contrat d'amorçage** : `BOOTSTRAP.md`, relu par un humain.
4. **Découpage des tâches** : de petites fonctionnalités dans `feature_list.json`, relues par un humain.

Le fichier `.claude/settings.json` du projet active ensuite le bon plugin pour toute
personne qui ouvre le dépôt. Prérequis : Docker avec le plugin compose, Python 3.10+, git.

## Ce que vous obtenez dans le dépôt Odoo

| Fichier | Rôle |
|---|---|
| `CLAUDE.md` | Règles de travail (WIP = 1, faire moins mais terminer), règles de la liste de fonctionnalités, définition de terminé, hiérarchie de validation |
| `PROGRESS.md` | État actuel (réécrit automatiquement), terminé / en cours, problèmes connus, prochaines étapes |
| `DECISIONS.md` | `- date : décision` |
| `feature_list.json` | `id`, `behavior`, `verification`, `state`, `evidence` ; modifié uniquement par `harness/feature.py` |
| `harness/feature.py` | `add`, `start` (refusé si une autre fonctionnalité est en cours), `block`, `verify` (le seul chemin vers `passing`), `check` |
| `harness/verify.sh` | Trois couches : analyse statique + pylint-odoo, tests Odoo unitaires/intégration, e2e Playwright avec un log serveur propre |
| `harness/checks/` | Vérifications du projet ; chaque nouveau type d'erreur trouvé en revue en devient une |
| `harness/errors.py` | Annotations au stylo rouge : chaque échec affiche POURQUOI et COMMENT CORRIGER |

## Ce que le plugin ajoute à Claude Code

- **Sessions automatiques** (hooks) : contexte chargé au début de session ; modifications
  de la liste de fonctionnalités, des preuves, du cœur Odoo/enterprise et des bases autres
  que la base de test refusées ; vérifications statiques après chaque modification ;
  contrôle de l'état propre à la fin de chaque tour.
- **Skills** : `init`, `update` (rafraîchir les fichiers du harness après une mise à jour du plugin), `add-harness-check`, et `odoo` : la référence Odoo de la version du
  plugin (ORM, vues, sécurité, OWL, contrôleurs, tests, migrations, notes de version),
  écrite à partir du vrai code `odoo/odoo` et vérifiée contre lui en CI.
- **Agents** : `odoo-reviewer` (grille d'évaluation + checklist Odoo, propose de nouvelles
  vérifications) et `odoo-explorer` (trouve les définitions parentes dans le code Odoo de
  votre version).

## Boucle autonome

`harness/loop.py run` avance seul dans `feature_list.json`, avec Claude Code sans
interface, sous forme de graphe producteur-vérificateur :

```
select -> maker (claude -p) -> verify (harness/feature.py verify) -> [review] -> commit -> select
             ^---- nouvel essai avec le stylo rouge (essais limités) ----|
             essais épuisés -> travail gardé dans un git stash, fonctionnalité bloquée avec la raison
```

- Le producteur ne juge jamais son propre travail : seul `feature.py verify` peut passer une
  fonctionnalité en `passing`, et `--review` ajoute l'agent `odoo-reviewer` comme second
  vérificateur indépendant.
- Seul le travail vérifié est commité. Le travail en échec est gardé dans un `git stash`
  nommé et la fonctionnalité est bloquée avec la raison et le nom du stash dans PROGRESS.md.
- Budgets : `--max-features` (1 par défaut, pour qu'un humain relise chaque fonctionnalité),
  `--attempts` (3 par défaut), `--max-turns` et `--max-budget-usd` par appel d'agent, `--timeout`.
- `--branch loop/<nom>` travaille sur une nouvelle branche. Journaux et sorties des agents :
  `.harness/loop/<run>/` ; dernier résumé : `harness/loop.py status`.
- Prérequis : un arbre de travail propre, une base saine (`harness/init.sh --check`), et la
  commande `claude` connectée avec le plugin installé.

## Collaborateurs

Dans les commandes ci-dessous, `<N>` est la version majeure d'Odoo (17, 18, 19 ou 20).


Le skill init active le plugin dans le `.claude/settings.json` du projet, mais Claude Code
ne télécharge pas un plugin à partir des seuls réglages du projet. Chaque personne
l'installe une fois :

```
claude plugin install odoo-harness-<N>@odoo-harness --scope project
```

## Mise à jour

**Le plugin** (skills, agents, hooks). Les projets installés par le skill init activent la
mise à jour automatique de la marketplace `odoo-harness` : Claude Code met le plugin à jour
en arrière-plan et vous demande de lancer `/reload-plugins`. Pour mettre à jour tout de suite :

```
claude plugin update odoo-harness-<N>@odoo-harness
```

ou `/plugin` → **Installed** → `odoo-harness-<N>` → **Update now**. Pour arrêter les mises
à jour automatiques : `/plugin` → **Marketplaces** → `odoo-harness` → **Disable auto-update**.

**Les fichiers du harness dans votre dépôt Odoo** (scripts du harness, vérifications,
catalogue stylo rouge, bloc CLAUDE.md). Après une mise à jour du plugin, lancez
`/odoo-harness-<N>:update`. Il remplace les fichiers du harness, conserve l'état du projet
(PROGRESS.md, DECISIONS.md, feature_list.json, BOOTSTRAP.md) et sa configuration
(docker-compose.yml, odoo.conf, harness/harness.env, e2e/conftest.py,
harness/errors_project.py), montre comment les modèles des fichiers conservés ont changé,
lance les vérifications et enregistre la mise à jour. Committez le résultat.

**Une autre version d'Odoo.** Passer un projet à la version suivante d'Odoo est une
migration, pas une mise à jour : installez le plugin de la nouvelle version, changez
`ODOO_VERSION` et `ODOO_IMAGE` dans `harness/harness.env` et le plugin activé dans
`.claude/settings.json`, puis suivez `references/migrations.md` du nouveau skill `odoo`.

## Désinstallation

- Le désactiver pour vous dans un projet : `claude plugin disable odoo-harness-<N>@odoo-harness --scope local`
- Désinstaller le plugin : `claude plugin uninstall odoo-harness-<N>@odoo-harness`
  (`--scope project` le retire du `.claude/settings.json` du projet pour tout le monde)
- Retirer la marketplace et tous les plugins installés depuis elle : `claude plugin marketplace remove odoo-harness`

Désinstaller le plugin ne modifie pas votre dépôt Odoo. Pour en retirer le harness :

1. Supprimez le bloc entre `<!-- odoo-harness:start -->` et `<!-- odoo-harness:end -->` dans `CLAUDE.md`.
2. Dans `.claude/settings.json`, retirez `odoo-harness-<N>@odoo-harness` de `enabledPlugins`,
   `odoo-harness` de `extraKnownMarketplaces`, et les règles de permission du harness dont vous ne voulez plus.
3. Arrêtez les conteneurs : `docker compose --env-file harness/harness.env down`
   (ajoutez `-v` seulement pour supprimer les volumes de la base de test).
4. Supprimez `harness/`, `.harness/`, et les fichiers ajoutés par le harness que vous ne gardez
   pas : `e2e/`, `docker-compose.yml`, `odoo.conf`, `.pylintrc`, `.pre-commit-config.yaml`.
5. Gardez ou archivez `PROGRESS.md`, `DECISIONS.md`, `feature_list.json` et `BOOTSTRAP.md` :
   c'est l'historique du projet.

## Comment c'est vérifié

Chaque branche de version exécute, à chaque push :
- la suite de tests (hooks, machine à états, couches de vérification, règles de version) ;
- `skill-check` : le skill `odoo` contre les faits extraits du code `odoo/odoo` correspondant ;
- `odoo-e2e` : un projet de démonstration contre un vrai Odoo, PostgreSQL et Playwright
  dans Docker ; une fonctionnalité passe à `passing`, puis un bug injecté doit faire
  échouer la vérification avec un message au stylo rouge ;
- `branches` : fichiers partagés identiques sur toutes les branches de version.

## Maintenance

Les changements communs se font sur `17.0` puis sont fusionnés vers l'avant :
`17.0 → 18.0 → 19.0 → 20.0`. Seuls `odoo_version.json`, `.claude-plugin/plugin.json` et
`skills/odoo/` diffèrent entre les branches (`git config merge.ours.driver true` une
fois, pour que les fusions les conservent). Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
