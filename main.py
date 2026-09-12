"""premortem CLI.

    python3 main.py elicit
    python3 main.py report household.toml -o out.pdf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_elicit(args: argparse.Namespace) -> int:
    from elicit.app import PremortemApp

    app = PremortemApp()
    app.run()
    if app.saved_path:
        print(f"Saved {app.saved_path}")
        return 0
    print("No household saved.", file=sys.stderr)
    return 1


def cmd_report(args: argparse.Namespace) -> int:
    import tomllib

    import model
    import shocks
    import runway
    from report.render import render_pdf

    try:
        text = Path(args.household_toml).read_text()
    except FileNotFoundError:
        print(f"error: no such file: {args.household_toml}", file=sys.stderr)
        return 1
    except IsADirectoryError:
        print(f"error: {args.household_toml} is a directory, not a file", file=sys.stderr)
        return 1

    try:
        household = model.from_toml(text)
    except tomllib.TOMLDecodeError as exc:
        print(f"error: {args.household_toml} is not valid TOML: {exc}", file=sys.stderr)
        return 1
    except (KeyError, ValueError) as exc:
        print(f"error: {args.household_toml} is missing or has invalid data: {exc}", file=sys.stderr)
        return 1

    projections = [runway.project(household, s) for s in shocks.presets(household)]
    render_pdf(household, projections, Path(args.output))
    print(f"Wrote {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="premortem")
    subparsers = parser.add_subparsers(dest="command", required=True)

    elicit_parser = subparsers.add_parser("elicit", help="Run the guided walkthrough and save a household TOML file.")
    elicit_parser.set_defaults(func=cmd_elicit)

    report_parser = subparsers.add_parser("report", help="Load a household TOML file and render the PDF report.")
    report_parser.add_argument("household_toml")
    report_parser.add_argument("-o", "--output", default="premortem.pdf")
    report_parser.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
