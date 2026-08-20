"""
Tests for Logging Manager module.
"""

import logging
from esimmate.logger import LoggingManager


def test_logging_manager_setup(tmp_path):
    log_dir = tmp_path / "logs"
    manager = LoggingManager(log_dir=log_dir, log_level=logging.DEBUG)
    logger = manager.setup_logging()

    assert logger.name == "esimmate"
    logger.info("Test log event message")
    assert (log_dir / "esimmate.log").exists()
