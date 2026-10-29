# ORM (Odoo 20.0)

## A model

```python
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain


class SaleDiscount(models.Model):
    _name = 'sale.discount'
    _description = "Sale Discount"
    _order = 'sequence, id'
    _rec_names_search = ('name', 'code')          # a tuple in 20.0
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    code = fields.Char(index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    rate = fields.Float(digits=(16, 2), aggregator='avg')
    amount = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', ondelete='restrict', check_company=True)
    line_ids = fields.One2many('sale.discount.line', 'discount_id')
    tag_ids = fields.Many2many('sale.discount.tag')
    state = fields.Selection([('draft', "Draft"), ('done', "Done")], default='draft', required=True)
    note = fields.Html(sanitize=True)
    total = fields.Float(compute='_compute_total', store=True)

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        "The code must be unique per company.",
    )
    _rate_positive = models.Constraint('CHECK(rate >= 0)', "The rate cannot be negative.")
```

Extend an existing model with `_inherit = 'sale.order'` (no `_name`), never by editing its module.

## Compute, inverse, onchange, constraints

```python
    @api.depends('line_ids.amount')
    def _compute_total(self):
        for discount in self:
            discount.total = sum(discount.line_ids.mapped('amount'))

    @api.constrains('rate')
    def _check_rate(self):
        for discount in self:
            if discount.rate > 100:
                raise ValidationError(self.env._("A discount cannot exceed 100%%."))

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id.lang:
            self.note = False

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if any(d.state == 'done' for d in self):
            raise UserError(self.env._("Done discounts cannot be deleted."))
```

- Every compute method assigns the field on every record of `self`.
- Stored computes need complete `@api.depends`; non-stored ones can depend on context with
  `@api.depends_context('company')`.
- `@api.constrains` only sees simple field names (no dotted paths).
- Use `@api.ondelete` instead of overriding `unlink` for business rules.

## Create, write, display name

```python
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('code', self.env['ir.sequence'].next_by_code('sale.discount'))
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'rate' in vals:
            self.line_ids._recompute_amounts()
        return res

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for discount in self:
            discount.display_name = f"[{discount.code}] {discount.name}"
```

x2many values are written with `Command`:
`Command.create({...})`, `Command.update(id, {...})`, `Command.delete(id)`,
`Command.unlink(id)`, `Command.link(id)`, `Command.clear()`, `Command.set(ids)`.

## Environment and recordsets

- `self.env.cr`, `self.env.uid`, `self.env.user`, `self.env.company`, `self.env.companies`,
  `self.env.context`, `self.env.lang`.
- Translations in Python: `self.env._("Text %s", value)`.
- `records.with_context(key=value)`, `records.with_company(company)`, `records.with_user(user)`,
  `records.sudo()` (see security.md before using it).
- `search(domain, order=..., limit=...)`, `search_count(domain)`, `search_fetch(domain, field_names)`,
  `browse(ids)`, `exists()`, `filtered(lambda r: ...)`, `filtered_domain(domain)`, `mapped('a.b')`,
  `grouped('field')`, `sorted('field')`.
- Aggregations: `self._read_group(domain, groupby=['partner_id'], aggregates=['amount:sum'])`
  returns a list of tuples.
- Methods that must not be callable over RPC start with `_`, or use `@api.private`.
  `@api.readonly` lets an RPC call run on a read-only cursor.

## Domains

Lists still work, but `Domain` objects compose safely:

```python
domain = Domain('state', '=', 'done') & Domain('partner_id', 'in', partners.ids)
domain |= Domain('company_id', '=', False)
records = self.env['sale.discount'].search(domain)
empty = Domain.FALSE
if domain.is_false():   # never bool(domain)
    ...
```

Operators are lower case (`'in'`, `'not in'`, `'ilike'`, `'child_of'`, `'any'`).

## SQL

Use the ORM first. When SQL is needed, always wrap it in `SQL`, never format values in:

```python
from odoo.tools import SQL

self.env.cr.execute(SQL(
    "SELECT id FROM %s WHERE company_id = %s AND rate > %s",
    SQL.identifier(self._table), self.env.company.id, 10,
))
```

Flush and invalidate around raw SQL: `self.env.flush_all()` before reading,
`self.env.invalidate_all()` after writing.

## Caching

```python
from odoo.api import ormcache

    @ormcache('code')
    def _get_rate_by_code(self, code):
        ...
```

Invalidate with `self.env.transaction.invalidate_ormcache()`.
