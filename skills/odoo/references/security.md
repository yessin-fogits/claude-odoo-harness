# Security (Odoo 20.0)

Odoo 20.0 has a single model for access control: `ir.access`. One record says which
**operations** a **group** may do on a **model**, optionally limited to the records of a
**domain**. Record rules are not a separate model any more: they are the `domain` column.

## ir.access.csv

`security/ir.access.csv`, listed in the manifest `data` (before the views):

```csv
id,name,model_id,group_id/id,operation,domain
access_sale_discount_user,sale.discount user,sale.discount,sales_team.group_sale_salesman,r,
access_sale_discount_own,sale.discount own,sale.discount,sales_team.group_sale_salesman,cru,"[('user_id', '=', user.id)]"
access_sale_discount_manager,sale.discount manager,sale.discount,sales_team.group_sale_manager,crud,
sale_discount_company_rule,sale.discount multi-company,sale.discount,,crud,"[('company_id', 'in', company_ids)]"
```

| Column | Meaning |
|---|---|
| `id` | XML id of the access record |
| `name` | label |
| `model_id` | the model **name** (`sale.discount`), not `model_sale_discount` |
| `group_id/id` | group XML id; **empty = a restriction for everybody** |
| `operation` | letters of `crud` in that order: `crud`, `cru`, `crd`, `cud`, `rud`, `cr`, `cu`, `cd`, `ru`, `rd`, `ud`, `c`, `r`, `u`, `d` |
| `domain` | optional; quoted when it contains commas |

How Odoo combines them (`_access_domain` in the ORM): the records a user may access for an
operation are `OR(permissions of the user's groups) AND AND(restrictions)`. A permission
with an empty domain grants all records; each group-less row restricts everybody.

Variables available in domains: `user` (the current user), `company_ids` (companies
active in the company switcher), `company_id` (current company), `time`.

Every new model needs at least one row, or only the superuser can use it (the harness
check `model-access` reports it).

## Groups

Groups belong to a privilege (`res.groups.privilege`), which is shown as one selection in
the user form:

```xml
<record id="res_groups_privilege_discount" model="res.groups.privilege">
    <field name="name">Discounts</field>
    <field name="sequence">50</field>
    <field name="category_id" ref="base.module_category_sales"/>
</record>

<record id="group_discount_user" model="res.groups">
    <field name="name">User</field>
    <field name="sequence">10</field>
    <field name="privilege_id" ref="res_groups_privilege_discount"/>
    <field name="implied_ids" eval="[Command.link(ref('base.group_user'))]"/>
</record>

<record id="group_discount_manager" model="res.groups">
    <field name="name">Administrator</field>
    <field name="sequence">20</field>
    <field name="privilege_id" ref="res_groups_privilege_discount"/>
    <field name="implied_ids" eval="[Command.link(ref('group_discount_user'))]"/>
    <field name="user_ids" eval="[Command.link(ref('base.user_admin'))]"/>
</record>
```

On users the fields are `group_ids` (explicit groups) and `all_group_ids` (with implied
groups). In code: `self.env.user.has_group('sale_discount.group_discount_manager')`.
In views: `groups="sale_discount.group_discount_manager"` on a field, button or menu.

## Checks in code

```python
discounts.check_access('write')                 # raises AccessError if not allowed
allowed = discounts._filtered_access('read')    # the subset the user may read
if discounts.has_access('unlink'):
    ...
```

## sudo()

`sudo()` bypasses all access control. Use it only for a precise technical need, on the
smallest recordset, and never on values coming from the request without checking them:

```python
# good: the user may confirm the order; the sequence is technical
order.check_access('write')
order.name = self.env['ir.sequence'].sudo().next_by_code('sale.order')
```

Never write `sudo()` to make an access error go away in a test or a controller: fix the
`ir.access` rows instead.

## Multi-company

- `company_id = fields.Many2one('res.company', default=lambda self: self.env.company)`
- `_check_company_auto = True` and `check_company=True` on relational fields.
- One group-less `ir.access` row per model: `"[('company_id', 'in', company_ids)]"`
  (add `'|', ('company_id', '=', False),` when records can be shared).
