"""
Tests for OrderManager.
"""

from datetime import datetime, timedelta

import pytest

from src.automation.order_manager import Order, OrderManager, OrderStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def base_config():
    return {
        "store": {"id": "test_store", "name": "Test Store"},
        "orders": {
            "notify_on_ship": True,
            "notify_on_delivery": True,
            "transit_update_days": 3,
        },
        "templates": {},
    }


@pytest.fixture()
def mock_db(mocker):
    db = mocker.MagicMock()
    db.get_orders_needing_notification.return_value = []
    return db


@pytest.fixture()
def manager(base_config, mock_db):
    return OrderManager(base_config, mock_db)


def _make_order(**kwargs):
    defaults = dict(
        order_id="ORD-001",
        buyer_id="buyer1",
        status=OrderStatus.SHIPPED,
        item_title="Test Item",
        tracking_number="9400111899223481712345",
        carrier="USPS",
        shipped_date=datetime.utcnow() - timedelta(days=1),
        estimated_delivery=datetime.utcnow() + timedelta(days=3),
    )
    defaults.update(kwargs)
    return Order(**defaults)


# ---------------------------------------------------------------------------
# send_shipping_notification
# ---------------------------------------------------------------------------


def test_send_shipping_notification_queues_message(manager, mock_db):
    order = _make_order()
    result = manager.send_shipping_notification(order)
    assert result is True
    mock_db.queue_outgoing_message.assert_called_once()
    call_kwargs = mock_db.queue_outgoing_message.call_args.kwargs
    assert call_kwargs["event_type"] == "shipping_notification"
    assert "9400111899223481712345" in call_kwargs["subject"]


def test_send_shipping_notification_fails_without_tracking(manager, mock_db):
    order = _make_order(tracking_number=None)
    result = manager.send_shipping_notification(order)
    assert result is False
    mock_db.queue_outgoing_message.assert_not_called()


# ---------------------------------------------------------------------------
# send_delivery_confirmation
# ---------------------------------------------------------------------------


def test_send_delivery_confirmation_queues_message(manager, mock_db):
    order = _make_order(status=OrderStatus.DELIVERED)
    result = manager.send_delivery_confirmation(order)
    assert result is True
    mock_db.queue_outgoing_message.assert_called_once()
    call_kwargs = mock_db.queue_outgoing_message.call_args.kwargs
    assert call_kwargs["event_type"] == "delivery_confirmation"


# ---------------------------------------------------------------------------
# process_order_updates
# ---------------------------------------------------------------------------


def test_process_order_updates_empty(manager, mock_db):
    result = manager.process_order_updates()
    assert result.total == 0


def test_process_order_updates_sends_shipping_notification(manager, mock_db):
    mock_db.get_orders_needing_notification.return_value = [
        {
            "order_id": "ORD-002",
            "buyer_id": "buyer2",
            "status": "shipped",
            "item_title": "Widget",
            "tracking_number": "TRACK123",
            "carrier": "UPS",
            "shipped_date": datetime.utcnow() - timedelta(hours=2),
            "estimated_delivery": datetime.utcnow() + timedelta(days=4),
            "delivered_date": None,
            "metadata": {},
        }
    ]
    result = manager.process_order_updates()
    assert result.shipping_notifications_sent == 1
    assert result.errors == 0


# ---------------------------------------------------------------------------
# Tracking URL builder
# ---------------------------------------------------------------------------


def test_usps_tracking_url():
    from src.automation.order_manager import _build_tracking_url

    url = _build_tracking_url("USPS", "9400111")
    assert url.startswith("https://tools.usps.com/")
    assert "9400111" in url


def test_ups_tracking_url():
    from src.automation.order_manager import _build_tracking_url

    url = _build_tracking_url("UPS", "1Z999")
    assert url.startswith("https://www.ups.com/")


def test_fedex_tracking_url():
    from src.automation.order_manager import _build_tracking_url

    url = _build_tracking_url("FedEx", "123456")
    assert url.startswith("https://www.fedex.com/")


def test_unknown_carrier_tracking_url():
    from src.automation.order_manager import _build_tracking_url

    url = _build_tracking_url("DHL", "TRACK999")
    assert "TRACK999" in url
