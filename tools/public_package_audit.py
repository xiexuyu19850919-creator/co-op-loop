#!/usr/bin/env python3
"""Deterministic, local-only audit for the public CO-OP Loop candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


PUBLIC_FILES = (
    "README.md",
    "README.en.md",
    "LICENSE",
    "VERSION",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    ".gitignore",
    "docs/why-co-op-loop.zh-CN.md",
    "tools/public_package_audit.py",
    "tools/test_public_package_audit.py",
    ".github/ISSUE_TEMPLATE/1-bug-report.yml",
    ".github/ISSUE_TEMPLATE/2-compatibility-report.yml",
    ".github/ISSUE_TEMPLATE/3-feature-request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/compatibility.yml",
    "co-op-loop/SKILL.md",
    "co-op-loop/agents/openai.yaml",
    "co-op-loop/references/host-adaptation.md",
    "co-op-loop/references/loop-protocol.md",
    "co-op-loop/references/storage-adaptation.md",
    "co-op-loop/scripts/scenario_tests.py",
    "co-op-loop/scripts/storage_preflight.py",
)

EXPECTED_DIRS = {
    "co-op-loop",
    "co-op-loop/agents",
    "co-op-loop/references",
    "co-op-loop/scripts",
    "docs",
    "tools",
    ".github",
    ".github/ISSUE_TEMPLATE",
    ".github/workflows",
}


def _word(parts: tuple[int, ...]) -> str:
    return "".join(chr(part) for part in parts)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _masked(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse_flag)


def _patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    username = _word((65, 100, 109, 105, 110, 105, 115, 116, 114, 97, 116, 111, 114))
    internal = (
        _word((66, 111, 115, 115)),
        _word((75, 79, 83)),
        _word((83, 112, 97, 114, 107)),
        _word((70, 108, 97, 114, 101)),
    )
    keys = tuple(
        "".join(chars)
        for chars in (
            ("t", "o", "k", "e", "n"),
            ("a", "p", "i", "_", "k", "e", "y"),
            ("s", "e", "c", "r", "e", "t"),
            ("p", "a", "s", "s", "w", "o", "r", "d"),
            ("c", "r", "e", "d", "e", "n", "t", "i", "a", "l"),
            ("c", "o", "o", "k", "i", "e"),
        )
    )
    key_expr = "|".join(re.escape(key) for key in keys)
    assignment = rf"(?i)\b(?:{key_expr})\b\s*[:=]\s*(['\"])([^'\"]+)\1"
    bearer = _word((66, 101, 97, 114, 101, 114))
    bearer_expr = rf"(?i)\b{re.escape(bearer)}\b\s+(['\"])([^'\"]+)\1"
    slash = chr(92)
    colon = chr(58)
    posix_slash = chr(47)
    windows_drive = r"(?i)(?:\b[A-Z]" + re.escape(colon + slash) + r")"
    unc_root = re.escape(slash + slash)
    unc_path = unc_root + r"[^\s\/]+" + re.escape(slash) + r"[^\s\/]+"
    posix_roots = (
        posix_slash + _word((104, 111, 109, 101)) + posix_slash,
        posix_slash + _word((85, 115, 101, 114, 115)) + posix_slash,
    )
    posix_home = r"(?:" + "|".join(re.escape(root) for root in posix_roots) + r")[^\s/]+"
    return (
        ("uuid_or_task_id", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
        ("windows_or_unc_path", re.compile(windows_drive + "|" + unc_path)),
        ("posix_home_path", re.compile("(?i)" + posix_home)),
        ("known_username", re.compile(rf"(?i)\b{re.escape(username)}\b")),
        ("internal_name", re.compile("|".join(re.escape(value) for value in internal))),
        ("credential_assignment", re.compile(assignment)),
        ("bearer_value", re.compile(bearer_expr)),
        ("private_key_header", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
    )


def _is_allowed_protocol_reference(relative_path: str, line: str, match: str) -> bool:
    if relative_path in {"README.md", "README.en.md"} and match == ".coop-loop/state.yaml":
        return True
    if relative_path == ".gitignore" and ("pycache" in line or ".pyc" in line or ".pyo" in line):
        return True
    if (
        relative_path == "co-op-loop/scripts/scenario_tests.py"
        and "endswith(" in line
        and match.startswith(chr(92) + chr(92))
        and ("state.yaml" in line or ("logs" + chr(92) * 2 + "reports") in line)
    ):
        return True
    if match in {"token", "secret", "password", "cookie", "credential"} and "=" not in line and ":" not in line:
        return True
    return False


def _inventory(root: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    actual_files: list[str] = []
    actual_dirs: list[str] = []
    reparse: list[str] = []
    unknown: list[str] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(root).as_posix() if current_path != root else ""
        kept_dirs: list[str] = []
        for name in sorted(directories):
            path = current_path / name
            relative = (Path(relative_current) / name).as_posix() if relative_current else name
            if _is_reparse(path):
                reparse.append(relative)
                continue
            actual_dirs.append(relative)
            kept_dirs.append(name)
            if relative not in EXPECTED_DIRS:
                unknown.append(relative)
        directories[:] = kept_dirs
        for name in sorted(files):
            path = current_path / name
            relative = (Path(relative_current) / name).as_posix() if relative_current else name
            if _is_reparse(path):
                reparse.append(relative)
                continue
            actual_files.append(relative)
            if relative not in PUBLIC_FILES:
                unknown.append(relative)
    return sorted(actual_files), sorted(actual_dirs), sorted(reparse), sorted(set(unknown))


def _read_text(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def audit(root: Path) -> tuple[dict[str, Any], int]:
    root = root.resolve(strict=True)
    if not root.is_dir() or _is_reparse(root):
        raise ValueError("root must be a non-reparse directory")

    actual_files, actual_dirs, reparse, unknown = _inventory(root)
    missing = sorted(set(PUBLIC_FILES) - set(actual_files))
    issues: list[dict[str, Any]] = []
    issues.extend(
        {
            "category": "reparse_or_symlink",
            "relative_path": path,
            "line": 0,
            "masked_preview": "***",
            "match_sha256": _sha256(path.encode("utf-8")),
        }
        for path in reparse
    )
    issues.extend(
        {
            "category": "unauthorized_file",
            "relative_path": path,
            "line": 0,
            "masked_preview": _masked(path),
            "match_sha256": _sha256(path.encode("utf-8")),
        }
        for path in unknown
    )

    patterns = _patterns()
    for relative in actual_files:
        if relative not in PUBLIC_FILES:
            continue
        path = root / Path(relative)
        try:
            lines = _read_text(path)
        except (OSError, UnicodeError) as exc:
            issues.append(
                {
                    "category": "unreadable_text",
                    "relative_path": relative,
                    "line": 0,
                    "masked_preview": type(exc).__name__,
                    "match_sha256": _sha256(type(exc).__name__.encode("utf-8")),
                }
            )
            continue
        for line_number, line in enumerate(lines, start=1):
            for category, pattern in patterns:
                for found in pattern.finditer(line):
                    value = found.group(0)
                    if _is_allowed_protocol_reference(relative, line, value):
                        continue
                    issues.append(
                        {
                            "category": category,
                            "relative_path": relative,
                            "line": line_number,
                            "masked_preview": _masked(value),
                            "match_sha256": _sha256(value.encode("utf-8")),
                        }
                    )

    issues = sorted(
        issues,
        key=lambda item: (
            item["relative_path"],
            item["line"],
            item["category"],
            item["masked_preview"],
        ),
    )
    result: dict[str, Any] = {
        "schema_version": "public-package-audit-v1",
        "expected_files": list(PUBLIC_FILES),
        "actual_files": actual_files,
        "actual_directories": actual_dirs,
        "missing_files": missing,
        "unexpected_files": unknown,
        "reparse_or_symlinks": reparse,
        "issues": issues,
        "status": "PASS" if not missing and not unknown and not reparse and not issues else "FAIL",
    }
    return result, 0 if result["status"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a CO-OP Loop public candidate.")
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result, exit_code = audit(args.root)
    except (OSError, UnicodeError, ValueError) as exc:
        result = {
            "schema_version": "public-package-audit-v1",
            "status": "ERROR",
            "error_type": type(exc).__name__,
            "error_sha256": _sha256(str(exc).encode("utf-8")),
        }
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
