#!/usr/bin/env bash
# Shared helpers for the harness scripts. Source it, do not run it.

# The engine (this folder) works on the repository in $HARNESS_REPO, set by the
# odoo-harness command (default: the current folder).
ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_REPO:-.}" && pwd)"
export HARNESS_REPO="$REPO_ROOT"
HARNESS_DIR="$REPO_ROOT/harness"
HARNESS_ENV="$HARNESS_DIR/harness.env"
# The compose file's build contexts and engine mount (see hlib.compose_cmd).
export HARNESS_HOME="$ENGINE_DIR"

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

# The same command as hlib.compose_cmd: runtime files first, then compose.
dc() {
    python3 "$ENGINE_DIR/hlib.py" runtime || return 1
    # shellcheck disable=SC2086
    ${HARNESS_COMPOSE:-docker compose} --project-directory "$REPO_ROOT" \
        -f "$ENGINE_DIR/docker-compose.yml" --env-file "$HARNESS_ENV" "$@"
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

# Every custom module of the project (CUSTOM_ADDONS), or base when there is none yet.
modules_or_base() {
    local mods
    mods="$(python3 "$ENGINE_DIR/hlib.py" modules)"
    if [ -n "$mods" ]; then printf '%s' "$mods"; else printf 'base'; fi
}
