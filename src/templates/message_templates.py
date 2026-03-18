"""
Message template system.

Provides Jinja2-powered templates for each message category.
Templates can be loaded from the configuration or overridden per store.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from jinja2 import Environment, StrictUndefined

logger = logging.getLogger(__name__)


class MessageCategory(str, Enum):
    SHIPPING = "shipping"
    RETURN = "return"
    PRODUCT_INFO = "product_info"
    ORDER_STATUS = "order_status"
    FEEDBACK = "feedback"
    GENERAL = "general"


@dataclass
class MessageTemplate:
    category: MessageCategory
    name: str
    subject_template: str
    body_template: str
    description: str = ""


# ---------------------------------------------------------------------------
# Built-in default templates
# ---------------------------------------------------------------------------

_DEFAULT_TEMPLATES: dict[MessageCategory, MessageTemplate] = {
    MessageCategory.SHIPPING: MessageTemplate(
        category=MessageCategory.SHIPPING,
        name="shipping_confirmation",
        subject_template="Your order has shipped! Tracking: {{ tracking_number }}",
        body_template=(
            "Hi {{ buyer_id }},\n\n"
            "Great news — your order"
            "{% if order_id %} ({{ order_id }}){% endif %}"
            "{% if item_title %} for **{{ item_title }}**{% endif %} "
            "has been shipped!\n\n"
            "{% if carrier %}Carrier: {{ carrier }}\n{% endif %}"
            "{% if tracking_number %}Tracking number: {{ tracking_number }}\n{% endif %}"
            "{% if tracking_url %}Track your package: {{ tracking_url }}\n{% endif %}"
            "{% if estimated_delivery %}Estimated delivery: {{ estimated_delivery }}\n{% endif %}"
            "\n"
            "Thank you for shopping with us. Please don't hesitate to reach out "
            "if you have any questions.\n\n"
            "Best regards,\n"
            "{{ store_name }}"
        ),
        description="Sent when an order is marked as shipped.",
    ),
    MessageCategory.RETURN: MessageTemplate(
        category=MessageCategory.RETURN,
        name="return_acknowledgement",
        subject_template="Return Request Received – Order {{ order_id }}",
        body_template=(
            "Hi {{ buyer_id }},\n\n"
            "We have received your return request for order {{ order_id }} "
            "({{ item_title }}).\n\n"
            "Reason: {{ return_reason }}\n"
            "Refund amount: {{ refund_amount }}\n"
            "Current status: {{ status }}\n\n"
            "We will process your request within 1–3 business days and keep you "
            "updated every step of the way.\n\n"
            "If you have any questions, please reply to this message.\n\n"
            "Best regards,\n"
            "{{ store_name }}"
        ),
        description="Acknowledges a new return / refund request.",
    ),
    MessageCategory.PRODUCT_INFO: MessageTemplate(
        category=MessageCategory.PRODUCT_INFO,
        name="product_info_response",
        subject_template="Re: Your inquiry about our listing",
        body_template=(
            "Hi {{ buyer_id }},\n\n"
            "Thank you for your question! We are happy to help.\n\n"
            "Please check the full product description and specifications in the "
            "listing page for detailed information. If you cannot find what you "
            "need, feel free to reply and we will answer as quickly as possible.\n\n"
            "Best regards,\n"
            "{{ store_name }}"
        ),
        description="Generic response to product specification enquiries.",
    ),
    MessageCategory.ORDER_STATUS: MessageTemplate(
        category=MessageCategory.ORDER_STATUS,
        name="order_status_update",
        subject_template="Update on your order {{ order_id }}",
        body_template=(
            "Hi {{ buyer_id }},\n\n"
            "Here is a quick update on your order {{ order_id }}:\n\n"
            "{% if tracking_number %}"
            "Your package is currently in transit.\n"
            "Tracking number: {{ tracking_number }}\n"
            "{% if tracking_url %}Track it here: {{ tracking_url }}\n{% endif %}"
            "{% if estimated_delivery %}Estimated delivery: {{ estimated_delivery }}\n"
            "{% endif %}"
            "{% else %}"
            "Your order is being processed and will be shipped soon.\n"
            "{% endif %}"
            "\n"
            "Thank you for your patience. Please don't hesitate to contact us with "
            "any questions.\n\n"
            "Best regards,\n"
            "{{ store_name }}"
        ),
        description="General order status / in-transit update.",
    ),
    MessageCategory.FEEDBACK: MessageTemplate(
        category=MessageCategory.FEEDBACK,
        name="review_request",
        subject_template="How did we do? – Order {{ order_id }}",
        body_template=(
            "Hi {{ buyer_id }},\n\n"
            "We hope you are enjoying your purchase of **{{ item_title }}** "
            "(order {{ order_id }})!\n\n"
            "If you are satisfied with your experience, we would really appreciate "
            "it if you could take a moment to leave us feedback on eBay. Your "
            "review helps other buyers and motivates our small team.\n\n"
            "If anything was less than perfect, please reply to this message before "
            "leaving feedback — we would love the chance to make it right.\n\n"
            "Thank you so much for your support!\n\n"
            "Best regards,\n"
            "{{ store_name }}"
        ),
        description="Post-delivery review request.",
    ),
    MessageCategory.GENERAL: MessageTemplate(
        category=MessageCategory.GENERAL,
        name="general_response",
        subject_template="Re: Your message",
        body_template=(
            "Hi {{ buyer_id }},\n\n"
            "Thank you for reaching out to us!\n\n"
            "We have received your message and will get back to you within "
            "1 business day.\n\n"
            "Best regards,\n"
            "{{ store_name }}"
        ),
        description="Catch-all response for unclassified messages.",
    ),
}


class MessageTemplateManager:
    """
    Manages message templates and renders them with Jinja2.

    Templates can be customised per store via the ``templates`` section
    of the store configuration file.
    """

    def __init__(self, config: dict):
        self.config = config
        self.store_name: str = config.get("store", {}).get("name", "Our Store")
        self._templates: dict[MessageCategory, MessageTemplate] = dict(
            _DEFAULT_TEMPLATES
        )
        self._load_custom_templates(config.get("templates", {}))
        self._jinja_env = Environment(undefined=StrictUndefined)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_template(self, category: MessageCategory) -> Optional[MessageTemplate]:
        """
        Return the template for *category*, or None if not found.

        Args:
            category: The message category.

        Returns:
            MessageTemplate instance, or None.
        """
        return self._templates.get(category)

    def render(self, category: MessageCategory, context: dict) -> Optional[str]:
        """
        Render the body template for *category* with the given *context*.

        A ``store_name`` key is automatically injected if not present in
        *context*.

        Args:
            category: Message category to use for template selection.
            context: Variables available inside the template.

        Returns:
            Rendered string, or None if no template exists for *category*.
        """
        template = self.get_template(category)
        if not template:
            logger.warning("No template found for category: %s", category)
            return None

        ctx = {"store_name": self.store_name, **context}
        try:
            return self._jinja_env.from_string(template.body_template).render(ctx)
        except Exception:
            logger.exception(
                "Failed to render template for category %s", category
            )
            return None

    def add_template(self, template: MessageTemplate) -> None:
        """
        Register (or replace) a template for its category.

        Args:
            template: The template to register.
        """
        self._templates[template.category] = template

    def list_templates(self) -> list[MessageTemplate]:
        """Return all registered templates."""
        return list(self._templates.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_custom_templates(self, templates_cfg: dict) -> None:
        """
        Override default templates with any custom ones from the config.

        The config format is::

            templates:
              shipping:
                body: "Custom body {{ buyer_id }}…"
              return:
                body: "Custom return body…"
        """
        for category_name, overrides in templates_cfg.items():
            try:
                category = MessageCategory(category_name)
            except ValueError:
                logger.warning("Unknown template category in config: %s", category_name)
                continue

            if category in self._templates and "body" in overrides:
                existing = self._templates[category]
                self._templates[category] = MessageTemplate(
                    category=existing.category,
                    name=existing.name,
                    subject_template=overrides.get(
                        "subject", existing.subject_template
                    ),
                    body_template=overrides["body"],
                    description=overrides.get("description", existing.description),
                )
                logger.debug("Loaded custom template for category: %s", category_name)
