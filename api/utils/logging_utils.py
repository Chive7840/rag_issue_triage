"""Centralized logging utilities for the RAG triage copilot.

This module provides a JSON formatter, structured context propagation, and helper APIs for
configuring application-wide logging. The design intentionally avoids side effects on import
to keep configuration explicit for the API, worker, and any auxiliary scripts.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Iterable, Iterator, Mapping, MutableMapping, Optional

__all__= [
    "setup_logging",
    "get_logger",
    "bind_context",
    "clear_context",
    "logging_context",
]

_LOG_CONTEXT: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "rag_triage_log_context", default={}
)

def _deepcopy_context(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy that is safe to mutate downstream."""
    return dict(data)

class JsonFormatter(logging.Formatter):
    """JSON formatter with consistent keys for ingestion pipelines."""

    default_msec_format = "%s.%03d"

    def format(self, record: logging.LogRecord) -> str:     # noqa: D401
        base: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%s", time.gmtime(record.created))
            + f".{int(record.msecs):03d}z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        context = _deepcopy_context(_LOG_CONTEXT.get())
        context.update(getattr(record, "context", {}))
        if context:
            base["context"] = context
        if record.stack_info:
            base["stack"] = self.formatStack(record.stack_info)
        return json.dumps(base, ensure_ascii=False)

class ContextualAdapter(logging.LoggerAdapter):
    """LoggerAdapter that merges structured context with each record."""

    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        context = _deepcopy_context(_LOG_CONTEXT.get())
        if "extra" in kwargs:
            extra = dict(kwargs["extra"])
        else:
            extra = {}
        provided_context = extra.pop("context", {})
        context.update(provided_context)
        extra.setdefault("context", context)
        kwargs["extra"] = extra
        return msg, kwargs

def setup_logging(*, level: Optional[str] = None, use_json: bool = True) -> None:
    """Configure root logging for the application.

    :param level:
            Optional log level name. Defaults to the ``LOG_LEVEL`` env value or ``INFO`` when not provided.
    :param use_json:
            When ``True`` (default) installs :class JsonFormatter.
            Set to ``False`` to use the standard formatter for local debugging.
    """

    log_level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    formatter: logging.Formatter
    if use_json:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%s"
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

def get_logger(name: str | None = None) -> ContextualAdapter:
    """Return a context-aware logger for the given name."""

    return ContextualAdapter(logging.getLogger(name), {})

def bind_context(**kwargs: Any) -> contextvars.Token[Dict[str, Any]]:
    """Bind key-value pairs to the current logging context.

    Returns a token that can be passed to :func:`clear_context` or
    used via the :func:`logging_context` context manager.
    """

    current = _deepcopy_context(_LOG_CONTEXT.get())
    current.update({k: v for k, v in kwargs.items() if v is not None})
    return _LOG_CONTEXT.set(current)

def clear_context(token: contextvars.Token[Dict[str, Any]]) -> None:
    """Revert to the previous logging context using the provided token."""

    _LOG_CONTEXT.reset(token)

@contextlib.contextmanager
def logging_context(**kwargs: Any) -> Iterator[None]:
    """Context manager for temporarily binding logging metadata."""

    token = bind_context(**kwargs)
    try:
        yield
    finally:
        clear_context(token)

def iter_context() -> Iterable[tuple[str, Any]]:
    """Expose the current context for diagnostics/testing purposes."""

    return _deepcopy_context(_LOG_CONTEXT.get()).items()