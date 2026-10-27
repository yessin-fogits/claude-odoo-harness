# Tests (Odoo 18.0)

The harness validation hierarchy:
level 1 unit and level 2 integration tests run inside Odoo (`odoo-bin --test-tags`);
level 3 e2e tests run Playwright against the running server (`e2e/`). A feature is done
only when its e2e test passes (`harness/feature.py verify`).

## Odoo tests

`<module>/tests/__init__.py` imports every test file; each file:

```python
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command
from odoo.tests import Form, TransactionCase, new_test_user, tagged, users


@tagged('post_install', '-at_install')
class TestSaleDiscount(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Do not rely on demo data (the harness test DB may not have it): create it.
        cls.partner = cls.env['res.partner'].create({'name': "Customer"})
        cls.salesman = new_test_user(cls.env, login='salesman',
                                     groups='sales_team.group_sale_salesman')
        cls.discount = cls.env['sale.discount'].create({
            'name': "Spring", 'rate': 10, 'partner_id': cls.partner.id,
            'line_ids': [Command.create({'amount': 5})],
        })

    def test_total_is_computed(self):
        self.assertEqual(self.discount.total, 5)

    def test_rate_cannot_exceed_100(self):
        with self.assertRaises(ValidationError):
            self.discount.rate = 150

    @users('salesman')
    def test_salesman_cannot_delete(self):
        discount = self.discount.with_user(self.env.user)
        with self.assertRaises(AccessError):
            discount.unlink()

    def test_form_onchange(self):
        with Form(self.env['sale.discount']) as form:
            form.name = "Summer"
            form.partner_id = self.partner
            form.rate = 5
        self.assertEqual(form.record.partner_id, self.partner)
```

- `TransactionCase`: each test is rolled back (prefer it to `SingleTransactionCase`).
- `@tagged('post_install', '-at_install')` runs after all modules are installed (needed when
  the test depends on other modules' data); default is at install.
- `@users('login')` runs the test as that user; `new_test_user(env, login, groups)` creates
  one. `Form` simulates the form view (onchanges, required fields, `invisible` rules).
- `freeze_time` (`from odoo.tests import freeze_time`) for date-dependent logic.
- Unit vs integration in this harness: unit tests target one model's logic; integration
  tests cross models/modules or the install/upgrade itself. Tag them
  (`@tagged('post_install', '-at_install', 'integration')`) so features can verify with
  `integration: /sale_discount:TestDiscountFlow` or `/sale_discount/integration`.

Run (the harness does it): `odoo -d <test_db> -u sale_discount --test-tags /sale_discount:TestSaleDiscount --stop-after-init`.
Tag spec: `[-][tag][/module][:Class][.method]`, comma-separated.

## Playwright e2e tests (harness level 3)

One file per feature: `e2e/test_<feature id>_<topic>.py`. The `odoo_page` fixture
(`e2e/conftest.py`) is a page logged in to the test DB.

```python
import re

from playwright.sync_api import expect


def test_salesman_applies_discount(odoo_page, unique):
    page = odoo_page
    name = f"Spring {unique}"
    page.goto("/odoo/discounts")                     # the action's `path`
    page.get_by_role("button", name="New").click()
    page.get_by_label("Name").fill(name)
    page.get_by_label("Rate").fill("10")
    page.locator(".o_form_button_save").click()
    expect(page.locator(".o_breadcrumb")).to_contain_text(name)

    page.goto("/odoo/discounts")
    row = page.locator(".o_data_row", has_text=name)
    expect(row).to_be_visible()
    expect(row).to_contain_text(re.compile(r"10[.,]00"))
```

- Prefer user-facing locators (`get_by_role`, `get_by_label`, `get_by_text`) and a few stable
  classes: `.o_main_navbar`, `.o_data_row`, `.o_form_button_save`, `.o_notification`.
- Assert with `expect(...)` (it waits); never `time.sleep`.
- The test DB persists between runs: give the records a test creates unique names (the
  `unique` fixture) and never assume a list starts empty.
- Create the data the test needs through the UI or in a fixture; do not rely on demo data.
- A failure keeps a trace (`.harness/runs/<run>/e2e/`): open it with
  `playwright show-trace <trace.zip>` to see each step.
