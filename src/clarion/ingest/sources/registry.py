"""Stream-type registry.

Maps the `stream_type` string stored in the `streams` table to the
(Stream class, config class) pair that knows how to build and validate
accounts of that type. New stream types register themselves here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Type

from pydantic import BaseModel

from clarion.ingest.sources.base import Stream


@dataclass(frozen=True)
class StreamSpec:
    """Describes how to instantiate and configure one stream type."""

    stream_type: str
    config_cls: Type[BaseModel]
    stream_cls: Type[Stream]
    # One-line human description of a config (the polled URL, typically).
    # Lets consumers render stream lists without importing config classes.
    describe: Callable[[BaseModel], str] = field(default=lambda cfg: "")


_REGISTRY: Dict[str, StreamSpec] = {}


def register(spec: StreamSpec) -> None:
    if spec.stream_type in _REGISTRY:
        raise ValueError(f"Stream type {spec.stream_type!r} already registered")
    _REGISTRY[spec.stream_type] = spec


def get(stream_type: str) -> StreamSpec:
    if stream_type not in _REGISTRY:
        raise KeyError(f"Unknown stream type: {stream_type!r}")
    return _REGISTRY[stream_type]


def all_specs() -> Dict[str, StreamSpec]:
    return dict(_REGISTRY)


def build_stream(
    stream_type: str,
    name: str,
    config_json: str,
    **extra: Any,
) -> Stream:
    """Instantiate a stream from serialized config."""
    spec = get(stream_type)
    config = spec.config_cls.model_validate_json(config_json)
    return spec.stream_cls(
        name=name,
        config=config,
        **extra,
    )


def _register_builtins() -> None:
    """Register the shipped stream types. Import-order-safe: we delay the
    imports until first call to avoid circular refs at module load."""
    if _REGISTRY:
        return
    from clarion.ingest.sources.rss.config import RSSStreamConfig
    from clarion.ingest.sources.rss.stream import RSSStream
    from clarion.ingest.sources.sitemap_news.config import SitemapNewsStreamConfig
    from clarion.ingest.sources.sitemap_news.stream import SitemapNewsStream

    register(
        StreamSpec(
            stream_type="rss",
            config_cls=RSSStreamConfig,
            stream_cls=RSSStream,
            describe=lambda cfg: str(cfg.feed_url),
        )
    )
    register(
        StreamSpec(
            stream_type="sitemap_news",
            config_cls=SitemapNewsStreamConfig,
            stream_cls=SitemapNewsStream,
            describe=lambda cfg: cfg.sitemap_url,
        )
    )


def ensure_loaded() -> None:
    """Call before looking up specs; idempotent."""
    _register_builtins()


def describe_stream_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Decorate raw `stream` table rows for display: parsed enabled flag,
    a one-line detail, and any config-validation error. Registry-driven —
    no per-type branching at call sites."""
    ensure_loaded()
    out: List[Dict[str, Any]] = []
    for row in rows:
        entry = {
            "name": row["name"],
            "stream_type": row["stream_type"],
            "enabled": True,
            "detail": "",
            "error": None,
        }
        try:
            spec = get(row["stream_type"])
            cfg = spec.config_cls.model_validate_json(row["config_json"])
            entry["enabled"] = getattr(cfg, "enabled", True)
            entry["detail"] = spec.describe(cfg)
        except Exception as exc:
            entry["error"] = str(exc)
            entry["enabled"] = False
        out.append(entry)
    return out
