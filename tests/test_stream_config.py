"""build_config_json: the one raw-inputs -> stream config path."""

from __future__ import annotations

import json

import pytest

from clarion.ingest.streams import all_specs, build_config_json


def test_blank_inputs_fall_back_to_config_defaults():
    cfg = json.loads(
        build_config_json("rss", {"feed_url": "https://example.com/feed.xml", "poll_seconds": ""})
    )
    assert cfg["poll_seconds"] == 300
    assert cfg["enabled"] is True


def test_string_inputs_are_coerced():
    cfg = json.loads(
        build_config_json(
            "sitemap_news",
            {"sitemap_url": "https://example.com/news.xml", "poll_seconds": "60"},
        )
    )
    assert cfg["poll_seconds"] == 60
    assert cfg["publication_name"] == ""


def test_invalid_input_raises_value_error():
    with pytest.raises(ValueError):
        build_config_json("rss", {"feed_url": "not a url"})
    with pytest.raises(ValueError):
        build_config_json("rss", {"feed_url": ""})  # dropped -> required missing


def test_unknown_type_raises_key_error():
    with pytest.raises(KeyError):
        build_config_json("carrier_pigeon", {})


def test_form_fields_name_real_config_fields():
    for spec in all_specs().values():
        unknown = {f.name for f in spec.form_fields} - set(spec.config_cls.model_fields)
        assert not unknown, f"{spec.source_type}: {unknown}"
