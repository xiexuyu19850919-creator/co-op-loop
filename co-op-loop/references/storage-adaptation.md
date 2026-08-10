# Storage adaptation

This reference is the storage contract for the CO-OP Loop. The project root is
the exact local project association supplied by the host. The current working
directory and a guessed Git root are never substitutes.

## Read-only preflight

Before any role creation, role-upgrade message, state write, report write, or
project-internal directory creation, the Codex adapter runs:

```text
python scripts/storage_preflight.py --project-root <exact-project-root> --mode current
```

The diagnostic mode is also available for a hypothetical first initialization:

```text
python scripts/storage_preflight.py --project-root <exact-project-root> --mode simulate-first-init
```

Both modes are read-only and return fixed JSON, including `classification`,
`state_candidates`, `valid_states`, `damaged_states`, `report_candidates`,
`resolved_state_path`, `resolved_report_root`, `conflicts`,
`task_creation_allowed`, `writes_performed: 0`, and
`task_creations_performed: 0`. There is no apply, write, locator, or state-file
path field.

The script reads only the project-root governance anchors, explicitly relevant
current indexes, a bounded set of governance/preflight scripts, and these four
state candidates:

```text
<rule-resolved exact state path>
<project-root>/.agents/co-op-loop/state.yaml
<project-root>/.codex/co-op-loop/state.yaml
<project-root>/.coop-loop/state.yaml
```

It uses UTF-8, supports Windows and POSIX path spelling, does not recurse over
the project, and never executes an unfamiliar governance script. Host fallback
must use this same evidence table and priority order.

## Evidence and path resolution

Strict governance is recognized only from an applicable rule that forbids
unregistered top-level additions or requires an exact path, an index that
actually covers top-level entries, a static allowlist/index-coverage check, or
an explicitly declared governance preflight. README, `.gitignore`, a tests
directory, or the existence of an arbitrary script is not enough.

For a strict project, a writable state path is authorized only by an exact rule
path or an exact index row marked `local_agent_state`, `agent_state`,
`runtime_state`, or `tool_state`. The same row is rejected when it contains
`read_only`, `archive`, `historical`, `forbidden`, or `deprecated`. A writable
state directory alone is not authorization.

For a strict project, a current report root is authorized only by an exact rule
path or an exact index row marked `current_governance_reports`,
`current_reports`, or `runtime_reports`, without archive/history/deprecation or
read-only markers. If the state evidence explicitly permits a writable runtime
subtree, its `reports/` child may be used only when no separate formal report
path is required. A missing side of the pair is `BLOCKED`; the root `reports/`
directory is never a fallback.

For a non-strict project, the deterministic state order is existing `.agents/`,
then existing `.codex/`, then `.coop-loop/`. Before falling back to the Loop-owned
`reports/` child, the adapter may reuse one current formal report root only when
all of these machine-checkable conditions hold:

1. the evidence is in the exact project-root `AGENTS.md`,
   `PROJECT_STRUCTURE.md`, or `FOLDER_INDEX.md`;
2. the source uses either a standalone `COOP_LOOP_REPORT_ROOT: <path>` line in
   a dedicated CO-OP Loop configuration section, or the bounded AGENTS report
   rule form: an approved report heading, an approved action word, and a
   path-only fenced block containing exactly one path;
3. the source precedence is `AGENTS.md` then `PROJECT_STRUCTURE.md` then
   `FOLDER_INDEX.md`, and the winning source resolves one unique path;
4. the path resolves inside the exact project root, is not the root itself,
   already exists as a directory, and has no archive, historical, deprecated,
   former, read-only, forbidden, or equivalent path semantics.

README, `.gitignore`, reports, examples, comments, ordinary prose, directory
existence, and unrelated Markdown never authorize a formal root. A missing or
out-of-project path required by an authoritative rule is `BLOCKED`; two
same-level paths are `AMBIGUOUS`; neither result falls back to another report
directory. With no formal evidence, the report root is the resolved state
directory's `reports/` child. Thus an ordinary Git project still has one Loop
namespace and the project-root `.gitignore` is not modified; a local-only
`.gitignore` may be created inside the Loop-owned directory when initialization
is authorized.

The state/report pair uses this fixed recovery table without adding a state
field, locator, lock, or migration marker:

| Current evidence | Classification | Resolved pair | Migration candidate |
| --- | --- | --- | --- |
| No valid state and one formal report root | `ADAPTED` | default state path plus the formal report root | none |
| One valid `.coop-loop/state.yaml` and an existing, in-project, non-reparse `.coop-loop/reports/` | `LEGACY` | the original `.coop-loop/state.yaml` plus `.coop-loop/reports/` | the unique formal root, if present |
| One valid `.coop-loop/state.yaml`, no local report directory, and one formal report root | `ADAPTED` | `.coop-loop/state.yaml` plus the formal report root | none |
| One valid `.coop-loop/state.yaml`, no local report directory, and no formal root | `LEGACY` | `.coop-loop/state.yaml` plus `.coop-loop/reports/` | none |
| Existing local report path is a file, outside the project, or reparse/uncanonicalizable | `BLOCKED` | no pair; do not fall back | none |
| Two valid seven-field states | `STATE_CONFLICT` | no pair; do not guess | none |

`READY`, `ENDED`, and every other legal phase use the same table. An existing
legacy pair is authoritative and is never changed by newly discovered formal
root evidence; formal-root ambiguity is not used to guess a migration target.
If the local legacy report directory is absent, a unique formal root may be
used as the current report side. A missing, outside, or ambiguous authoritative
formal root remains `BLOCKED` or `AMBIGUOUS` and never silently falls back.
Migration is a separate authorization and is never performed by storage
preflight.

Two same-priority authorized state or report paths are `AMBIGUOUS` and require
an exact user choice. A rule exact path outranks an index marker. During a
first-init simulation, an indexed state candidate whose `co-op-loop/` parent
does not exist is not a current writable anchor; if exactly one candidate
parent exists, that candidate is selected, while two existing parents (or no
existing parent) remain `AMBIGUOUS`. This bounded rule lets a governed project
reuse its current state subtree without creating another top-level namespace.
Two valid seven-field states are always `STATE_CONFLICT`, including when one is
legacy or ended. A single valid `.coop-loop/state.yaml` is `LEGACY`: continue
from that path and suggest migration separately, never migrate automatically. A
single damaged state enters the existing repair menu; multiple damaged or
contradictory states stop with no creation.

Only `DEFAULT`, a complete unambiguous `ADAPTED`, or a complete unique `LEGACY`
may set `task_creation_allowed: true`. `BLOCKED`, `STATE_CONFLICT`, and an
unresolved `AMBIGUOUS` result are hard pre-creation stops. The control task
must assert that boolean immediately before any consultant/control creation or
binding call.

## BLOCKED menus

When strict governance has no safe storage pair, initialization has created
nothing. Use the applicable fixed message:

```text
检测到当前项目限制新增顶层目录，但未找到已授权的 Loop 状态位置。初始化尚未创建任何文件或任务。
1. 停止初始化，并查看本轮兼容性检测与建议报告
2. 直接停止初始化
```

```text
检测到当前项目限制新增顶层目录。Loop 状态位置可用，但未找到已授权的报告位置。初始化尚未创建任何文件或任务。
1. 停止初始化，并查看本轮兼容性检测与建议报告
2. 直接停止初始化
```

```text
检测到当前项目限制新增顶层目录，但未找到完整可用的 Loop 状态与报告位置。初始化尚未创建任何文件或任务。
1. 停止初始化，并查看本轮兼容性检测与建议报告
2. 直接停止初始化
```

Only an entire reply exactly equal to `1` or `2` is accepted. Choice `1` may
write a compatibility report only after a separately authorized report root is
resolved; without one, show the diagnostic in chat only. Choice `2` stops. Any
other input waits without writing or creating a task. An unresolved
`AMBIGUOUS` result shows every exact candidate and evidence source and has
`task_creation_allowed: false` until the authorized human approver chooses or stops.

## Recovery boundary

The state content remains exactly seven fields:

```text
project_root
initialized_at
consultant_thread_id
control_thread_id
phase
red_count
updated_at
```

The path is rediscovered from the finite evidence table on every activation; it
is never stored as a locator or an extra state field. Existing legacy activity
continues at its original path. An `ENDED` legacy state is recoverable, but any
migration is a separate authorization and is `NOT_RUN` in this project plan.
