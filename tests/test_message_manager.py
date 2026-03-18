"""
Tests for MessageManager.
"""

import pytest

from src.automation.message_manager import (
    IncomingMessage,
    MessageManager,
    MessageStatus,
)
from src.templates.message_templates import MessageCategory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def base_config():
    return {
        "store": {"id": "test_store", "name": "Test Store"},
        "messaging": {"auto_respond": True, "max_auto_responses_per_run": 50},
        "templates": {},
    }


@pytest.fixture()
def mock_db(mocker):
    db = mocker.MagicMock()
    db.get_pending_messages.return_value = []
    return db


@pytest.fixture()
def manager(base_config, mock_db):
    return MessageManager(base_config, mock_db)


# ---------------------------------------------------------------------------
# categorise_message
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject,body,expected_category",
    [
        ("Shipping question", "When will my order arrive?", MessageCategory.SHIPPING),
        ("Tracking info", "I need my tracking number please", MessageCategory.SHIPPING),
        ("Return request", "I want to return this item", MessageCategory.RETURN),
        ("Refund please", "I need a refund for my order", MessageCategory.RETURN),
        (
            "Product question",
            "What are the dimensions and weight?",
            MessageCategory.PRODUCT_INFO,
        ),
        ("Order update", "What is the status of my order?", MessageCategory.ORDER_STATUS),
        ("Feedback", "I want to leave a review", MessageCategory.FEEDBACK),
        ("Hello", "Just a general message", MessageCategory.GENERAL),
    ],
)
def test_categorise_message(manager, subject, body, expected_category):
    msg = IncomingMessage(
        message_id="msg1",
        buyer_id="buyer1",
        subject=subject,
        body=body,
    )
    assert manager.categorise_message(msg) == expected_category


def test_categorise_message_prefers_highest_score(manager):
    """If multiple categories match, the one with the most keywords wins."""
    msg = IncomingMessage(
        message_id="msg2",
        buyer_id="buyer2",
        subject="Shipping shipping shipping",
        body="Return",  # one keyword vs. three above
    )
    category = manager.categorise_message(msg)
    assert category == MessageCategory.SHIPPING


# ---------------------------------------------------------------------------
# compose_response
# ---------------------------------------------------------------------------


def test_compose_response_returns_string(manager):
    msg = IncomingMessage(
        message_id="msg3",
        buyer_id="buyer3",
        subject="Shipping question",
        body="When does it arrive?",
        order_id="ORD-001",
    )
    response = manager.compose_response(msg, MessageCategory.SHIPPING)
    assert response is not None
    assert "buyer3" in response


def test_compose_response_includes_store_name(manager):
    msg = IncomingMessage(
        message_id="msg4",
        buyer_id="buyer4",
        subject="Help",
        body="Question",
    )
    response = manager.compose_response(msg, MessageCategory.GENERAL)
    assert "Test Store" in response


# ---------------------------------------------------------------------------
# process_incoming_messages
# ---------------------------------------------------------------------------


def test_process_messages_empty(manager, mock_db):
    result = manager.process_incoming_messages()
    assert result.total == 0
    assert result.responded == 0


def test_process_messages_responds_to_pending(manager, mock_db):
    mock_db.get_pending_messages.return_value = [
        {
            "message_id": "m1",
            "buyer_id": "buyer1",
            "subject": "Shipping query",
            "body": "When will my item ship?",
            "order_id": "ORD-100",
            "status": "pending",
            "metadata": {},
        }
    ]
    result = manager.process_incoming_messages()
    assert result.total == 1
    assert result.responded == 1
    mock_db.save_message_response.assert_called_once()
    mock_db.update_message_status.assert_called()


def test_process_messages_escalates_when_auto_respond_off(mock_db, base_config):
    base_config["messaging"]["auto_respond"] = False
    mgr = MessageManager(base_config, mock_db)
    mock_db.get_pending_messages.return_value = [
        {
            "message_id": "m2",
            "buyer_id": "buyer2",
            "subject": "Question",
            "body": "Hello",
            "order_id": None,
            "status": "pending",
            "metadata": {},
        }
    ]
    result = mgr.process_incoming_messages()
    assert result.escalated == 1
    assert result.responded == 0
