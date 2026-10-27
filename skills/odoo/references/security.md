# Security (Odoo 17.0)

Two layers: **access rights** (`ir.model.access`, per model and group, in a CSV) say
which operations a group may do on a model at all; **record rules** (`ir.rule`, in XML)
restrict which records.

## ir.model.access.csv

`security/ir.model.access.csv`, listed in the manifest `data` (before the views):

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_sale_discount_user,sale.discount user,model_sale_discount,sales_team.group_sale_salesman,1,1,1,0
access_sale_discount_manager,sale.discount manager,model_sale_discount,sales_team.group_sale_manager,1,1,1,1
```

- `model_id:id` is the XML id of the model: `model_` + the model name with dots replaced by
  underscores (`model_sale_discount`), prefixed by the module when it belongs to another one.
- An empty `group_id:id` gives the rights to everybody (avoid it).
- Every new model needs at least one line, or only the superuser can use it (the harness
  check `model-access` reports it).

## Record rules

```xml
<record id="sale_discount_rule_own" model="ir.rule">
    <field name="name">Discounts: own documents</field>
    <field name="model_id" ref="model_sale_discount"/>
    <field name="domain_force">[('user_id', '=', user.id)]</field>
    <field name="groups" eval="[Command.link(ref('sales_team.group_sale_salesman'))]"/>
    <field name="perm_unlink" eval="False"/>
</record>

<record id="sale_discount_comp_rule" model="ir.rule">
    <field name="name">Discounts: multi-company</field>
    <field name="model_id" ref="model_sale_discount"/>
    <field name="domain_force">[('company_id', 'in', company_ids)]</field>
</record>
```

- A rule with `groups` applies to those groups; rules of the same user's groups are
  combined with OR. A rule without `groups` is global: it applies to everybody and
  global rules are combined with AND.
- `perm_read/write/create/unlink` (default true) choose the operations the rule applies to.
- Variables in `domain_force`: `user`, `company_ids` (companies active in the switcher),
  `company_id`.

## Groups

Groups of one application share an `ir.module.category`, shown as one selection in the
user form:

```xml
<record id="module_category_discount" model="ir.module.category">
    <field name="name">Discounts</field>
    <field name="sequence">50</field>
</record>

<record id="group_discount_user" model="res.groups">
    <field name="name">User</field>
    <field name="category_id" ref="module_category_discount"/>
    <field name="implied_ids" eval="[Command.link(ref('base.group_user'))]"/>
</record>

<record id="group_discount_manager" model="res.groups">
    <field name="name">Administrator</field>
    <field name="category_id" ref="module_category_discount"/>
    <field name="implied_ids" eval="[Command.link(ref('group_discount_user'))]"/>
    <field name="users" eval="[Command.link(ref('base.user_admin'))]"/>
</record>
```

On users the groups field is `groups_id`. In code: `self.env.user.has_group('sale_discount.group_discount_manager')`.
In views: `groups="sale_discount.group_discount_manager"` on a field, button or menu.

## Checks in code

```python
discounts.check_access_rights('write')          # model level, raises AccessError
discounts.check_access_rule('write')            # record rules on these records
allowed = discounts._filter_access_rules('read')   # the subset the user may read
if discounts.check_access_rights('unlink', raise_exception=False):
    ...
```

## sudo()

`sudo()` bypasses all access control. Use it only for a precise technical need, on the
smallest recordset, and never on values coming from the request without checking them:

```python
# good: the user may confirm the order; the sequence is technical
order.check_access_rights('write')
order.check_access_rule('write')
order.name = self.env['ir.sequence'].sudo().next_by_code('sale.order')
```

Never write `sudo()` to make an access error go away in a test or a controller: fix the
access rights or rules instead.

## Multi-company

- `company_id = fields.Many2one('res.company', default=lambda self: self.env.company)`
- `_check_company_auto = True` and `check_company=True` on relational fields.
- One global record rule per model: `[('company_id', 'in', company_ids)]`
  (`['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]` when records can be shared).
