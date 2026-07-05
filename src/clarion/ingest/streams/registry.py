"""Stream-type registry.

Maps the `source_type` string stored in the `stream` table to the spec
that knows how to validate and fetch that type. This is the one
sanctioned cross-domain contract: the collector runs specs, the catalog
writes stream rows, the CLI validates and describes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Type

from pydantic import BaseModel

from clarion.ingest.streams import rss, sitemap_news
from clarion.ingest.streams.base import Fetcher


class FormField(NamedTuple):
    """One user-facing config input: the config field it fills, the label
    to prompt with, and the default to offer (None = required)."""

    name: str
    label: str
    default: str | None = None


@dataclass(frozen=True)
class StreamSpec:
    """Everything the runtime knows about one stream type."""

    source_type: str
    config_cls: Type[BaseModel]
    fetch: Fetcher
    # One-line human description of a config (the polled URL, typically).
    # Lets consumers render stream lists without importing config classes.
    describe: Callable[[Any], str]
    # The inputs an add-stream flow asks for; everything else keeps its
    # config default.
    form_fields: tuple[FormField, ...]


SPECS: Dict[str, StreamSpec] = {
    rss.SOURCE_TYPE: StreamSpec(
        source_type=rss.SOURCE_TYPE,
        config_cls=rss.RSSStreamConfig,
        fetch=rss.fetch,
        describe=lambda cfg: str(cfg.feed_url),
        form_fields=(
            FormField("feed_url", "Feed URL (RSS or Atom)"),
            FormField("poll_seconds", "Poll interval (seconds)", "300"),
        ),
    ),
    sitemap_news.SOURCE_TYPE: StreamSpec(
        source_type=sitemap_news.SOURCE_TYPE,
        config_cls=sitemap_news.SitemapNewsStreamConfig,
        fetch=sitemap_news.fetch,
        describe=lambda cfg: cfg.sitemap_url,
        form_fields=(
            FormField(
                "sitemap_url",
                "Sitemap URL (e.g. https://www.bloomberg.com/sitemaps/news/latest.xml)",
            ),
            FormField("publication_name", "Publication display name (blank = stream name)", ""),
            FormField("poll_seconds", "Poll interval (seconds)", "120"),
        ),
    ),
}


def build_config_json(source_type: str, fields: Mapping[str, str]) -> str:
    """Validate raw string inputs into a stream's config JSON — the one
    add-stream path, whatever the surface (CLI prompts, a future form).
    Blank values are dropped so config defaults apply; pydantic coerces
    the rest ('300' -> 300). Raises KeyError on an unknown type and
    ValueError (pydantic's ValidationError) on bad input."""
    spec = get(source_type)
    data = {k: v for k, v in fields.items() if v != ""}
    return spec.config_cls.model_validate(data).model_dump_json()


def get(source_type: str) -> StreamSpec:
    if source_type not in SPECS:
        raise KeyError(f"Unknown stream type: {source_type!r}")
    return SPECS[source_type]


def all_specs() -> Dict[str, StreamSpec]:
    return dict(SPECS)


def describe_stream_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Decorate raw `stream` table rows for display: parsed enabled flag,
    a one-line detail, and any config-validation error. Registry-driven —
    no per-type branching at call sites."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        entry = {
            "name": row["name"],
            "source_type": row["source_type"],
            "enabled": True,
            "detail": "",
            "error": None,
        }
        try:
            spec = get(row["source_type"])
            cfg = spec.config_cls.model_validate_json(row["config_json"])
            entry["enabled"] = getattr(cfg, "enabled", True)
            entry["detail"] = spec.describe(cfg)
        except Exception as exc:
            entry["error"] = str(exc)
            entry["enabled"] = False
        out.append(entry)
    return out
