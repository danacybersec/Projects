"""
Basic usage example for the eBay Customer Interaction Automation System.

This script demonstrates how to:
1. Load configuration
2. Initialise the AutomationEngine
3. Run all automation tasks once (useful for testing or cron-based setups)
4. Start the full scheduler loop

Run:
    python examples/basic_usage.py
"""

import logging
import os
import sys

import yaml

# Allow running from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.automation.engine import AutomationEngine

# ---------------------------------------------------------------------------
# Configure logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def main() -> None:
    config_path = os.environ.get(
        "EBAY_AUTOMATION_CONFIG",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml"),
    )

    logger.info("Loading configuration from: %s", config_path)
    config = load_config(config_path)

    engine = AutomationEngine(config)

    # -----------------------------------------------------------------------
    # Option 1: Run all tasks once and exit (good for cron jobs)
    # -----------------------------------------------------------------------
    logger.info("Running all automation tasks once…")
    results = engine.run_all_now()
    for task, status in results.items():
        logger.info("  %-20s → %s", task, status)

    # -----------------------------------------------------------------------
    # Option 2: Start the blocking scheduler loop (uncomment to enable)
    # -----------------------------------------------------------------------
    # logger.info("Starting scheduler loop (Ctrl+C to stop)…")
    # engine.start(blocking=True)


if __name__ == "__main__":
    main()
