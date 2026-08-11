"""Deterministic checks for the final CO-OP Loop v0.2 contract."""

from __future__ import annotations

import unittest
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Mapping


STATE_FIELDS = {
    "project_root",
    "initialized_at",
    "consultant_thread_id",
    "control_thread_id",
    "phase",
    "red_count",
    "updated_at",
}
PHASES = {"INITIALIZING", "READY", "RED", "EXECUTION", "REVIEW", "WAITING_USER", "ENDED"}
TRIGGERS = {"loop", "/loop", "$loop", "$co-op-loop"}
TERMINAL_NEXT = {"ENDED", "PLAN_DISPLAYED", "DIRECTION_REQUESTED"}
EXECUTION_STATUSES = {"EXECUTION_COMPLETE", "EXECUTION_PAUSED", "EXECUTION_FAILED"}
SKILL_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"
PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "references" / "loop-protocol.md"
HOST_ADAPTATION_PATH = PROTOCOL_PATH.parent / "host-adaptation.md"
STORAGE_REFERENCE_PATH = Path(__file__).resolve().parents[1] / "references" / "storage-adaptation.md"
STORAGE_SCRIPT_PATH = Path(__file__).resolve().parent / "storage_preflight.py"


def normalized_trigger(text: str) -> str:
    return text.strip().casefold()


def is_loop_trigger(text: str) -> bool:
    return normalized_trigger(text) in TRIGGERS


def is_strict_choice(text: str, choices: set[str]) -> bool:
    return text.strip() in choices


def plan_confirmation(text: str) -> str:
    return "SEND_RED" if text.strip() in {"1", "执行"} else "WAIT_FOR_LATEST_LOOP" if text.strip() in {"2", "再等等"} else "ORDINARY_TEXT"


def authorized_human_plan_confirmation(text: str, *, actor: str, authorized_actor: str) -> bool:
    return actor == authorized_actor and plan_confirmation(text) == "SEND_RED"


PLAN_BEGIN_MARKER = "BEGIN_PLAN_TEXT"
PLAN_END_MARKER = "END_PLAN_TEXT"


def normalized_plan_text(text: str) -> str:
    if text.count(PLAN_BEGIN_MARKER) != 1 or text.count(PLAN_END_MARKER) != 1:
        raise ValueError("plan markers must each occur exactly once")
    start = text.index(PLAN_BEGIN_MARKER) + len(PLAN_BEGIN_MARKER)
    end = text.index(PLAN_END_MARKER)
    if end < start:
        raise ValueError("plan markers are out of order")
    body = text[start:end].replace("\r\n", "\n").replace("\r", "\n")
    return body.rstrip("\n")


def plan_version_sha256(text: str) -> str:
    return hashlib.sha256(normalized_plan_text(text).encode("utf-8")).hexdigest().upper()


def plan_version_matches(text: str, expected_sha256: str) -> bool:
    return plan_version_sha256(text) == expected_sha256


def plan_confirmation_binds_exact_version(text: str, displayed_plan: str, latest_plan: str) -> bool:
    return plan_confirmation(text) == "SEND_RED" and displayed_plan == latest_plan


def red_all_pass_route(*, round_number: int, plan_confirmed: bool, gates_clear: bool, plan_version_match: bool) -> str:
    if round_number not in {1, 2, 3}:
        raise ValueError("RED round must be 1..3")
    if not plan_confirmed:
        return "PLAN_CONFIRMATION_REQUIRED"
    if not plan_version_match:
        return "PLAN_VERSION_MISMATCH"
    if not gates_clear:
        return "EXECUTION_PAUSED"
    return "AUTO_EXECUTE"


def preflight(actions: list[str], allowed: set[str]) -> str:
    return "EXECUTION_PAUSED" if any(action not in allowed for action in actions) else "PROCEED"


def retry_state(failure_fingerprint: str, methods: list[str]) -> str:
    if len(methods) >= 2 and methods[-1] == methods[-2]:
        return "REPEATED_FAILURE"
    return "RETRY_ALLOWED"


def correction_state(failure_fingerprint: str, sent_fingerprints: set[str]) -> str:
    return "CORRECTION_ALLOWED" if failure_fingerprint not in sent_fingerprints else "EXECUTION_PAUSED"


def tracking_mode(event: str) -> str:
    return "SILENT" if event in {"normal_progress", "safe_self_repair", "single_timeout_with_progress"} else "INTERVENE"


def execution_report_contract(*, business_report_required: bool) -> dict[str, bool]:
    return {
        "loop_report_required": True,
        "business_report_required": business_report_required,
        "consultant_evaluation_required": True,
    }


def execution_status(status: str) -> str:
    if status not in EXECUTION_STATUSES:
        raise ValueError("unsupported execution status")
    return status


def next_round_suggestion(*, complete: bool, project_type: str) -> str:
    if complete:
        return "建议下一步做一次最小真实证据验证，仅建议不自动执行"
    return "本轮仍有未完成项，建议根据本轮报告生成第二轮计划"


def model_switch_prompt(role: str, switched: bool) -> str:
    if switched:
        return ""
    if role == "consultant":
        return "顾问任务推荐使用 Sol High 或更高模式，当前暂时无法自动为您切换，请你人工切换模型类型。"
    return "中控任务推荐使用 Luna Max（最高），当前无法自动切换，请你人工检查模型类型。"


def control_source_choices() -> tuple[str, ...]:
    return (
        "新建一个本地中控台任务",
        "查找并复用本项目已有的“中控”任务，升级为本 Loop 的中控台",
        "通过任务线程 ID 指定并升级为中控台任务",
        "取消本次初始化",
    )


def eligible_control_candidates(candidates: list[Mapping[str, Any]], *, consultant_id: str, project_root: str) -> list[Mapping[str, Any]]:
    return [
        candidate
        for candidate in candidates
        if candidate.get("status") == "active"
        and candidate.get("environment") == "local"
        and candidate.get("project_root") == project_root
        and candidate.get("thread_id") != consultant_id
        and any(marker in str(candidate.get("title", "")) for marker in ("中控", "中控台"))
    ]


def control_candidate_mode(candidates: list[Mapping[str, Any]]) -> str:
    if not candidates:
        return "ZERO_CANDIDATES"
    if len(candidates) == 1:
        return "UNIQUE_REQUIRES_ID_CONFIRMATION"
    return "MULTI_REQUIRES_ID_SELECTION"


def role_upgrade_binding_ready(*, exact_id_known: bool, declaration_delivered: bool, role_verified: bool) -> bool:
    return exact_id_known and declaration_delivered and role_verified


def role_upgrade_declaration(thread_id: str, role: str = "CONTROL") -> str:
    return (
        f"COOP_ROLE_UPGRADE target_thread_id: {thread_id}; old context is historical material only; "
        f"no current plan or execution authorization is inherited; role_contract: {role}_ROLE."
    )


def business_route(*, business_request: bool, control_status: str, plan_confirmed: bool, red_passed: bool, high_risk_cleared: bool, stop_conditions_clear: bool) -> dict[str, Any]:
    if not business_request:
        return {"route": "CONSULTANT_GOVERNANCE", "action": "HANDLE_IN_CONSULTANT"}
    if control_status in {"archived", "deleted", "missing"}:
        return {"route": "CONTROL_RECOVERY", "action": "RESTORE_OR_REBUILD"}
    if control_status != "active":
        return {"route": "CONTROL_SOURCE_SELECTION", "action": "BIND_CONTROL"}
    if not plan_confirmed:
        return {"route": "PLAN_CONFIRMATION", "action": "DISPLAY_PLAN_GATE"}
    if not red_passed:
        return {"route": "RED_FLOW", "action": "SEND_OR_CONTINUE_RED"}
    if not high_risk_cleared or not stop_conditions_clear:
        return {"route": "HIGH_RISK_GATE", "action": "PAUSE"}
    return {"route": "CONTROL", "action": "SEND_EXECUTION_PACKAGE", "duplicate_transfer_confirmation": False}


def completed_evidence_suggestion() -> dict[str, Any]:
    return {
        "text": "若本轮已经完成全部既定目标，顾问仍应根据项目类型推理一个最小、能产生真实证据的后续建议，例如真实业务 canary、跨操作系统测试、本机冷启动、automation dry-run、小规模 API 调用、内容样例或迁移 canary；只建议，不自动执行。",
        "auto_execute": False,
    }


def completed_closeout_message(user_name: str, action_name: str) -> str:
    return (
        f"{user_name}，本轮既定目标已经全部完成。建议下一轮进行一次{action_name}。\n\n"
        f"如果继续，顾问将基于本轮报告生成最小{action_name}计划；经你确认后发送到指定任务执行。顾问负责静默跟踪、回读执行报告并形成下一轮评估。你现在可以：\n\n"
        f"1. 继续，指派中控任务执行{action_name}计划\n"
        f"2. 继续，新建业务任务执行{action_name}计划\n"
        f"3. 不做{action_name}，结束 Loop\n\n"
        "（无回复默认选择 3。）"
    )


def completed_closeout_choice(text: str) -> str:
    value = text.strip()
    if value == "1":
        return "CONTROL_NEXT_ROUND"
    if value == "2":
        return "BUSINESS_TASK_NEXT_ROUND"
    if value in {"3", ""}:
        return "ENDED"
    return "ORDINARY_TEXT"


def closeout_execution_target(
    choice: str,
    *,
    control_thread_id: str,
    business_thread_id: str,
    action_name: str,
    project_name: str,
) -> dict[str, Any]:
    if choice == "1":
        return {
            "target_kind": "CONTROL",
            "thread_id": control_thread_id,
            "requires_plan_confirmation": True,
            "requires_red": True,
            "requires_high_risk_clear": True,
            "requires_stop_clear": True,
            "consultant_is_target": False,
        }
    if choice == "2":
        if not action_name.strip() or action_name.strip() == project_name.strip():
            raise ValueError("business task requires the actual action name")
        return {
            "target_kind": "BUSINESS_TASK",
            "thread_id": business_thread_id,
            "title": f"业务 | {action_name}",
            "environment": "local",
            "one_time": True,
            "requires_plan_confirmation": True,
            "requires_red": True,
            "requires_high_risk_clear": True,
            "requires_stop_clear": True,
            "consultant_is_target": False,
            "state_patch": {},
        }
    return {"target_kind": "NONE", "tracking": "ENDED"}


def state_is_exact(state: Mapping[str, Any]) -> bool:
    return set(state) == STATE_FIELDS and state["phase"] in PHASES and state["red_count"] in {0, 1, 2, 3}


def initialization_steps(*, project: bool, can_create_local: bool, current_mode: str) -> list[str]:
    if not project:
        return ["PROJECTLESS_STOP"]
    if not can_create_local:
        return ["LOCAL_TASK_UNAVAILABLE"]
    if current_mode in {"cloud", "worktree"}:
        return ["CONSULTANT_NEW_LOCAL_ONLY", "CONTROL_CREATE", "INITIALIZATION_COMPLETE"]
    return ["CONSULTANT_SELECT", "CONTROL_CREATE", "INITIALIZATION_COMPLETE"]


def first_consultant_choice() -> tuple[str, ...]:
    return ("当前任务升级为顾问", "新建本地顾问", "取消执行 Skill")


def control_choice() -> tuple[str, ...]:
    return ("创建全新的中控台任务", "取消执行 Skill")


def cancellation_choices() -> tuple[str, ...]:
    return ("保留产物及任务", "删除产物但不删除任务", "删除产物及任务")


def cancellation_effect(choice: str, *, hard_delete: bool) -> str:
    if choice not in {"1", "2", "3"}:
        return "INVALID"
    if choice == "1":
        return "KEEP"
    if choice == "2":
        return "CLEAN_ARTIFACTS_KEEP_TASK"
    return "DELETE_TASKS" if hard_delete else "ARCHIVE_OR_MANUAL_DELETE"


def recovery_choices(consultant: str, control: str) -> tuple[str, ...]:
    if consultant == "archived" and control == "archived":
        return ("忽略归档并新建", "从归档恢复", "停止")
    if {consultant, control} == {"archived", "deleted"}:
        return ("忽略归档并重建缺失角色", "恢复可恢复角色并重建缺失角色", "停止")
    if consultant in {"missing", "deleted"} or control in {"missing", "deleted"}:
        return ("强制重建缺失角色", "停止")
    return ("无需恢复",)


def state_error_choices() -> tuple[str, ...]:
    return ("授权检查并尝试修复", "重新新建状态文件", "停止执行 Skill")


def transfer_choices() -> tuple[str, ...]:
    return ("携带上下文与最新计划切换", "不携带上下文直接切换", "取消并留在当前任务")


def transfer_contract(*, with_context: bool, plan: str, paths: list[str]) -> dict[str, Any]:
    return {
        "source_task": "SELF_CURRENT",
        "target_consultant": "019-consultant",
        "project_root": "D:/project",
        "context": "integrated context" if with_context else None,
        "latest_complete_plan": plan if with_context else None,
        "explicit_paths": paths if with_context else [],
        "switch_last": True,
        "fresh_loop_required_after_switch": True,
    }


def red_result(round_number: int, verdict: str, blocking_items: list[str]) -> dict[str, Any]:
    if round_number not in {1, 2, 3}:
        raise ValueError("round must be 1..3")
    if verdict not in {"RED_ALL_PASS", "CHANGES_REQUIRED"}:
        raise ValueError("formal verdict must be current two-valued contract")
    if verdict == "CHANGES_REQUIRED" and not blocking_items:
        raise ValueError("CHANGES_REQUIRED needs a blocking item")
    return {"round": round_number, "verdict": verdict, "blocking_items": blocking_items}


def after_red(result: Mapping[str, Any]) -> str:
    if result["verdict"] == "RED_ALL_PASS":
        return "AUTO_EXECUTE"
    if result["round"] < 3:
        return "FIX_PLAN_AND_RESUBMIT"
    return "FINAL_RISK_AUDIT"


def red_dispatch(
    result: Mapping[str, Any],
    *,
    plan_confirmed: bool,
    gates_clear: bool,
    current_red_count: int,
    plan_version_match: bool,
) -> dict[str, Any]:
    if result["verdict"] == "RED_ALL_PASS":
        route = red_all_pass_route(
            round_number=result["round"],
            plan_confirmed=plan_confirmed,
            gates_clear=gates_clear,
            plan_version_match=plan_version_match,
        )
        return {
            "route": route,
            "phase": "EXECUTION" if route == "AUTO_EXECUTE" else "RED",
            "red_count": current_red_count,
        }
    if result["round"] < 3:
        return {"route": "FIX_PLAN_AND_RESUBMIT", "phase": "RED", "red_count": current_red_count}
    return {"route": "FINAL_RISK_AUDIT", "phase": "RED", "red_count": 3}


def red_item_disposition(*, blocker_kind: str, evidence_clear: bool, within_authority: bool) -> str:
    if blocker_kind in {
        "preference",
        "future",
        "unrelated",
        "duplicate",
        "unsupported_risk",
        "permission_expansion",
        "goal_change",
        "complexity_only",
    }:
        return "REJECT"
    if blocker_kind in {"goal", "rule", "permission", "security", "verification"} and evidence_clear and within_authority:
        return "ACCEPT"
    return "CHALLENGE"


def challenge_resolution(*, fingerprint: str, evidence_supplements: int, materially_new_evidence: bool) -> dict[str, Any]:
    if not fingerprint:
        raise ValueError("challenge fingerprint is required")
    if evidence_supplements == 0:
        disposition = "CHALLENGE"
    elif evidence_supplements == 1:
        disposition = "ACCEPT" if materially_new_evidence else "REJECT"
    else:
        disposition = "REJECT"
    return {"fingerprint": fingerprint, "disposition": disposition, "red_count_delta": 0, "nested_red": False}


def accepted_red_items(items: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in items if item.get("disposition") == "ACCEPT"]


def final_risk_audit(
    *,
    red3_version_sha256: str,
    red4_candidate_sha256: str,
    verdict: str,
    red3_unresolved_items: list[str],
    red4_changes: list[str],
    red4_remaining_risks: list[str],
    authority_change_requested: str,
    recommended_route: str,
    unresolved_disagreement: list[str],
) -> dict[str, Any]:
    if verdict not in {"RISK_ACCEPTABLE", "RISK_REMAINS"}:
        raise ValueError("unsupported final risk verdict")
    if authority_change_requested not in {"YES", "NO"}:
        raise ValueError("authority_change_requested must be YES or NO")
    if recommended_route not in {"RED3", "RED4"}:
        raise ValueError("recommended_route must be RED3 or RED4")
    return {
        "based_on_red_count": 3,
        "red3_version_sha256": red3_version_sha256,
        "reviewed_version": "RED4_CANDIDATE",
        "red4_candidate_sha256": red4_candidate_sha256,
        "verdict": verdict,
        "red3_unresolved_items": red3_unresolved_items,
        "red4_changes": red4_changes,
        "red4_remaining_risks": red4_remaining_risks,
        "authority_change_requested": authority_change_requested,
        "recommended_route": recommended_route,
        "unresolved_disagreement": unresolved_disagreement,
    }


def final_risk_choice(
    text: str,
    *,
    red3_plan: str,
    red3_sha256: str,
    red4_plan: str | None = None,
    red4_sha256: str | None = None,
) -> str:
    value = text.strip()
    if value == "1":
        if not plan_version_matches(red3_plan, red3_sha256):
            raise ValueError("RED3 plan version mismatch")
        return "EXECUTE_RED3"
    if value == "2":
        if red4_plan is None or red4_sha256 is None or not plan_version_matches(red4_plan, red4_sha256):
            raise ValueError("RED4 candidate version mismatch")
        return "EXECUTE_RED4_FINAL"
    if value == "3":
        return "ENDED"
    return "WAIT"


def message_only_probe(
    *,
    consultant_id: str,
    control_id: str,
    host_id: str,
    tools_used: bool = False,
    files_changed: bool = False,
    business_state_changed: bool = False,
    extra_tasks: int = 0,
) -> dict[str, Any]:
    return {
        "consultant_thread_id": consultant_id,
        "control_thread_id": control_id,
        "hostId": host_id,
        "message_only": True,
        "tools_used": tools_used,
        "files_changed": files_changed,
        "business_state_changed": business_state_changed,
        "extra_tasks": extra_tasks,
    }


def next_round_action(text: str) -> str:
    value = text.strip()
    if value == "1":
        return "PLAN_DISPLAYED"
    if value == "2":
        return "DIRECTION_REQUESTED"
    if value == "3" or value == "":
        return "ENDED"
    return "ENDED"


def state_recovery_state(consultant_id: str, control_id: str, now: str) -> dict[str, Any]:
    return {
        "project_root": "D:/project",
        "initialized_at": now,
        "consultant_thread_id": consultant_id,
        "control_thread_id": control_id,
        "phase": "READY",
        "red_count": 0,
        "updated_at": now,
    }


def run_storage_preflight(project_root: Path, mode: str = "current") -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", str(STORAGE_SCRIPT_PATH), "--project-root", str(project_root), "--mode", mode],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=True,
    )
    return json.loads(completed.stdout)


def make_strict_index(root: Path, *, state_row: str | None = None, report_row: str | None = None) -> None:
    rows = ["# FOLDER_INDEX", "Top-level entries are indexed and must remain registered."]
    if state_row:
        rows.append(state_row)
    if report_row:
        rows.append(report_row)
    (root / "FOLDER_INDEX.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_valid_state(root: Path, relative: str, *, phase: str = "ENDED", red_count: int = 3) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = "2026-08-09T12:00:00+08:00"
    path.write_text(
        textwrap.dedent(
            f"""\
            project_root: {root}
            initialized_at: {timestamp}
            consultant_thread_id: consultant-exact
            control_thread_id: control-exact
            phase: {phase}
            red_count: {red_count}
            updated_at: {timestamp}
            """
        ),
        encoding="utf-8",
    )
    return path


def controlled_temp_initialization(root: Path, *, strict: bool = False) -> dict[str, Any]:
    result = run_storage_preflight(root, "simulate-first-init")
    assert result["task_creation_allowed"]
    state_path = Path(result["resolved_state_path"])
    report_root = Path(result["resolved_report_root"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    write_valid_state(root, str(state_path.relative_to(root)))
    (report_root / "execution.md").write_text("temporary controlled report\n", encoding="utf-8")
    if not strict:
        (state_path.parent / ".gitignore").write_text("*\n", encoding="utf-8")
    return result


def top_level_names(root: Path) -> set[str]:
    return {item.name for item in root.iterdir()}


def fixture_snapshot(root: Path) -> tuple[tuple[str, int, bytes], ...]:
    return tuple(
        sorted(
            (
                path.relative_to(root).as_posix(),
                path.stat().st_size,
                path.read_bytes(),
            )
            for path in root.rglob("*")
            if path.is_file()
        )
    )


class FinalContractScenarios(unittest.TestCase):
    def test_all_exact_activation_entries_and_no_sentence_trigger(self) -> None:
        for trigger in ("loop", "/loop", "$loop", "$co-op-loop", " LOOP ", "/LOOP", "$CO-OP-LOOP"):
            self.assertTrue(is_loop_trigger(trigger))
        for ordinary in ("please loop", "loop now", "use $loop here", "a $co-op-loop sentence"):
            self.assertFalse(is_loop_trigger(ordinary))

    def test_state_is_exactly_seven_fields_and_all_phases(self) -> None:
        state = state_recovery_state("consultant", "control", "2026-08-09T12:00:00+08:00")
        self.assertTrue(state_is_exact(state))
        self.assertEqual(set(state), STATE_FIELDS)
        self.assertEqual(PHASES, {"INITIALIZING", "READY", "RED", "EXECUTION", "REVIEW", "WAITING_USER", "ENDED"})
        self.assertFalse(state_is_exact(dict(state, extra="forbidden")))
        self.assertFalse(state_is_exact(dict(state, phase="PLAN_READY")))

    def test_first_initialization_three_gates(self) -> None:
        self.assertEqual(initialization_steps(project=False, can_create_local=True, current_mode="local"), ["PROJECTLESS_STOP"])
        self.assertEqual(initialization_steps(project=True, can_create_local=False, current_mode="local"), ["LOCAL_TASK_UNAVAILABLE"])
        self.assertEqual(initialization_steps(project=True, can_create_local=True, current_mode="cloud"), ["CONSULTANT_NEW_LOCAL_ONLY", "CONTROL_CREATE", "INITIALIZATION_COMPLETE"])
        self.assertEqual(first_consultant_choice(), ("当前任务升级为顾问", "新建本地顾问", "取消执行 Skill"))
        self.assertEqual(control_choice(), ("创建全新的中控台任务", "取消执行 Skill"))

    def test_cancellation_and_host_delete_downgrade(self) -> None:
        self.assertEqual(cancellation_choices(), ("保留产物及任务", "删除产物但不删除任务", "删除产物及任务"))
        self.assertEqual(cancellation_effect("1", hard_delete=False), "KEEP")
        self.assertEqual(cancellation_effect("2", hard_delete=False), "CLEAN_ARTIFACTS_KEEP_TASK")
        self.assertEqual(cancellation_effect("3", hard_delete=False), "ARCHIVE_OR_MANUAL_DELETE")
        self.assertEqual(cancellation_effect("3", hard_delete=True), "DELETE_TASKS")

    def test_active_archive_deleted_and_mixed_recovery(self) -> None:
        self.assertEqual(len(recovery_choices("archived", "archived")), 3)
        mixed = recovery_choices("archived", "deleted")
        self.assertIn("重建缺失角色", mixed[1])
        self.assertEqual(len(recovery_choices("missing", "active")), 2)
        recovered = state_recovery_state("new-consultant", "restored-control", "now")
        self.assertEqual(recovered["phase"], "READY")
        self.assertEqual(recovered["red_count"], 0)

    def test_state_error_repair_rebuild_stop(self) -> None:
        self.assertEqual(len(state_error_choices()), 3)
        broken = {"project_root": "D:/project", "phase": "BAD"}
        self.assertFalse(state_is_exact(broken))

    def test_wrong_task_transfer_with_and_without_context(self) -> None:
        self.assertEqual(len(transfer_choices()), 3)
        with_context = transfer_contract(with_context=True, plan="complete plan", paths=["D:/project/reports/a.md"])
        self.assertEqual(with_context["latest_complete_plan"], "complete plan")
        self.assertEqual(with_context["explicit_paths"], ["D:/project/reports/a.md"])
        self.assertTrue(with_context["switch_last"])
        self.assertTrue(with_context["fresh_loop_required_after_switch"])
        without_context = transfer_contract(with_context=False, plan="complete plan", paths=[])
        self.assertIsNone(without_context["context"])

    def test_red_all_pass_auto_dispatch_after_initial_confirmation(self) -> None:
        passed = red_result(1, "RED_ALL_PASS", [])
        self.assertEqual(after_red(passed), "AUTO_EXECUTE")
        self.assertEqual(
            red_dispatch(
                passed,
                plan_confirmed=True,
                gates_clear=True,
                current_red_count=1,
                plan_version_match=True,
            ),
            {"route": "AUTO_EXECUTE", "phase": "EXECUTION", "red_count": 1},
        )
        with self.assertRaises(ValueError):
            red_result(1, "CHANGES_REQUIRED", [])

    def test_plan_wait_and_latest_plan_confirmation(self) -> None:
        self.assertEqual(plan_confirmation("1"), "SEND_RED")
        self.assertEqual(plan_confirmation("执行"), "SEND_RED")
        self.assertEqual(plan_confirmation("2"), "WAIT_FOR_LATEST_LOOP")
        self.assertEqual(plan_confirmation("再等等"), "WAIT_FOR_LATEST_LOOP")
        self.assertEqual(plan_confirmation("确认发送"), "ORDINARY_TEXT")

    def test_execution_preflight_retry_correction_silence_and_statuses(self) -> None:
        self.assertEqual(preflight(["read", "write_report"], {"read", "write_report"}), "PROCEED")
        self.assertEqual(preflight(["read", "publish"], {"read", "write_report"}), "EXECUTION_PAUSED")
        self.assertEqual(retry_state("f-1", ["method-a", "method-a"]), "REPEATED_FAILURE")
        self.assertEqual(retry_state("f-1", ["method-a", "method-b"]), "RETRY_ALLOWED")
        self.assertEqual(correction_state("f-1", set()), "CORRECTION_ALLOWED")
        self.assertEqual(correction_state("f-1", {"f-1"}), "EXECUTION_PAUSED")
        self.assertEqual(tracking_mode("normal_progress"), "SILENT")
        self.assertEqual(tracking_mode("digest_mismatch"), "INTERVENE")
        self.assertEqual(execution_report_contract(business_report_required=True), {"loop_report_required": True, "business_report_required": True, "consultant_evaluation_required": True})
        self.assertEqual({execution_status(value) for value in EXECUTION_STATUSES}, EXECUTION_STATUSES)
        with self.assertRaises(ValueError):
            execution_status("COMPLETED")

    def test_second_round_semantics_and_real_evidence_suggestion(self) -> None:
        self.assertIn("最小真实证据", next_round_suggestion(complete=True, project_type="skill"))
        self.assertIn("第二轮计划", next_round_suggestion(complete=False, project_type="skill"))
        self.assertEqual(next_round_action("2"), "DIRECTION_REQUESTED")
        self.assertEqual(next_round_action("3"), "ENDED")

    def test_model_switch_fallback_prompt(self) -> None:
        self.assertIn("Sol High", model_switch_prompt("consultant", False))
        self.assertIn("Luna Max（最高）", model_switch_prompt("control", False))
        self.assertEqual(model_switch_prompt("consultant", True), "")

    def test_control_source_menu_and_candidate_discovery_modes(self) -> None:
        self.assertEqual(
            control_source_choices(),
            (
                "新建一个本地中控台任务",
                "查找并复用本项目已有的“中控”任务，升级为本 Loop 的中控台",
                "通过任务线程 ID 指定并升级为中控台任务",
                "取消本次初始化",
            ),
        )
        protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
        self.assertIn("请发送需要指定的完整任务线程 ID。", protocol)
        self.assertIn("Only exact `1` confirms the upgrade", protocol)
        candidates = [
            {"thread_id": "consultant", "title": "中控顾问", "status": "active", "environment": "local", "project_root": "D:/project"},
            {"thread_id": "control-1", "title": "项目中控", "status": "active", "environment": "local", "project_root": "D:/project"},
            {"thread_id": "cloud-1", "title": "中控云任务", "status": "active", "environment": "cloud", "project_root": "D:/project"},
            {"thread_id": "other-project", "title": "中控台", "status": "active", "environment": "local", "project_root": "D:/other"},
            {"thread_id": "inactive", "title": "中控归档", "status": "archived", "environment": "local", "project_root": "D:/project"},
            {"thread_id": "ordinary", "title": "普通本地任务", "status": "active", "environment": "local", "project_root": "D:/project"},
        ]
        eligible = eligible_control_candidates(candidates, consultant_id="consultant", project_root="D:/project")
        self.assertEqual([candidate["thread_id"] for candidate in eligible], ["control-1"])
        self.assertEqual(control_candidate_mode(eligible), "UNIQUE_REQUIRES_ID_CONFIRMATION")
        self.assertEqual(control_candidate_mode(eligible + [{"thread_id": "control-2", "title": "中控台二", "status": "active", "environment": "local", "project_root": "D:/project"}]), "MULTI_REQUIRES_ID_SELECTION")
        self.assertEqual(control_candidate_mode([]), "ZERO_CANDIDATES")

    def test_exact_id_role_upgrade_and_historical_context_boundary(self) -> None:
        self.assertFalse(role_upgrade_binding_ready(exact_id_known=False, declaration_delivered=True, role_verified=True))
        self.assertFalse(role_upgrade_binding_ready(exact_id_known=True, declaration_delivered=False, role_verified=True))
        self.assertFalse(role_upgrade_binding_ready(exact_id_known=True, declaration_delivered=True, role_verified=False))
        self.assertTrue(role_upgrade_binding_ready(exact_id_known=True, declaration_delivered=True, role_verified=True))
        declaration = role_upgrade_declaration("control-1")
        self.assertIn("control-1", declaration)
        self.assertIn("historical material only", declaration)
        self.assertIn("no current plan or execution authorization", declaration)

    def test_short_role_contracts_and_read_timing(self) -> None:
        skill = SKILL_PATH.read_text(encoding="utf-8")
        protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
        for marker in ("CONSULTANT_ROLE", "CONTROL_ROLE", "MISSION:", "PROHIBITED:", "PREFERENCE:"):
            self.assertIn(marker, skill)
        self.assertIn("smallest executable plan", skill)
        self.assertIn("RED is blocker-only", skill)
        self.assertIn("Before drafting or revising each plan version", protocol)
        self.assertIn("Before issuing RED for that plan version", protocol)
        self.assertIn("Do not repeat the role read per message", protocol)

    def test_control_host_access_separates_read_capability_from_write_authority(self) -> None:
        skill = SKILL_PATH.read_text(encoding="utf-8")
        adapter = " ".join(HOST_ADAPTATION_PATH.read_text(encoding="utf-8").split())
        self.assertIn("unrestricted local read access", skill)
        self.assertIn("no per-path sandbox approval", skill)
        self.assertIn("writes and side effects unauthorized", adapter)
        self.assertIn("user-confirmed", adapter)
        self.assertIn("do not request paths one by one", adapter)

    def test_consultant_business_request_routes_without_bypassing_gates(self) -> None:
        self.assertEqual(
            business_route(business_request=False, control_status="active", plan_confirmed=True, red_passed=True, high_risk_cleared=True, stop_conditions_clear=True),
            {"route": "CONSULTANT_GOVERNANCE", "action": "HANDLE_IN_CONSULTANT"},
        )
        self.assertEqual(
            business_route(business_request=True, control_status="unbound", plan_confirmed=False, red_passed=False, high_risk_cleared=False, stop_conditions_clear=False),
            {"route": "CONTROL_SOURCE_SELECTION", "action": "BIND_CONTROL"},
        )
        self.assertEqual(
            business_route(business_request=True, control_status="archived", plan_confirmed=True, red_passed=True, high_risk_cleared=True, stop_conditions_clear=True),
            {"route": "CONTROL_RECOVERY", "action": "RESTORE_OR_REBUILD"},
        )
        self.assertEqual(
            business_route(business_request=True, control_status="active", plan_confirmed=False, red_passed=True, high_risk_cleared=True, stop_conditions_clear=True),
            {"route": "PLAN_CONFIRMATION", "action": "DISPLAY_PLAN_GATE"},
        )
        self.assertEqual(
            business_route(business_request=True, control_status="active", plan_confirmed=True, red_passed=False, high_risk_cleared=True, stop_conditions_clear=True),
            {"route": "RED_FLOW", "action": "SEND_OR_CONTINUE_RED"},
        )
        self.assertEqual(
            business_route(business_request=True, control_status="active", plan_confirmed=True, red_passed=True, high_risk_cleared=False, stop_conditions_clear=True),
            {"route": "HIGH_RISK_GATE", "action": "PAUSE"},
        )
        routed = business_route(business_request=True, control_status="active", plan_confirmed=True, red_passed=True, high_risk_cleared=True, stop_conditions_clear=True)
        self.assertEqual(routed["route"], "CONTROL")
        self.assertEqual(routed["action"], "SEND_EXECUTION_PACKAGE")
        self.assertFalse(routed["duplicate_transfer_confirmation"])

    def test_completed_goals_keep_minimal_evidence_suggestion_without_auto_execution(self) -> None:
        suggestion = completed_evidence_suggestion()
        self.assertIn("真实业务 canary", suggestion["text"])
        self.assertIn("跨操作系统测试", suggestion["text"])
        self.assertIn("本机冷启动", suggestion["text"])
        self.assertIn("只建议，不自动执行", suggestion["text"])
        self.assertFalse(suggestion["auto_execute"])

    def test_completed_goals_use_runtime_addressed_compact_three_choice_closeout(self) -> None:
        action = "基于当前操作系统的真实兼容性测试"
        message = completed_closeout_message("Stella", action)
        self.assertTrue(message.startswith("Stella，本轮既定目标已经全部完成。"))
        self.assertNotIn("authorized human approver，本轮", message)
        self.assertIn(action, message)
        self.assertIn("1. 继续，指派中控任务执行", message)
        self.assertIn("2. 继续，新建业务任务执行", message)
        self.assertIn("3. 不做", message)
        self.assertIn("无回复默认选择 3", message)
        self.assertEqual(completed_closeout_choice("1"), "CONTROL_NEXT_ROUND")
        self.assertEqual(completed_closeout_choice("2"), "BUSINESS_TASK_NEXT_ROUND")
        self.assertEqual(completed_closeout_choice("3"), "ENDED")
        self.assertEqual(completed_closeout_choice(""), "ENDED")
        self.assertEqual(completed_closeout_choice("确认"), "ORDINARY_TEXT")

    def test_completed_closeout_targets_and_original_gates_remain_required(self) -> None:
        action = "基于当前操作系统的真实兼容性测试"
        control = closeout_execution_target(
            "1",
            control_thread_id="control-exact-1",
            business_thread_id="business-next-1",
            action_name=action,
            project_name="co-op-loop",
        )
        self.assertEqual(control["target_kind"], "CONTROL")
        self.assertEqual(control["thread_id"], "control-exact-1")
        self.assertFalse(control["consultant_is_target"])
        for gate in ("requires_plan_confirmation", "requires_red", "requires_high_risk_clear", "requires_stop_clear"):
            self.assertTrue(control[gate])

        business = closeout_execution_target(
            "2",
            control_thread_id="control-exact-1",
            business_thread_id="business-next-1",
            action_name=action,
            project_name="co-op-loop",
        )
        self.assertEqual(business["target_kind"], "BUSINESS_TASK")
        self.assertEqual(business["thread_id"], "business-next-1")
        self.assertEqual(business["title"], f"业务 | {action}")
        self.assertEqual(business["environment"], "local")
        self.assertTrue(business["one_time"])
        self.assertNotEqual(business["title"], "业务 | co-op-loop")
        self.assertFalse(business["consultant_is_target"])
        self.assertEqual(business["state_patch"], {})
        for gate in ("requires_plan_confirmation", "requires_red", "requires_high_risk_clear", "requires_stop_clear"):
            self.assertTrue(business[gate])
        self.assertNotIn("consultant_thread_id", business["state_patch"])
        self.assertNotIn("control_thread_id", business["state_patch"])
        self.assertEqual(closeout_execution_target("3", control_thread_id="control-exact-1", business_thread_id="business-next-1", action_name=action, project_name="co-op-loop"), {"target_kind": "NONE", "tracking": "ENDED"})
        self.assertEqual(closeout_execution_target("", control_thread_id="control-exact-1", business_thread_id="business-next-1", action_name=action, project_name="co-op-loop"), {"target_kind": "NONE", "tracking": "ENDED"})
        with self.assertRaises(ValueError):
            closeout_execution_target("2", control_thread_id="control-exact-1", business_thread_id="business-next-1", action_name="co-op-loop", project_name="co-op-loop")

    def test_protocol_text_scopes_closeout_option_two_and_uses_generic_report_wording(self) -> None:
        protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
        incomplete_menu = "If the evaluation reports unfinished items, show the next-step text without a\npopup:"
        completed_menu = "If the evaluation confirms that all goals are complete, do not show the\nunfinished-item menu."
        unfinished_scope = "For the unfinished-item menu only, an entire reply exactly equal to `1`, `2`,\nor `3` matches."
        self.assertIn(incomplete_menu, protocol)
        self.assertIn(completed_menu, protocol)
        self.assertIn(unfinished_scope, protocol)
        self.assertIn("Exact `2` stays in the current conversation waiting for normal text direction", protocol)
        completed_start = protocol.index(completed_menu)
        unfinished_scope_start = protocol.index(unfinished_scope)
        self.assertLess(completed_start, unfinished_scope_start)
        completed_text = protocol[completed_start:unfinished_scope_start]
        self.assertIn("For exact reply `2`,\ncreate one local one-time business task", completed_text)
        self.assertNotIn("Exact `2` stays in the current conversation", completed_text)
        self.assertIn("回读执行报告", completed_text)
        self.assertNotIn("回读测试报告", completed_text)
        self.assertIn("After the initial exact plan confirmation", protocol)
        self.assertIn("FINAL_RISK_AUDIT", protocol)
        self.assertIn("CHALLENGE", protocol)
        self.assertNotIn("On `RED_ALL_PASS`, ask authorized human approver", protocol)

    def test_three_red_enters_final_risk_audit(self) -> None:
        for number in (1, 2):
            result = red_result(number, "CHANGES_REQUIRED", ["blocking evidence"])
            self.assertEqual(after_red(result), "FIX_PLAN_AND_RESUBMIT")
        third = red_result(3, "CHANGES_REQUIRED", ["blocking evidence"])
        self.assertEqual(after_red(third), "FINAL_RISK_AUDIT")
        self.assertEqual(
            red_dispatch(
                third,
                plan_confirmed=True,
                gates_clear=True,
                current_red_count=3,
                plan_version_match=True,
            ),
            {"route": "FINAL_RISK_AUDIT", "phase": "RED", "red_count": 3},
        )

    def test_red_all_pass_any_first_three_round_auto_executes(self) -> None:
        for number in (1, 2, 3):
            with self.subTest(round_number=number):
                result = red_result(number, "RED_ALL_PASS", [])
                self.assertEqual(
                    red_all_pass_route(round_number=number, plan_confirmed=True, gates_clear=True, plan_version_match=True),
                    "AUTO_EXECUTE",
                )
                self.assertEqual(after_red(result), "AUTO_EXECUTE")

    def test_auto_execution_enters_execution_and_retains_red_count(self) -> None:
        result = red_result(2, "RED_ALL_PASS", [])
        dispatched = red_dispatch(
            result,
            plan_confirmed=True,
            gates_clear=True,
            current_red_count=2,
            plan_version_match=True,
        )
        self.assertEqual(dispatched["phase"], "EXECUTION")
        self.assertEqual(dispatched["red_count"], 2)

    def test_unconfirmed_plan_blocks_red_all_pass_dispatch(self) -> None:
        result = red_result(1, "RED_ALL_PASS", [])
        dispatched = red_dispatch(
            result,
            plan_confirmed=False,
            gates_clear=True,
            current_red_count=1,
            plan_version_match=True,
        )
        self.assertEqual(dispatched["route"], "PLAN_CONFIRMATION_REQUIRED")
        self.assertEqual(dispatched["phase"], "RED")

    def test_plan_confirmation_binds_exact_plan_version(self) -> None:
        displayed = "BEGIN_PLAN_TEXT\nexact plan\nEND_PLAN_TEXT"
        self.assertTrue(plan_confirmation_binds_exact_version("1", displayed, displayed))
        self.assertTrue(plan_confirmation_binds_exact_version("执行", displayed, displayed))
        self.assertFalse(plan_confirmation_binds_exact_version("1", displayed, displayed + " changed"))
        self.assertFalse(plan_confirmation_binds_exact_version("确认", displayed, displayed))
        self.assertTrue(
            authorized_human_plan_confirmation(
                "1", actor="authorized_human", authorized_actor="authorized_human"
            )
        )
        for actor in ("agent", "ordinary_text", "forwarded_message", "unauthorized_caller"):
            self.assertFalse(
                authorized_human_plan_confirmation(
                    "1", actor=actor, authorized_actor="authorized_human"
                )
            )
        self.assertFalse(
            authorized_human_plan_confirmation(
                "确认发送", actor="authorized_human", authorized_actor="authorized_human"
            )
        )

    def test_unmet_high_risk_or_stop_gate_pauses_auto_execution(self) -> None:
        self.assertEqual(
            red_all_pass_route(round_number=1, plan_confirmed=True, gates_clear=False, plan_version_match=True),
            "EXECUTION_PAUSED",
        )
        self.assertEqual(
            red_all_pass_route(round_number=1, plan_confirmed=True, gates_clear=True, plan_version_match=False),
            "PLAN_VERSION_MISMATCH",
        )

    def test_third_changes_required_triggers_final_audit_without_round_four(self) -> None:
        result = red_result(3, "CHANGES_REQUIRED", ["blocking evidence"])
        self.assertEqual(after_red(result), "FINAL_RISK_AUDIT")
        self.assertRaises(ValueError, red_result, 4, "CHANGES_REQUIRED", ["blocking evidence"])

    def test_final_risk_audit_contract_and_verdict_are_fixed(self) -> None:
        audit = final_risk_audit(
            red3_version_sha256="A" * 64,
            red4_candidate_sha256="B" * 64,
            verdict="RISK_REMAINS",
            red3_unresolved_items=["risk"],
            red4_changes=["bounded change"],
            red4_remaining_risks=["residual"],
            authority_change_requested="NO",
            recommended_route="RED4",
            unresolved_disagreement=[],
        )
        self.assertEqual(audit["based_on_red_count"], 3)
        self.assertEqual(audit["reviewed_version"], "RED4_CANDIDATE")
        self.assertEqual(audit["verdict"], "RISK_REMAINS")
        self.assertEqual(set(audit), {
            "based_on_red_count", "red3_version_sha256", "reviewed_version", "red4_candidate_sha256",
            "verdict", "red3_unresolved_items", "red4_changes", "red4_remaining_risks",
            "authority_change_requested", "recommended_route", "unresolved_disagreement",
        })

    def test_final_risk_audit_keeps_red_count_three_before_and_after(self) -> None:
        third = red_dispatch(
            red_result(3, "CHANGES_REQUIRED", ["blocking evidence"]),
            plan_confirmed=True,
            gates_clear=True,
            current_red_count=3,
            plan_version_match=True,
        )
        audit = final_risk_audit(
            red3_version_sha256="A" * 64,
            red4_candidate_sha256="B" * 64,
            verdict="RISK_ACCEPTABLE",
            red3_unresolved_items=[],
            red4_changes=[],
            red4_remaining_risks=[],
            authority_change_requested="NO",
            recommended_route="RED4",
            unresolved_disagreement=[],
        )
        self.assertEqual(third["red_count"], 3)
        self.assertEqual(audit["based_on_red_count"], 3)

    def test_exact_one_rechecks_hash_then_executes_red3(self) -> None:
        red3 = "BEGIN_PLAN_TEXT\nRED3 exact body\nEND_PLAN_TEXT"
        result = final_risk_choice("1", red3_plan=red3, red3_sha256=plan_version_sha256(red3))
        self.assertEqual(result, "EXECUTE_RED3")
        with self.assertRaises(ValueError):
            final_risk_choice("1", red3_plan=red3, red3_sha256="0" * 64)

    def test_exact_two_forms_red4_final_without_more_red(self) -> None:
        red3 = "BEGIN_PLAN_TEXT\nRED3 exact body\nEND_PLAN_TEXT"
        red4 = "BEGIN_PLAN_TEXT\nRED4 bounded body\nEND_PLAN_TEXT"
        self.assertEqual(
            final_risk_choice(
                "2",
                red3_plan=red3,
                red3_sha256=plan_version_sha256(red3),
                red4_plan=red4,
                red4_sha256=plan_version_sha256(red4),
            ),
            "EXECUTE_RED4_FINAL",
        )

    def test_exact_three_ends_and_non_exact_waits(self) -> None:
        plan = "BEGIN_PLAN_TEXT\nbody\nEND_PLAN_TEXT"
        digest = plan_version_sha256(plan)
        self.assertEqual(final_risk_choice("3", red3_plan=plan, red3_sha256=digest), "ENDED")
        self.assertEqual(final_risk_choice("3 ", red3_plan=plan, red3_sha256=digest), "ENDED")
        self.assertEqual(final_risk_choice("确认", red3_plan=plan, red3_sha256=digest), "WAIT")

    def test_valid_red_blocker_is_accepted(self) -> None:
        self.assertEqual(red_item_disposition(blocker_kind="security", evidence_clear=True, within_authority=True), "ACCEPT")
        self.assertEqual(red_item_disposition(blocker_kind="verification", evidence_clear=True, within_authority=True), "ACCEPT")

    def test_challenge_allows_one_evidence_supplement_without_count(self) -> None:
        challenged = challenge_resolution(fingerprint="fp-1", evidence_supplements=0, materially_new_evidence=False)
        resolved = challenge_resolution(fingerprint="fp-1", evidence_supplements=1, materially_new_evidence=True)
        self.assertEqual(challenged["disposition"], "CHALLENGE")
        self.assertEqual(resolved["disposition"], "ACCEPT")
        self.assertEqual(resolved["red_count_delta"], 0)
        self.assertFalse(resolved["nested_red"])

    def test_same_fingerprint_without_new_evidence_rejects_without_nesting(self) -> None:
        resolved = challenge_resolution(fingerprint="fp-1", evidence_supplements=1, materially_new_evidence=False)
        repeated = challenge_resolution(fingerprint="fp-1", evidence_supplements=2, materially_new_evidence=True)
        self.assertEqual(resolved["disposition"], "REJECT")
        self.assertEqual(repeated["disposition"], "REJECT")
        self.assertFalse(repeated["nested_red"])

    def test_preference_future_expansion_rejected_and_mixed_accept_only(self) -> None:
        self.assertEqual(red_item_disposition(blocker_kind="preference", evidence_clear=True, within_authority=True), "REJECT")
        self.assertEqual(red_item_disposition(blocker_kind="future", evidence_clear=True, within_authority=True), "REJECT")
        self.assertEqual(red_item_disposition(blocker_kind="permission_expansion", evidence_clear=True, within_authority=False), "REJECT")
        items = [
            {"id": "valid", "disposition": "ACCEPT"},
            {"id": "preference", "disposition": "REJECT"},
            {"id": "challenge", "disposition": "CHALLENGE"},
        ]
        self.assertEqual(accepted_red_items(items), [{"id": "valid", "disposition": "ACCEPT"}])

    def test_plan_hash_normalization_and_message_only_probe(self) -> None:
        body = "Mixed Case  \nkeep  spaces\n"
        lf_plan = "prefix\nBEGIN_PLAN_TEXT\n" + body + "END_PLAN_TEXT\n"
        crlf_plan = lf_plan.replace("\n", "\r\n")
        self.assertEqual(plan_version_sha256(lf_plan), plan_version_sha256(crlf_plan))
        changed = lf_plan.replace("Mixed Case", "mixed case")
        self.assertNotEqual(plan_version_sha256(lf_plan), plan_version_sha256(changed))
        probe = message_only_probe(
            consultant_id="TEST_CONSULTANT_SYNTHETIC",
            control_id="TEST_CONTROL_SYNTHETIC",
            host_id="local",
        )
        self.assertEqual(probe["consultant_thread_id"], "TEST_CONSULTANT_SYNTHETIC")
        self.assertEqual(probe["control_thread_id"], "TEST_CONTROL_SYNTHETIC")
        self.assertTrue(probe["message_only"])
        self.assertFalse(probe["tools_used"])
        self.assertFalse(probe["files_changed"])
        self.assertFalse(probe["business_state_changed"])
        self.assertEqual(probe["extra_tasks"], 0)

    def test_single_round_closeout_and_fresh_loop(self) -> None:
        self.assertEqual(next_round_action("1"), "PLAN_DISPLAYED")
        self.assertEqual(next_round_action("2"), "DIRECTION_REQUESTED")
        self.assertEqual(next_round_action("3"), "ENDED")
        self.assertEqual(next_round_action(""), "ENDED")
        self.assertEqual(next_round_action("loop"), "ENDED")


class StorageAdaptationScenarios(unittest.TestCase):
    def test_empty_and_non_git_projects_use_one_default_namespace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-empty-") as raw:
            root = Path(raw) / "项目中文"
            root.mkdir()
            before = top_level_names(root)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "DEFAULT")
            self.assertTrue(result["task_creation_allowed"])
            self.assertEqual(result["writes_performed"], 0)
            self.assertEqual(result["task_creations_performed"], 0)
            self.assertEqual(top_level_names(root), before)
            self.assertTrue(str(result["resolved_state_path"]).endswith(".coop-loop\\state.yaml") or str(result["resolved_state_path"]).endswith(".coop-loop/state.yaml"))
            controlled_temp_initialization(root)
            self.assertTrue((root / ".coop-loop" / "state.yaml").is_file())
            self.assertTrue((root / ".coop-loop" / "reports" / "execution.md").is_file())
            self.assertFalse((root / "reports").exists())
            self.assertEqual(top_level_names(root) - before, {".coop-loop"})

    def test_existing_agents_and_codex_conventions_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-agents-") as raw:
            agents_root = Path(raw) / "agents"
            agents_root.mkdir()
            (agents_root / ".agents").mkdir()
            result = run_storage_preflight(agents_root)
            self.assertEqual(result["classification"], "DEFAULT")
            self.assertTrue(str(result["resolved_state_path"]).endswith(".agents\\co-op-loop\\state.yaml") or str(result["resolved_state_path"]).endswith(".agents/co-op-loop/state.yaml"))

            codex_root = Path(raw) / "codex"
            codex_root.mkdir()
            (codex_root / ".codex").mkdir()
            codex_result = run_storage_preflight(codex_root)
            self.assertEqual(codex_result["classification"], "DEFAULT")
            self.assertTrue(str(codex_result["resolved_state_path"]).endswith(".codex\\co-op-loop\\state.yaml") or str(codex_result["resolved_state_path"]).endswith(".codex/co-op-loop/state.yaml"))

    def test_strict_fixture_reuses_indexed_state_and_report_pair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-strict-") as raw:
            root = Path(raw)
            make_strict_index(root, state_row="| .agents/ | local_agent_state |", report_row="| logs/reports/ | current_governance_reports |")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertTrue(result["task_creation_allowed"])
            self.assertTrue(str(result["resolved_state_path"]).endswith(".agents\\co-op-loop\\state.yaml") or str(result["resolved_state_path"]).endswith(".agents/co-op-loop/state.yaml"))
            self.assertTrue(str(result["resolved_report_root"]).endswith("logs\\reports") or str(result["resolved_report_root"]).endswith("logs/reports"))
            controlled_temp_initialization(root, strict=True)
            self.assertFalse((root / ".coop-loop").exists())
            self.assertFalse((root / "reports").exists())
            self.assertTrue((root / ".agents" / "co-op-loop" / "state.yaml").is_file())
            self.assertTrue((root / "logs" / "reports" / "execution.md").is_file())
            after = run_storage_preflight(root)
            self.assertEqual(after["classification"], "ADAPTED")

    def test_strict_rule_exact_paths_are_supported_without_index_markers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-rule-exact-") as raw:
            root = Path(raw)
            (root / "AGENTS.md").write_text(
                "Top-level additions are forbidden. The exact writable state path is `.agents/co-op-loop/state.yaml`.\n"
                "The current report root is `logs/reports/`.\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root, "simulate-first-init")
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertTrue(result["task_creation_allowed"])
            self.assertTrue(str(result["resolved_state_path"]).endswith(".agents\\co-op-loop\\state.yaml") or str(result["resolved_state_path"]).endswith(".agents/co-op-loop/state.yaml"))
            self.assertTrue(str(result["resolved_report_root"]).endswith("logs\\reports") or str(result["resolved_report_root"]).endswith("logs/reports"))

    def test_strict_missing_state_report_or_pair_is_blocked(self) -> None:
        cases = (
            ("state-only", "| .agents/ | local_agent_state |", None),
            ("report-only", None, "| logs/reports/ | current_governance_reports |"),
            ("both-missing", None, None),
        )
        for name, state_row, report_row in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="coop-blocked-") as raw:
                root = Path(raw)
                make_strict_index(root, state_row=state_row, report_row=report_row)
                result = run_storage_preflight(root)
                self.assertEqual(result["classification"], "BLOCKED")
                self.assertFalse(result["task_creation_allowed"])
                self.assertEqual(result["writes_performed"], 0)
                self.assertEqual(result["task_creations_performed"], 0)
                self.assertFalse((root / ".coop-loop").exists())
                self.assertFalse((root / "reports").exists())

    def test_runtime_state_marker_allows_only_state_subtree_reports(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-runtime-") as raw:
            root = Path(raw)
            make_strict_index(root, state_row="| .agents/ | runtime_state |")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertTrue(str(result["resolved_report_root"]).endswith("co-op-loop\\reports") or str(result["resolved_report_root"]).endswith("co-op-loop/reports"))
            self.assertFalse(str(result["resolved_report_root"]).endswith("\\reports") and str(result["resolved_report_root"]).count("\\") == 1)

    def test_two_valid_states_are_unconditional_state_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-conflict-") as raw:
            root = Path(raw)
            write_valid_state(root, ".agents/co-op-loop/state.yaml")
            write_valid_state(root, ".coop-loop/state.yaml", phase="READY", red_count=0)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "STATE_CONFLICT")
            self.assertFalse(result["task_creation_allowed"])
            self.assertIn("multiple_valid_states", result["conflicts"])

    def test_legacy_active_and_ended_are_recovered_without_migration(self) -> None:
        for phase in ("READY", "ENDED"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(prefix="coop-legacy-") as raw:
                root = Path(raw)
                legacy = write_valid_state(root, ".coop-loop/state.yaml", phase=phase, red_count=0 if phase == "READY" else 3)
                result = run_storage_preflight(root)
                self.assertEqual(result["classification"], "LEGACY")
                self.assertTrue(result["task_creation_allowed"])
                self.assertEqual(Path(result["resolved_state_path"]), legacy.resolve())
                self.assertFalse((root / ".agents").exists())
                self.assertFalse((root / ".codex").exists())

    def test_damaged_and_multiple_damaged_states_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-damaged-") as raw:
            root = Path(raw)
            damaged = root / ".coop-loop" / "state.yaml"
            damaged.parent.mkdir()
            damaged.write_text("phase: BAD\nextra: value\n", encoding="utf-8")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])
            (root / ".agents" / "co-op-loop").mkdir(parents=True)
            (root / ".agents" / "co-op-loop" / "state.yaml").write_text("phase: BAD\n", encoding="utf-8")
            multiple = run_storage_preflight(root)
            self.assertEqual(multiple["classification"], "STATE_CONFLICT")
            self.assertFalse(multiple["task_creation_allowed"])

    def test_same_level_candidates_and_forbidden_markers_do_not_get_guessed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-ambiguous-") as raw:
            root = Path(raw)
            make_strict_index(root, state_row="| .agents/ | local_agent_state |\n| .codex/ | agent_state |", report_row="| logs/reports/ | current_governance_reports |")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "AMBIGUOUS")
            self.assertFalse(result["task_creation_allowed"])

        with tempfile.TemporaryDirectory(prefix="coop-forbidden-") as raw:
            root = Path(raw)
            make_strict_index(root, state_row="| .agents/ | local_agent_state | read_only |", report_row="| logs/reports/ | current_governance_reports |")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])
            self.assertIn("prohibited_evidence_rejected", result["conflicts"])

    def test_strict_simulation_prefers_the_only_existing_candidate_parent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-existing-anchor-") as raw:
            root = Path(raw)
            make_strict_index(root, state_row="| .agents/ | local_agent_state |\n| .codex/ | agent_state |", report_row="| logs/reports/ | current_governance_reports |")
            (root / ".agents" / "co-op-loop").mkdir(parents=True)
            result = run_storage_preflight(root, "simulate-first-init")
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertTrue(str(result["resolved_state_path"]).endswith(".agents\\co-op-loop\\state.yaml") or str(result["resolved_state_path"]).endswith(".agents/co-op-loop/state.yaml"))
            self.assertTrue(result["task_creation_allowed"])

    def test_readme_and_gitignore_are_not_strict_governance_signals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-nonstrict-") as raw:
            root = Path(raw)
            (root / "README.md").write_text("top-level folders are described here\n", encoding="utf-8")
            (root / ".gitignore").write_text("reports/\n", encoding="utf-8")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "DEFAULT")
            self.assertEqual(result["strict_signals"], [])

    def test_unreadable_governance_anchor_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-unreadable-anchor-") as raw:
            root = Path(raw)
            (root / "AGENTS.md").write_bytes(bytes((0xFF, 0xFE, 0xFA)))
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])
            self.assertIn("governance_anchor_read_error", result["conflicts"])

    def test_formal_report_root_syntax_a_and_b_reuses_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-formal-root-") as raw:
            root = Path(raw)
            report_root = root / "正式报告"
            report_root.mkdir()
            (root / "AGENTS.md").write_text(
                "# Rules\n\n## Report Contract\n\nAll formal reports must be written to:\n\n```text\n正式报告\n```\n",
                encoding="utf-8",
            )
            current = run_storage_preflight(root, "current")
            simulated = run_storage_preflight(root, "simulate-first-init")
            for result in (current, simulated):
                self.assertEqual(result["classification"], "ADAPTED")
                self.assertTrue(result["task_creation_allowed"])
                self.assertEqual(Path(result["resolved_report_root"]), report_root.resolve())
                self.assertEqual(result["formal_report_status"], "OK")

        with tempfile.TemporaryDirectory(prefix="coop-formal-marker-") as raw:
            root = Path(raw)
            report_root = root / "reports"
            report_root.mkdir()
            (root / "AGENTS.md").write_text(
                "# Rules\n\n## CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: reports\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertEqual(Path(result["resolved_report_root"]), report_root.resolve())

        with tempfile.TemporaryDirectory(prefix="coop-formal-absolute-") as raw:
            root = Path(raw)
            report_root = root / "绝对报告"
            report_root.mkdir()
            absolute = str(report_root.resolve())
            (root / "PROJECT_STRUCTURE.md").write_text(
                f"# CO-OP Loop Storage\nCOOP_LOOP_REPORT_ROOT: {absolute}\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertEqual(Path(result["resolved_report_root"]), report_root.resolve())

        with tempfile.TemporaryDirectory(prefix="coop-formal-index-") as raw:
            root = Path(raw)
            report_root = root / "index-reports"
            report_root.mkdir()
            (root / "FOLDER_INDEX.md").write_text(
                "# CO-OP Loop\nCOOP_LOOP_REPORT_ROOT: index-reports\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertEqual(Path(result["resolved_report_root"]), report_root.resolve())

    def test_formal_report_root_ignores_non_evidence_contexts(self) -> None:
        cases = {
            "fenced": "# Rules\n\n## CO-OP Loop Configuration\n```text\nCOOP_LOOP_REPORT_ROOT: reports\n```\n",
            "html": "# Rules\n\n## CO-OP Loop Configuration\n<!-- COOP_LOOP_REPORT_ROOT: reports -->\n",
            "reference": "# Rules\n\n## CO-OP Loop Configuration\n[report]: # COOP_LOOP_REPORT_ROOT: reports\n",
            "quote": "# Rules\n\n## CO-OP Loop Configuration\n> COOP_LOOP_REPORT_ROOT: reports\n",
            "list": "# Rules\n\n## CO-OP Loop Configuration\n- COOP_LOOP_REPORT_ROOT: reports\n",
            "root_prose": "COOP_LOOP_REPORT_ROOT: reports\n",
            "example_section": "# Rules\n\n## CO-OP Loop Configuration\n### Examples\nCOOP_LOOP_REPORT_ROOT: reports\n",
            "missing_action": "# Rules\n\n## Report Contract\nSee the report location:\n```text\nreports\n```\n",
            "multi_line_block": "# Rules\n\n## Report Contract\nAll formal reports must be written to:\n```text\nreports\nsecond\n```\n",
        }
        for name, text in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="coop-formal-negative-") as raw:
                root = Path(raw)
                (root / "reports").mkdir()
                (root / "AGENTS.md").write_text(text, encoding="utf-8")
                result = run_storage_preflight(root)
                self.assertEqual(result["classification"], "DEFAULT")
                self.assertTrue(str(result["resolved_report_root"]).endswith(".coop-loop\\reports") or str(result["resolved_report_root"]).endswith(".coop-loop/reports"))

        with tempfile.TemporaryDirectory(prefix="coop-formal-directory-only-") as raw:
            root = Path(raw)
            (root / "reports").mkdir()
            (root / "README.md").write_text("reports is the preferred folder\n", encoding="utf-8")
            (root / ".gitignore").write_text("reports/\n", encoding="utf-8")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "DEFAULT")

    def test_formal_report_root_fail_closed_and_source_precedence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-formal-fail-") as raw:
            root = Path(raw)
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: missing-reports\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])
            self.assertIn("formal_report_path_blocked", result["conflicts"])

        with tempfile.TemporaryDirectory(prefix="coop-formal-outside-") as raw:
            parent = Path(raw)
            root = parent / "project"
            root.mkdir()
            outside = parent / "outside-reports"
            outside.mkdir()
            (root / "AGENTS.md").write_text(
                f"# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: {outside.resolve()}\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])

        with tempfile.TemporaryDirectory(prefix="coop-formal-traversal-") as raw:
            parent = Path(raw)
            root = parent / "project"
            root.mkdir()
            (parent / "outside-reports").mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: ../outside-reports\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])

        with tempfile.TemporaryDirectory(prefix="coop-formal-forbidden-") as raw:
            root = Path(raw)
            (root / "archive" / "reports").mkdir(parents=True)
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: archive/reports\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")

        with tempfile.TemporaryDirectory(prefix="coop-formal-ambiguous-") as raw:
            root = Path(raw)
            (root / "reports-a").mkdir()
            (root / "reports-b").mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\n"
                "COOP_LOOP_REPORT_ROOT: reports-a\n"
                "COOP_LOOP_REPORT_ROOT: reports-b\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "AMBIGUOUS")
            self.assertFalse(result["task_creation_allowed"])

        with tempfile.TemporaryDirectory(prefix="coop-formal-priority-") as raw:
            root = Path(raw)
            (root / "agents-reports").mkdir()
            (root / "structure-reports").mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: agents-reports\n",
                encoding="utf-8",
            )
            (root / "PROJECT_STRUCTURE.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: structure-reports\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertEqual(Path(result["resolved_report_root"]), (root / "agents-reports").resolve())
            self.assertTrue(result["ignored_lower_priority"])

    def test_formal_report_root_preserves_state_and_legacy_pairs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-formal-state-") as raw:
            root = Path(raw)
            report_root = root / "formal-reports"
            report_root.mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: formal-reports\n",
                encoding="utf-8",
            )
            state = write_valid_state(root, ".agents/co-op-loop/state.yaml", phase="READY", red_count=0)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertEqual(Path(result["resolved_state_path"]), state.resolve())
            self.assertEqual(Path(result["resolved_report_root"]), report_root.resolve())

        for phase in ("READY", "ENDED"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(prefix="coop-formal-legacy-") as raw:
                root = Path(raw)
                formal = root / "formal-reports"
                formal.mkdir()
                (root / "AGENTS.md").write_text(
                    "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: formal-reports\n",
                    encoding="utf-8",
                )
                (root / ".coop-loop" / "reports").mkdir(parents=True)
                legacy = write_valid_state(root, ".coop-loop/state.yaml", phase=phase, red_count=0 if phase == "READY" else 3)
                result = run_storage_preflight(root)
                self.assertEqual(result["classification"], "LEGACY")
                self.assertEqual(Path(result["resolved_state_path"]), legacy.resolve())
                self.assertEqual(Path(result["resolved_report_root"]), (root / ".coop-loop" / "reports").resolve())
                self.assertEqual(Path(result["migration_candidate"]), formal.resolve())

    def test_storage_pairing_no_state_with_formal_report_is_adapted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-pair-no-state-") as raw:
            root = Path(raw)
            formal = root / "reports"
            formal.mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: reports\n",
                encoding="utf-8",
            )
            before = fixture_snapshot(root)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertTrue(str(result["resolved_state_path"]).endswith(".coop-loop\\state.yaml") or str(result["resolved_state_path"]).endswith(".coop-loop/state.yaml"))
            self.assertEqual(Path(result["resolved_report_root"]), formal.resolve())
            self.assertIsNone(result["migration_candidate"])
            self.assertTrue(result["task_creation_allowed"])
            self.assertEqual(result["writes_performed"], 0)
            self.assertEqual(result["task_creations_performed"], 0)
            self.assertEqual(fixture_snapshot(root), before)

    def test_storage_pairing_ready_state_without_local_reports_stays_formal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-pair-ready-") as raw:
            root = Path(raw)
            formal = root / "reports"
            formal.mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: reports\n",
                encoding="utf-8",
            )
            state = write_valid_state(root, ".coop-loop/state.yaml", phase="READY", red_count=0)
            before = fixture_snapshot(root)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertEqual(Path(result["resolved_state_path"]), state.resolve())
            self.assertEqual(Path(result["resolved_report_root"]), formal.resolve())
            self.assertIsNone(result["migration_candidate"])
            self.assertTrue(result["task_creation_allowed"])
            self.assertEqual(result["writes_performed"], 0)
            self.assertEqual(result["task_creations_performed"], 0)
            self.assertEqual(fixture_snapshot(root), before)

    def test_storage_pairing_ended_state_without_local_reports_stays_formal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-pair-ended-") as raw:
            root = Path(raw)
            formal = root / "reports"
            formal.mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: reports\n",
                encoding="utf-8",
            )
            state = write_valid_state(root, ".coop-loop/state.yaml", phase="ENDED", red_count=3)
            before = fixture_snapshot(root)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "ADAPTED")
            self.assertEqual(Path(result["resolved_state_path"]), state.resolve())
            self.assertEqual(Path(result["resolved_report_root"]), formal.resolve())
            self.assertIsNone(result["migration_candidate"])
            self.assertTrue(result["task_creation_allowed"])
            self.assertEqual(result["writes_performed"], 0)
            self.assertEqual(result["task_creations_performed"], 0)
            self.assertEqual(fixture_snapshot(root), before)

    def test_storage_pairing_legacy_local_report_is_authoritative_and_invalid_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-pair-legacy-") as raw:
            root = Path(raw)
            formal = root / "formal-reports"
            formal.mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: formal-reports\n",
                encoding="utf-8",
            )
            write_valid_state(root, ".coop-loop/state.yaml", phase="READY", red_count=0)
            local = root / ".coop-loop" / "reports"
            local.mkdir(parents=True)
            before = fixture_snapshot(root)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "LEGACY")
            self.assertEqual(Path(result["resolved_report_root"]), local.resolve())
            self.assertEqual(Path(result["migration_candidate"]), formal.resolve())
            self.assertTrue(result["task_creation_allowed"])
            self.assertEqual(fixture_snapshot(root), before)

        with tempfile.TemporaryDirectory(prefix="coop-pair-file-") as raw:
            root = Path(raw)
            formal = root / "formal-reports"
            formal.mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: formal-reports\n",
                encoding="utf-8",
            )
            write_valid_state(root, ".coop-loop/state.yaml", phase="READY", red_count=0)
            (root / ".coop-loop" / "reports").write_text("not a directory\n", encoding="utf-8")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])

        with tempfile.TemporaryDirectory(prefix="coop-pair-reparse-") as raw:
            parent = Path(raw)
            root = parent / "project"
            root.mkdir()
            outside = parent / "outside-reports"
            outside.mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: formal-reports\n",
                encoding="utf-8",
            )
            (root / "formal-reports").mkdir()
            write_valid_state(root, ".coop-loop/state.yaml", phase="READY", red_count=0)
            local = root / ".coop-loop" / "reports"
            try:
                local.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory reparse fixture unavailable in this Windows environment")
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])

    def test_storage_pairing_legacy_without_formal_root_falls_back_local(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-pair-fallback-") as raw:
            root = Path(raw)
            state = write_valid_state(root, ".coop-loop/state.yaml", phase="ENDED", red_count=3)
            before = fixture_snapshot(root)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "LEGACY")
            self.assertEqual(Path(result["resolved_state_path"]), state.resolve())
            self.assertEqual(Path(result["resolved_report_root"]), (root / ".coop-loop" / "reports").resolve())
            self.assertIsNone(result["migration_candidate"])
            self.assertTrue(result["task_creation_allowed"])
            self.assertEqual(result["writes_performed"], 0)
            self.assertEqual(result["task_creations_performed"], 0)
            self.assertEqual(fixture_snapshot(root), before)

    def test_storage_pairing_two_valid_states_remains_unconditional_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-pair-conflict-") as raw:
            root = Path(raw)
            formal = root / "reports"
            formal.mkdir()
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: reports\n",
                encoding="utf-8",
            )
            write_valid_state(root, ".agents/co-op-loop/state.yaml", phase="READY", red_count=0)
            write_valid_state(root, ".coop-loop/state.yaml", phase="ENDED", red_count=3)
            before = fixture_snapshot(root)
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "STATE_CONFLICT")
            self.assertFalse(result["task_creation_allowed"])
            self.assertIsNone(result["resolved_report_root"])
            self.assertEqual(result["writes_performed"], 0)
            self.assertEqual(result["task_creations_performed"], 0)
            self.assertEqual(fixture_snapshot(root), before)

    def test_formal_report_root_rejects_symlink_escape_when_supported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-formal-symlink-") as raw:
            parent = Path(raw)
            root = parent / "project"
            root.mkdir()
            outside = parent / "outside"
            outside.mkdir()
            link = root / "linked-reports"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink unavailable in this Windows test environment")
            (root / "AGENTS.md").write_text(
                "# CO-OP Loop Configuration\nCOOP_LOOP_REPORT_ROOT: linked-reports\n",
                encoding="utf-8",
            )
            result = run_storage_preflight(root)
            self.assertEqual(result["classification"], "BLOCKED")
            self.assertFalse(result["task_creation_allowed"])

    def test_current_and_simulated_modes_are_read_only_and_keep_seven_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coop-readonly-") as raw:
            root = Path(raw) / "中文路径"
            root.mkdir()
            before = top_level_names(root)
            current = run_storage_preflight(root, "current")
            simulated = run_storage_preflight(root, "simulate-first-init")
            self.assertEqual(current["writes_performed"], 0)
            self.assertEqual(simulated["writes_performed"], 0)
            self.assertEqual(current["task_creations_performed"], 0)
            self.assertEqual(simulated["task_creations_performed"], 0)
            self.assertEqual(top_level_names(root), before)
            controlled_temp_initialization(root)
            values = {}
            for line in (root / ".coop-loop" / "state.yaml").read_text(encoding="utf-8").splitlines():
                key, value = line.split(":", 1)
                values[key] = value.strip()
            self.assertTrue(state_is_exact({**values, "red_count": int(values["red_count"])}))
            self.assertEqual(set(values), STATE_FIELDS)

    def test_git_fixture_keeps_loop_state_local_only(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git executable unavailable; local-only check is SKIP, not PASS")
        with tempfile.TemporaryDirectory(prefix="coop-git-") as raw:
            root = Path(raw)
            controlled_temp_initialization(root)
            subprocess.run(["git", "init", "--quiet"], cwd=root, check=True, capture_output=True)
            status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8")
            self.assertNotIn("state.yaml", status.stdout)
            self.assertNotIn("execution.md", status.stdout)

    def test_protocol_and_reference_keep_storage_gate_explicit(self) -> None:
        protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
        reference = STORAGE_REFERENCE_PATH.read_text(encoding="utf-8")
        self.assertIn("## Storage preflight", protocol)
        self.assertIn("storage-adaptation.md", protocol)
        self.assertNotIn("The only runtime state path is:", protocol)
        self.assertNotIn("under `reports/`", protocol)
        self.assertIn("writes_performed: 0", reference)
        self.assertIn("task_creations_performed: 0", reference)
        self.assertIn("STATE_CONFLICT", reference)
        self.assertIn("directory is never a fallback", reference)

    def test_luna_max_and_model_failure_remain_best_effort(self) -> None:
        adaptation = (PROTOCOL_PATH.parent / "host-adaptation.md").read_text(encoding="utf-8")
        self.assertIn("Luna Max", adaptation)
        self.assertIn("Model failure never", adaptation)
        self.assertIn("one-time business: `Luna Max`", adaptation)
        self.assertIn('已选择“<模型名称> <推理等级>”创建<任务标题>。', adaptation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
