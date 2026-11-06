# ORM (Odoo 16.0)

## A model

```python
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.osv import expression


class SaleDiscount(models.Model):
    _name = 'sale.discount'
    _description = "Sale Discount"
    _order = 'sequence, id'
    _rec_names_search = ['name', 'code']
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    code = fields.Char(index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    rate = fields.Float(digits=(16, 2), group_operator='avg')
    amount = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    partner_id = fields.Many2one(
        'res.partner', ondelete='restrict', check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    line_ids = fields.One2many('sale.discount.line', 'discount_id')
    tag_ids = fields.Many2many('sale.discount.tag')
    state = fields.Selection([('draft', "Draft"), ('done', "Done")], default='draft', required=True)
    note = fields.Html(sanitize=True)
    total = fields.Float(compute='_compute_total', store=True)

    _sql_constraints = [
        ('code_company_uniq', 'UNIQUE(code, company_id)', "The code must be unique per company."),
        ('rate_positive', 'CHECK(rate >= 0)', "The rate cannot be negative."),
    ]
```

Extend an existing model with `_inherit = 'sale.order'` (no `_name`), never by editing its module.

- `check_company=True` makes the ORM check the company consistency on write; it does not
  restrict the dropdown. Write the `domain` on the field yourself, as above.
- Translated fields (`translate=True`) are stored as JSONB, one value per language.

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
                raise ValidationError(_("A discount cannot exceed 100%%."))

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id.lang:
            self.note = False

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if any(d.state == 'done' for d in self):
            raise UserError(_("Done discounts cannot be deleted."))
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

    def name_get(self):
        return [(discount.id, f"[{discount.code}] {discount.name}") for discount in self]
```

- The display name is `name_get()`: `display_name` is computed from it, and `name_search`
  and the many2one dropdowns return it. Override `name_get`, not `_compute_display_name`.
- Custom search on the display name: set `_rec_names_search`, or override
  `_name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None)`,
  which returns ids.

x2many values are written with `Command`:
`Command.create({...})`, `Command.update(id, {...})`, `Command.delete(id)`,
`Command.unlink(id)`, `Command.link(id)`, `Command.clear()`, `Command.set(ids)`.

## Environment and recordsets

- `self.env.cr`, `self.env.uid`, `self.env.user`, `self.env.company`, `self.env.companies`,
  `self.env.context`, `self.env.lang`.
- Translations in Python: `_("Text %s", value)` with `from odoo import _`.
- `records.with_context(key=value)`, `records.with_company(company)`, `records.with_user(user)`,
  `records.sudo()` (see security.md before using it).
- `search(domain, order=..., limit=...)`, `search_count(domain)`, `search_read(domain, fields)`,
  `browse(ids)`, `exists()`, `filtered(lambda r: ...)`, `filtered_domain(domain)`, `mapped('a.b')`,
  `sorted('field')`. There is no `search_fetch` and no `grouped` (17.0).
- Aggregations: `self._read_group(domain, fields=['partner_id'], groupby=['partner_id'])`
  returns a list of dicts like `read_group`: `group['partner_id']` is `(id, name)`, the count is
  `group['partner_id_count']`, an aggregated field is `group['amount']` (with
  `fields=['amount:sum']`).
- Methods that must not be callable over RPC start with `_`, or use `@api.private`.

## Domains

Domains are lists of `(field, operator, value)` leaves in prefix notation (`'|'`, `'&'`, `'!'`).
Combine them with `odoo.osv.expression`, not by concatenating lists:

```python
domain = expression.AND([
    [('state', '=', 'done')],
    expression.OR([[('partner_id', 'in', partners.ids)], [('company_id', '=', False)]]),
])
records = self.env['sale.discount'].search(domain)
```

Operators: `'='`, `'!='`, `'in'`, `'not in'`, `'ilike'`, `'=like'`, `'child_of'`, `'parent_of'`...
(no `'any'`: it is 17.0; use a dotted path such as `('line_ids.amount', '>', 0)`).

## SQL

Use the ORM first. When SQL is needed, pass the values as query parameters, never format
them into the string; table and column names come from the code, never from the request:

```python
self.env.cr.execute(
    f"SELECT id FROM {self._table} WHERE company_id = %s AND rate > %s",
    (self.env.company.id, 10),
)
ids = [row[0] for row in self.env.cr.fetchall()]
```

There is no `SQL` wrapper (`odoo.tools.SQL` is 17.0). Flush and invalidate around raw SQL:
`self.env.flush_all()` (or `records.flush_model(['rate'])`) before reading,
`self.env.invalidate_all()` (or `records.invalidate_model(['rate'])`) after writing.
`flush()`, `invalidate_cache()` and `recompute()` are deprecated in 16.0.

## Caching

```python
from odoo.tools import ormcache

    @ormcache('code')
    def _get_rate_by_code(self, code):
        ...
```

Invalidate with `self.clear_caches()` (or `self.env.registry.clear_caches()`).
