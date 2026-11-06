# Front end: OWL 2 (Odoo 16.0)

Odoo 16.0 ships OWL 2 (see `version-facts.md` for the exact version and exports): the
form, list and kanban views were rewritten in OWL in this version. Do not copy OWL 1 code
from 15.0 (`owl.Component`, `owl.hooks`, `web.AbstractField`, `field_registry`) nor
OWL 3 code from Odoo 20 (`useProps`, `signal`, `proxy`). Patterns below come from
Odoo 16.0's own `web` module, which writes static members as assignments after the class.

## Every JS file starts with `@odoo-module`

```javascript
/** @odoo-module **/
```

Odoo 16.0 transpiles a file to an Odoo module only when this comment is at its top;
without it, `import`/`export` reach the browser untranspiled and the whole asset bundle
fails to load.

## A component

```javascript
/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class DiscountSummary extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ lines: [], loading: true });
        onWillStart(async () => {
            this.state.lines = await this.orm.searchRead(
                "sale.order.line", [["order_id", "=", this.props.orderId]], ["name", "discount"],
            );
            this.state.loading = false;
        });
    }

    get isEmpty() {
        return this.state.lines.length === 0;
    }

    onApply() {
        if (this.props.onApply) {
            this.props.onApply(this.state.lines);
        }
        this.notification.add(_t("Discount applied"), { type: "success" });
    }
}

DiscountSummary.template = "sale_discount.DiscountSummary";
DiscountSummary.components = {};
DiscountSummary.props = {
    orderId: Number,
    title: { type: String, optional: true },
    onApply: { type: Function, optional: true },
};
```

- Props are declared in `props` (`String`, `Number`, `Boolean`, `Object`, `Array`,
  `Function`, or `{ type, optional }`), validated in debug mode.
- `useState(obj)`: a reactive object; mutate its properties directly.
- Lifecycle: `onWillStart`, `onMounted`, `onWillUpdateProps`, `onWillPatch`, `onPatched`,
  `onWillUnmount`, `onWillDestroy`, `onError`. DOM listeners: `useExternalListener`.
- Element references: `this.inputRef = useRef("input")` with `t-ref="input"` in the template.
- Services: `useService("orm")`, `useService("notification")`, `useService("dialog")`
  from `@web/core/utils/hooks`.
- Translations: `_t("...")` inside methods; strings evaluated when the file loads
  (`displayName`, constants) use `_lt("...")`, the lazy version, from the same module.

## Its template

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="sale_discount.DiscountSummary" owl="1">
        <div class="o_discount_summary">
            <h3 t-if="props.title" t-out="props.title"/>
            <span t-if="isEmpty">No discount</span>
            <ul t-else="">
                <li t-foreach="state.lines" t-as="line" t-key="line.id">
                    <t t-out="line.name"/>: <t t-out="line.discount"/>%
                </li>
            </ul>
            <button class="btn btn-primary" t-on-click="onApply">Apply</button>
        </div>
    </t>
</templates>
```

- `owl="1"` on the template marks it as an OWL template (16.0 core sets it on each one).
- Template expressions see the component: `props.title`, `state.lines`, `isEmpty`
  (writing `this.` in front also works).
- Prefer `t-out` (escapes unless the value is `markup`); `t-esc` still works.
- Event handlers: `t-on-click="onApply"` or `t-on-click="() => this.onApply(arg)"`.

## Field widget

```javascript
/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _lt } from "@web/core/l10n/translation";

export class DiscountBadgeField extends Component {
    get value() {
        return this.props.value;
    }

    onReset() {
        this.props.update(0);
    }
}

DiscountBadgeField.template = "sale_discount.DiscountBadgeField";
DiscountBadgeField.props = { ...standardFieldProps };
DiscountBadgeField.displayName = _lt("Discount Badge");
DiscountBadgeField.supportedTypes = ["float"];

registry.category("fields").add("discount_badge", DiscountBadgeField);
```

- The `fields` registry takes the component class itself; `supportedTypes`, `displayName`
  and `extractProps` are static members of the class. (A `{ component: ... }` object is 17.0.)
- The field's value is `this.props.value`; change it with `this.props.update(value)`.
  `this.props.record` and `this.props.name` are there for the rest of the record.

Use it in a view: `<field name="rate" widget="discount_badge"/>`.

## Calling the server

- Model methods: `this.orm.call(model, method, args, kwargs)`, `this.orm.searchRead(...)`.
- Custom routes: `this.rpc = useService("rpc")` in `setup()`, then `await this.rpc("/route", params)`.

## Assets

Declare files in the manifest; globs are allowed. OWL templates go in the same bundle as
their JS (there is no `web.assets_qweb` in 16.0):

```python
'assets': {
    'web.assets_backend': [
        'sale_discount/static/src/**/*',
    ],
},
```

JS (QUnit) tests (`static/tests/`) go in `web.qunit_suite_tests`.
