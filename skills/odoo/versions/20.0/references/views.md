# Views, actions, menus, QWeb (Odoo 20.0)

Patterns below are taken from Odoo 20.0's own `sale` module. View architectures are
validated by the RNG schemas listed in `version-facts.md`.

## List

```xml
<record id="sale_discount_view_list" model="ir.ui.view">
    <field name="name">sale.discount.list</field>
    <field name="model">sale.discount</field>
    <field name="arch" type="xml">
        <list multi_edit="1" decoration-muted="state == 'done'">
            <field name="sequence" widget="handle"/>
            <field name="name"/>
            <field name="partner_id" widget="many2one_avatar" optional="show"/>
            <field name="rate" optional="show" readonly="state == 'done'"/>
            <field name="amount" widget="monetary" sum="Total"/>
            <field name="currency_id" column_invisible="True"/>
            <field name="company_id" groups="base.group_multi_company" optional="hide"/>
            <field name="state" widget="badge" decoration-success="state == 'done'"/>
        </list>
    </field>
</record>
```

## Form

```xml
<record id="sale_discount_view_form" model="ir.ui.view">
    <field name="name">sale.discount.form</field>
    <field name="model">sale.discount</field>
    <field name="arch" type="xml">
        <form>
            <header>
                <button name="action_done" type="object" string="Validate" class="btn-primary"
                        invisible="state != 'draft'"/>
                <field name="state" widget="statusbar" statusbar_visible="draft,done"/>
            </header>
            <sheet>
                <div class="oe_title">
                    <h1><field name="name" placeholder="Discount name"/></h1>
                </div>
                <group>
                    <group>
                        <field name="partner_id"/>
                        <field name="rate" readonly="state == 'done'" required="state == 'draft'"/>
                    </group>
                    <group>
                        <field name="company_id" groups="base.group_multi_company"/>
                        <field name="tag_ids" widget="many2many_tags"/>
                    </group>
                </group>
                <notebook>
                    <page string="Lines" name="lines">
                        <field name="line_ids">
                            <list editable="bottom">
                                <field name="product_id"/>
                                <field name="amount"/>
                            </list>
                        </field>
                    </page>
                </notebook>
            </sheet>
            <chatter/>
        </form>
    </field>
</record>
```

- `invisible`, `readonly`, `required`, `column_invisible` take Python-like expressions
  over the record's fields (`state != 'draft'`, `not partner_id`). There is no `attrs` and no
  `states` attribute.
- `<chatter/>` needs the model to inherit `mail.thread` (and `mail` in `depends`).
- Buttons: `type="object"` calls a public model method; `type="action"` opens
  `%(module.action_xmlid)d`.

## Search

```xml
<search string="Search Discounts">
    <field name="name" filter_domain="['|', ('name', 'ilike', self), ('code', 'ilike', self)]"/>
    <field name="partner_id" operator="child_of"/>
    <filter name="my_discounts" string="My Discounts" domain="[('create_uid', '=', uid)]"/>
    <filter name="archived" string="Archived" domain="[('active', '=', False)]"/>
    <separator/>
    <filter name="create_date" string="Creation Date" date="create_date"/>
    <group>
        <filter name="by_partner" string="Customer" context="{'group_by': 'partner_id'}"/>
    </group>
</search>
```

Date filters are only `<filter name="..." date="field"/>`: Odoo 20.0 rejects the old
`start_month`/`end_month`/`start_year`/`end_year` attributes.

## Kanban

```xml
<kanban class="o_kanban_mobile" sample="1" quick_create="false">
    <field name="state"/>
    <templates>
        <t t-name="card">
            <field name="name" class="fw-bold"/>
            <field name="partner_id"/>
            <footer>
                <field name="amount" widget="monetary"/>
                <field name="state" widget="label_selection"/>
            </footer>
        </t>
    </templates>
</kanban>
```

## Action and menu

```xml
<record id="sale_discount_action" model="ir.actions.act_window">
    <field name="name">Discounts</field>
    <field name="res_model">sale.discount</field>
    <field name="path">discounts</field>
    <field name="view_mode">list,kanban,form</field>
    <field name="context">{'search_default_my_discounts': 1}</field>
    <field name="help" type="html">
        <p class="o_view_nocontent_smiling_face">Create your first discount</p>
    </field>
</record>

<menuitem id="sale_discount_menu" name="Discounts" parent="sale.sale_order_menu"
          action="sale_discount_action" sequence="40"/>
```

`path` gives the action a readable URL (`/odoo/discounts`).

## Inheritance

```xml
<record id="view_order_form_inherit_discount" model="ir.ui.view">
    <field name="name">sale.order.form.inherit.discount</field>
    <field name="model">sale.order</field>
    <field name="inherit_id" ref="sale.view_order_form"/>
    <field name="arch" type="xml">
        <field name="payment_term_id" position="after">
            <field name="discount_id"/>
        </field>
        <xpath expr="//list/field[@name='price_unit']" position="after">
            <field name="discount_rate" optional="show"/>
        </xpath>
    </field>
</record>
```

Read the parent view of this exact version before writing an xpath: an expression that
matches nothing fails the module install.

## QWeb (reports, website, email templates)

- Output with `t-out` (escapes unless the value is `Markup`).
- Parameters of `t-call` are attributes of the `t-call` node:

```xml
<t t-call="sale_discount.discount_badge" discount="doc.discount_id" label.f="Discount {{ doc.name }}"
   title.translate="Applied discount"/>
```

`name="expr"` passes an expression, `name.f="..."` a format string,
`name.translate="..."` a translatable literal.

- Icons are Material Symbols: `<i class="oi" data-icon="person"/>` (not `fa fa-*`).
- Binary files in XML data: `<field name="datas" type="bytes" file="module/static/img/x.png"/>`.
