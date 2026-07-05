"""Small text/url helpers shared by the digest builder and the web UI.

Deliberately dependency-free: clarion.web imports this, and the web
process must keep running without the optional ML extra installed.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

# Some sitemap "titles" are whole paragraphs (live-blog minutes); cap what
# we feed the encoder. Display always uses the stored event title.
MAX_TITLE_CHARS = 300
_WS = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    return _WS.sub(" ", title).strip()[:MAX_TITLE_CHARS]


def source_domain(url: Optional[str], stream_name: str) -> str:
    """Publication identity for coverage counting: the url host minus
    www., falling back to the stream name for url-less items."""
    if url:
        netloc = urlsplit(url).netloc.lower()
        netloc = netloc.rpartition("@")[2].partition(":")[0]
        netloc = netloc.removeprefix("www.")
        if netloc:
            return netloc
    return stream_name
