"""Shared Playwright fixtures for the Odoo web client.

The e2e container runs pytest with --base-url http://odoo:8069 against the test DB.
Changing this file is a shared change: the full e2e suite runs on the next verify.
"""

import os

import pytest
from playwright.sync_api import Page, expect

DB = os.environ.get("ODOO_DB", "harness_test")
LOGIN = os.environ.get("ODOO_LOGIN", "admin")
PASSWORD = os.environ.get("ODOO_PASSWORD", "admin")


@pytest.fixture
def odoo_page(page: Page) -> Page:
    """A page logged in to the Odoo web client on the test DB."""
    page.goto(f"/web/login?db={DB}")
    page.fill("input[name=login]", LOGIN)
    page.fill("input[name=password]", PASSWORD)
    # Enter submits the login form; newer versions have several submit buttons on the page.
    page.press("input[name=password]", "Enter")
    expect(page.locator(".o_main_navbar")).to_be_visible()
    return page
