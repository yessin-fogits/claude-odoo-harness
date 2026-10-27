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
1. Ajouter ce plugin à Claude Code depuis la branche de votre version d'Odoo.
2. Dans votre dépôt Odoo, lancer `/odoo-harness:init`. La commande suit les 4 étapes d'initialisation :
   1. environnement exécutable (Docker Compose, base de test, modules installés) ;
   2. cadre de test vérifiable (un test qui passe à chaque niveau) ;
   3. document de contrat d'amorçage (`BOOTSTRAP.md`) ;
   4. découpage des tâches (`feature_list.json`).

## État
Les phases 1 à 4 sont en place : harness de base, machine à états et vérification en 3 couches, hooks de session automatiques, et le skill Odoo par version. Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) pour le plan
complet et [PROGRESS.md](PROGRESS.md) pour l'état actuel.
