"""Shared stream contract and the built-in stream types."""

from clarion.ingest.streams.base import Item
from clarion.ingest.streams.registry import (
    StreamSpec,
    all_specs,
    describe_stream_rows,
    get,
)

__all__ = [
    "Item",
    "StreamSpec",
    "all_specs",
    "describe_stream_rows",
    "get",
]
