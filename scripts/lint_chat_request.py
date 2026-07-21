#!/usr/bin/env python3
"""Lint a chat_request*.json for conflicting open rules (ZC-35 / ZC-36).

Read-only: never rewrites contract-locked content.

Examples::

  python scripts/lint_chat_request.py path/to/chat_request.json
  python scripts/lint_chat_request.py path/to/chat_request.json --json
  python scripts/lint_chat_request.py --fail-on hard path/to/chat_request.json
  python scripts/lint_chat_request.py --schema
  python scripts/lint_chat_request.py --policy

Exit codes:
  0  report produced (or severity below --fail-on threshold)
  1  load error, or findings meet/exceed --fail-on policy
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zeus_client import hash_policy_summary, lint_chat_request
from zeus_client.zeus.lint import (
    resolve_lint_config,
    structured_rule_schema,
)


def _load_doc(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint chat_request open rules for conflicts (ZC-35/ZC-36)",
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=None,
        help="Path to a chat_request*.json file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit ConflictReport as JSON instead of text",
    )
    parser.add_argument(
        "--fail-on",
        choices=("none", "hard", "low", "medium", "high"),
        default=None,
        help=(
            "Exit 1 when findings meet this policy. "
            "'hard' fails on hard or open_vs_locked findings (CI default). "
            "Severity bands use overall conflict score band."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("off", "assemble", "debug", "ci"),
        default=None,
        help="Override catalog_lint.mode (default: assemble for CLI)",
    )
    parser.add_argument(
        "--no-soft",
        action="store_true",
        help="Disable soft NL heuristics (hard + open-vs-locked only)",
    )
    parser.add_argument(
        "--no-hard",
        action="store_true",
        help="Disable structured hard conflict checks",
    )
    parser.add_argument(
        "--no-open-vs-locked",
        action="store_true",
        help="Disable open-vs-locked checks",
    )
    parser.add_argument(
        "--policy",
        action="store_true",
        help="Print locked vs open hash policy and exit",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print structured open-rule schema (V2) and exit",
    )
    args = parser.parse_args(argv)

    if args.policy:
        print(json.dumps(hash_policy_summary(), indent=2))
        return 0
    if args.schema:
        print(json.dumps(structured_rule_schema(), indent=2))
        return 0

    path = args.path
    if path is None:
        parser.error("path is required unless --policy or --schema is set")
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    try:
        doc = _load_doc(path)
    except Exception as exc:
        print(f"ERROR: failed to load {path}: {exc}", file=sys.stderr)
        return 1

    overrides: dict = {"mode": args.mode or "assemble"}
    if args.no_soft:
        overrides["soft_nl"] = False
    if args.no_hard:
        overrides["hard_conflicts"] = False
    if args.no_open_vs_locked:
        overrides["open_vs_locked"] = False
    if args.fail_on is not None:
        overrides["fail_on"] = args.fail_on

    cfg = resolve_lint_config(doc, overrides=overrides)
    report = lint_chat_request(doc, config=cfg)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"catalog: {path}")
        print(report.format_text())

    fail_on = args.fail_on if args.fail_on is not None else cfg.fail_on
    if report.meets_fail_on(fail_on):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
