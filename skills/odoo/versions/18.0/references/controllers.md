# Controllers and HTTP routes (Odoo 18.0)

Route types in 18.0: `http`, `json` (see `version-facts.md`).

## Routes

```python
from odoo import http
from odoo.http import request


class DiscountController(http.Controller):

    @http.route('/sale_discount/rates', type='json', auth='user', readonly=True)
    def rates(self, order_id):
        order = request.env['sale.order'].browse(order_id)
        order.check_access('read')
        return [{'id': line.id, 'rate': line.discount} for line in order.order_line]

    @http.route('/my/discounts', type='http', auth='user', website=True)
    def portal_discounts(self, **kw):
        discounts = request.env['sale.discount'].search([])
        return request.render('sale_discount.portal_my_discounts', {'discounts': discounts})

    @http.route('/sale_discount/hook', type='http', auth='public', methods=['POST'], csrf=False)
    def hook(self, **payload):
        ...
```

- `type='json'`: JSON-RPC 2.0 body, called from the web client (`rpc("/route", params)`).
- `type='http'`: form posts and pages; POST requests need a CSRF token unless `csrf=False`
  (only for machine-to-machine endpoints, with their own authentication).
- `auth='user'` (logged in), `auth='public'` (public user if not logged in), `auth='none'`
  (no environment user, rare), `auth='bearer'` (API key in `Authorization: Bearer ...`).
- `readonly=True` lets the route run on a read-only database replica cursor; only for
  routes that do not write.
- `request.env` is the environment (`request.env.cr`, `request.env.uid`,
  `request.env.context`); `request.params`, `request.httprequest` for the raw request.
- Routes run with the user's rights. Do not `sudo()` user-provided ids; check access with
  `check_access` instead.

## External API (integrations)

`/xmlrpc/2/object` (XML-RPC) and `/jsonrpc` (JSON-RPC, service `object`) expose
`execute_kw(db, uid, password_or_api_key, model, method, args, kwargs)` for every public
model method. Methods whose name starts with `_` or decorated with `@api.private` are not
callable. Prefer this API over custom controllers for integrations that only read or
write records.

## Calling from JavaScript

```javascript
import { rpc } from "@web/core/network/rpc";

const rates = await rpc("/sale_discount/rates", { order_id: orderId });
```

For model methods, use the `orm` service (`this.orm.call(model, method, args, kwargs)`),
not a custom route.
