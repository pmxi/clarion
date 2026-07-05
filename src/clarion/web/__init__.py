"""Clarion web UI.

A standalone Flask app and admin/control plane that reads the collector's
append-only `event` table and manages stream config. Deployed as its own
process (entry point `clarion-web`); it shares the Postgres database with
the collector but runs independently of it.
"""
