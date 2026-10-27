from odoo.tests import TransactionCase


class TestThing(TransactionCase):
    def test_create(self):
        thing = self.env["demo.thing"].create({"name": "x"})
        self.assertEqual(thing.name, "x")
