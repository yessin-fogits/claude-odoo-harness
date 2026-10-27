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
/plugin marketplace add yessin-fogits/claude-odoo-harness
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
- **Skills** : `init`, `add-harness-check`, et `odoo` : la référence Odoo de la version du
  plugin (ORM, vues, sécurité, OWL, contrôleurs, tests, migrations, notes de version),
  écrite à partir du vrai code `odoo/odoo` et vérifiée contre lui en CI.
- **Agents** : `odoo-reviewer` (grille d'évaluation + checklist Odoo, propose de nouvelles
  vérifications) et `odoo-explorer` (trouve les définitions parentes dans le code Odoo de
  votre version).

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
