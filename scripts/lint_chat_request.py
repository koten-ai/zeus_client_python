#!/usr/bin/env python3
"""Lint a chat_request*.json for conflicting open (hash-excluded) rules (ZC-35).

Read-only: never rewrites contract-locked content.

Examples::

  python scripts/lint_chat_request.py path/to/chat_request.json
  python scripts/lint_chat_request.py path/to/chat_request.json --json
  python scripts/lint_chat_request.py --fail-on high path/to/chat_request.json

Exit codes:
  0  report produced (or severity below --fail-on threshold)
  1  load error, or findings meet/exceed --fail-on severity
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zeus_client import hash_policy_summary, lint_chat_request


_SEV_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _load_doc(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint chat_request open rules for conflicts (ZC-35)",
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
        choices=("low", "medium", "high"),
        default=None,
        help="Exit 1 when report severity is at least this band (default: always 0)",
    )
    parser.add_argument(
        "--policy",
        action="store_true",
        help="Print locked vs open hash policy and exit",
    )
    args = parser.parse_args(argv)

    if args.policy:
        print(json.dumps(hash_policy_summary(), indent=2))
        return 0

    path = args.path
    if path is None:
        parser.error("path is required unless --policy is set")
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    try:
        doc = _load_doc(path)
    except Exception as exc:
        print(f"ERROR: failed to load {path}: {exc}", file=sys.stderr)
        return 1

    report = lint_chat_request(doc)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"catalog: {path}")
        print(report.format_text())

    if args.fail_on is not None:
        if _SEV_RANK.get(report.severity, 0) >= _SEV_RANK[args.fail_on]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
