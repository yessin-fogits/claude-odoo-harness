# claude-odoo-harness

Un harness [Claude Code](https://claude.com/claude-code) pour les projets Odoo, basé sur
[Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/fr/).

Le harness est le système de travail autour du modèle. Il rend l'agent fiable sur les projets Odoo longs :
- **L'état vit dans le dépôt** : `PROGRESS.md`, `DECISIONS.md` et `feature_list.json`.
- **WIP = 1** : une fonctionnalité à la fois. La suivante ne commence qu'après la vérification e2e.
- **Le harness contrôle les états** : l'agent ne peut pas passer lui-même son travail en `passing`.
- **Trois couches de vérification** : analyse statique (pylint-odoo), tests Odoo, puis e2e Playwright.
- **Annotations au stylo rouge** : chaque échec dit ce qui a échoué, POURQUOI et COMMENT corriger.
- **Sessions automatiques** : des hooks chargent le contexte au début et vérifient l'état propre à la fin.

> 🇬🇧 [English version](README.md)

## Branches = versions d'Odoo
| Branche | Odoo |
|---|---|
| `17.0` | 17.0 |
| `18.0` | 18.0 |
| `19.0` | 19.0 |
| `20.0` | 20.0 |

## Le skill Odoo

Chaque branche fournit `skills/odoo/` pour sa version d'Odoo : ORM, vues, sécurité, OWL,
contrôleurs, tests, migrations, et les changements depuis les versions précédentes. Il est
écrit à partir du vrai code source `odoo/odoo`, et la CI le vérifie contre ce code :

```
tools/odoo-skill-extract/fetch_odoo.sh 20.0 /tmp/odoo-20.0
python3 tools/odoo-skill-extract/extract.py /tmp/odoo-20.0 -o /tmp/facts.json
python3 tools/odoo-skill-extract/check_skill.py /tmp/facts.json skills/odoo
```

## Installer dans un projet Odoo
1. Ajouter la marketplace (`/plugin marketplace add yessin-fogits/claude-odoo-harness@main`) et installer `odoo-harness-<N>@odoo-harness` pour votre version d'Odoo.
2. Dans votre dépôt Odoo, lancer `/odoo-harness-<N>:init`. La commande suit les 4 étapes d'initialisation :
   1. environnement exécutable (Docker Compose, base de test, modules installés) ;
   2. cadre de test vérifiable (un test qui passe à chaque niveau) ;
   3. document de contrat d'amorçage (`BOOTSTRAP.md`) ;
   4. découpage des tâches (`feature_list.json`).

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

## État
Les phases 1 à 4 sont en place : harness de base, machine à états et vérification en 3 couches, hooks de session automatiques, et le skill Odoo par version. Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) pour le plan
complet et [PROGRESS.md](PROGRESS.md) pour l'état actuel.
