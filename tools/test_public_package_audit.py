"""Persistent local regression checks for the public-package scanner."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from public_package_audit import PUBLIC_FILES


def _run_scanner(scanner: Path, root: Path) -> tuple[int, dict]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", str(scanner), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    if completed.stderr:
        raise AssertionError(f"scanner stderr is not empty: {completed.stderr}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError("scanner did not return JSON") from exc
    return completed.returncode, result


def _copy_candidate(repo_root: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for relative in PUBLIC_FILES:
        source = repo_root / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _fragment(*parts: int) -> str:
    return "".join(chr(part) for part in parts)


def _blocked_samples() -> list[tuple[str, str]]:
    uuid_value = "-".join(("01234567", "89ab", "cdef", "0123", "456789abcdef"))
    slash = chr(92)
    windows_value = chr(67) + chr(58) + slash + "Users" + slash + "Public" + slash + "fixture"
    unc_value = slash + slash + "server" + slash + "share"
    posix_value = chr(47) + _fragment(104, 111, 109, 101) + chr(47) + "fixture"
    internal_value = _fragment(66, 111, 115, 115)
    credential_value = _fragment(116, 111, 107, 101, 110) + '="fixture-value"'
    bearer_value = _fragment(66, 101, 97, 114, 101, 114) + ' "fixture-value"'
    private_key_value = "-" * 5 + "BEGIN RSA " + "PRIVATE KEY" + "-" * 5
    return [
        ("uuid_or_task_id", uuid_value),
        ("windows_or_unc_path", windows_value),
        ("windows_or_unc_path", unc_value),
        ("posix_home_path", posix_value),
        ("internal_name", internal_value),
        ("credential_assignment", credential_value),
        ("bearer_value", bearer_value),
        ("private_key_header", private_key_value),
    ]


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--temp-root":
        raise SystemExit("usage: test_public_package_audit.py --temp-root <exact-temp-root>")
    temp_root = Path(sys.argv[2]).resolve(strict=True)
    repo_root = Path(__file__).resolve().parents[1]
    scanner = repo_root / "tools" / "public_package_audit.py"
    run_root = temp_root / "scanner-regression-v3"
    clean = run_root / "clean-candidate"
    _copy_candidate(repo_root, clean)

    first_code, first_result = _run_scanner(scanner, clean)
    second_code, second_result = _run_scanner(scanner, clean)
    first_hash = _stable_hash(first_result)
    second_hash = _stable_hash(second_result)
    if first_code != 0 or second_code != 0 or first_result != second_result or first_hash != second_hash:
        raise AssertionError("clean candidate is not deterministic and clean")

    blocked_results: list[dict[str, object]] = []
    for index, (expected_category, sample) in enumerate(_blocked_samples(), start=1):
        fixture = run_root / "blocked" / f"fixture-{index:02d}"
        _copy_candidate(repo_root, fixture)
        marker = fixture / "README.md"
        marker.write_text(marker.read_text(encoding="utf-8") + "\n" + sample + "\n", encoding="utf-8")
        code, result = _run_scanner(scanner, fixture)
        categories = {issue["category"] for issue in result.get("issues", [])}
        masked = [issue.get("masked_preview", "") for issue in result.get("issues", [])]
        if code != 1 or result.get("status") != "FAIL" or expected_category not in categories:
            raise AssertionError(f"blocked fixture failed contract: {expected_category}")
        if any(sample in value for value in masked):
            raise AssertionError("blocked fixture echoed its raw value")
        blocked_results.append({"expected_category": expected_category, "exit_code": code, "categories": sorted(categories)})

    error_root = run_root / "error-root-that-does-not-exist"
    error_code, error_result = _run_scanner(scanner, error_root)
    if error_code != 2 or error_result.get("status") != "ERROR":
        raise AssertionError("scanner error fixture did not fail closed")

    print(
        json.dumps(
            {
                "clean_candidate": {"exit_codes": [first_code, second_code], "result_sha256": first_hash},
                "blocked_fixtures": blocked_results,
                "error_fixture": {"exit_code": error_code, "status": error_result.get("status")},
                "public_file_count": len(PUBLIC_FILES),
                "status": "PASS",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
