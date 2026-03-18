"""
Order management automation module.

Handles:
- Shipping notifications with tracking information
- Order status updates
- Delivery confirmation workflows
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from src.database.db_manager import DatabaseManager
from src.templates.message_templates import MessageCategory, MessageTemplateManager

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PAID = "paid"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Order:
    order_id: str
    buyer_id: str
    status: OrderStatus
    item_title: str
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    shipped_date: Optional[datetime] = None
    estimated_delivery: Optional[datetime] = None
    delivered_date: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class OrderProcessingResult:
    total: int = 0
    shipping_notifications_sent: int = 0
    status_updates_sent: int = 0
    delivery_confirmations_sent: int = 0
    errors: int = 0


class OrderManager:
    """
    Automates buyer communications throughout the order lifecycle.

    Sends:
    - Shipping confirmation with tracking link once an order is shipped
    - In-transit status updates for long-running deliveries
    - Delivery confirmation messages
    """

    def __init__(self, config: dict, db: DatabaseManager):
        self.config = config
        self.db = db
        self.template_manager = MessageTemplateManager(config)
        order_cfg = config.get("orders", {})
        self.notify_on_ship = order_cfg.get("notify_on_ship", True)
        self.notify_on_delivery = order_cfg.get("notify_on_delivery", True)
        self.transit_update_days = order_cfg.get("transit_update_days", 3)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_order_updates(self) -> OrderProcessingResult:
        """
        Process all pending order events and send appropriate notifications.

        Returns:
            OrderProcessingResult with per-event type counts.
        """
        result = OrderProcessingResult()
        orders = self.db.get_orders_needing_notification()
        result.total = len(orders)

        for order_data in orders:
            order = Order(**order_data)
            try:
                self._process_single_order(order, result)
            except Exception:
                logger.exception("Error processing order %s", order.order_id)
                result.errors += 1

        logger.info(
            "Order processing complete – total=%d shipped=%d "
            "in_transit=%d delivered=%d errors=%d",
            result.total,
            result.shipping_notifications_sent,
            result.status_updates_sent,
            result.delivery_confirmations_sent,
            result.errors,
        )
        return result

    def send_shipping_notification(self, order: Order) -> bool:
        """
        Compose and queue a shipping notification for *order*.

        Args:
            order: The order that has just been shipped.

        Returns:
            True if the notification was successfully queued.
        """
        if not order.tracking_number:
            logger.warning("Order %s has no tracking number", order.order_id)
            return False

        context = self._build_order_context(order)
        message = self.template_manager.render(MessageCategory.SHIPPING, context)
        if not message:
            return False

        self.db.queue_outgoing_message(
            buyer_id=order.buyer_id,
            subject=f"Your order has shipped! Tracking: {order.tracking_number}",
            body=message,
            order_id=order.order_id,
            event_type="shipping_notification",
        )
        self.db.mark_order_shipping_notified(order.order_id)
        return True

    def send_delivery_confirmation(self, order: Order) -> bool:
        """
        Send a delivery confirmation and thank-you message for *order*.

        Args:
            order: The order confirmed as delivered.

        Returns:
            True if the message was successfully queued.
        """
        context = self._build_order_context(order)
        message = self.template_manager.render(MessageCategory.ORDER_STATUS, context)
        if not message:
            return False

        self.db.queue_outgoing_message(
            buyer_id=order.buyer_id,
            subject="Your order has been delivered!",
            body=message,
            order_id=order.order_id,
            event_type="delivery_confirmation",
        )
        self.db.mark_order_delivery_notified(order.order_id)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_single_order(
        self, order: Order, result: OrderProcessingResult
    ) -> None:
        if order.status == OrderStatus.SHIPPED and self.notify_on_ship:
            if self.send_shipping_notification(order):
                result.shipping_notifications_sent += 1

        elif order.status == OrderStatus.IN_TRANSIT:
            if self._should_send_transit_update(order):
                if self._send_transit_update(order):
                    result.status_updates_sent += 1

        elif order.status == OrderStatus.DELIVERED and self.notify_on_delivery:
            if self.send_delivery_confirmation(order):
                result.delivery_confirmations_sent += 1

    def _should_send_transit_update(self, order: Order) -> bool:
        if not order.shipped_date:
            return False
        days_in_transit = (datetime.utcnow() - order.shipped_date).days
        return days_in_transit > 0 and days_in_transit % self.transit_update_days == 0

    def _send_transit_update(self, order: Order) -> bool:
        context = self._build_order_context(order)
        message = self.template_manager.render(MessageCategory.ORDER_STATUS, context)
        if not message:
            return False

        self.db.queue_outgoing_message(
            buyer_id=order.buyer_id,
            subject="Update on your order",
            body=message,
            order_id=order.order_id,
            event_type="transit_update",
        )
        return True

    @staticmethod
    def _build_order_context(order: Order) -> dict:
        tracking_url = ""
        if order.tracking_number and order.carrier:
            tracking_url = _build_tracking_url(order.carrier, order.tracking_number)

        estimated = ""
        if order.estimated_delivery:
            estimated = order.estimated_delivery.strftime("%B %d, %Y")

        return {
            "buyer_id": order.buyer_id,
            "order_id": order.order_id,
            "item_title": order.item_title,
            "tracking_number": order.tracking_number or "",
            "carrier": order.carrier or "",
            "tracking_url": tracking_url,
            "estimated_delivery": estimated,
        }


def _build_tracking_url(carrier: str, tracking_number: str) -> str:
    """Return a tracking URL for common carriers."""
    carrier_lower = carrier.lower()
    if "usps" in carrier_lower:
        return f"https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}"
    if "ups" in carrier_lower:
        return f"https://www.ups.com/track?tracknum={tracking_number}"
    if "fedex" in carrier_lower:
        return f"https://www.fedex.com/fedextrack/?trknbr={tracking_number}"
    return f"https://www.google.com/search?q={carrier}+tracking+{tracking_number}"
