from __future__ import annotations

import logging
from typing import Any

import structlog

_SENSITIVE_MARKERS = (
    "authorization",
    "token",
    "secret",
    "api_key",
    "init_data",
    "phone",
    "text",
    "body",
)
_MASK = "***"


def _is_sensitive_key(key: object) -> bool:
    lowered = str(key).lower()
    return any(marker in lowered for marker in _SENSITIVE_MARKERS)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (_MASK if _is_sensitive_key(k) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(v) for v in value]
    return value


def mask_sensitive(
    logger: object, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    return _redact(event_dict)


def configure_logging(env: str) -> None:
    level = logging.DEBUG if env in {"local", "test"} else logging.INFO
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        mask_sensitive,
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
