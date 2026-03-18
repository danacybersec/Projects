"""
Customer service workflows module.

Handles:
- Return request processing
- Refund status updates
- Escalation procedures for unresolved issues
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from src.database.db_manager import DatabaseManager
from src.templates.message_templates import MessageCategory, MessageTemplateManager

logger = logging.getLogger(__name__)


class ReturnStatus(str, Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    ITEM_RECEIVED = "item_received"
    REFUND_ISSUED = "refund_issued"
    COMPLETED = "completed"
    DENIED = "denied"
    ESCALATED = "escalated"


class EscalationLevel(int, Enum):
    NONE = 0
    SELLER = 1
    EBAY = 2


@dataclass
class ReturnRequest:
    return_id: str
    order_id: str
    buyer_id: str
    reason: str
    status: ReturnStatus
    created_date: datetime
    item_title: str
    refund_amount: float = 0.0
    escalation_level: EscalationLevel = EscalationLevel.NONE
    metadata: dict = field(default_factory=dict)


@dataclass
class ServiceProcessingResult:
    total: int = 0
    return_acknowledgements_sent: int = 0
    refund_updates_sent: int = 0
    escalations_created: int = 0
    errors: int = 0


class CustomerServiceManager:
    """
    Manages return requests, refunds, and escalations.

    Workflow:
    1. New return requests are acknowledged automatically.
    2. Refund-issued events trigger a status-update message to the buyer.
    3. Requests open beyond the auto-escalation threshold are escalated.
    """

    def __init__(self, config: dict, db: DatabaseManager):
        self.config = config
        self.db = db
        self.template_manager = MessageTemplateManager(config)
        cs_cfg = config.get("customer_service", {})
        self.auto_acknowledge_returns: bool = cs_cfg.get(
            "auto_acknowledge_returns", True
        )
        self.auto_notify_refunds: bool = cs_cfg.get("auto_notify_refunds", True)
        self.escalation_threshold_days: int = cs_cfg.get(
            "escalation_threshold_days", 5
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_service_requests(self) -> ServiceProcessingResult:
        """
        Process all open customer-service items and send appropriate messages.

        Returns:
            ServiceProcessingResult with per-action counts.
        """
        result = ServiceProcessingResult()
        open_returns = self.db.get_open_return_requests()
        result.total = len(open_returns)

        for return_data in open_returns:
            req = ReturnRequest(**return_data)
            try:
                self._process_return(req, result)
            except Exception:
                logger.exception(
                    "Error processing return request %s", req.return_id
                )
                result.errors += 1

        logger.info(
            "Customer service processing – total=%d acks=%d refund_updates=%d "
            "escalations=%d errors=%d",
            result.total,
            result.return_acknowledgements_sent,
            result.refund_updates_sent,
            result.escalations_created,
            result.errors,
        )
        return result

    def acknowledge_return_request(self, request: ReturnRequest) -> bool:
        """
        Send an acknowledgement message for a newly received return request.

        Args:
            request: The return request to acknowledge.

        Returns:
            True if the message was queued successfully.
        """
        context = self._build_return_context(request)
        message = self.template_manager.render(MessageCategory.RETURN, context)
        if not message:
            return False

        self.db.queue_outgoing_message(
            buyer_id=request.buyer_id,
            subject=f"Return Request Received – Order {request.order_id}",
            body=message,
            order_id=request.order_id,
            event_type="return_acknowledgement",
        )
        self.db.mark_return_acknowledged(request.return_id)
        return True

    def send_refund_update(self, request: ReturnRequest) -> bool:
        """
        Notify the buyer that their refund has been issued.

        Args:
            request: The return request with refund details.

        Returns:
            True if the message was queued successfully.
        """
        context = self._build_return_context(request)
        message = self.template_manager.render(MessageCategory.RETURN, context)
        if not message:
            return False

        self.db.queue_outgoing_message(
            buyer_id=request.buyer_id,
            subject=f"Refund Issued – Order {request.order_id}",
            body=message,
            order_id=request.order_id,
            event_type="refund_notification",
        )
        self.db.mark_refund_notified(request.return_id)
        return True

    def escalate_request(self, request: ReturnRequest) -> bool:
        """
        Escalate an unresolved return request.

        Args:
            request: The return request to escalate.

        Returns:
            True if the escalation was recorded.
        """
        new_level = EscalationLevel(
            min(request.escalation_level + 1, EscalationLevel.EBAY)
        )
        self.db.create_alert(
            alert_type="return_escalation",
            reference_id=request.return_id,
            details={
                "order_id": request.order_id,
                "buyer_id": request.buyer_id,
                "reason": request.reason,
                "escalation_level": new_level.name,
                "days_open": (datetime.utcnow() - request.created_date).days,
            },
        )
        self.db.update_return_escalation(request.return_id, new_level)
        logger.warning(
            "Return request %s escalated to level %s (order=%s)",
            request.return_id,
            new_level.name,
            request.order_id,
        )
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_return(
        self, request: ReturnRequest, result: ServiceProcessingResult
    ) -> None:
        days_open = (datetime.utcnow() - request.created_date).days

        if request.status == ReturnStatus.REQUESTED and self.auto_acknowledge_returns:
            if self.acknowledge_return_request(request):
                result.return_acknowledgements_sent += 1

        elif request.status == ReturnStatus.REFUND_ISSUED and self.auto_notify_refunds:
            if self.send_refund_update(request):
                result.refund_updates_sent += 1

        if (
            days_open >= self.escalation_threshold_days
            and request.escalation_level == EscalationLevel.NONE
            and request.status not in {
                ReturnStatus.COMPLETED,
                ReturnStatus.ESCALATED,
            }
        ):
            if self.escalate_request(request):
                result.escalations_created += 1

    @staticmethod
    def _build_return_context(request: ReturnRequest) -> dict:
        return {
            "buyer_id": request.buyer_id,
            "order_id": request.order_id,
            "item_title": request.item_title,
            "return_reason": request.reason,
            "refund_amount": f"${request.refund_amount:.2f}",
            "status": request.status.value,
        }
