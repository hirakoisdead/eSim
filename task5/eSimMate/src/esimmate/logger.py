"""
Logging Manager Module.
Configures dual console and rotating persistent file logging.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


class LoggingManager:
    """Manages application logging setup and file routing."""

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        log_level: int = logging.INFO,
    ) -> None:
        self.log_dir = log_dir or Path("logs")
        self.log_level = log_level
        self._logger: Optional[logging.Logger] = None

    def setup_logging(self) -> logging.Logger:
        """Initialize console and file logger."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / "esimmate.log"

        logger = logging.getLogger("esimmate")
        logger.setLevel(self.log_level)

        # Ensure a file handler targeting current log_file path exists
        resolved_path_str = str(log_file.resolve())
        has_matching_handler = any(
            isinstance(h, RotatingFileHandler) and str(Path(getattr(h, "baseFilename", "")).resolve()) == resolved_path_str
            for h in logger.handlers
        )

        if not has_matching_handler:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)

        self._logger = logger
        return logger

    def get_logger(self) -> logging.Logger:
        """Return configured logger instance."""
        if self._logger is None:
            return self.setup_logging()
        return self._logger
