import logging
import sys
from typing import Any, Dict, Optional
import structlog
from nexus.config import settings


def configure_logger() -> None:
    """Configures structlog and standard logging libraries for consistent structured logs."""
    # Determine which renderer to use based on the environment
    is_prod = settings.env.lower() == "production"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if is_prod:
        # JSON logs for production (excellent for aggregators like Kibana, Loki)
        renderer = structlog.processors.JSONRenderer()
    else:
        # Readable, colorized console output for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure standard logging to redirect through structlog if needed, or set base level
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO if is_prod else logging.DEBUG,
    )

    structlog.configure(
        processors=shared_processors + [renderer],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


# Configure logging immediately upon import
configure_logger()


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Returns a structured logger with an optional context name.

    Args:
        name: Name of the component or module to bind to the logger.

    Returns:
        BoundLogger: A structured logger instance.
    """
    logger = structlog.get_logger()
    if name:
        return logger.bind(logger_name=name)
    return logger
