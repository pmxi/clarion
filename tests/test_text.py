"""Pure text/url helpers: digest.text and catalog.canonicalize."""

from __future__ import annotations

from clarion.catalog.canonicalize import canonical_domain
from clarion.digest.text import MAX_TITLE_CHARS, normalize_lang, normalize_title, source_domain


def test_normalize_title_collapses_whitespace_and_caps_length():
    assert normalize_title("  a\n\tb   c ") == "a b c"
    assert len(normalize_title("x" * 1000)) == MAX_TITLE_CHARS


def test_source_domain_strips_www_port_and_userinfo():
    assert source_domain("https://www.example.com/a", "s") == "example.com"
    assert source_domain("http://example.com:8080/a", "s") == "example.com"
    assert source_domain("http://user:pw@example.com/a", "s") == "example.com"


def test_source_domain_falls_back_to_stream_name():
    assert source_domain(None, "my-stream") == "my-stream"
    assert source_domain("not a url", "my-stream") == "my-stream"


def test_normalize_lang():
    assert normalize_lang("EN-us") == "en"
    assert normalize_lang(" fr ") == "fr"
    assert normalize_lang("") is None
    assert normalize_lang(None) is None


def test_canonical_domain_variants_collapse():
    assert canonical_domain("http://example.com") == "example.com"
    assert canonical_domain("https://www.example.com/") == "example.com"
    assert canonical_domain("Example.com:8080/path") == "example.com"
    assert canonical_domain("example.com") == "example.com"


def test_canonical_domain_rejects_empty():
    assert canonical_domain(None) is None
    assert canonical_domain("   ") is None
    assert canonical_domain("http://") is None
