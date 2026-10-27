#!/usr/bin/env bash
# Initialization step 1: executable environment.
# Brings the stack up, prepares the disposable test DB, installs the modules in
# scope and runs the baseline verification. Safe to run again at any time.
#
#   harness/init.sh            full initialization
#   harness/init.sh --check    quick health check (no install, no tests)
#   harness/init.sh --reset    drop the test DB and its filestore, then full initialization
set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"

mode=full
case "${1:-}" in
    --check) mode=check ;;
    --reset) mode=reset ;;
    "") ;;
    *) echo "usage: $0 [--check|--reset]" >&2; exit 2 ;;
esac

LOG_DIR="$REPO_ROOT/.harness/logs"
mkdir -p "$LOG_DIR"

require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        redpen env "docker not found" \
            "The harness runs Odoo and PostgreSQL with Docker Compose." \
            "Install Docker Engine with the compose plugin, then re-run harness/init.sh."
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        redpen env "docker daemon not reachable" \
            "The docker CLI is installed but cannot talk to the daemon." \
            "Start Docker (or check your permissions on the docker socket), then re-run harness/init.sh."
        exit 1
    fi
}

check() {
    local failed=0 running svc
    running="$(dc ps --status running --services 2>/dev/null)"
    for svc in db odoo; do
        if grep -qx "$svc" <<<"$running"; then
            ok "$svc container running"
        else
            redpen env "$svc container is not running" \
                "The stack is stopped or the container crashed." \
                "Run harness/init.sh. If it keeps failing, read: docker compose logs $svc"
            failed=1
        fi
    done
    if grep -qx db <<<"$running"; then
        if test_db_exists; then
            ok "test DB '$TEST_DB' exists"
        else
            redpen env "test DB '$TEST_DB' does not exist" \
                "The disposable test database was never created or was dropped." \
                "Run harness/init.sh to create it and install the modules in scope."
            failed=1
        fi
    fi
    if grep -qx odoo <<<"$running"; then
        if curl -fsS "http://localhost:${ODOO_PORT}/web/health" >/dev/null 2>&1; then
            ok "Odoo answers on http://localhost:${ODOO_PORT}"
        else
            redpen env "Odoo does not answer on http://localhost:${ODOO_PORT}/web/health" \
                "The server is starting, crashed at startup, or the port is taken." \
                "Wait a few seconds and re-run harness/init.sh --check. Otherwise read: docker compose logs odoo"
            failed=1
        fi
    fi
    return "$failed"
}

reset_test_db() {
    step "dropping test DB '$TEST_DB' and its filestore"
    dc stop odoo >/dev/null 2>&1
    psql_db "DROP DATABASE IF EXISTS \"${TEST_DB}\" WITH (FORCE)" >/dev/null
    dc run --rm -T --entrypoint rm odoo -rf "/var/lib/odoo/filestore/${TEST_DB}" >/dev/null 2>&1
}

install_modules() {
    local action log rc
    if test_db_exists; then action=-u; else action=-i; fi
    log="$LOG_DIR/init-install.log"
    step "odoo $action $(modules_or_base) on '$TEST_DB' (log: ${log#"$REPO_ROOT"/})"
    odoo_run -d "$TEST_DB" "$action" "$(modules_or_base)" --stop-after-init >"$log" 2>&1
    rc=$?
    if [ "$rc" -ne 0 ] || grep -qE ' (ERROR|CRITICAL) |^Traceback' "$log"; then
        grep -nE ' (ERROR|CRITICAL) |^Traceback' -A 12 "$log" | head -40 >&2
        redpen env "module install/update failed on '$TEST_DB'" \
            "Odoo logged errors while loading the modules in scope (excerpt above, full log in ${log#"$REPO_ROOT"/})." \
            "Fix the first error in the log (manifest, XML, Python import, missing dependency), then re-run harness/init.sh."
        return 1
    fi
    ok "modules installed/updated: $(modules_or_base)"
}

start_server() {
    step "starting Odoo"
    if ! dc up -d --wait odoo >/dev/null 2>&1; then
        redpen env "Odoo container did not become healthy" \
            "The server crashed at startup or /web/health never answered." \
            "Read: docker compose logs odoo. Fix the first error, then re-run harness/init.sh."
        return 1
    fi
    ok "Odoo running on http://localhost:${ODOO_PORT} (db: $TEST_DB)"
}

baseline_verify() {
    if [ ! -x "$HARNESS_DIR/verify.sh" ]; then
        redpen verify "harness/verify.sh is missing or not executable" \
            "Initialization step 2 (verifiable test frame) is not in place, so the baseline cannot be proven." \
            "Install the verification frame (odoo-harness plugin) or run: chmod +x harness/verify.sh"
        return 1
    fi
    step "baseline verification"
    "$HARNESS_DIR/verify.sh" || {
        redpen verify "baseline verification failed" \
            "The code on this branch does not pass the harness verification." \
            "Fix the failures reported above before starting any feature work."
        return 1
    }
}

require_docker

if [ "$mode" = check ]; then
    check && ok "health check OK"
    exit $?
fi

step "starting database"
if ! dc up -d --wait db >/dev/null 2>&1; then
    redpen env "PostgreSQL container did not become healthy" \
        "The db service failed to start (image pull, volume or port problem)." \
        "Read: docker compose logs db. Fix it, then re-run harness/init.sh."
    exit 1
fi
ok "database running"

[ "$mode" = reset ] && reset_test_db

install_modules || exit 1
start_server || exit 1
baseline_verify || exit 1
ok "baseline OK"
