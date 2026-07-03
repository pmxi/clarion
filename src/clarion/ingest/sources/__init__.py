"""Shared stream abstractions and built-in stream implementations."""

from clarion.ingest.sources.base import Item, Stream
from clarion.ingest.sources.registry import (
    StreamSpec,
    all_specs,
    build_stream,
    describe_stream_rows,
    ensure_loaded,
    get,
    register,
)

__all__ = [
    "Item",
    "Stream",
    "StreamSpec",
    "all_specs",
    "build_stream",
    "describe_stream_rows",
    "ensure_loaded",
    "get",
    "register",
]
