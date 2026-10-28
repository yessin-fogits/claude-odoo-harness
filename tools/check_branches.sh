#!/usr/bin/env bash
# Shared harness files must be identical on every Odoo version branch.
# Only these paths may differ: odoo_version.json, .claude-plugin/plugin.json and skills/odoo/.
# Changes land on the lowest branch and are forward-ported:
#   17.0 -> 18.0 -> 19.0 -> 20.0 (git merge, keeping each branch's own files).
#
# Usage: tools/check_branches.sh [--warn]
#   --warn  report the branches still to forward-port to, but exit 0.
#           Used on pull requests and work branches: a PR that changes a shared file always differs
#           from every version branch (its own base included) until it is merged
#           and forward-ported, so a failing check there would be red by design.
set -uo pipefail
warn=0
[ "${1:-}" = "--warn" ] && warn=1
branches=(17.0 18.0 19.0 20.0)
git fetch -q origin "${branches[@]/#/+refs/heads/}" 2>/dev/null || true
status=0
for b in "${branches[@]}"; do
    git rev-parse -q --verify "origin/$b" >/dev/null || continue
    if ! git diff --quiet "origin/$b" -- . ':(exclude)odoo_version.json' ':(exclude).claude-plugin/plugin.json' ':(exclude)skills/odoo'; then
        echo "✗ shared files differ from origin/$b:"
        git diff --stat "origin/$b" -- . ':(exclude)odoo_version.json' ':(exclude).claude-plugin/plugin.json' ':(exclude)skills/odoo' | tail -20
        [ "$warn" -eq 1 ] && echo "::warning::shared files differ from origin/$b: forward-port this change after merging"
        status=1
    else
        echo "✓ same shared files as origin/$b"
    fi
done
if [ "$status" -ne 0 ]; then
    echo "HOW TO FIX: forward-port the change: merge 17.0 into 18.0, 18.0 into 19.0, 19.0 into 20.0"
    echo "(run 'git config merge.ours.driver true' once so odoo_version.json keeps each branch's value)."
    [ "$warn" -eq 1 ] && status=0
fi
exit "$status"
