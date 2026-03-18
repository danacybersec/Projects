"""
Analytics and reporting module.

Tracks:
- Customer interaction metrics
- Response time tracking
- Customer satisfaction scoring
- Generates daily and weekly reports
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from src.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class DailyReport:
    date: str
    messages_processed: int = 0
    messages_responded: int = 0
    messages_escalated: int = 0
    orders_shipped: int = 0
    orders_delivered: int = 0
    review_requests_sent: int = 0
    feedback_responses_sent: int = 0
    negative_feedback_count: int = 0
    return_requests: int = 0
    refunds_issued: int = 0
    satisfaction_score: float = 0.0
    avg_response_time_minutes: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class AnalyticsEvent:
    event_type: str
    count: int
    metadata: dict = field(default_factory=dict)


class AnalyticsManager:
    """
    Collects analytics events from other managers and generates reports.

    All numeric counters are persisted to the database so data survives
    across restarts and can be queried later.
    """

    def __init__(self, config: dict, db: DatabaseManager):
        self.config = config
        self.db = db
        self._buffer: list[AnalyticsEvent] = []

    # ------------------------------------------------------------------
    # Event recording (called by AutomationEngine)
    # ------------------------------------------------------------------

    def record_messages_processed(self, result: Any) -> None:
        """Record metrics from a message processing run."""
        self._record("messages_processed", getattr(result, "total", 0))
        self._record("messages_responded", getattr(result, "responded", 0))
        self._record("messages_escalated", getattr(result, "escalated", 0))

    def record_orders_processed(self, result: Any) -> None:
        """Record metrics from an order processing run."""
        self._record(
            "orders_shipping_notifications",
            getattr(result, "shipping_notifications_sent", 0),
        )
        self._record(
            "orders_delivery_confirmations",
            getattr(result, "delivery_confirmations_sent", 0),
        )
        self._record(
            "orders_transit_updates",
            getattr(result, "status_updates_sent", 0),
        )

    def record_reviews_processed(self, result: Any) -> None:
        """Record metrics from a review processing run."""
        self._record("review_requests_sent", getattr(result, "review_requests_sent", 0))
        self._record(
            "feedback_responses_queued",
            getattr(result, "feedback_responses_queued", 0),
        )
        self._record(
            "negative_feedback_alerts",
            getattr(result, "negative_alerts_raised", 0),
        )

    def record_service_requests(self, result: Any) -> None:
        """Record metrics from a customer-service processing run."""
        self._record(
            "return_acknowledgements",
            getattr(result, "return_acknowledgements_sent", 0),
        )
        self._record("refund_updates", getattr(result, "refund_updates_sent", 0))
        self._record("escalations", getattr(result, "escalations_created", 0))

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def generate_daily_report(self) -> DailyReport:
        """
        Generate a summary report for today's activity.

        Returns:
            DailyReport dataclass instance.
        """
        self._flush_buffer()
        summary = self.db.get_analytics_summary()
        totals: dict[str, int] = {row["event_type"]: row["total"] for row in summary}

        report = DailyReport(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            messages_processed=totals.get("messages_processed", 0),
            messages_responded=totals.get("messages_responded", 0),
            messages_escalated=totals.get("messages_escalated", 0),
            orders_shipped=totals.get("orders_shipping_notifications", 0),
            orders_delivered=totals.get("orders_delivery_confirmations", 0),
            review_requests_sent=totals.get("review_requests_sent", 0),
            feedback_responses_sent=totals.get("feedback_responses_queued", 0),
            negative_feedback_count=totals.get("negative_feedback_alerts", 0),
            return_requests=totals.get("return_acknowledgements", 0),
            refunds_issued=totals.get("refund_updates", 0),
        )

        report.satisfaction_score = self._calculate_satisfaction_score(totals)

        logger.info(
            "Daily report generated for %s – messages=%d orders=%d reviews=%d",
            report.date,
            report.messages_processed,
            report.orders_shipped + report.orders_delivered,
            report.review_requests_sent,
        )
        return report

    def get_response_rate(self) -> float:
        """
        Calculate the automated response rate as a percentage.

        Returns:
            Float between 0.0 and 100.0.
        """
        summary = self.db.get_analytics_summary()
        totals = {row["event_type"]: row["total"] for row in summary}
        total = totals.get("messages_processed", 0)
        responded = totals.get("messages_responded", 0)
        if total == 0:
            return 0.0
        return round((responded / total) * 100, 2)

    def get_customer_satisfaction_score(self) -> float:
        """
        Compute a satisfaction score based on feedback and escalation data.

        Score is in the range 0–100.

        Returns:
            Float satisfaction score.
        """
        summary = self.db.get_analytics_summary()
        totals = {row["event_type"]: row["total"] for row in summary}
        return self._calculate_satisfaction_score(totals)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(self, event_type: str, count: int) -> None:
        if count > 0:
            self._buffer.append(AnalyticsEvent(event_type=event_type, count=count))

    def _flush_buffer(self) -> None:
        for event in self._buffer:
            self.db.record_analytics_event(
                event_type=event.event_type,
                count=event.count,
                metadata=event.metadata,
            )
        self._buffer.clear()

    @staticmethod
    def _calculate_satisfaction_score(totals: dict[str, int]) -> float:
        """
        Derive a 0–100 satisfaction score.

        Logic: start at 100, deduct points for escalations and negative
        feedback relative to total interactions.
        """
        total_interactions = max(totals.get("messages_processed", 0), 1)
        negative_events = totals.get("negative_feedback_alerts", 0) + totals.get(
            "escalations", 0
        )
        penalty = (negative_events / total_interactions) * 100
        return max(0.0, round(100.0 - penalty, 2))
