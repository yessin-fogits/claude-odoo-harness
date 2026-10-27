# Front end: OWL 2 (Odoo 18.0)

Odoo 18.0 ships OWL 2 (see `version-facts.md` for the exact version and exports).
Do not copy OWL 3 code from Odoo 20 (`useProps`, `signal`, `proxy`, plugins): it does not
exist here. Patterns below come from Odoo 18.0's own `web` module.

## A component

```javascript
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class DiscountSummary extends Component {
    static template = "sale_discount.DiscountSummary";
    static components = {};
    static props = {
        orderId: Number,
        title: { type: String, optional: true },
        onApply: { type: Function, optional: true },
    };

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
        this.props.onApply?.(this.state.lines);
        this.notification.add(_t("Discount applied"), { type: "success" });
    }
}
```

- Props are declared with `static props` (`String`, `Number`, `Boolean`, `Object`,
  `Array`, `Function`, or `{ type, optional }`), validated in debug mode.
- `useState(obj)`: a reactive object; mutate its properties directly.
- Lifecycle: `onWillStart`, `onMounted`, `onWillUpdateProps`, `onWillPatch`, `onPatched`,
  `onWillUnmount`, `onWillDestroy`, `onError`. DOM listeners: `useExternalListener`.
- Element references: `this.inputRef = useRef("input")` with `t-ref="input"` in the template.
- Services: `useService("orm")`, `useService("notification")`, `useService("dialog")`
  from `@web/core/utils/hooks`.

## Its template

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="sale_discount.DiscountSummary">
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

- Template expressions see the component: `props.title`, `state.lines`, `isEmpty`
  (writing `this.` in front also works).
- Prefer `t-out` (escapes unless the value is `markup`); `t-esc` still works.
- Event handlers: `t-on-click="onApply"` or `t-on-click="() => this.onApply(arg)"`.

## Field widget

```javascript
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

export class DiscountBadgeField extends Component {
    static template = "sale_discount.DiscountBadgeField";
    static props = { ...standardFieldProps };

    get value() {
        return this.props.record.data[this.props.name];
    }
}

registry.category("fields").add("discount_badge", {
    component: DiscountBadgeField,
    displayName: _t("Discount Badge"),
    supportedTypes: ["float"],
});
```

Use it in a view: `<field name="rate" widget="discount_badge"/>`.

## Calling the server

- Model methods: `this.orm.call(model, method, args, kwargs)`, `this.orm.searchRead(...)`.
- Custom routes: `import { rpc } from "@web/core/network/rpc";` then `await rpc("/route", params)`.

## Assets

Declare files in the manifest; globs are allowed:

```python
'assets': {
    'web.assets_backend': [
        'sale_discount/static/src/**/*',
    ],
},
```

JS tests (`static/tests/`) go in `web.assets_unit_tests`.
