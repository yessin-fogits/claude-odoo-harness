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

# docker compose on the harness stack, through hlib.compose_cmd (runtime files, compose
# files of the database mode, database settings).
dc() {
    python3 "$ENGINE_DIR/hlib.py" compose "$@"
}

# Run an odoo-bin command in a one-off container (no published ports).
odoo_run() {
    dc run --rm -T odoo odoo "$@"
}

# One SQL statement on the harness's PostgreSQL server (the dev stack's in dev DB mode).
psql_db() {
    python3 "$ENGINE_DIR/hlib.py" psql "$1"
}

test_db_exists() {
    [ "$(psql_db "SELECT 1 FROM pg_database WHERE datname='${TEST_DB//\'/\'\'}'" 2>/dev/null)" = "1" ]
}

# Dev DB mode: the e2e tests run on DEV_DB, on the dev stack's PostgreSQL.
dev_mode() {
    [ -n "${DEV_DB:-}" ]
}

# Every custom module of the project (CUSTOM_ADDONS), or base when there is none yet.
modules_or_base() {
    local mods
    mods="$(python3 "$ENGINE_DIR/hlib.py" modules)"
    if [ -n "$mods" ]; then printf '%s' "$mods"; else printf 'base'; fi
}
