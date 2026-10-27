#!/usr/bin/env bash
# Sparse, blob-less checkout of the parts of odoo/odoo that extract.py reads.
#   tools/odoo-skill-extract/fetch_odoo.sh 20.0 /tmp/odoo-20.0
set -euo pipefail
branch="${1:?usage: fetch_odoo.sh BRANCH DEST}"
dest="${2:?usage: fetch_odoo.sh BRANCH DEST}"
if [ ! -d "$dest/.git" ]; then
    git clone -q --depth 1 --filter=blob:none --no-checkout -b "$branch" \
        https://github.com/odoo/odoo "$dest"
fi
git -C "$dest" sparse-checkout set --no-cone \
    '/odoo/*.py' '/odoo/orm/' '/odoo/api/' '/odoo/fields/' '/odoo/models/' '/odoo/tests/' \
    '/odoo/http/' '/odoo/tools/' '/odoo/modules/' '/odoo/upgrade_code/' \
    '/odoo/addons/base/rng/' '/odoo/addons/base/security/' '/odoo/addons/base/models/' \
    '/addons/web/static/lib/owl/owl.js'
git -C "$dest" checkout -q
git -C "$dest" log -1 --format='%H %cd' > "$dest/.harness-source"
echo "odoo $branch at $(cut -c1-12 "$dest/.harness-source") in $dest"
