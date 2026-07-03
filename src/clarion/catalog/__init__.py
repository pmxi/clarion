"""Catalog: the source-coverage domain.

Wraps the Media Cloud publisher catalog (Postgres schema `sources`):
syncing it, discovering news sitemaps and RSS feeds per publisher, and
materializing catalog rows into runtime `stream` rows for the collector.
"""
