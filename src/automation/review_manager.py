"""
Review and feedback automation module.

Handles:
- Automated review requests sent after confirmed delivery
- Monitoring feedback received and generating response drafts
- Alerting on negative reviews
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from src.database.db_manager import DatabaseManager
from src.templates.message_templates import MessageCategory, MessageTemplateManager

logger = logging.getLogger(__name__)


class FeedbackRating(int, Enum):
    POSITIVE = 1
    NEUTRAL = 0
    NEGATIVE = -1


@dataclass
class ReviewRequest:
    order_id: str
    buyer_id: str
    item_title: str
    delivered_date: datetime
    request_sent: bool = False
    request_sent_date: Optional[datetime] = None


@dataclass
class FeedbackItem:
    feedback_id: str
    order_id: str
    buyer_id: str
    rating: FeedbackRating
    comment: str
    received_date: datetime
    responded: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class ReviewProcessingResult:
    review_requests_sent: int = 0
    feedback_responses_queued: int = 0
    negative_alerts_raised: int = 0
    errors: int = 0


class ReviewManager:
    """
    Drives the post-sale review and feedback lifecycle.

    - Sends review-request messages N days after delivery
    - Drafts responses to received feedback
    - Raises alerts for negative feedback so the seller can act
    """

    def __init__(self, config: dict, db: DatabaseManager):
        self.config = config
        self.db = db
        self.template_manager = MessageTemplateManager(config)
        review_cfg = config.get("reviews", {})
        self.request_delay_days: int = review_cfg.get("request_delay_days", 3)
        self.auto_respond_feedback: bool = review_cfg.get("auto_respond_feedback", True)
        self.negative_alert_enabled: bool = review_cfg.get(
            "negative_alert_enabled", True
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_review_requests(self) -> ReviewProcessingResult:
        """
        Send review requests for recently delivered orders and process
        any feedback that has come in.

        Returns:
            ReviewProcessingResult with counts per action.
        """
        result = ReviewProcessingResult()

        # Review request sends
        eligible_orders = self.db.get_orders_eligible_for_review_request(
            min_days_since_delivery=self.request_delay_days
        )
        for order_data in eligible_orders:
            try:
                sent = self._send_review_request(ReviewRequest(**order_data))
                if sent:
                    result.review_requests_sent += 1
            except Exception:
                logger.exception(
                    "Error sending review request for order %s",
                    order_data.get("order_id"),
                )
                result.errors += 1

        # Feedback response processing
        new_feedback = self.db.get_unresponded_feedback()
        for fb_data in new_feedback:
            try:
                fb = FeedbackItem(**fb_data)
                self._handle_feedback(fb, result)
            except Exception:
                logger.exception(
                    "Error processing feedback %s", fb_data.get("feedback_id")
                )
                result.errors += 1

        logger.info(
            "Review processing – requests_sent=%d responses_queued=%d "
            "negative_alerts=%d errors=%d",
            result.review_requests_sent,
            result.feedback_responses_queued,
            result.negative_alerts_raised,
            result.errors,
        )
        return result

    def send_review_request(self, request: ReviewRequest) -> bool:
        """
        Compose and queue a review-request message for *request*.

        Args:
            request: The review request to send.

        Returns:
            True if the message was successfully queued.
        """
        return self._send_review_request(request)

    def generate_feedback_response(self, feedback: FeedbackItem) -> Optional[str]:
        """
        Render a response template for the given feedback item.

        Args:
            feedback: The received feedback to respond to.

        Returns:
            Rendered response string, or None if no template is available.
        """
        context = {
            "buyer_id": feedback.buyer_id,
            "order_id": feedback.order_id,
            "rating": feedback.rating.name.lower(),
            "comment": feedback.comment,
        }
        return self.template_manager.render(MessageCategory.FEEDBACK, context)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_review_request(self, request: ReviewRequest) -> bool:
        context = {
            "buyer_id": request.buyer_id,
            "order_id": request.order_id,
            "item_title": request.item_title,
        }
        message = self.template_manager.render(MessageCategory.FEEDBACK, context)
        if not message:
            return False

        self.db.queue_outgoing_message(
            buyer_id=request.buyer_id,
            subject="How did we do? Please leave feedback",
            body=message,
            order_id=request.order_id,
            event_type="review_request",
        )
        self.db.mark_review_request_sent(request.order_id)
        return True

    def _handle_feedback(
        self, feedback: FeedbackItem, result: ReviewProcessingResult
    ) -> None:
        if feedback.rating == FeedbackRating.NEGATIVE and self.negative_alert_enabled:
            self._raise_negative_alert(feedback)
            result.negative_alerts_raised += 1

        if self.auto_respond_feedback:
            response = self.generate_feedback_response(feedback)
            if response:
                self.db.queue_outgoing_message(
                    buyer_id=feedback.buyer_id,
                    subject="Thank you for your feedback",
                    body=response,
                    order_id=feedback.order_id,
                    event_type="feedback_response",
                )
                self.db.mark_feedback_responded(feedback.feedback_id)
                result.feedback_responses_queued += 1

    def _raise_negative_alert(self, feedback: FeedbackItem) -> None:
        """Log and record a negative-feedback alert for seller review."""
        logger.warning(
            "NEGATIVE FEEDBACK received – feedback_id=%s order_id=%s buyer=%s "
            "comment=%r",
            feedback.feedback_id,
            feedback.order_id,
            feedback.buyer_id,
            feedback.comment,
        )
        self.db.create_alert(
            alert_type="negative_feedback",
            reference_id=feedback.feedback_id,
            details={
                "order_id": feedback.order_id,
                "buyer_id": feedback.buyer_id,
                "comment": feedback.comment,
                "received_date": feedback.received_date.isoformat(),
            },
        )
