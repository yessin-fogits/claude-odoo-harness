#!/usr/bin/env bash
# Initialization step 1: executable environment.
# Builds the test image (the project's Dockerfile), brings the harness stack up,
# prepares the disposable test DB with demo data, installs every custom module of
# the project and runs the baseline verification. Safe to run again at any time.
#
#   odoo-harness init            full initialization
#   odoo-harness init --check    quick health check (no install, no tests)
#   odoo-harness init --reset    drop the test DB and its filestore, then full initialization
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
            "Install Docker Engine with the compose plugin, then re-run odoo-harness init."
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        redpen env "docker daemon not reachable" \
            "The docker CLI is installed but cannot talk to the daemon." \
            "Start Docker (or check your permissions on the docker socket), then re-run odoo-harness init."
        exit 1
    fi
}

require_enterprise() {
    [ -z "${ENTERPRISE_DIR:-}" ] && return 0
    if [ ! -d "$REPO_ROOT/$ENTERPRISE_DIR" ] || [ -z "$(ls -A "$REPO_ROOT/$ENTERPRISE_DIR" 2>/dev/null)" ]; then
        redpen env "Odoo Enterprise not found in $ENTERPRISE_DIR" \
            "The project uses Enterprise modules (ENTERPRISE_DIR in harness/harness.env); without them the custom modules cannot install." \
            "Clone odoo/enterprise branch $ODOO_VERSION into $ENTERPRISE_DIR (next to the repository, as the dev stack does), or empty ENTERPRISE_DIR if the project does not use Enterprise."
        exit 1
    fi
}

build_image() {
    [ -z "${ODOO_DOCKERFILE:-}" ] && return 0
    local log="$LOG_DIR/build.log"
    step "building $ODOO_IMAGE from $ODOO_DOCKERFILE (log: ${log#"$REPO_ROOT"/})"
    if ! docker build -f "$REPO_ROOT/$ODOO_DOCKERFILE" -t "$ODOO_IMAGE" "$REPO_ROOT" >"$log" 2>&1; then
        tail -20 "$log" >&2
        redpen env "the project image does not build from $ODOO_DOCKERFILE" \
            "The harness tests with the project's own image, so the Python dependencies match production." \
            "If the base image is in a private registry, run docker login <registry> first. Otherwise fix the Dockerfile (a human change), or set ODOO_DOCKERFILE= and ODOO_IMAGE=odoo:$ODOO_VERSION in harness/harness.env."
        exit 1
    fi
    ok "image $ODOO_IMAGE built"
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
                "Run odoo-harness init. If it keeps failing, read: odoo-harness compose logs $svc"
            failed=1
        fi
    done
    if grep -qx db <<<"$running"; then
        if test_db_exists; then
            ok "test DB '$TEST_DB' exists"
        else
            redpen env "test DB '$TEST_DB' does not exist" \
                "The disposable test database was never created or was dropped." \
                "Run odoo-harness init to create it and install the custom modules."
            failed=1
        fi
    fi
    if grep -qx odoo <<<"$running"; then
        if curl -fsS "http://localhost:${ODOO_PORT}/web/health" >/dev/null 2>&1; then
            ok "Odoo answers on http://localhost:${ODOO_PORT}"
        else
            redpen env "Odoo does not answer on http://localhost:${ODOO_PORT}/web/health" \
                "The server is starting, crashed at startup, or the port is taken." \
                "Wait a few seconds and re-run odoo-harness init --check. Otherwise read: odoo-harness compose logs odoo"
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
            "Odoo logged errors while loading the custom modules (excerpt above, full log in ${log#"$REPO_ROOT"/})." \
            "Fix the first error in the log (manifest, XML, Python import, missing dependency), then re-run odoo-harness init."
        return 1
    fi
    ok "modules installed/updated: $(modules_or_base)"
}

start_server() {
    step "starting Odoo"
    if ! dc up -d --wait odoo >/dev/null 2>&1; then
        redpen env "Odoo container did not become healthy" \
            "The server crashed at startup or /web/health never answered." \
            "Read: odoo-harness compose logs odoo. Fix the first error, then re-run odoo-harness init."
        return 1
    fi
    ok "Odoo running on http://localhost:${ODOO_PORT} (db: $TEST_DB)"
}

baseline_verify() {
    step "baseline verification"
    python3 "$ENGINE_DIR/verify.py" || {
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

require_enterprise
build_image

step "starting database"
if ! dc up -d --wait db >/dev/null 2>&1; then
    redpen env "PostgreSQL container did not become healthy" \
        "The db service failed to start (image pull, volume or port problem)." \
        "Read: odoo-harness compose logs db. Fix it, then re-run odoo-harness init."
    exit 1
fi
ok "database running"

[ "$mode" = reset ] && reset_test_db

install_modules || exit 1
start_server || exit 1
baseline_verify || exit 1
ok "baseline OK"
