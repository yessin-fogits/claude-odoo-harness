"""Baseline e2e test: the web client loads for a logged-in user."""

from playwright.sync_api import expect


def test_web_client_loads(odoo_page):
    expect(odoo_page.locator(".o_main_navbar")).to_be_visible()
