# Front end: OWL 3 (Odoo 20.0)

Odoo 20.0 ships OWL 3 (see `version-facts.md` for the exact version and exports).
OWL 2 code from older Odoo versions does not run as is: `useState`, `useRef`,
`reactive`, `useEnv`, `useComponent`, `onWillRender`... are not exported by `@odoo/owl`.
Patterns below come from Odoo 20.0's own `web` module.

## A component

```javascript
import { Component, onWillStart, proxy, signal, computed, t, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class DiscountSummary extends Component {
    static template = "sale_discount.DiscountSummary";
    static components = {};

    props = useProps({
        orderId: t.number(),
        title: t.string().optional(),
        onApply: t.function().optional(),
    });

    count = signal(0);                       // read: this.count()  write: this.count.set(n)
    isEmpty = computed(() => this.count() === 0);
    state = proxy({ lines: [], loading: true });   // reactive object (was useState)

    setup() {
        this.orm = useService("orm");
        onWillStart(async () => {
            this.state.lines = await this.orm.searchRead(
                "sale.order.line", [["order_id", "=", this.props.orderId]], ["name", "discount"],
            );
            this.count.set(this.state.lines.length);
            this.state.loading = false;
        });
    }

    onApply() {
        this.props.onApply?.(this.state.lines);
    }
}
```

- Props are declared with `props = useProps({...})` and the type helpers `t.string()`,
  `t.number()`, `t.boolean()`, `t.object()`, `t.array(...)`, `t.function()`, `t.any()`,
  `.optional(default)`. There is no `static props`.
- `signal(value)`: call it to read, `.set()` to write. `computed(fn)` derives from signals.
- `proxy(obj)`: a reactive object; mutate its properties directly.
- Lifecycle hooks still exported: `onWillStart`, `onMounted`, `onWillUpdateProps`,
  `onWillPatch`, `onPatched`, `onWillUnmount`, `onWillDestroy`, `onError`.
- DOM listeners: `useListener(target, "event", handler)`.
- Element references: `signal.ref()` in the component.
- Removed OWL 2 hooks that some code still needs (`useEnv`, `useSubEnv`, `useLayoutEffect`,
  `onWillRender`, `useComponent`) are in the compatibility module `@web/owl2/utils`.
  Do not use it in new code unless there is no OWL 3 way.

## Its template

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="sale_discount.DiscountSummary">
        <div class="o_discount_summary">
            <h3 t-if="this.props.title" t-out="this.props.title"/>
            <span t-if="this.isEmpty()">No discount</span>
            <ul t-else="">
                <li t-foreach="this.state.lines" t-as="line" t-key="line.id">
                    <t t-out="line.name"/>: <t t-out="line.discount"/>%
                </li>
            </ul>
            <button class="btn btn-primary" t-on-click="() => this.onApply()">Apply</button>
        </div>
    </t>
</templates>
```

- Component members are read through `this.` in templates (`this.props.title`,
  `this.state.lines`); loop variables (`line`) are not.
- Output with `t-out`. Event handlers: `t-on-click="this.onApply"` or
  `t-on-click="() => this.onApply(arg)"`.

## Field widget

```javascript
import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

export class DiscountBadgeField extends Component {
    static template = "sale_discount.DiscountBadgeField";
    props = useProps({ ...standardFieldProps });

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

## Services and plugins

- `useService("orm")` and `useService("dialog")` (from `@web/core/utils/hooks`) still work;
  `this.orm.searchRead(model, domain, fields)`, `this.orm.call(model, method, args)`.
- Some services are now plugins: `this.notification = usePlugin(NotificationPlugin)` with
  `import { NotificationPlugin } from "@web/core/notifications/notification_plugin"`, then
  `this.notification.add(message, { type: "warning" })`.

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
