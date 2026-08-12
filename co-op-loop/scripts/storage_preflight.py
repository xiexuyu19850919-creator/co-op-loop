#!/usr/bin/env python3
"""Read-only, deterministic storage preflight for CO-OP Loop.

The script deliberately has no write/apply mode.  It reads only the project
root governance anchors, a bounded set of candidate governance scripts, and
the four state paths defined by the protocol.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable


STATE_FIELDS = {
    "project_root",
    "initialized_at",
    "consultant_thread_id",
    "control_thread_id",
    "phase",
    "red_count",
    "updated_at",
}
PHASES = {
    "INITIALIZING",
    "READY",
    "RED",
    "EXECUTION",
    "REVIEW",
    "WAITING_USER",
    "ENDED",
}
STATE_MARKERS = {
    "local_agent_state",
    "agent_state",
    "runtime_state",
    "tool_state",
}
REPORT_MARKERS = {
    "current_governance_reports",
    "current_reports",
    "runtime_reports",
}
FORBIDDEN_MARKERS = {
    "read_only",
    "archive",
    "historical",
    "former",
    "forbidden",
    "deprecated",
}
RULE_FILES = ("AGENTS.md", "FOLDER_INDEX.md", "PROJECT_STRUCTURE.md")
SCRIPT_NAME_HINTS = ("governance", "preflight", "folder", "structure", "index")
FORMAL_SOURCE_PRIORITY = {"AGENTS.md": 0, "PROJECT_STRUCTURE.md": 1, "FOLDER_INDEX.md": 2}
FORMAL_CONFIG_HEADINGS = {
    "co-op loop",
    "co-op loop storage",
    "co-op loop configuration",
    "co-op loop 配置",
    "co-op loop 存储",
    "loop storage",
    "loop configuration",
    "loop 配置",
    "loop 存储",
}
FORMAL_LEGACY_HEADINGS = {
    "强制报告门禁",
    "报告要求",
    "报告目录",
    "report contract",
    "reporting",
    "report root",
}
FORMAL_NEGATIVE_HEADING_TOKENS = {
    "example",
    "examples",
    "sample",
    "samples",
    "示例",
    "例如",
    "archive",
    "archived",
    "history",
    "historical",
    "deprecated",
    "归档",
    "历史",
    "废弃",
    "只读",
    "read only",
    "read_only",
}
FORMAL_FORBIDDEN_PATH_TOKENS = {
    "archive",
    "archived",
    "history",
    "historical",
    "deprecated",
    "former",
    "read_only",
    "read-only",
    "read only",
    "forbidden",
    "归档",
    "历史",
    "废弃",
    "只读",
    "禁止",
}
FORMAL_ACTION_WORDS = (
    "统一写入",
    "必须写入",
    "报告路径",
    "report root",
    "must be written to",
    "must write to",
)
PATH_RE = re.compile(
    r"(?:(?:[A-Za-z]:)?[\\/])?(?:[\w.\-一-龥]+[\\/])+[\w.\-一-龥]+/?"
)
KNOWN_DIR_RE = re.compile(r"(?<![\w.-])(?:\.agents|\.codex|\.coop-loop)(?:[\\/]\w[\w.\-]*)?[\\/]?")


def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _same_existing_path(left: Path, right: Path) -> bool:
    if _key(left) == _key(right):
        return True
    try:
        return _key(left.resolve(strict=True)) == _key(right.resolve(strict=True))
    except (OSError, RuntimeError):
        return False


def _absolute(root: Path, raw: str) -> Path | None:
    value = raw.strip().strip("`'\"<>()[]{}|\n\r\t")
    value = value.rstrip(".,;:")
    value = value.replace("\\", "/")
    if not value or value in {".", "./", "project-root", "<project-root>"}:
        return None
    value = value.replace("<project-root>", "").replace("project-root/", "")
    if value.startswith("./"):
        value = value[2:]
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / value
    try:
        return candidate.resolve()
    except OSError:
        return candidate.absolute()


def _extract_paths(line: str) -> list[str]:
    matches = PATH_RE.findall(line)
    matches.extend(KNOWN_DIR_RE.findall(line))
    result: list[str] = []
    seen: set[str] = set()
    for item in matches:
        cleaned = item.strip().strip("`'\"<>()[]{}|\n\r\t").rstrip(".,;:")
        if cleaned and ("/" in cleaned or "\\" in cleaned):
            marker = cleaned.casefold().replace("\\", "/")
            if marker not in seen:
                result.append(cleaned)
                seen.add(marker)
    return result


def _read_utf8(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _normalize_heading(text: str) -> str:
    value = re.sub(r"\s+#+\s*$", "", text.strip())
    value = re.sub(r"^\d+[.)]\s*", "", value)
    return " ".join(value.split()).casefold()


def _atx_heading(line: str) -> tuple[int, str] | None:
    if _is_quote_or_list(line):
        return None
    match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), _normalize_heading(match.group(2))


def _is_quote_or_list(line: str) -> bool:
    return bool(re.match(r"^ {0,3}(?:>|[-+*]|\d+[.)])[ \t]+", line))


def _is_reference_comment(line: str) -> bool:
    return bool(re.match(r"^ {0,3}\[[^\]]+\]:\s*#(?:\s|$).*", line))


def _fence_open(line: str) -> tuple[str, int] | None:
    if _is_quote_or_list(line):
        return None
    match = re.match(r"^ {0,3}(`{3,}|~{3,})(?:.*)$", line)
    if not match:
        return None
    token = match.group(1)
    return token[0], len(token)


def _fence_close(line: str, fence: tuple[str, int]) -> bool:
    char, length = fence
    return bool(re.match(rf"^ {{0,3}}{re.escape(char)}{{{length},}}\s*$", line))


def _section_is_allowed(stack: list[tuple[int, str]], headings: set[str]) -> bool:
    if not any(text in headings for _, text in stack):
        return False
    return not any(
        token in text
        for _, text in stack
        for token in FORMAL_NEGATIVE_HEADING_TOKENS
    )


def _previous_action_line(lines: list[str], index: int) -> str | None:
    cursor = index - 1
    while cursor >= 0:
        line = lines[cursor]
        if not line.strip() or _is_reference_comment(line):
            cursor -= 1
            continue
        if "<!--" in line or _atx_heading(line) is not None or _is_quote_or_list(line):
            return None
        return line.strip()
    return None


def _scan_formal_report_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    lines = str(source["text"]).splitlines()
    stack: list[tuple[int, str]] = []
    candidates: list[dict[str, Any]] = []
    html_comment = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if html_comment:
            if "-->" in line:
                html_comment = False
            index += 1
            continue
        if "<!--" in line:
            html_comment = "-->" not in line
            index += 1
            continue
        if _is_reference_comment(line):
            index += 1
            continue

        fence = _fence_open(line)
        if fence is not None:
            close = index + 1
            while close < len(lines) and not _fence_close(lines[close], fence):
                close += 1
            body = [item.strip() for item in lines[index + 1 : close] if item.strip()]
            if _section_is_allowed(stack, FORMAL_LEGACY_HEADINGS):
                action = _previous_action_line(lines, index)
                if action and any(word.casefold() in action.casefold() for word in FORMAL_ACTION_WORDS):
                    if len(body) == 1:
                        candidates.append(
                            {
                                "raw": body[0],
                                "source": source["path"],
                                "source_name": source["name"],
                                "line": index + 2,
                                "kind": "formal_report_root",
                                "syntax": "B",
                                "source_priority": FORMAL_SOURCE_PRIORITY.get(str(source["name"]), 9),
                                "section": [text for _, text in stack],
                            }
                        )
            index = close + 1 if close < len(lines) else len(lines)
            continue

        heading = _atx_heading(line)
        if heading is not None:
            level, text = heading
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            index += 1
            continue
        if _is_quote_or_list(line):
            index += 1
            continue

        marker = re.fullmatch(r"COOP_LOOP_REPORT_ROOT\s*:\s*(.+?)\s*", line)
        if marker and _section_is_allowed(stack, FORMAL_CONFIG_HEADINGS):
            candidates.append(
                {
                    "raw": marker.group(1).strip(),
                    "source": source["path"],
                    "source_name": source["name"],
                    "line": index + 1,
                    "kind": "formal_report_root",
                    "syntax": "A",
                    "source_priority": FORMAL_SOURCE_PRIORITY.get(str(source["name"]), 9),
                    "section": [text for _, text in stack],
                }
            )
        index += 1
    return candidates


def _formal_path(root: Path, raw: str, section: list[str]) -> tuple[Path | None, str | None]:
    value = raw.strip()
    if not value:
        return None, "empty_path"
    normalized = value.replace("\\", "/")
    if any(part == ".." for part in normalized.split("/")):
        return None, "parent_traversal"
    lowered = f"{normalized} {' '.join(section)}".casefold()
    if any(token in lowered for token in FORMAL_FORBIDDEN_PATH_TOKENS):
        return None, "forbidden_path_semantics"
    if value.startswith(("<", "`", "'", '"')) or "\n" in value or "\r" in value:
        return None, "non_path_value"
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = root / normalized
    try:
        resolved = candidate.resolve()
    except OSError:
        return None, "path_resolution_error"
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, "outside_project_root"
    if _key(resolved) == _key(root):
        return None, "project_root_not_report_root"
    if not candidate.exists():
        return None, "required_report_path_missing"
    if not candidate.is_dir():
        return None, "report_path_not_directory"
    return resolved, None


def _formal_report_evidence(
    root: Path, sources: Iterable[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for source in sources:
        if str(source.get("name")) not in FORMAL_SOURCE_PRIORITY:
            continue
        for candidate in _scan_formal_report_source(source):
            path, error = _formal_path(root, str(candidate["raw"]), list(candidate.get("section", [])))
            item = dict(candidate)
            item["raw_path"] = item.pop("raw")
            if path is None:
                item["path"] = None
                item["authorized"] = False
                item["reason"] = error or "invalid_report_path"
                rejected.append(item)
            else:
                item["path"] = str(path)
                item["exists"] = True
                item["authorized"] = True
                valid.append(item)
    return valid, rejected


def _select_formal_report_evidence(
    valid: list[dict[str, Any]], rejected: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    all_items = valid + rejected
    if not all_items:
        return "NONE", [], []
    best_priority = min(int(item.get("source_priority", 9)) for item in all_items)
    best = [item for item in all_items if int(item.get("source_priority", 9)) == best_priority]
    lower = [item for item in all_items if int(item.get("source_priority", 9)) > best_priority]
    invalid = [item for item in best if not item.get("authorized")]
    if invalid:
        return "BLOCKED", [], lower
    by_path: dict[str, dict[str, Any]] = {}
    for item in best:
        key = _key(Path(str(item["path"])))
        by_path.setdefault(key, item)
    if len(by_path) > 1:
        return "AMBIGUOUS", list(by_path.values()), lower
    return "OK", list(by_path.values()), lower


def _collect_anchors(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    sources: list[dict[str, Any]] = []
    read_errors: list[str] = []
    for name in RULE_FILES:
        path = root / name
        if not path.is_file():
            continue
        text = _read_utf8(path)
        if text is None:
            read_errors.append(str(path))
            continue
        sources.append({"path": str(path), "kind": "rule_or_index", "name": name, "text": text})

    scripts = root / "scripts"
    if scripts.is_dir():
        try:
            entries = sorted(scripts.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            entries = []
        for path in entries:
            name = path.name.casefold()
            if not path.is_file() or path.suffix.casefold() not in {".py", ".ps1", ".sh"}:
                continue
            if not any(hint in name for hint in SCRIPT_NAME_HINTS):
                continue
            text = _read_utf8(path)
            if text is None:
                read_errors.append(str(path))
                continue
            sources.append({"path": str(path), "kind": "governance_script", "name": path.name, "text": text})
    return sources, read_errors


def _strong_signals(sources: Iterable[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    signals: list[str] = []
    evidence: list[dict[str, Any]] = []
    for source in sources:
        text = str(source["text"])
        lower = text.casefold()
        name = str(source["name"])
        signal: str | None = None
        if (
            "禁止新增顶层" in text
            or "顶层必须登记" in text
            or "只能写入 exact path" in lower
            or "forbid new top-level" in lower
            or "top-level additions are forbidden" in lower
            or "top-level entries must be registered" in lower
            or "only write to exact path" in lower
        ):
            signal = "explicit_top_level_rule"
        elif (
            source["kind"] == "rule_or_index"
            and (name.casefold() in {"folder_index.md", "project_structure.md"})
            and (
                "top-level" in lower
                or "顶层" in text
                or "allowlist" in lower
                or "local_agent_state" in lower
                or any(marker in lower for marker in REPORT_MARKERS)
            )
        ):
            signal = "top_level_index_coverage"
        elif "governance preflight" in lower or "治理 preflight" in text or "治理预检" in text:
            signal = "declared_governance_preflight"
        elif (
            source["kind"] == "governance_script"
            and ("iterdir" in lower or "top-level" in lower or "顶层" in text)
            and ("allowlist" in lower or "index" in lower or "登记" in text)
        ):
            signal = "static_top_level_allowlist_check"
        if signal:
            if signal not in signals:
                signals.append(signal)
            evidence.append({"source": source["path"], "kind": signal})
    return signals, evidence


def _markers(line: str) -> tuple[set[str], set[str]]:
    lower = line.casefold()
    present_states = {marker for marker in STATE_MARKERS if marker in lower}
    present_reports = {marker for marker in REPORT_MARKERS if marker in lower}
    if re.search(r"(?:writable|exact)\s+(?:state|runtime|tool|agent[- ]state)\s+path", lower) or "state path is" in lower:
        present_states.add("rule_exact_state")
    if re.search(r"(?:current|governance)\s+report(?:s)?\s+(?:path|root)", lower) or "current report path" in lower:
        present_reports.add("rule_exact_report")
    forbidden: set[str] = set()
    for marker in FORBIDDEN_MARKERS:
        if marker not in lower:
            continue
        if "_" in marker or re.search(
            rf"\|\s*{re.escape(marker)}\b|\b{re.escape(marker)}\s+(?:state|report|path|root)\b|\b(?:state|report|path|root)\b(?:\s+\w+){{0,2}}\s+\b{re.escape(marker)}\b",
            lower,
        ):
            forbidden.add(marker)
    return present_states | present_reports, forbidden


def _state_path(root: Path, raw: str) -> Path | None:
    path = _absolute(root, raw)
    if path is None:
        return None
    name = path.name.casefold()
    parts = [part.casefold() for part in path.parts]
    if name in {"state.yaml", "state.yml"}:
        return path
    if name in {".agents", ".codex", ".coop-loop"}:
        return path / "co-op-loop" / "state.yaml"
    if name == "co-op-loop":
        return path / "state.yaml"
    if ".agents" in parts or ".codex" in parts or ".coop-loop" in parts:
        return path / "state.yaml"
    return None


def _report_path(root: Path, raw: str) -> Path | None:
    path = _absolute(root, raw)
    if path is None:
        return None
    if path.suffix.casefold() in {".md", ".markdown"}:
        return path.parent
    return path


def _parse_evidence(root: Path, sources: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    state_evidence: list[dict[str, Any]] = []
    report_evidence: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for source in sources:
        for line_number, line in enumerate(str(source["text"]).splitlines(), 1):
            present, forbidden = _markers(line)
            if not present:
                continue
            paths = _extract_paths(line)
            if not paths:
                continue
            state_markers = (present & STATE_MARKERS) | ({"rule_exact_state"} if "rule_exact_state" in present else set())
            report_markers = (present & REPORT_MARKERS) | ({"rule_exact_report"} if "rule_exact_report" in present else set())
            source_kind = "rule_exact" if source["kind"] == "rule_or_index" and (
                "exact" in line.casefold() or "writable" in line.casefold() or "path" in line.casefold()
            ) else "index_marker"
            for raw in paths:
                if state_markers:
                    path = _state_path(root, raw)
                    if path is None:
                        continue
                    item = {
                        "path": str(path),
                        "source": source["path"],
                        "line": line_number,
                        "kind": source_kind,
                        "markers": sorted(state_markers),
                    }
                    if forbidden:
                        rejected.append({**item, "forbidden": sorted(forbidden)})
                    else:
                        state_evidence.append(item)
                if report_markers:
                    path = _report_path(root, raw)
                    if path is None:
                        continue
                    item = {
                        "path": str(path),
                        "source": source["path"],
                        "line": line_number,
                        "kind": source_kind,
                        "markers": sorted(report_markers),
                    }
                    if forbidden:
                        rejected.append({**item, "forbidden": sorted(forbidden)})
                    else:
                        report_evidence.append(item)
    return state_evidence, report_evidence, rejected


def _parse_state(path: Path, root: Path) -> tuple[bool, dict[str, Any] | None, str | None]:
    text = _read_utf8(path)
    if text is None:
        return False, None, "unreadable_or_non_utf8"
    values: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            return False, None, "invalid_yaml_line"
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key in values:
            return False, None, "duplicate_key"
        values[key] = value
    if set(values) != STATE_FIELDS:
        return False, values, "seven_field_contract_mismatch"
    if not all(str(values[field]).strip() for field in ("project_root", "initialized_at", "consultant_thread_id", "control_thread_id", "updated_at")):
        return False, values, "empty_required_value"
    if values["phase"] not in PHASES:
        return False, values, "invalid_phase"
    try:
        values["red_count"] = int(str(values["red_count"]))
    except ValueError:
        return False, values, "invalid_red_count"
    if values["red_count"] not in {0, 1, 2, 3}:
        return False, values, "invalid_red_count"
    declared_root = Path(str(values["project_root"]).replace("\\", os.sep))
    if not declared_root.is_absolute():
        declared_root = root / declared_root
    if not _same_existing_path(declared_root, root):
        return False, values, "project_root_mismatch"
    return True, values, None


def _unique_evidence(items: Iterable[dict[str, Any]], priority: dict[str, int]) -> tuple[list[dict[str, Any]], list[str]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        path_key = os.path.normcase(os.path.normpath(str(item["path"])))
        current = grouped.get(path_key)
        if current is None or priority.get(str(item["kind"]), 9) < priority.get(str(current["kind"]), 9):
            grouped[path_key] = dict(item)
        elif current is not None:
            current["markers"] = sorted(set(current.get("markers", [])) | set(item.get("markers", [])))
    values = list(grouped.values())
    if not values:
        return [], []
    best = min(priority.get(str(item["kind"]), 9) for item in values)
    selected = [item for item in values if priority.get(str(item["kind"]), 9) == best]
    return selected, [str(item["path"]) for item in selected]


def _prefer_existing_state_anchor(root: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use an existing indexed top-level anchor to resolve absent alternatives.

    A strict index may document more than one optional agent namespace. During
    a first-init simulation, an existing candidate parent is the only one that
    can be proven current without creating a new state subtree. If two
    candidate parents exist (or none exists), the result remains ambiguous.
    """
    if len(items) <= 1:
        return items
    existing: list[dict[str, Any]] = []
    for item in items:
        path = Path(str(item["path"]))
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if relative.parts and path.parent.exists():
            existing.append(item)
    return existing if len(existing) == 1 else items


def _candidate_record(path: Path, *, source: str, authorized: bool) -> dict[str, Any]:
    return {"path": str(path), "source": source, "exists": path.is_file(), "authorized": authorized}


def _finite_candidates(root: Path, state_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths: list[tuple[Path, str, bool]] = []
    for item in state_evidence:
        paths.append((Path(str(item["path"])), str(item["source"]), True))
    paths.extend(
        [
            (root / ".agents" / "co-op-loop" / "state.yaml", "finite_candidate", False),
            (root / ".codex" / "co-op-loop" / "state.yaml", "finite_candidate", False),
            (root / ".coop-loop" / "state.yaml", "finite_candidate", False),
        ]
    )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, source, authorized in paths:
        marker = _key(path)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(_candidate_record(path, source=source, authorized=authorized))
    return result


def _report_candidates(root: Path, report_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in report_evidence:
        path = Path(str(item["path"]))
        marker = _key(path)
        if marker in seen:
            continue
        seen.add(marker)
        result.append({**item, "exists": path.exists(), "authorized": True})
    return result


def _non_strict_paths(root: Path) -> tuple[Path, Path, str]:
    if (root / ".agents").is_dir():
        state = root / ".agents" / "co-op-loop" / "state.yaml"
        source = "existing_agents_convention"
    elif (root / ".codex").is_dir():
        state = root / ".codex" / "co-op-loop" / "state.yaml"
        source = "existing_codex_convention"
    else:
        state = root / ".coop-loop" / "state.yaml"
        source = "default_coop_loop_convention"
    return state, state.parent / "reports", source


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
        return bool(attributes & 0x400)
    except OSError:
        return True


def _legacy_report_pair(root: Path) -> tuple[str, Path, str | None]:
    """Resolve the existing legacy report side without guessing or migrating."""
    report_path = root / ".coop-loop" / "reports"
    parent = report_path.parent
    if parent.exists() and _is_reparse(parent):
        return "BLOCKED", report_path, "legacy_report_parent_reparse"
    if report_path.is_symlink() or (report_path.exists() and _is_reparse(report_path)):
        return "BLOCKED", report_path, "legacy_report_reparse"
    if not report_path.exists():
        return "MISSING", report_path, None
    if not report_path.is_dir():
        return "BLOCKED", report_path, "legacy_report_not_directory"
    try:
        resolved = report_path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return "BLOCKED", report_path, "legacy_report_outside_project"
    if _key(resolved) == _key(root):
        return "BLOCKED", report_path, "legacy_report_is_project_root"
    return "VALID", resolved, None


def run_preflight(project_root: str, mode: str) -> dict[str, Any]:
    root = Path(project_root)
    if not root.is_absolute():
        raise ValueError("--project-root must be an exact absolute path")
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("project root does not exist or is not a directory")
    if mode not in {"current", "simulate-first-init"}:
        raise ValueError("unsupported mode")

    sources, read_errors = _collect_anchors(root)
    strict_signals, strong_evidence = _strong_signals(sources)
    state_evidence, report_evidence, rejected = _parse_evidence(root, sources)
    formal_report_valid, formal_report_rejected = _formal_report_evidence(root, sources)
    formal_report_status, formal_report_authorized, ignored_lower_priority = _select_formal_report_evidence(
        formal_report_valid,
        formal_report_rejected,
    )
    strict = bool(strict_signals)
    priority = {"rule_exact": 0, "formal_report_root": 0, "index_marker": 1}
    state_authorized, state_paths = _unique_evidence(state_evidence, priority)
    state_authorized = _prefer_existing_state_anchor(root, state_authorized)
    state_paths = [str(item["path"]) for item in state_authorized]
    report_pool = report_evidence + formal_report_valid if strict else report_evidence
    report_authorized, report_paths = _unique_evidence(report_pool, priority)
    candidates = _finite_candidates(root, state_evidence)

    valid_states: list[dict[str, Any]] = []
    damaged_states: list[dict[str, Any]] = []
    for candidate in candidates:
        path = Path(str(candidate["path"]))
        if not path.is_file():
            continue
        valid, values, error = _parse_state(path, root)
        if valid:
            valid_states.append({"path": str(path), "phase": values["phase"], "red_count": values["red_count"], "fields": sorted(STATE_FIELDS)})
        else:
            damaged_states.append({"path": str(path), "reason": error or "invalid_state"})

    conflicts: list[str] = []
    if len(valid_states) > 1:
        conflicts.append("multiple_valid_states")
    if len(damaged_states) > 1 and not valid_states:
        conflicts.append("multiple_damaged_states")
    if len(state_paths) > 1:
        conflicts.append("multiple_authorized_state_paths")
    if len(report_paths) > 1:
        conflicts.append("multiple_authorized_report_paths")
    if formal_report_status == "AMBIGUOUS":
        conflicts.append("multiple_formal_report_paths")
    elif formal_report_status == "BLOCKED":
        conflicts.append("formal_report_path_blocked")
    if rejected:
        conflicts.append("prohibited_evidence_rejected")
    if read_errors:
        conflicts.append("governance_anchor_read_error")

    legacy_report_status = "NONE"
    legacy_report_path = root / ".coop-loop" / "reports"
    legacy_report_error: str | None = None
    if mode == "current" and len(valid_states) == 1 and _key(Path(valid_states[0]["path"])) == _key(root / ".coop-loop" / "state.yaml"):
        legacy_report_status, legacy_report_path, legacy_report_error = _legacy_report_pair(root)
        if legacy_report_status == "BLOCKED":
            conflicts.append("legacy_report_pair_blocked")
    if legacy_report_status == "VALID":
        conflicts = [
            item
            for item in conflicts
            if item not in {"multiple_authorized_report_paths", "multiple_formal_report_paths", "formal_report_path_blocked"}
        ]

    resolved_state: Path | None = None
    resolved_report: Path | None = None
    classification = "DEFAULT"
    reason = "ordinary project uses the bounded default storage pair"

    if mode == "current" and len(valid_states) > 1:
        classification = "STATE_CONFLICT"
        reason = "more than one valid seven-field state exists; no state is selected"
    elif mode == "current" and len(damaged_states) > 1 and not valid_states:
        classification = "STATE_CONFLICT"
        reason = "more than one damaged state exists without a unique recovery authority"
    elif mode == "current" and len(valid_states) == 1:
        resolved_state = Path(valid_states[0]["path"])
        legacy = _key(resolved_state) == _key(root / ".coop-loop" / "state.yaml")
        classification = "LEGACY" if legacy else "ADAPTED"
        reason = "one valid state is the sole recovery authority; no migration is performed" if legacy else "one valid state is the sole recovery authority"
        if legacy:
            if legacy_report_status == "BLOCKED":
                classification = "BLOCKED"
                resolved_report = None
                reason = legacy_report_error or "legacy report pair is unsafe"
            elif legacy_report_status == "VALID":
                resolved_report = legacy_report_path
                reason = "one valid legacy state continues with its existing local report pair"
            elif strict:
                if len(report_paths) > 1:
                    classification = "AMBIGUOUS"
                    reason = "multiple same-level authorized report paths require an exact choice"
                elif report_authorized:
                    classification = "ADAPTED"
                    resolved_report = Path(report_authorized[0]["path"])
                    reason = "legacy state has no local report pair; one authorized formal report root is reused"
                elif formal_report_status == "AMBIGUOUS":
                    classification = "AMBIGUOUS"
                    reason = "multiple same-level formal report roots require an exact choice"
                elif formal_report_status == "BLOCKED":
                    classification = "BLOCKED"
                    reason = "the authoritative formal report path is invalid or unavailable"
                else:
                    classification = "LEGACY"
                    resolved_report = legacy_report_path
                    reason = "legacy state has no local report pair and no formal root; local pair remains the fallback"
            else:
                if formal_report_status == "AMBIGUOUS":
                    classification = "AMBIGUOUS"
                    reason = "multiple same-level formal report roots require an exact choice"
                elif formal_report_status == "BLOCKED":
                    classification = "BLOCKED"
                    reason = "the authoritative formal report path is invalid or unavailable"
                elif formal_report_status == "OK":
                    classification = "ADAPTED"
                    resolved_report = Path(str(formal_report_authorized[0]["path"]))
                    reason = "legacy state has no local report pair; one formal report root is reused"
                else:
                    classification = "LEGACY"
                    resolved_report = legacy_report_path
                    reason = "legacy state has no local report pair and no formal root; local pair remains the fallback"
        elif strict:
            if len(report_paths) > 1:
                classification = "AMBIGUOUS"
                reason = "multiple same-level authorized report paths require an exact choice"
            elif report_authorized:
                resolved_report = Path(report_authorized[0]["path"])
            else:
                classification = "BLOCKED"
                reason = "state is readable but no authorized report root forms a complete writable pair"
        else:
            if formal_report_status == "AMBIGUOUS":
                classification = "AMBIGUOUS"
                reason = "multiple same-level formal report roots require an exact choice"
            elif formal_report_status == "BLOCKED":
                classification = "BLOCKED"
                reason = "the authoritative formal report path is invalid or unavailable"
            elif formal_report_status == "OK":
                resolved_report = Path(str(formal_report_authorized[0]["path"]))
            else:
                resolved_report = resolved_state.parent / "reports"
    elif mode == "current" and len(damaged_states) == 1 and not valid_states:
        classification = "BLOCKED"
        reason = "one damaged state requires the existing state-repair menu before initialization"
    elif strict:
        if len(state_paths) > 1 or len(report_paths) > 1:
            classification = "AMBIGUOUS"
            reason = "multiple same-level authorized storage candidates require an exact choice"
        elif not state_authorized and not report_authorized:
            classification = "BLOCKED"
            reason = "strict project has neither an authorized state root nor an authorized report root"
        elif not state_authorized:
            classification = "BLOCKED"
            reason = "strict project has an authorized report root but no authorized state root"
        elif not report_authorized:
            chosen = state_authorized[0]
            markers = set(chosen.get("markers", []))
            if markers & {"runtime_state", "tool_state"}:
                resolved_state = Path(str(chosen["path"]))
                resolved_report = resolved_state.parent / "reports"
                classification = "ADAPTED"
                reason = "state evidence explicitly permits a runtime subtree report root"
            else:
                classification = "BLOCKED"
                reason = "strict project has a state root but no authorized report root"
        else:
            resolved_state = Path(str(state_authorized[0]["path"]))
            resolved_report = Path(str(report_authorized[0]["path"]))
            classification = "ADAPTED"
            reason = "strict project has one exact evidence-backed state/report pair"
    else:
        resolved_state, resolved_report, source = _non_strict_paths(root)
        if formal_report_status == "AMBIGUOUS":
            classification = "AMBIGUOUS"
            resolved_report = None
            reason = "multiple same-level formal report roots require an exact choice"
        elif formal_report_status == "BLOCKED":
            classification = "BLOCKED"
            resolved_report = None
            reason = "the authoritative formal report path is invalid or unavailable"
        elif formal_report_status == "OK":
            classification = "ADAPTED"
            resolved_report = Path(str(formal_report_authorized[0]["path"]))
            reason = f"ordinary project uses {source} state and its formal report root"
        else:
            reason = f"ordinary project uses {source}"

    if mode == "simulate-first-init":
        conflicts = [item for item in conflicts if item not in {"multiple_valid_states", "multiple_damaged_states"}]
        if strict:
            if len(state_paths) > 1 or len(report_paths) > 1:
                classification = "AMBIGUOUS"
                reason = "simulated first init has multiple same-level authorized storage candidates"
            elif not state_authorized and not report_authorized:
                classification = "BLOCKED"
                reason = "simulated first init found no complete strict storage pair"
            elif not state_authorized or not report_authorized:
                if not report_authorized and state_authorized and set(state_authorized[0].get("markers", [])) & {"runtime_state", "tool_state"}:
                    resolved_state = Path(str(state_authorized[0]["path"]))
                    resolved_report = resolved_state.parent / "reports"
                    classification = "ADAPTED"
                    reason = "simulated first init uses an explicitly writable runtime subtree"
                else:
                    classification = "BLOCKED"
                    reason = "simulated first init lacks one side of the strict storage pair"
            else:
                resolved_state = Path(str(state_authorized[0]["path"]))
                resolved_report = Path(str(report_authorized[0]["path"]))
                classification = "ADAPTED"
                reason = "simulated first init resolved one exact evidence-backed state/report pair"
        else:
            resolved_state, resolved_report, source = _non_strict_paths(root)
            if formal_report_status == "AMBIGUOUS":
                classification = "AMBIGUOUS"
                resolved_report = None
                reason = "simulated first init has multiple same-level formal report roots"
            elif formal_report_status == "BLOCKED":
                classification = "BLOCKED"
                resolved_report = None
                reason = "simulated first init has an invalid or unavailable formal report root"
            elif formal_report_status == "OK":
                classification = "ADAPTED"
                resolved_report = Path(str(formal_report_authorized[0]["path"]))
                reason = f"simulated first init uses {source} state and its formal report root"
            else:
                classification = "DEFAULT"
                reason = f"simulated first init uses {source}"

    if conflicts and classification not in {"STATE_CONFLICT", "AMBIGUOUS"}:
        if "governance_anchor_read_error" in conflicts:
            classification = "BLOCKED"
            resolved_state = None
            resolved_report = None
            reason = "governance anchor read error; no storage action is allowed"
        elif any(item in conflicts for item in ("multiple_authorized_state_paths", "multiple_authorized_report_paths")):
            classification = "AMBIGUOUS"
            reason = "multiple same-level authorized storage candidates require an exact choice"
        elif "prohibited_evidence_rejected" in conflicts and strict and not resolved_state:
            classification = "BLOCKED"
            reason = "prohibited evidence cannot authorize a storage location"

    task_allowed = classification in {"DEFAULT", "ADAPTED", "LEGACY"} and resolved_state is not None and resolved_report is not None and not conflicts
    if classification == "STATE_CONFLICT" or classification == "AMBIGUOUS" or classification == "BLOCKED":
        task_allowed = False

    state_candidate_output = candidates
    report_candidate_output = _report_candidates(root, report_pool + formal_report_valid)
    evidence = strong_evidence + state_evidence + report_evidence + formal_report_valid + formal_report_rejected + rejected
    if read_errors:
        evidence.extend({"source": path, "kind": "read_error"} for path in read_errors)

    migration_candidate = None
    if (
        mode == "current"
        and
        len(valid_states) == 1
        and _key(Path(valid_states[0]["path"])) == _key(root / ".coop-loop" / "state.yaml")
        and legacy_report_status == "VALID"
    ):
        if formal_report_status == "OK":
            migration_candidate = str(formal_report_authorized[0]["path"])
        elif strict and len(report_authorized) == 1:
            migration_candidate = str(report_authorized[0]["path"])

    return {
        "project_root": str(root),
        "mode": mode,
        "classification": classification,
        "strict_signals": sorted(strict_signals),
        "evidence": evidence,
        "state_candidates": state_candidate_output,
        "valid_states": valid_states,
        "damaged_states": damaged_states,
        "report_candidates": report_candidate_output,
        "formal_report_status": formal_report_status,
        "ignored_lower_priority": ignored_lower_priority,
        "migration_candidate": migration_candidate,
        "resolved_state_path": str(resolved_state) if resolved_state else None,
        "resolved_report_root": str(resolved_report) if resolved_report else None,
        "conflicts": sorted(set(conflicts)),
        "task_creation_allowed": bool(task_allowed),
        "reason": reason,
        "writes_performed": 0,
        "task_creations_performed": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only CO-OP Loop storage preflight")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--mode", choices=("current", "simulate-first-init"), default="current")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = run_preflight(args.project_root, args.mode)
    except (OSError, ValueError) as exc:
        result = {
            "project_root": args.project_root,
            "mode": args.mode,
            "classification": "BLOCKED",
            "strict_signals": [],
            "evidence": [],
            "state_candidates": [],
            "valid_states": [],
            "damaged_states": [],
            "report_candidates": [],
            "resolved_state_path": None,
            "resolved_report_root": None,
            "conflicts": ["preflight_input_error"],
            "task_creation_allowed": False,
            "reason": str(exc),
            "writes_performed": 0,
            "task_creations_performed": 0,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
