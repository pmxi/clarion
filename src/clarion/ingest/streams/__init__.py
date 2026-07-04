"""Shared stream abstractions and built-in stream implementations."""

from clarion.ingest.streams.base import Item, Stream
from clarion.ingest.streams.registry import (
    all_specs,
    build_stream,
    describe_stream_rows,
    ensure_loaded,
    get,
)

__all__ = [
    "Item",
    "Stream",
    "all_specs",
    "build_stream",
    "describe_stream_rows",
    "ensure_loaded",
    "get",
]
