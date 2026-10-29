import sys

import pytest

from conftest import CLI, ODOO_VERSION
from test_static_and_errors import write


def check(repo, rel, text, version):
    path = write(repo, rel, text)
    result = repo.run(CLI, "static", str(path), odoo_version=version)
    return result.stderr


PY = "extra-addons/client/demo_mod/models/other.py"
XML = "extra-addons/client/demo_mod/views/other.xml"
JS = "extra-addons/client/demo_mod/static/src/other.js"


@pytest.mark.parametrize("rel,text,flagged_in,clean_in", [
    (XML, '<odoo><record id="v" model="ir.ui.view"><field name="arch" type="xml"><tree/></field>'
          '</record></odoo>', ["18.0", "20.0"], ["17.0"]),
    (XML, '<odoo><record id="v" model="ir.ui.view"><field name="arch" type="xml"><list/></field>'
          '</record></odoo>', ["17.0"], ["18.0", "20.0"]),
    (XML, '<odoo><record id="a" model="ir.actions.act_window"><field name="view_mode">tree,form'
          '</field></record></odoo>', ["18.0"], ["17.0"]),
    (PY, "class A:\n    _sql_constraints = [('u', 'unique(name)', 'x')]\n", ["19.0", "20.0"],
     ["17.0", "18.0"]),
    (PY, "class A:\n    _name_uniq = models.Constraint('UNIQUE(name)')\n", ["17.0", "18.0"],
     ["19.0"]),
    (PY, "@http.route('/x', type='json', auth='user')\ndef x(self):\n    pass\n", ["19.0"],
     ["17.0", "18.0"]),
    (PY, "@http.route('/x', type='jsonrpc', auth='user')\ndef x(self):\n    pass\n", ["18.0"],
     ["19.0", "20.0"]),
    (PY, "def f(self):\n    self._cr.execute('select 1')\n", ["19.0"], ["18.0"]),
    (PY, "def f(self):\n    self.check_access_rights('read')\n", ["18.0"], ["17.0"]),
    (PY, "class A:\n    def name_get(self):\n        return []\n", ["17.0", "20.0"], []),
    (PY, "from odoo.tests import SingleTransactionCase\n", ["20.0"], ["19.0"]),
    (PY, "from odoo.tools import ormcache\n", ["20.0"], ["19.0"]),
    (PY, "class A:\n    _rec_names_search = ['name']\n", ["20.0"], ["19.0"]),
    (XML, '<odoo><record id="a" model="ir.attachment"><field name="datas" type="base64" '
          'file="demo_mod/static/x.png"/></record></odoo>', ["20.0"], ["19.0"]),
    (XML, '<odoo><template id="t"><span t-esc="x"/></template></odoo>', ["20.0"], ["19.0"]),
    (JS, 'import { Component, useState } from "@odoo/owl";\n', ["20.0"], ["19.0", "17.0"]),
    (PY, "class A:\n    rate = fields.Float(group_operator='avg')\n", ["18.0", "20.0"], ["17.0"]),
    (PY, "class A:\n    rate = fields.Float(aggregator='avg')\n", ["17.0"], ["18.0"]),
    (PY, "def f(self):\n    return self.env._('Hello')\n", ["17.0"], ["18.0"]),
    (PY, "def f(self):\n    return self.env.user.groups_id\n", ["19.0"], ["18.0"]),
])
def test_version_rules(hrepo, rel, text, flagged_in, clean_in):
    for version in flagged_in:
        assert "[odoo-version-api]" in check(hrepo, rel, text, version), version
    for version in clean_in:
        assert "[odoo-version-api]" not in check(hrepo, rel, text, version), version


def test_owl3_message_names_the_replacement(hrepo):
    out = check(hrepo, JS, 'import { Component, useState, useRef as r } from "@odoo/owl";\n',
                "20.0")
    assert "OWL 3 (Odoo 20.0) does not export useState" in out
    assert "Use proxy() (or signal())" in out
    assert "does not export useRef" in out and "signal.ref()" in out


def test_owl3_allowed_imports(hrepo):
    out = check(hrepo, JS, 'import { Component, proxy, signal, useProps } from "@odoo/owl";\n',
                "20.0")
    assert "[odoo-version-api]" not in out


# --- model access ----------------------------------------------------------------

MODEL = '''from odoo import fields, models


class Gadget(models.Model):
    _name = "demo.gadget"
    _description = "Gadget"

    name = fields.Char()


class Partner(models.Model):
    _name = "res.partner"
    _inherit = "res.partner"


class Mixin(models.AbstractModel):
    _name = "demo.mixin"
    _description = "Mixin"
'''


@pytest.mark.parametrize("version,expected", [
    ("19.0", "model_demo_gadget,base.group_user,1,1,1,1"),
    ("20.0", "demo.gadget,base.group_user,crud,"),
])
def test_new_model_without_access_is_flagged(hrepo, version, expected):
    out = check(hrepo, "extra-addons/client/demo_mod/models/gadget.py", MODEL, version)
    assert "[model-access] model 'demo.gadget' has no access rights" in out
    assert expected in out
    assert "res.partner" not in out and "demo.mixin" not in out


def test_model_with_access_is_clean(hrepo):
    # demo.thing is covered by the fixture's security CSV
    out = check(hrepo, "extra-addons/client/demo_mod/models/thing.py",
                (hrepo.path / "extra-addons/client/demo_mod/models/thing.py").read_text(), ODOO_VERSION)
    assert "[model-access]" not in out
