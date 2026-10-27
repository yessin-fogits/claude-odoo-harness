#!/usr/bin/env python3
"""Build a demo Odoo project with the harness installed, for this branch's Odoo version.

    tools/make_demo_project.py DEST [--no-feature]

DEST gets: the harness template, the demo_mod module (tests/fixtures/demo_mod adapted to
the version, plus an action and a menu), a git repository, and feature F-001 with its
Playwright test. CI runs the real harness on it (harness/init.sh, feature.py verify).
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import install_template  # noqa: E402

ODOO_VERSION = install_template.ODOO_VERSION
MAJOR = int(ODOO_VERSION.split(".")[0])
FIXTURE = ROOT / "tests" / "fixtures" / "demo_mod"
E2E_FILE = "e2e/test_F001_demo_thing.py"

MENUS_XML = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="demo_thing_view_list" model="ir.ui.view">
        <field name="name">demo.thing.list</field>
        <field name="model">demo.thing</field>
        <field name="arch" type="xml">
            <{list_tag}>
                <field name="name"/>
            </{list_tag}>
        </field>
    </record>

    <record id="demo_thing_action" model="ir.actions.act_window">
        <field name="name">Demo Things</field>
        <field name="res_model">demo.thing</field>
{path_field}        <field name="view_mode">{list_mode},form</field>
    </record>

    <menuitem id="demo_thing_menu_root" name="Demo Things" action="demo_thing_action"/>
</odoo>
"""

E2E_TEST = '''"""F-001: a user creates a demo thing and finds it in the list."""

import os

from playwright.sync_api import expect

MAJOR = int(os.environ.get("ODOO_VERSION", "17.0").split(".")[0])
URL = "/odoo/demo-things" if MAJOR >= 18 else "/web#action=demo_mod.demo_thing_action"


def test_create_demo_thing(odoo_page):
    page = odoo_page
    page.goto(URL)
    page.get_by_role("button", name="New").click()
    page.locator(".o_field_widget[name=name] input").fill("Thing from e2e")
    page.locator(".o_form_button_save").click()
    expect(page.locator(".o_form_button_save")).to_be_hidden()

    page.goto(URL)
    expect(page.locator(".o_data_row", has_text="Thing from e2e")).to_be_visible()
'''


def adapt_fixture_module(module, version=ODOO_VERSION):
    """The fixture is written for 17.0; make it valid for `version`."""
    major = int(version.split(".")[0])
    manifest = module / "__manifest__.py"
    manifest.write_text(manifest.read_text().replace('"17.0.', f'"{version}.'))
    if major >= 20:
        (module / "security/ir.model.access.csv").unlink()
        (module / "security/ir.access.csv").write_text(
            "id,name,model_id,group_id/id,operation,domain\n"
            "access_demo_thing_user,demo.thing user,demo.thing,base.group_user,crud,\n")
        manifest.write_text(manifest.read_text().replace("ir.model.access.csv", "ir.access.csv"))


def add_menus(module, version=ODOO_VERSION):
    major = int(version.split(".")[0])
    (module / "views" / "thing_menus.xml").write_text(MENUS_XML.format(
        list_tag="list" if major >= 18 else "tree",
        list_mode="list" if major >= 18 else "tree",
        path_field='        <field name="path">demo-things</field>\n' if major >= 18 else "",
    ))
    manifest = module / "__manifest__.py"
    manifest.write_text(manifest.read_text().replace(
        '"views/thing_views.xml",', '"views/thing_views.xml",\n        "views/thing_menus.xml",'))


def run(dest, *args):
    subprocess.run(list(args), cwd=dest, check=True)


def build(dest, feature=True):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    install_template.main([str(dest), "--modules", "demo_mod"])
    module = dest / "addons" / "demo_mod"
    shutil.copytree(FIXTURE, module)
    adapt_fixture_module(module)
    add_menus(module)
    git = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
    run(dest, "git", "init", "-q")
    if feature:
        (dest / E2E_FILE).write_text(E2E_TEST)
        run(dest, sys.executable, "harness/feature.py", "add",
            "--behavior", "A user creates a demo thing and finds it in the list",
            "--verify", "unit: /demo_mod:TestThing", "--verify", f"e2e: {E2E_FILE}")
    run(dest, "git", "add", "-A")
    run(dest, *git, "commit", "-q", "-m", "demo project")
    return dest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dest", type=Path)
    p.add_argument("--no-feature", action="store_true")
    args = p.parse_args(argv)
    build(args.dest, feature=not args.no_feature)
    print(f"demo project for Odoo {ODOO_VERSION} in {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
