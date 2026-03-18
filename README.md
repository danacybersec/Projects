# eBay Customer Interaction Automation System

A Python-based automation system for eBay sellers that handles common
customer communication workflows — shipping notifications, order updates,
review requests, return/refund handling, and analytics.

Built for the [kaimerch](https://www.ebay.com/str/kaimerch) eBay store and
designed to be reusable by any eBay seller.

---

## Features

| Feature | Description |
|---|---|
| **Message Management** | Categorise incoming messages and send automated responses using customisable Jinja2 templates |
| **Order Notifications** | Shipping confirmations with carrier tracking links, in-transit updates, and delivery confirmations |
| **Review Automation** | Send review requests N days after delivery; draft responses to received feedback; alert on negative reviews |
| **Customer Service** | Acknowledge return requests, send refund status updates, escalate stale cases |
| **Analytics** | Track response rates, satisfaction scores, and daily interaction metrics |
| **Configuration** | YAML config files per store; all templates fully customisable |

---

## Project Structure

```
ebay-projects/
├── src/
│   ├── automation/
│   │   ├── engine.py           # Core automation engine + scheduler
│   │   ├── message_manager.py  # Message categorisation & auto-response
│   │   ├── order_manager.py    # Shipping / delivery notifications
│   │   ├── review_manager.py   # Review requests & feedback responses
│   │   └── customer_service.py # Returns, refunds & escalations
│   ├── api/
│   │   └── ebay_client.py      # eBay REST API client (OAuth 2.0)
│   ├── templates/
│   │   └── message_templates.py# Jinja2 message template system
│   ├── database/
│   │   └── db_manager.py       # SQLite persistence layer (SQLAlchemy)
│   └── analytics/
│       └── metrics.py          # Analytics & daily reporting
├── config/
│   ├── config.yaml             # Default configuration template
│   └── kaimerch.yaml           # kaimerch store configuration
├── examples/
│   ├── basic_usage.py          # Quick-start script
│   └── seo_listing_examples.md # SEO best practices from kaimerch
├── tests/
│   ├── test_message_manager.py
│   ├── test_order_manager.py
│   └── test_templates.py
├── docs/
│   └── PROJECT_OVERVIEW.md
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your store

Copy and edit the default config:

```bash
cp config/config.yaml config/config.local.yaml
```

Set your eBay API credentials (never commit these):

```bash
export EBAY_CLIENT_ID="your-client-id"
export EBAY_CLIENT_SECRET="your-client-secret"
```

Or put them directly in `config.local.yaml` (listed in `.gitignore`).

### 3. Run the automation once

```bash
EBAY_AUTOMATION_CONFIG=config/config.local.yaml python examples/basic_usage.py
```

### 4. Run tests

```bash
pytest tests/
```

---

## Configuration

All settings live in YAML files under `config/`.

Key sections:

```yaml
store:
  id: "kaimerch"
  name: "kaimerch"
  ebay_username: "kaimerch"

messaging:
  auto_respond: true
  max_auto_responses_per_run: 100

orders:
  notify_on_ship: true
  notify_on_delivery: true
  transit_update_days: 3

reviews:
  request_delay_days: 3
  auto_respond_feedback: true
  negative_alert_enabled: true

customer_service:
  auto_acknowledge_returns: true
  escalation_threshold_days: 5

schedule:
  message_check_interval_minutes: 15
  order_check_interval_minutes: 30
  review_request_time: "09:00"
  analytics_report_time: "18:00"
```

Message templates are fully customisable per store — see `config/kaimerch.yaml`
for examples.

---

## eBay API Setup

1. Register a developer account at <https://developer.ebay.com>
2. Create an application to get your **Client ID** and **Client Secret**
3. Set the credentials via environment variables or in your local config file

The `EbayClient` class handles OAuth 2.0 token refresh automatically.

---

## SEO Listing Examples

See [`examples/seo_listing_examples.md`](examples/seo_listing_examples.md) for
real-world listing examples from the kaimerch store, covering:

- Title optimisation (keywords, model numbers, compatibility)
- Item specifics best practices
- Structured description templates
- Per-listing SEO checklist

---

## Goals

- Reduce time spent on repetitive customer communications
- Improve response times and consistency across all buyer interactions
- Maintain a professional, on-brand voice in every message
- Provide actionable analytics to track store performance