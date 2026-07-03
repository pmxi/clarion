"""CLI surface smoke test: every advertised command still parses."""

from clarion.cli import build_parser


def test_commands_parse():
    parser = build_parser()
    for argv in (
        ["init"],
        ["run"],
        ["stream", "list"],
        ["digest", "build", "--day", "2026-01-01", "--dry-run"],
        ["sources", "materialize", "--dry-run"],
        ["dev", "firehose", "--count", "1"],
    ):
        args = parser.parse_args(argv)
        assert callable(args.func), argv
