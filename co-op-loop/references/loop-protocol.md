# CO-OP Loop v0.2 protocol

Load the branch needed for the current task. This reference is the current
contract; historical reports do not add fields or gates.

## Contents

1. [Activation](#activation)
2. [State contract](#state-contract)
3. [Storage preflight](#storage-preflight)
4. [First initialization](#first-initialization)
5. [Existing Loop and recovery](#existing-loop-and-recovery)
6. [Wrong-task transfer](#wrong-task-transfer)
7. [Plan and RED](#plan-and-red)
8. [Execution and closeout](#execution-and-closeout)
9. [Known limitation](#known-limitation)

## Activation

Normalize the full user input with `trim` and case-folding. Trigger only on an
exact whole-input match from this set:

```text
loop
/loop
$loop
$co-op-loop
```

Thus ` LOOP `, `/LOOP`, `$LOOP`, and `$CO-OP-LOOP` match; `please loop`,
`loop now`, and a sentence containing `$loop` do not. The native Skill call
`$co-op-loop` must enter the same startup state machine as the product entry;
it cannot skip first initialization.

Every activation writes no plan or RED process file. A plan and each RED
handoff remain long text in the task context.

## State contract

The runtime state path is resolved by the read-only storage adapter, not stored
in the state file. Before first initialization, no state file may exist. Do
not create an uninitialized placeholder. After successful initialization, the
resolved path must contain exactly these seven keys and no others:

```yaml
project_root: <project-root>
initialized_at: 2026-08-09T12:00:00+08:00
consultant_thread_id: 019...
control_thread_id: 019...
phase: READY
red_count: 0
updated_at: 2026-08-09T12:00:00+08:00
```

The only accepted `phase` values are:

```text
INITIALIZING
READY
RED
EXECUTION
REVIEW
WAITING_USER
ENDED
```

`red_count` is an integer from 0 through 3. Preserve exact task IDs as opaque
strings. After every state write, independently read the file back and compare
all seven fields. When restoring an archive, rebuilding a role, or rebuilding
the state file, use the current exact IDs, current timestamps, `phase: READY`,
and `red_count: 0`.

If the file is malformed, has missing/extra keys, an invalid phase, an invalid
count, or an ID contradiction, show:

```text
Error：检测到当前 CO-OP Loop 状态文件异常，你可以：
1. 授权我检查并尝试修复文件
2. 重新新建状态文件
3. 停止执行 Skill
```

Repair only from unique evidence and read back immediately. Rebuilding requires
role rediscovery, reuse of available roles, and creation of missing roles. Do
not guess an ID or silently erase a contradictory state.

## Storage preflight

Before any consultant/control task creation or upgrade, role-declaration
message, project-internal directory/file, report, or state write, run the
read-only storage preflight in
[storage-adaptation.md](storage-adaptation.md). It must use the exact local
project association supplied by the host, never the current working directory
or a guessed Git root. The finite state candidates are the rule-resolved path,
`.agents/co-op-loop/state.yaml`, `.codex/co-op-loop/state.yaml`, and
`.coop-loop/state.yaml`; the state content remains the seven-field contract.

The preflight separately resolves a state path and a current report root,
returns a fixed JSON result with `task_creation_allowed`, and always reports
`writes_performed: 0` and `task_creations_performed: 0`. `DEFAULT`, a complete
unambiguous `ADAPTED`, or a complete unique `LEGACY` may continue. `BLOCKED`,
`STATE_CONFLICT`, and unresolved `AMBIGUOUS` are hard stops: do not call
`create_role_session`, send a role-upgrade declaration, create a task, create a
directory, or write a report. The control task asserts
`task_creation_allowed == true` again immediately before any creation/binding
call. A strict project never falls back to a new root `reports/` directory. For
an ordinary project, a current formal report root is reused only from the
bounded exact-root rule sources and finite machine contract in
`storage-adaptation.md`; a directory name or ordinary prose is not evidence.
An authoritative missing, outside, or ambiguous formal root is a hard stop,
not a silent fallback. The storage reference's fixed table distinguishes an
existing legacy report pair from a missing one: an existing, safe
`.coop-loop/reports` pair remains authoritative and a formal root is only a
migration candidate; when that local report directory is absent, one unique
formal root may become the current report side without changing the seven-field
state path. Migration is never automatic.

Two valid state files always produce `STATE_CONFLICT`; an existing legacy or
`ENDED` value does not override that priority. A single damaged state enters
the existing repair menu, while multiple damaged or contradictory candidates
stop without creation. The exact fixed `BLOCKED` menus and the evidence table are kept in
[storage-adaptation.md](storage-adaptation.md).

## First initialization

Execute the storage preflight and its zero-creation gate first, then execute
these gates in order. If structured UI is unavailable, render the same text and
values in chat.

### 1. Project scope

If the current task has no project association, show only:

```text
未检测到当前任务归属于任何项目。CO-OP Loop 只能在项目内运行。
1. 停止执行 Skill
```

Do not create a project or state file from this branch.

### 2. Local-task capability

If the current runtime cannot create a local task, show:

```text
当前运行前端无法创建本地任务，你可以：
1. 停止运行 Skill
2. 停止运行 Skill并让我评估原因
```

Choice 2 performs read-only diagnosis only. It does not install, configure, or
enable anything automatically.

### 3. Consultant selection

For a local saved project, show:

```text
1. 在当前任务升级为顾问（保留上下文）
2. 在新建本地任务中创建顾问（适合新项目，并转移当前上下文）
3. 取消执行 Skill
```

If the current task is cloud or worktree, do not offer upgrade; offer a new
local consultant, stop and evaluate the environment, or stop. A new consultant
uses the fixed title `顾问｜项目名`, receives the integrated current context,
and uses the adapter's best-effort consultant model recommendation. Model
failure does not block initialization.

### 4. Control source

After consultant creation or upgrade, show:

```text
顾问任务已经就绪。接下来请选择中控台任务的来源：
1. 新建一个本地中控台任务
2. 查找并复用本项目已有的“中控”任务，升级为本 Loop 的中控台
3. 取消本次初始化
```

Choice 1 creates one new local task in the saved project with fixed title
`中控｜项目名`. Choice 3 enters the cancellation confirmation below.

Choice 2 searches only active tasks in the current saved local project. Exclude
the consultant task, cloud/worktree tasks, and tasks from other projects.
“中控” and “中控台” in a title are discovery hints only. A candidate is not a
binding until the authorized human approver sees its title and exact task ID and confirms it. For one
candidate show its title and exact ID for confirmation; for multiple candidates
show all eligible titles and exact IDs for selection. If none is eligible,
show:

```text
未找到可复用的本地中控任务，你可以：
1. 新建一个本地中控台任务
2. 取消本次初始化
```

After exact ID confirmation, send a role-upgrade declaration to the target. The
declaration preserves its old context as historical material only; it does not
make an old plan or execution authorization current. Only after the exact ID is
known, the declaration is delivered, and the target role is read back as
verified, write the seven-field state and read it back immediately.

### 5. Initialization complete

Only after both exact current task IDs are known, write the seven-field state,
read it back, and show:

```text
初始化已完成，请你确认：
1. 检索当前任务上下文定位待执行计划
2. 计划还没做，回到当前对话框
```

Choice 1 enters the consultant's plan-retrieval branch. Choice 2 ends this
activation without RED. It does not silently execute or create another state.

## Consultant business routing

The consultant remains the user's default entry for business requests. It may
read context, formulate or revise plans, perform RED exchange, maintain state,
communicate with and track the control, read back results, independently verify,
and write the consultant evaluation. It must not perform the governed business
plan itself.

For a business-plan request, route as follows:

1. If no control is bound, enter the control-source flow above.
2. If no plan is formed or confirmed, organize the plan and use the normal plan
   confirmation prompt.
3. If RED is not complete, continue the normal RED flow.
4. If a high-risk gate or stop condition is unmet, pause there.
5. If all gates are already satisfied, automatically send the complete execution
   package to the exact control task without asking whether to transfer.

Default routing never bypasses plan confirmation, RED, high-risk authorization,
or stop conditions. Real business modification, production execution,
publication, and external writes remain control-task actions only. If the host
cannot technically prevent a consultant from calling tools after leaving the
Skill flow, describe this as a workflow constraint, not OS-level isolation or
another host's FULL compatibility.

## Existing Loop and recovery

When the seven-field state exists, rerun the read-only storage preflight, read
the uniquely resolved state, and perform only minimum checks:

1. Verify the project root and exact active/archived/deleted status of both IDs.
2. If both are active, set the current phase as appropriate and display the
   latest complete plan; do not repeat first initialization.
3. If a role is archived, offer one combined choice:

```text
检测到顾问台或中控台任务已归档，你可以：
1. 忽略归档并新建
2. 从归档恢复
3. 停止执行 Skill
```

4. If one role is archived and the other deleted, use one combined choice that
   explains the recoverable role and forced rebuild of the deleted role.
5. If an exact ID is absent from active and archive areas, force rebuilding that
   role. After any restore/rebuild, reinitialize the current run and reset the
   state to current IDs, `READY`, and `red_count: 0`.

When activation is cancelled before completion, ask:

```text
你已经选择了取消执行 Skill，请确认：
1. 保留所有 Skill 执行产物及任务
2. 删除所有 Skill 执行产物，但不删除任务
3. 删除所有 Skill 执行产物及任务（上下文有可能丢失）
```

If the host lacks hard-delete capability, state that choice 3 can only be
degraded to archive or manual deletion. Never call archive deletion.

## Wrong-task transfer

If the entry is received in a non-consultant task while an active consultant
exists, show:

```text
检测到你当前已存在顾问任务，你可以：
1. 携带当前上下文与最新计划并切换到顾问任务
2. 不携带上下文，直接切换到顾问任务
3. 取消本次 Loop，留在当前任务
```

The transfer is one long text message, not a file. Option 1 must include the
source task ID/title, project root, integrated current context, the latest
complete plan and all explicit post-plan modifications, and explicit file paths.
Option 2 includes only the exact target and the no-context warning. Create or
write state and send the message before switching; switching is the final step.
After arrival, do not inherit an active phase: require a new standalone `loop`.

## Plan and RED

After initialization or an existing aligned check, `loop` retrieves and displays
the latest complete plan, followed by:

```text
检测到目前最新版本计划，是否确认发送到中控台任务进行第一轮 RED？
1. 执行
2. 再等等
```

It is not approval by itself. Only the next single reply, after this display,
that is exactly `1` or `执行` authorizes sending the RED package. Exact `2` or
`再等等` means do not send; a later standalone `loop` must retrieve and display
the latest plan again. A sentence, `确认`, or a second `loop` does not authorize
RED.

The RED package is one long text containing governance background, the complete
plan, and any added instructions for the control task. During RED, the control
task audits only; it does not execute, generate process files, or create
business outputs. The consultant waits silently except for required redelivery.

Every plan that can be selected or executed must contain one `BEGIN_PLAN_TEXT`
and one `END_PLAN_TEXT` marker pair. To calculate
`normalized_text_sha256`, use only the Unicode text between those markers:
preserve all characters, case, spaces, punctuation, and internal blank lines;
convert CRLF and lone CR to LF; remove only trailing LF characters; encode as
UTF-8 without BOM; then calculate SHA-256 and emit 64 uppercase hexadecimal
characters. Do not include the markers, governance wrapper, RED result, or
transport packaging. Recalculate before execution and pause as
`PLAN_VERSION_MISMATCH` if the expected hash differs.

The formal result is:

```text
COOP_RED_RESULT
loop_id: <id>
round: 1 | 2 | 3
reviewed_plan: <complete plan text>
verdict: RED_ALL_PASS | CHANGES_REQUIRED
blocking_items: <list>
authority_change: YES | NO
unresolved_disagreement: <list>
```

`CHANGES_REQUIRED` is valid only when `blocking_items` contains at least one
issue that would fail the goal, violate a rule/permission, create a concrete
security risk, or cannot be verified. Preferences, future extensions, and
general governance suggestions are not blockers. Questions and challenges do
not increment `red_count`; only a complete fixed-plan resubmission increments
it.

After the initial exact plan confirmation, `RED_ALL_PASS` on RED1, RED2, or
RED3 automatically dispatches the exact passed plan when the control minimum
preflight, high-risk gates, stop conditions, and version hash check are clear.
Do not ask for a second execution confirmation. If initial confirmation is
absent, the version hash differs, or any gate is unmet, remain paused and do
not send an execution package.

Classify each `CHANGES_REQUIRED` item independently:

- `ACCEPT` requires a direct goal, rule/permission, concrete security, or
  verification failure, clear evidence, and a minimal repair within authority.
- `CHALLENGE` is limited to one challenge and at most one evidence supplement
  for one fingerprint; it must then resolve to `ACCEPT` or `REJECT` and never
  creates nested RED.
- `REJECT` excludes preferences, future work, unrelated governance,
  unsupported risk, permission expansion, goal changes, and complexity-only
  safety claims.

Only accepted items enter the next fixed plan. A complete fixed-plan
resubmission increments `red_count`; questions, challenges, and rejected items
do not. Keep the item, disposition, evidence, and action in task context only;
do not add state fields or process files for them.

If the third complete fixed plan is still `CHANGES_REQUIRED`, keep
`red_count: 3`, retain the exact RED3 plan hash, and create a RED4 candidate
after the item-level dispositions are resolved. RED4 is not `COOP_RED_RESULT`,
has no round 4, and does not increment `red_count`. Send an independent:

```text
COOP_FINAL_RISK_AUDIT
based_on_red_count: 3
red3_version_sha256: <sha256>
reviewed_version: RED4_CANDIDATE
red4_candidate_sha256: <sha256>
verdict: RISK_ACCEPTABLE | RISK_REMAINS
red3_unresolved_items: <list>
red4_changes: <list>
red4_remaining_risks: <list>
authority_change_requested: YES | NO
recommended_route: RED3 | RED4
unresolved_disagreement: <list>
```

`FINAL_RISK_AUDIT` is risk evidence only and never executes automatically.
Exclude every authority-expansion request from `RED4_FINAL`. Then show:

```text
中控任务已连续完成三轮自动 RED，计划仍未通过；第四版风险审计也已完成。

请确认：
1. 无视第四次 RED 审计，按照 RED3 版本让中控任务直接执行
2. 按照第四次 RED 审计结论，完成必要修正后让中控任务直接执行
3. 停止执行并退出 Skill
```

Only exact `1`, `2`, or `3` is accepted. Exact `1` rechecks the RED3 hash
and records authorized human approver acceptance of unresolved risk before execution. Exact `2`
forms `RED4_FINAL`, rechecks source hashes, excludes authority expansion, and
executes without another RED. Exact `3` sets `phase: ENDED`; any other reply
waits. Neither route may change the initial goal, permission boundary, or
acceptance standard.

## Execution and closeout

The execution instruction is one long text with a prefix that states the plan
passed RED or reached 3/3 final adjudication, the authorized human approver authorization state,
original goal and permission boundary, minimum preflight, exact scope, stop
conditions, validation/readback requirements, and the requirement to write a
Markdown execution report under the resolved report root, followed by the
complete plan. If the plan separately requires an implementation report, write
that second report in the same resolved report root; never create a new
project-root `reports/` directory as a fallback.

Before any real action, the control task must run a minimum preflight. If the
plan would require deletion, moving, publication, an external call, an
irreversible modification, a permission expansion, or has an uncertain side
effect, stop first and return `EXECUTION_PAUSED`; do not wait for a cross-task
message to provide a real-time brake.

For ordinary errors, keep the evidence in the control task context. If the same
failure fingerprint is attempted with the same method twice, return
`REPEATED_FAILURE`, preserve attempted methods, current现场, and error evidence,
pause, and do not perform a third blind retry. A consultant may send one
minimum correction per fingerprint only when the issue is a clear goal/scope/
output/completion deviation, a permission risk, repeated failure, or missing
completion evidence. A second occurrence after that correction pauses and
requires a report. Credentials, publication, deletion/move, authority
expansion, or uncertain side effects are paused directly without remote
correction. Normal progress and one-off safe self-repair are tracked silently.

The control task returns exactly one of these execution statuses:

```text
EXECUTION_COMPLETE
EXECUTION_PAUSED
EXECUTION_FAILED
```

`EXECUTION_COMPLETE` is only a signal for consultant verification; it is not
the final Loop conclusion. The control task writes one mandatory Loop execution
report. If the plan separately requires a business execution report, write that
second report too; this is a deliberate double-check. The consultant reads the
reports back and independently checks key files, tests, and results, then writes
one complete single-round evaluation containing completed items, errors, major
failures, unfinished items, attribution, repair status, risks, and next step.
After that report, write the seven-field state with `phase: ENDED`; tracking
ends.

If the evaluation reports unfinished items, show the next-step text without a
popup:

```text
下一步建议：本轮仍有 N 项未完成，基于本轮报告，你可以：
1. 根据本轮报告生成第二轮计划（默认下一步）
2. 我先补充修改方向
3. 结束 Loop，保持待命
（请以选项数字如：“1”，直接回复即可）
```

If the evaluation confirms that all goals are complete, do not show the
unfinished-item menu. Infer one smallest project-appropriate action that can
produce real evidence, and replace `<action_name>` below with that concrete
action name (for example, `基于当前操作系统的真实兼容性测试`). Replace
`<runtime_user_name>` with the user address known by the runtime; do not
hard-code a universal name:

```text
<runtime_user_name>，本轮既定目标已经全部完成。建议下一轮进行一次<action_name>。

如果继续，顾问将基于本轮报告生成最小<action_name>计划；经你确认后发送到指定任务执行。顾问负责静默跟踪、回读执行报告并形成下一轮评估。你现在可以：

1. 继续，指派中控任务执行<action_name>计划
2. 继续，新建业务任务执行<action_name>计划
3. 不做<action_name>，结束 Loop

（无回复默认选择 3。）
```

The recommendation is not execution. For exact reply `1`, use the current
exactly bound control task as the next execution target. For exact reply `2`,
create one local one-time business task in the current saved project with the
fixed title `业务 | 运行任务名称`, where `运行任务名称` is the actual action
name, not the default project name. The business task is only an execution
target; it is not the consultant or control role and its ID must not be written
to `consultant_thread_id` or `control_thread_id` in the seven-field state.
After either choice, the consultant generates the minimum next plan, obtains
the normal plan confirmation, completes required RED, high-risk permission,
and stop-condition gates, then sends the package to the selected target,
silently tracks, reads back the report, and evaluates. Neither choice bypasses
those gates. Exact `3` and no reply end the Loop with no background tracking.

Recommend only; do not create or execute the next action without the user's
matching choice and the subsequent gates.

For the unfinished-item menu only, an entire reply exactly equal to `1`, `2`,
or `3` matches. In that unfinished-item branch, exact `1` re-reads the control
report and consultant evaluation, generates and displays a second complete
plan, and asks again whether to send RED; it does not send automatically.
Exact `2` stays in the current conversation waiting for normal text direction
and does not require another `loop`. Exact `3` ends and waits. No reply
defaults to `3` with no background tracking. Other replies are ordinary
conversation. After `ENDED`, a fresh standalone `loop` is required.

## Known limitation

The loop cannot reliably intercept a user who enters the control task and gives
it a same-level manual instruction while the loop is running. Keep this as a
known limitation; do not add a project-level `AGENTS.md` hard ban or claim the
problem is solved.
