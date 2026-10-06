"""Logging that scrubs values this plugin should never write down."""

from __future__ import annotations

import logging

from ecommerce_agent.redaction import redact

LOGGER_NAME = "ecommerce_agent"


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(item) if isinstance(item, str) else item for item in record.args)
        return True


def configure_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(item, RedactFilter) for item in logger.filters):
        logger.addFilter(RedactFilter())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
