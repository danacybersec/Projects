"""
Message management module.

Handles:
- Categorising incoming eBay buyer messages
- Selecting and rendering the appropriate response template
- Recording interactions in the database
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.database.db_manager import DatabaseManager
from src.templates.message_templates import MessageCategory, MessageTemplateManager

logger = logging.getLogger(__name__)


class MessageStatus(str, Enum):
    PENDING = "pending"
    RESPONDED = "responded"
    ESCALATED = "escalated"
    IGNORED = "ignored"


@dataclass
class IncomingMessage:
    message_id: str
    buyer_id: str
    subject: str
    body: str
    order_id: Optional[str] = None
    status: MessageStatus = MessageStatus.PENDING
    metadata: dict = field(default_factory=dict)


@dataclass
class MessageProcessingResult:
    total: int = 0
    responded: int = 0
    escalated: int = 0
    skipped: int = 0
    errors: int = 0


class MessageManager:
    """
    Automates responses to common buyer enquiries.

    Categorises each message, selects the best matching template, renders
    a personalised response, and records the interaction.
    """

    # Keywords mapped to message categories for simple rule-based routing
    _CATEGORY_KEYWORDS: dict[MessageCategory, list[str]] = {
        MessageCategory.SHIPPING: [
            "shipping", "ship", "delivery", "tracking", "arrive", "arrival",
            "dispatch", "carrier", "usps", "fedex", "ups",
        ],
        MessageCategory.RETURN: [
            "return", "refund", "money back", "send back", "returned",
            "cancel", "cancellation",
        ],
        MessageCategory.PRODUCT_INFO: [
            "spec", "specification", "dimension", "size", "weight", "color",
            "colour", "compatible", "fit", "material", "description",
        ],
        MessageCategory.ORDER_STATUS: [
            "order", "status", "update", "when", "yet", "still",
        ],
        MessageCategory.FEEDBACK: [
            "feedback", "review", "rating", "stars", "comment",
        ],
    }

    def __init__(self, config: dict, db: DatabaseManager):
        self.config = config
        self.db = db
        self.template_manager = MessageTemplateManager(config)
        self.auto_respond = config.get("messaging", {}).get("auto_respond", True)
        self.max_auto_responses = config.get("messaging", {}).get(
            "max_auto_responses_per_run", 50
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_incoming_messages(self) -> MessageProcessingResult:
        """
        Fetch unread messages from the DB queue and respond to eligible ones.

        Returns:
            MessageProcessingResult with counts per outcome.
        """
        result = MessageProcessingResult()
        messages = self.db.get_pending_messages(limit=self.max_auto_responses)
        result.total = len(messages)

        for msg_data in messages:
            msg = IncomingMessage(**msg_data)
            try:
                outcome = self._handle_message(msg)
                if outcome == MessageStatus.RESPONDED:
                    result.responded += 1
                elif outcome == MessageStatus.ESCALATED:
                    result.escalated += 1
                else:
                    result.skipped += 1
            except Exception:
                logger.exception("Error handling message %s", msg.message_id)
                result.errors += 1

        logger.info(
            "Message processing complete – total=%d responded=%d "
            "escalated=%d skipped=%d errors=%d",
            result.total,
            result.responded,
            result.escalated,
            result.skipped,
            result.errors,
        )
        return result

    def categorise_message(self, message: IncomingMessage) -> MessageCategory:
        """
        Determine the category of a message using keyword matching.

        Args:
            message: The incoming message to categorise.

        Returns:
            The best matching MessageCategory, or GENERAL if none match.
        """
        text = f"{message.subject} {message.body}".lower()
        scores: dict[MessageCategory, int] = {}
        for category, keywords in self._CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score:
                scores[category] = score

        if not scores:
            return MessageCategory.GENERAL

        return max(scores, key=lambda c: scores[c])

    def compose_response(
        self, message: IncomingMessage, category: MessageCategory
    ) -> Optional[str]:
        """
        Render a response for *message* using the template for *category*.

        Args:
            message: The original buyer message.
            category: Pre-determined category.

        Returns:
            Rendered response string, or None if no template is available.
        """
        context = {
            "buyer_id": message.buyer_id,
            "order_id": message.order_id or "",
            "store_name": self.config.get("store", {}).get("name", "our store"),
            # Optional order fields – empty strings so templates using {% if %} guards work
            "item_title": "",
            "tracking_number": "",
            "carrier": "",
            "tracking_url": "",
            "estimated_delivery": "",
        }
        return self.template_manager.render(category, context)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_message(self, message: IncomingMessage) -> MessageStatus:
        """Route a single message and record the outcome."""
        category = self.categorise_message(message)

        if not self.auto_respond:
            self.db.update_message_status(message.message_id, MessageStatus.ESCALATED)
            return MessageStatus.ESCALATED

        response = self.compose_response(message, category)
        if not response:
            logger.warning(
                "No template found for category %s on message %s",
                category,
                message.message_id,
            )
            self.db.update_message_status(message.message_id, MessageStatus.ESCALATED)
            return MessageStatus.ESCALATED

        self.db.save_message_response(
            message_id=message.message_id,
            response=response,
            category=category.value,
        )
        self.db.update_message_status(message.message_id, MessageStatus.RESPONDED)
        logger.debug(
            "Responded to message %s (category=%s)", message.message_id, category.value
        )
        return MessageStatus.RESPONDED
