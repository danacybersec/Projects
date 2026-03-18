"""
Tests for MessageTemplateManager.
"""

import pytest

from src.templates.message_templates import (
    MessageCategory,
    MessageTemplate,
    MessageTemplateManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def base_config():
    return {
        "store": {"id": "test_store", "name": "Test Store"},
        "templates": {},
    }


@pytest.fixture()
def manager(base_config):
    return MessageTemplateManager(base_config)


# ---------------------------------------------------------------------------
# get_template
# ---------------------------------------------------------------------------


def test_get_template_returns_default_for_each_category(manager):
    for category in MessageCategory:
        tmpl = manager.get_template(category)
        assert tmpl is not None, f"Missing template for {category}"
        assert isinstance(tmpl, MessageTemplate)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_shipping_template(manager):
    context = {
        "buyer_id": "testbuyer",
        "order_id": "ORD-123",
        "item_title": "Test Widget",
        "tracking_number": "TRACK001",
        "carrier": "USPS",
        "tracking_url": "https://example.com/track",
        "estimated_delivery": "March 25, 2026",
    }
    result = manager.render(MessageCategory.SHIPPING, context)
    assert result is not None
    assert "testbuyer" in result
    assert "TRACK001" in result
    assert "Test Store" in result


def test_render_injects_store_name_automatically(manager):
    result = manager.render(MessageCategory.GENERAL, {"buyer_id": "b1"})
    assert "Test Store" in result


def test_render_unknown_category_returns_none(manager):
    # Patch a fake category that has no template
    result = manager.render(None, {})
    assert result is None


def test_render_return_template(manager):
    context = {
        "buyer_id": "buyer1",
        "order_id": "ORD-456",
        "item_title": "Blue Shirt",
        "return_reason": "Wrong size",
        "refund_amount": "$29.99",
        "status": "requested",
    }
    result = manager.render(MessageCategory.RETURN, context)
    assert result is not None
    assert "buyer1" in result
    assert "Wrong size" in result


# ---------------------------------------------------------------------------
# Custom template loading
# ---------------------------------------------------------------------------


def test_custom_template_overrides_default():
    config = {
        "store": {"name": "Custom Store"},
        "templates": {
            "general": {
                "body": "Custom body for {{ buyer_id }} from {{ store_name }}"
            }
        },
    }
    mgr = MessageTemplateManager(config)
    result = mgr.render(MessageCategory.GENERAL, {"buyer_id": "buyer99"})
    assert "Custom body for buyer99" in result
    assert "Custom Store" in result


def test_unknown_category_in_config_is_ignored():
    config = {
        "store": {"name": "My Store"},
        "templates": {"nonexistent_category": {"body": "Should be ignored"}},
    }
    # Should not raise
    mgr = MessageTemplateManager(config)
    assert mgr.get_template(MessageCategory.GENERAL) is not None


# ---------------------------------------------------------------------------
# add_template
# ---------------------------------------------------------------------------


def test_add_template_replaces_existing(manager):
    new_tmpl = MessageTemplate(
        category=MessageCategory.GENERAL,
        name="custom_general",
        subject_template="Subject",
        body_template="Hello {{ buyer_id }}, this is the new template.",
    )
    manager.add_template(new_tmpl)
    result = manager.render(MessageCategory.GENERAL, {"buyer_id": "xyz"})
    assert "this is the new template" in result


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------


def test_list_templates_returns_all(manager):
    templates = manager.list_templates()
    categories = {t.category for t in templates}
    for category in MessageCategory:
        assert category in categories
