#!/usr/bin/env bash
# Shared helpers for the harness scripts. Source it, do not run it.

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HARNESS_DIR/.." && pwd)"
HARNESS_ENV="$HARNESS_DIR/harness.env"

set -a
# shellcheck source=/dev/null
. "$HARNESS_ENV"
set +a

# "Red pen" failure: what failed, why, and how to fix it. Agents act on HOW TO FIX.
redpen() {
    local layer="$1" what="$2" why="$3" how="$4"
    {
        printf '✗ [%s] %s\n' "$layer" "$what"
        printf 'WHY: %s\n' "$why"
        printf 'HOW TO FIX: %s\n' "$how"
    } >&2
}

ok()   { printf '✓ %s\n' "$*"; }
step() { printf '→ %s\n' "$*"; }

dc() {
    docker compose --project-directory "$REPO_ROOT" --env-file "$HARNESS_ENV" "$@"
}

# Run an odoo-bin command in a one-off container (no published ports).
odoo_run() {
    dc run --rm -T odoo odoo "$@"
}

psql_db() {
    dc exec -T db psql -U odoo -d postgres -tAc "$1"
}

test_db_exists() {
    [ "$(psql_db "SELECT 1 FROM pg_database WHERE datname='${TEST_DB}'" 2>/dev/null)" = "1" ]
}

modules_or_base() {
    if [ -n "${MODULES:-}" ]; then printf '%s' "$MODULES"; else printf 'base'; fi
}
