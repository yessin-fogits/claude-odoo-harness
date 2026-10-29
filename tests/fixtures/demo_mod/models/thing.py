from odoo import fields, models


class DemoThing(models.Model):
    _name = "demo.thing"
    _description = "Demo thing"

    name = fields.Char(required=True)
