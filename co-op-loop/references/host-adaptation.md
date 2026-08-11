# Host adaptation

## Capability interface

The core protocol is host-neutral. The Codex adapter may probe:

```text
create_role_session
list_sessions
send_message
wait_or_track
navigate_session
structured_choice_ui
select_model_and_reasoning
storage_preflight
```

Record each capability as verified, manual, or unavailable. Do not claim a
capability because a tool name exists; cold-start evidence must show the actual
branch or bounded user step.

## Codex-first local adapter

Codex is the first adapter target. For first initialization, verify project
association, run the read-only storage preflight, assert
`task_creation_allowed`, then verify local-task creation, exact role IDs, task
titles, long-text handoff, choice fallback, and state readback. New role tasks
must use the saved local project with `environment.type: local`; never create
cloud or worktree tasks for this protocol. A `BLOCKED`, `STATE_CONFLICT`, or
unresolved `AMBIGUOUS` preflight is an immediate zero-creation stop; do not
call `create_role_session`, send a role declaration, or create a
project-internal path. The adapter fallback uses the same finite candidates,
evidence markers, priority, and fixed JSON semantics as
`scripts/storage_preflight.py`.

For a current local task, upgrading the current task to consultant is allowed
when the host supports it. A cloud or worktree current task cannot be upgraded;
offer a new local consultant or stop/evaluate the environment. The fixed titles
are `顾问｜项目名` and `中控｜项目名`.

For a control task, request unrestricted local read access when the host exposes
that capability. Local reads need no per-path sandbox approval. If only a
full-access profile exists, use it, while the role contract keeps writes and
side effects unauthorized outside the exact consultant-issued, user-confirmed
plan. If access selection is not programmable, continue initialization and ask
for one manual host-setting change; do not request paths one by one.

Existing-role checks must inspect exact IDs in active and archive areas. For
initialization reuse, list only active tasks in the current local project,
exclude the consultant, cloud/worktree tasks, and other projects, and use
“中控”/“中控台” only as discovery hints. Always display title plus exact task
ID and obtain exact authorized human confirmation; a unique candidate is not auto-bound. After
binding, send the applicable short role contract, read back delivery and role
verification, and only then write/read back the seven-field state. If
cross-task creation, delivery, waiting, or navigation requires the user's
action, preserve the full text package and report `MANUAL_BRIDGE`.

The consultant is the default business entry. The Codex adapter may route a
business-plan request directly to a verified control task once plan, RED,
high-risk, and stop gates are satisfied; it must not execute the business plan
itself. This is a process-level constraint, not technical permission isolation.

When the consultant evaluation confirms all current goals are complete, infer a
concrete real-evidence action and render the compact closeout with the runtime-
known user address. Choice `1` targets the current exact control ID. Choice `2`
creates one local one-time business task in the saved project titled
`业务 | 运行任务名称`, using the actual action name rather than the default
project name; the consultant is never the execution target. The business task
ID is not written to either consultant/control field in the seven-field state.
After choice `1` or `2`, retain plan confirmation, RED, high-risk, and stop
gates before dispatch. Choice `3` or no reply ends the Loop with no background
tracking. If local task creation or routing needs a user step, report
`MANUAL_BRIDGE`.

## Host grading

- `FULL`: real local evidence verifies role creation/discovery, exact IDs,
  bidirectional messages, wait, navigation/resume, recovery, and the required
  choice behavior.
- `MANUAL_BRIDGE`: the protocol is safe but one or more bounded user actions are
  needed. Show exact text and preserve phase and IDs.
- `UNSUPPORTED`: safe exact-target communication cannot be established. Stop or
  hand off without simulating two roles.

Do not mark Codex `FULL` from static source inspection or a single discovery
snapshot. Other hosts remain unverified until a supported-environment test.

## Models

Use these best-effort defaults for newly created tasks:

- consultant: `Sol High` or higher;
- control: `Luna Max` (`最高` in Chinese UI);
- one-time business: `Luna Max` (`最高` in Chinese UI).

Request the applicable default during creation. After creation, check the
selected values and report:

```text
已选择“<模型名称> <推理等级>”创建<任务标题>。
```

If the consultant model cannot be switched automatically, show:

```text
顾问任务推荐使用 Sol High 或更高模式，当前暂时无法自动为您切换，请你人工切换模型类型。
```

If the control model cannot be selected, tell the user that `Luna Max` (shown
as `最高` in Chinese UI) is recommended and must be checked manually. The core
protocol must not use model names as fields, identities, or initialization
gates. Model failure never blocks initialization.

## Text fallback and safety

When structured choice is unavailable, render the exact same question, options,
and strict reply values as text. A text fallback is not evidence of full UI
support.

For a strict storage stop, render the fixed `BLOCKED` state/report menu from
`references/storage-adaptation.md` and accept only a whole reply exactly equal
to `1` or `2`. An unresolved candidate menu must show every exact path and its
evidence source; until the authorized human approver chooses, creation remains disabled. Choice `1` may
write a compatibility report only under an already authorized report root;
otherwise keep the diagnostic in the conversation. Choice `2` stops with zero
writes and zero tasks.

The adapter does not authorize GitHub, Issue, Release, credentials, production
automation, external publication, cloud/worktree creation, or destructive file
actions. The known limitation about user instructions entered directly in a
control task remains explicit and unresolved.
