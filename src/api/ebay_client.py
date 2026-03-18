"""
eBay API client module.

Provides a thin wrapper around the eBay REST APIs used by this automation
system.  All API calls are authenticated with OAuth 2.0 tokens loaded from
the configuration / environment.

Supported APIs:
- Post-Order API  (returns, refunds, cancellations)
- Messaging API   (buyer messages)
- Order API       (order details, fulfillment)
- Feedback API    (feedback retrieval)
"""

import logging
import os
from typing import Any, Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.ebay.com"
_SANDBOX_BASE_URL = "https://api.sandbox.ebay.com"

_TOKEN_URL_PROD = "https://api.ebay.com/identity/v1/oauth2/token"
_TOKEN_URL_SANDBOX = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"


class EbayApiError(Exception):
    """Raised when the eBay API returns an unexpected response."""

    def __init__(self, status_code: int, message: str, response: Optional[dict] = None):
        super().__init__(f"eBay API error {status_code}: {message}")
        self.status_code = status_code
        self.response = response or {}


class EbayClient:
    """
    Low-level eBay REST API client.

    Authentication is handled automatically – the client exchanges the
    configured client credentials for an access token and refreshes it
    transparently when it expires.

    Usage::

        client = EbayClient(config["ebay_api"])
        orders = client.get_orders(order_status="PAID")
    """

    def __init__(self, config: dict):
        """
        Args:
            config: eBay API configuration dict with keys:
                - client_id (str)
                - client_secret (str)
                - sandbox (bool, default False)
                - marketplace_id (str, default "EBAY_US")
        """
        self.client_id: str = config.get("client_id") or os.environ.get(
            "EBAY_CLIENT_ID", ""
        )
        self.client_secret: str = config.get("client_secret") or os.environ.get(
            "EBAY_CLIENT_SECRET", ""
        )
        self.sandbox: bool = config.get("sandbox", False)
        self.marketplace_id: str = config.get("marketplace_id", "EBAY_US")
        self.base_url: str = (
            _SANDBOX_BASE_URL if self.sandbox else _DEFAULT_BASE_URL
        )
        self._access_token: Optional[str] = None
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------

    def get_access_token(self) -> str:
        """
        Return a valid OAuth access token, refreshing if necessary.

        Returns:
            Bearer token string.
        """
        if self._access_token:
            return self._access_token
        self._access_token = self._fetch_app_token()
        return self._access_token

    def _fetch_app_token(self) -> str:
        token_url = _TOKEN_URL_SANDBOX if self.sandbox else _TOKEN_URL_PROD
        response = self._session.post(
            token_url,
            auth=(self.client_id, self.client_secret),
            data={
                "grant_type": "client_credentials",
                "scope": (
                    "https://api.ebay.com/oauth/api_scope "
                    "https://api.ebay.com/oauth/api_scope/sell.fulfillment "
                    "https://api.ebay.com/oauth/api_scope/sell.messaging "
                ),
            },
            timeout=30,
        )
        self._raise_for_status(response)
        return response.json()["access_token"]

    # ------------------------------------------------------------------
    # Order API
    # ------------------------------------------------------------------

    def get_orders(
        self,
        order_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Retrieve orders from the eBay Order API.

        Args:
            order_status: Optional status filter (e.g. "PAID", "FULFILLED").
            limit: Maximum number of orders to return.
            offset: Pagination offset.

        Returns:
            List of order dicts from the API response.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if order_status:
            params["orderStatus"] = order_status

        data = self._get("/sell/fulfillment/v1/order", params=params)
        return data.get("orders", [])

    def get_order(self, order_id: str) -> dict:
        """
        Retrieve a single order by ID.

        Args:
            order_id: eBay order ID.

        Returns:
            Order dict.
        """
        return self._get(f"/sell/fulfillment/v1/order/{order_id}")

    # ------------------------------------------------------------------
    # Messaging API
    # ------------------------------------------------------------------

    def get_messages(self, limit: int = 50) -> list[dict]:
        """
        Retrieve buyer messages.

        Args:
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts.
        """
        data = self._get(
            "/sell/messaging/v1/message",
            params={"limit": limit, "filter": "READ:false"},
        )
        return data.get("messages", [])

    def send_message(self, buyer_username: str, subject: str, body: str) -> dict:
        """
        Send a message to a buyer.

        Args:
            buyer_username: The buyer's eBay username.
            subject: Message subject.
            body: Message body text.

        Returns:
            API response dict.
        """
        payload = {
            "recipientUsername": buyer_username,
            "subject": subject,
            "text": body,
        }
        return self._post("/sell/messaging/v1/message", json=payload)

    # ------------------------------------------------------------------
    # Feedback API
    # ------------------------------------------------------------------

    def get_feedback(self, limit: int = 50) -> list[dict]:
        """
        Retrieve received feedback entries.

        Args:
            limit: Maximum number of feedback entries to return.

        Returns:
            List of feedback dicts.
        """
        data = self._get(
            "/sell/feedback/v1/feedback_summary",
            params={"limit": limit},
        )
        return data.get("feedbackPeriods", [])

    # ------------------------------------------------------------------
    # Post-Order (Returns/Refunds) API
    # ------------------------------------------------------------------

    def get_return_requests(self, status: Optional[str] = None) -> list[dict]:
        """
        Retrieve return requests.

        Args:
            status: Optional filter (e.g. "RETURN_REQUESTED").

        Returns:
            List of return request dicts.
        """
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        data = self._get("/post-order/v2/return", params=params)
        return data.get("returns", [])

    def issue_refund(self, return_id: str, amount: float, currency: str = "USD") -> dict:
        """
        Issue a refund for a return.

        Args:
            return_id: The eBay return ID.
            amount: Refund amount.
            currency: Currency code (default "USD").

        Returns:
            API response dict.
        """
        payload = {
            "refundDetail": {
                "refundAmount": {"currency": currency, "value": str(amount)}
            }
        }
        return self._post(f"/post-order/v2/return/{return_id}/issue_refund", json=payload)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = urljoin(self.base_url, path)
        response = self._session.get(
            url,
            headers=self._auth_headers(),
            params=params,
            timeout=30,
        )
        self._raise_for_status(response)
        return response.json()

    def _post(self, path: str, json: Optional[dict] = None) -> dict:
        url = urljoin(self.base_url, path)
        response = self._session.post(
            url,
            headers=self._auth_headers(),
            json=json,
            timeout=30,
        )
        self._raise_for_status(response)
        return response.json() if response.content else {}

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
        }

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if not response.ok:
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text}
            raise EbayApiError(
                status_code=response.status_code,
                message=response.reason or "Unknown error",
                response=body,
            )
