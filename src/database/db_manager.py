"""
Database manager module.

Provides a lightweight SQLite-backed persistence layer for storing:
- Customer interactions and message history
- Order notification state
- Return / refund request tracking
- Review request state
- Outgoing message queue
- Analytics data
- Alerts
"""

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class MessageRecord(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(128), unique=True, nullable=False, index=True)
    buyer_id = Column(String(128), nullable=False)
    subject = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    order_id = Column(String(128), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="pending")
    category = Column(String(64), nullable=True)
    response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OrderRecord(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(128), unique=True, nullable=False, index=True)
    buyer_id = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False)
    item_title = Column(Text, nullable=True)
    tracking_number = Column(String(128), nullable=True)
    carrier = Column(String(64), nullable=True)
    shipped_date = Column(DateTime, nullable=True)
    estimated_delivery = Column(DateTime, nullable=True)
    delivered_date = Column(DateTime, nullable=True)
    shipping_notified = Column(Integer, default=0)
    delivery_notified = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReturnRecord(Base):
    __tablename__ = "returns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    return_id = Column(String(128), unique=True, nullable=False, index=True)
    order_id = Column(String(128), nullable=False, index=True)
    buyer_id = Column(String(128), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="requested")
    item_title = Column(Text, nullable=True)
    refund_amount = Column(Float, default=0.0)
    escalation_level = Column(Integer, default=0)
    acknowledged = Column(Integer, default=0)
    refund_notified = Column(Integer, default=0)
    created_date = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReviewRequestRecord(Base):
    __tablename__ = "review_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(128), unique=True, nullable=False, index=True)
    buyer_id = Column(String(128), nullable=False)
    item_title = Column(Text, nullable=True)
    delivered_date = Column(DateTime, nullable=True)
    request_sent = Column(Integer, default=0)
    request_sent_date = Column(DateTime, nullable=True)


class FeedbackRecord(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feedback_id = Column(String(128), unique=True, nullable=False, index=True)
    order_id = Column(String(128), nullable=False, index=True)
    buyer_id = Column(String(128), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    received_date = Column(DateTime, default=datetime.utcnow)
    responded = Column(Integer, default=0)


class OutgoingMessage(Base):
    __tablename__ = "outgoing_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    buyer_id = Column(String(128), nullable=False)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    order_id = Column(String(128), nullable=True, index=True)
    event_type = Column(String(64), nullable=True)
    sent = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)


class AlertRecord(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_type = Column(String(64), nullable=False, index=True)
    reference_id = Column(String(128), nullable=True)
    details_json = Column(Text, nullable=True)
    resolved = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnalyticsRecord(Base):
    __tablename__ = "analytics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False, index=True)
    count = Column(Integer, default=0)
    metadata_json = Column(Text, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------


class DatabaseManager:
    """
    Manages the SQLite database connection and provides helper methods
    for each domain area (messages, orders, returns, etc.).
    """

    def __init__(self, config: dict):
        db_path = config.get("path", "ebay_automation.db")
        echo = config.get("echo_sql", False)
        url = f"sqlite:///{db_path}" if not db_path.startswith("sqlite") else db_path
        self.engine = create_engine(url, echo=echo, future=True)

        # Enable WAL mode for better concurrent read performance
        @event.listens_for(self.engine, "connect")
        def set_wal(dbapi_conn, _conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Yield a transactional session that commits or rolls back on exit."""
        sess = self.SessionFactory()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    def get_pending_messages(self, limit: int = 50) -> list[dict]:
        with self.session() as s:
            rows = (
                s.query(MessageRecord)
                .filter(MessageRecord.status == "pending")
                .limit(limit)
                .all()
            )
            return [_message_to_dict(r) for r in rows]

    def update_message_status(self, message_id: str, status: Any) -> None:
        with self.session() as s:
            row = (
                s.query(MessageRecord)
                .filter(MessageRecord.message_id == message_id)
                .first()
            )
            if row:
                row.status = str(status.value) if hasattr(status, "value") else str(status)

    def save_message_response(
        self, message_id: str, response: str, category: str
    ) -> None:
        with self.session() as s:
            row = (
                s.query(MessageRecord)
                .filter(MessageRecord.message_id == message_id)
                .first()
            )
            if row:
                row.response = response
                row.category = category

    def upsert_message(self, data: dict) -> None:
        with self.session() as s:
            existing = (
                s.query(MessageRecord)
                .filter(MessageRecord.message_id == data["message_id"])
                .first()
            )
            if existing:
                for k, v in data.items():
                    if hasattr(existing, k):
                        setattr(existing, k, v)
            else:
                s.add(MessageRecord(**data))

    # ------------------------------------------------------------------
    # Order helpers
    # ------------------------------------------------------------------

    def get_orders_needing_notification(self) -> list[dict]:
        with self.session() as s:
            rows = (
                s.query(OrderRecord)
                .filter(
                    (
                        (OrderRecord.status == "shipped")
                        & (OrderRecord.shipping_notified == 0)
                    )
                    | (OrderRecord.status == "in_transit")
                    | (
                        (OrderRecord.status == "delivered")
                        & (OrderRecord.delivery_notified == 0)
                    )
                )
                .all()
            )
            return [_order_to_dict(r) for r in rows]

    def mark_order_shipping_notified(self, order_id: str) -> None:
        with self.session() as s:
            row = (
                s.query(OrderRecord)
                .filter(OrderRecord.order_id == order_id)
                .first()
            )
            if row:
                row.shipping_notified = 1

    def mark_order_delivery_notified(self, order_id: str) -> None:
        with self.session() as s:
            row = (
                s.query(OrderRecord)
                .filter(OrderRecord.order_id == order_id)
                .first()
            )
            if row:
                row.delivery_notified = 1

    def upsert_order(self, data: dict) -> None:
        with self.session() as s:
            existing = (
                s.query(OrderRecord)
                .filter(OrderRecord.order_id == data["order_id"])
                .first()
            )
            if existing:
                for k, v in data.items():
                    if hasattr(existing, k):
                        setattr(existing, k, v)
            else:
                s.add(OrderRecord(**data))

    # ------------------------------------------------------------------
    # Return helpers
    # ------------------------------------------------------------------

    def get_open_return_requests(self) -> list[dict]:
        from src.automation.customer_service import ReturnStatus

        with self.session() as s:
            rows = (
                s.query(ReturnRecord)
                .filter(
                    ReturnRecord.status.notin_(
                        [ReturnStatus.COMPLETED.value, ReturnStatus.DENIED.value]
                    )
                )
                .all()
            )
            return [_return_to_dict(r) for r in rows]

    def mark_return_acknowledged(self, return_id: str) -> None:
        with self.session() as s:
            row = (
                s.query(ReturnRecord)
                .filter(ReturnRecord.return_id == return_id)
                .first()
            )
            if row:
                row.acknowledged = 1

    def mark_refund_notified(self, return_id: str) -> None:
        with self.session() as s:
            row = (
                s.query(ReturnRecord)
                .filter(ReturnRecord.return_id == return_id)
                .first()
            )
            if row:
                row.refund_notified = 1

    def update_return_escalation(self, return_id: str, level: Any) -> None:
        with self.session() as s:
            row = (
                s.query(ReturnRecord)
                .filter(ReturnRecord.return_id == return_id)
                .first()
            )
            if row:
                row.escalation_level = int(level)
                row.status = "escalated"

    # ------------------------------------------------------------------
    # Review helpers
    # ------------------------------------------------------------------

    def get_orders_eligible_for_review_request(
        self, min_days_since_delivery: int = 3
    ) -> list[dict]:
        with self.session() as s:
            rows = (
                s.query(ReviewRequestRecord)
                .filter(ReviewRequestRecord.request_sent == 0)
                .all()
            )
            cutoff = datetime.utcnow()
            eligible = []
            for r in rows:
                if r.delivered_date:
                    days = (cutoff - r.delivered_date).days
                    if days >= min_days_since_delivery:
                        eligible.append(_review_request_to_dict(r))
            return eligible

    def mark_review_request_sent(self, order_id: str) -> None:
        with self.session() as s:
            row = (
                s.query(ReviewRequestRecord)
                .filter(ReviewRequestRecord.order_id == order_id)
                .first()
            )
            if row:
                row.request_sent = 1
                row.request_sent_date = datetime.utcnow()

    def get_unresponded_feedback(self) -> list[dict]:
        with self.session() as s:
            rows = (
                s.query(FeedbackRecord)
                .filter(FeedbackRecord.responded == 0)
                .all()
            )
            return [_feedback_to_dict(r) for r in rows]

    def mark_feedback_responded(self, feedback_id: str) -> None:
        with self.session() as s:
            row = (
                s.query(FeedbackRecord)
                .filter(FeedbackRecord.feedback_id == feedback_id)
                .first()
            )
            if row:
                row.responded = 1

    # ------------------------------------------------------------------
    # Outgoing message queue
    # ------------------------------------------------------------------

    def queue_outgoing_message(
        self,
        buyer_id: str,
        subject: str,
        body: str,
        order_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> None:
        with self.session() as s:
            s.add(
                OutgoingMessage(
                    buyer_id=buyer_id,
                    subject=subject,
                    body=body,
                    order_id=order_id,
                    event_type=event_type,
                )
            )

    def get_unsent_messages(self, limit: int = 100) -> list[dict]:
        with self.session() as s:
            rows = (
                s.query(OutgoingMessage)
                .filter(OutgoingMessage.sent == 0)
                .limit(limit)
                .all()
            )
            return [_outgoing_to_dict(r) for r in rows]

    def mark_message_sent(self, message_id: int) -> None:
        with self.session() as s:
            row = s.get(OutgoingMessage, message_id)
            if row:
                row.sent = 1
                row.sent_at = datetime.utcnow()

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def create_alert(
        self, alert_type: str, reference_id: str, details: dict
    ) -> None:
        with self.session() as s:
            s.add(
                AlertRecord(
                    alert_type=alert_type,
                    reference_id=reference_id,
                    details_json=json.dumps(details),
                )
            )

    def get_open_alerts(self, alert_type: Optional[str] = None) -> list[dict]:
        with self.session() as s:
            q = s.query(AlertRecord).filter(AlertRecord.resolved == 0)
            if alert_type:
                q = q.filter(AlertRecord.alert_type == alert_type)
            return [_alert_to_dict(r) for r in q.all()]

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def record_analytics_event(
        self, event_type: str, count: int, metadata: Optional[dict] = None
    ) -> None:
        with self.session() as s:
            s.add(
                AnalyticsRecord(
                    event_type=event_type,
                    count=count,
                    metadata_json=json.dumps(metadata or {}),
                )
            )

    def get_analytics_summary(
        self, event_type: Optional[str] = None, days: int = 30
    ) -> list[dict]:
        from sqlalchemy import func

        cutoff = datetime.utcnow()
        with self.session() as s:
            q = (
                s.query(
                    AnalyticsRecord.event_type,
                    func.sum(AnalyticsRecord.count).label("total"),
                )
                .group_by(AnalyticsRecord.event_type)
            )
            if event_type:
                q = q.filter(AnalyticsRecord.event_type == event_type)
            return [{"event_type": r.event_type, "total": r.total} for r in q.all()]


# ---------------------------------------------------------------------------
# Row → dict helpers
# ---------------------------------------------------------------------------


def _message_to_dict(r: MessageRecord) -> dict:
    return {
        "message_id": r.message_id,
        "buyer_id": r.buyer_id,
        "subject": r.subject or "",
        "body": r.body or "",
        "order_id": r.order_id,
        "status": r.status,
        "metadata": {},
    }


def _order_to_dict(r: OrderRecord) -> dict:
    return {
        "order_id": r.order_id,
        "buyer_id": r.buyer_id,
        "status": r.status,
        "item_title": r.item_title or "",
        "tracking_number": r.tracking_number,
        "carrier": r.carrier,
        "shipped_date": r.shipped_date,
        "estimated_delivery": r.estimated_delivery,
        "delivered_date": r.delivered_date,
        "metadata": {},
    }


def _return_to_dict(r: ReturnRecord) -> dict:
    from src.automation.customer_service import EscalationLevel

    return {
        "return_id": r.return_id,
        "order_id": r.order_id,
        "buyer_id": r.buyer_id,
        "reason": r.reason or "",
        "status": r.status,
        "item_title": r.item_title or "",
        "refund_amount": r.refund_amount or 0.0,
        "escalation_level": EscalationLevel(r.escalation_level or 0),
        "created_date": r.created_date or datetime.utcnow(),
        "metadata": {},
    }


def _review_request_to_dict(r: ReviewRequestRecord) -> dict:
    return {
        "order_id": r.order_id,
        "buyer_id": r.buyer_id,
        "item_title": r.item_title or "",
        "delivered_date": r.delivered_date or datetime.utcnow(),
        "request_sent": bool(r.request_sent),
        "request_sent_date": r.request_sent_date,
    }


def _feedback_to_dict(r: FeedbackRecord) -> dict:
    from src.automation.review_manager import FeedbackRating

    return {
        "feedback_id": r.feedback_id,
        "order_id": r.order_id,
        "buyer_id": r.buyer_id,
        "rating": FeedbackRating(r.rating),
        "comment": r.comment or "",
        "received_date": r.received_date or datetime.utcnow(),
        "responded": bool(r.responded),
        "metadata": {},
    }


def _outgoing_to_dict(r: OutgoingMessage) -> dict:
    return {
        "id": r.id,
        "buyer_id": r.buyer_id,
        "subject": r.subject,
        "body": r.body,
        "order_id": r.order_id,
        "event_type": r.event_type,
        "sent": bool(r.sent),
    }


def _alert_to_dict(r: AlertRecord) -> dict:
    return {
        "id": r.id,
        "alert_type": r.alert_type,
        "reference_id": r.reference_id,
        "details": json.loads(r.details_json) if r.details_json else {},
        "resolved": bool(r.resolved),
        "created_at": r.created_at,
    }
