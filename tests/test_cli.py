"""CLI surface smoke test: every advertised command still parses."""

from clarion.cli import parse_cli


def test_commands_parse():
    for argv in (
        ["run"],
        ["status"],
        ["stream", "list"],
        ["digest", "run", "--poll-seconds", "5"],
        ["digest", "build", "--day", "2026-01-01", "--dry-run"],
        ["db", "migrate"],
        ["catalog", "materialize", "--dry-run"],
        ["catalog", "sync", "--limit", "10"],
        ["catalog", "discover-sitemaps"],
        ["catalog", "discover-feeds"],
        ["dev", "firehose", "--count", "1"],
    ):
        args = parse_cli(argv)
        assert callable(args.func), argv


def test_passthrough_flags_are_forwarded():
    args = parse_cli(["catalog", "sync", "--limit", "10", "--dry-run"])
    assert args.args == ["--limit", "10", "--dry-run"]
