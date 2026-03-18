"""
Core automation engine for eBay customer interaction workflows.

Orchestrates message management, order updates, review requests, and
customer service tasks on a configurable schedule.
"""

import logging
import time
from datetime import datetime
from typing import Optional

import schedule

from src.analytics.metrics import AnalyticsManager
from src.automation.customer_service import CustomerServiceManager
from src.automation.message_manager import MessageManager
from src.automation.order_manager import OrderManager
from src.automation.review_manager import ReviewManager
from src.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class AutomationEngine:
    """
    Central engine that coordinates all customer interaction automation tasks.

    Responsibilities:
    - Schedule and execute recurring automation jobs
    - Wire together sub-managers (messages, orders, reviews, customer service)
    - Collect and expose analytics
    - Provide graceful start / stop lifecycle management
    """

    def __init__(self, config: dict):
        """
        Initialise the engine with a fully-populated configuration dictionary.

        Args:
            config: Top-level configuration dict (typically loaded from config.yaml).
        """
        self.config = config
        self.store_id: str = config.get("store", {}).get("id", "default")
        self._running = False

        self.db = DatabaseManager(config.get("database", {}))
        self.message_manager = MessageManager(config, self.db)
        self.order_manager = OrderManager(config, self.db)
        self.review_manager = ReviewManager(config, self.db)
        self.customer_service = CustomerServiceManager(config, self.db)
        self.analytics = AnalyticsManager(config, self.db)

        logger.info("AutomationEngine initialised for store: %s", self.store_id)

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    def start(self, blocking: bool = True) -> None:
        """
        Start the automation engine.

        Args:
            blocking: When True the call blocks and runs the scheduler loop
                      indefinitely.  Set to False in tests or when embedding
                      inside an async framework.
        """
        logger.info("Starting AutomationEngine for store: %s", self.store_id)
        self._running = True
        self._schedule_jobs()

        if blocking:
            self._run_loop()

    def stop(self) -> None:
        """Signal the engine to stop after the current iteration."""
        logger.info("Stopping AutomationEngine")
        self._running = False
        schedule.clear()

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def _schedule_jobs(self) -> None:
        """Register all recurring jobs with the schedule library."""
        sched_cfg = self.config.get("schedule", {})

        msg_interval = sched_cfg.get("message_check_interval_minutes", 15)
        schedule.every(msg_interval).minutes.do(self._run_message_processing)

        order_interval = sched_cfg.get("order_check_interval_minutes", 30)
        schedule.every(order_interval).minutes.do(self._run_order_processing)

        review_time = sched_cfg.get("review_request_time", "09:00")
        schedule.every().day.at(review_time).do(self._run_review_processing)

        cs_interval = sched_cfg.get("customer_service_interval_minutes", 20)
        schedule.every(cs_interval).minutes.do(self._run_customer_service)

        analytics_time = sched_cfg.get("analytics_report_time", "18:00")
        schedule.every().day.at(analytics_time).do(self._run_analytics_report)

        logger.info("Scheduled all automation jobs")

    def _run_loop(self) -> None:
        """Block and run pending scheduled jobs until stop() is called."""
        logger.info("Scheduler loop started")
        while self._running:
            schedule.run_pending()
            time.sleep(1)
        logger.info("Scheduler loop exited")

    # ------------------------------------------------------------------
    # Job implementations
    # ------------------------------------------------------------------

    def _run_message_processing(self) -> None:
        """Process incoming customer messages and send automated responses."""
        logger.info("[%s] Running message processing", _now())
        try:
            result = self.message_manager.process_incoming_messages()
            self.analytics.record_messages_processed(result)
        except Exception:
            logger.exception("Message processing failed")

    def _run_order_processing(self) -> None:
        """Send shipping notifications and order status updates."""
        logger.info("[%s] Running order processing", _now())
        try:
            result = self.order_manager.process_order_updates()
            self.analytics.record_orders_processed(result)
        except Exception:
            logger.exception("Order processing failed")

    def _run_review_processing(self) -> None:
        """Request reviews for recently delivered orders."""
        logger.info("[%s] Running review processing", _now())
        try:
            result = self.review_manager.process_review_requests()
            self.analytics.record_reviews_processed(result)
        except Exception:
            logger.exception("Review processing failed")

    def _run_customer_service(self) -> None:
        """Handle return requests, refunds, and escalations."""
        logger.info("[%s] Running customer service workflows", _now())
        try:
            result = self.customer_service.process_service_requests()
            self.analytics.record_service_requests(result)
        except Exception:
            logger.exception("Customer service processing failed")

    def _run_analytics_report(self) -> None:
        """Generate and store daily analytics report."""
        logger.info("[%s] Generating analytics report", _now())
        try:
            report = self.analytics.generate_daily_report()
            logger.info("Analytics report generated: %s", report)
        except Exception:
            logger.exception("Analytics report generation failed")

    # ------------------------------------------------------------------
    # Manual trigger helpers (useful for ad-hoc runs)
    # ------------------------------------------------------------------

    def run_all_now(self) -> dict:
        """
        Immediately execute every automation task once and return a summary.

        Returns:
            dict: Keyed results from each task.
        """
        results = {}
        for name, fn in [
            ("messages", self._run_message_processing),
            ("orders", self._run_order_processing),
            ("reviews", self._run_review_processing),
            ("customer_service", self._run_customer_service),
            ("analytics", self._run_analytics_report),
        ]:
            try:
                fn()
                results[name] = "ok"
            except Exception as exc:
                results[name] = f"error: {exc}"
        return results


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
