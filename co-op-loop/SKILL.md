---
name: co-op-loop
description: Governed consultant-control collaboration for long-running Codex work. Use when an authorized human approver explicitly enters loop, /loop, $loop, or $co-op-loop, or asks to initialize, restore, transfer, RED-review, execute, read back, or close a project-scoped Loop.
---

# CO-OP Loop

Run one project-scoped consultant/control loop with exact task IDs, explicit
user gates, bounded RED, execution reports, independent readback, and a single-
round closeout. Treat the authorized human approver's current instruction and current project rules as
authority; never infer authority from a title, cached ID, or prior PASS.

## Start

1. Normalize the entire input with trim and case-folding. Trigger only when the
   whole input is exactly `loop`, `/loop`, `$loop`, or `$co-op-loop`. The host's
   native `$co-op-loop` invocation enters this same state machine; it is not a
   second flow. Ordinary sentences never trigger.
2. Before any role creation, role upgrade, project-internal file, or state
   write, run the read-only storage preflight described in
   [storage-adaptation.md](references/storage-adaptation.md). It resolves the
   exact state/report pair from finite evidence without adding a locator field.
   If no seven-field state is present, continue to first initialization only
   for `DEFAULT`, complete `ADAPTED`, or complete unique `LEGACY`; do not create
   a placeholder. `BLOCKED`, `AMBIGUOUS`, and `STATE_CONFLICT` stop before any
   task or file creation. After successful initialization, write exactly the
   seven-field state contract described in [loop-protocol.md](references/loop-protocol.md)
   at the resolved state path, then immediately read it back. If a state
   exists, perform only the minimum ID, archive, deletion, and damage checks
   before resuming.
3. Use structured choice when verified; otherwise show the identical numbered
   text. Every choice that can create, delete, restore, transfer, RED, or
   execute requires the exact documented reply.

## First initialization

Follow the ordered first-run gates: project scope, local-task capability,
consultant selection/creation, control-source selection, role-declaration
verification, then initialization-complete choice. After the consultant is
ready, choose new local control or search/reuse an active local control in this
project. Use fixed titles `顾问｜项目名` and `中控｜项目名`; create only local
tasks in the saved project, never cloud or worktree. New-task defaults are
`Sol High` or higher for consultant and `Luna Max` (`最高`) for control and
one-time business. Request the default at creation and report the selected
model/reasoning afterward; this remains best-effort and non-blocking.

The consultant is the user's default business entry. If a business plan request
arrives in the consultant task, route it to the exact bound control task after
the existing plan-confirmation, RED, high-risk, and stop gates. Do not ask for a
duplicate “transfer to control” confirmation, and do not execute the business
work in the consultant. This is a workflow constraint, not host-level
permission isolation.

## Role contracts

Read `CONSULTANT_ROLE` once before drafting or revising each plan version:

```text
CONSULTANT_ROLE
MISSION: Turn the user's confirmed goal into the smallest executable plan and independently verify the outcome.
PROHIBITED: Execute governed business work; expand scope; add controls without a concrete blocker; treat optional follow-up as unfinished work.
PREFERENCE: Outcome first. Minimum plan. Reach verifiable evidence quickly. Accept only evidence-backed RED blockers.
```

Read `CONTROL_ROLE` once before issuing RED for each plan version:

```text
CONTROL_ROLE
MISSION: RED only for real blockers, then execute the confirmed plan to a verifiable outcome.
PROHIBITED: Execute during RED; expand scope; turn preferences or future work into blockers; repeat unchanged checks; redesign the plan.
PREFERENCE: RED is blocker-only. Execution is outcome-first with minimum preflight. Remove unnecessary steps.
```

Give the control task unrestricted local read access when the host supports it;
local reads require no per-path sandbox approval. If the host exposes only a
full-access profile, use it, but keep every write or side effect dormant unless
the exact consultant-issued, user-confirmed plan authorizes it. This capability
does not authorize irrelevant broad scans or credential/secret reads.

If the current task is not the consultant task and an active consultant exists,
offer the exact transfer menu. Transfer the source information, integrated
context, latest complete plan, and explicit file paths as one long text message;
switch last. On arrival, require a fresh standalone `loop`.

## Existing Loop and plan gate

- An existing Loop reads only the seven state fields and performs minimum
  checks. It does not repeat first initialization.
- Each valid activation displays the latest complete plan followed by the exact
  `执行 / 再等等` confirmation contract. `loop` is never plan approval. Only
  the next single reply exactly equal to `1` or `执行` binds that exact plan
  version and authorizes sending the RED package; `2` or `再等等` keeps it
  unsent, and a later standalone `loop` must retrieve the latest plan again.
- After that initial plan confirmation, a RED1/RED2/RED3 `RED_ALL_PASS` result
  dispatches the exact passed plan automatically once minimum preflight,
  high-risk gates, and stop conditions are clear. It does not ask for a second
  execution confirmation. A missing plan confirmation, version mismatch, or
  unmet gate pauses execution.

## RED, execution, and closeout

- Send RED and execution packages as long text containing the governance
  background, complete current plan, scope, and explicit instructions. RED is
  audit-only: no execution and no process files.
- Formal RED verdicts are only `RED_ALL_PASS` and `CHANGES_REQUIRED`.
  `CHANGES_REQUIRED` must name at least one blocking failure, violation,
  concrete security risk, or unverifiable requirement; preferences and future
  ideas do not block.
- A complete fixed-plan resubmission increments `red_count`; questions and
  challenges do not. Classify each `CHANGES_REQUIRED` item independently as
  `ACCEPT`, `CHALLENGE`, or `REJECT`. A `CHALLENGE` allows one evidence return
  for one fingerprint and then must resolve; it cannot create nested RED.
  After a third complete `CHANGES_REQUIRED`, keep `red_count: 3`, create a
  `RED4_CANDIDATE`, and run the independent `FINAL_RISK_AUDIT` contract. Do
  not auto-execute either version; show the exact three-choice authorized human approver route.
- Before any real action, require the control preflight and self-pause for
  out-of-scope deletion, publication, external calls, irreversible changes,
  permission expansion, or uncertain side effects. The same error with the
  same method failing twice becomes `REPEATED_FAILURE`; pause without a third
  blind retry. Allow one minimal correction per failure fingerprint, then pause
  on recurrence. Track ordinary progress silently.
- Require control status `EXECUTION_COMPLETE`, `EXECUTION_PAUSED`, or
  `EXECUTION_FAILED`, one mandatory Loop report, any separately required
  business report, and the consultant's independent single-round evaluation.
  Write the seven-field state with `phase: ENDED`, then show the appropriate
  closeout choices. If all goals are complete, infer a concrete real-evidence
  action and use the runtime-known user address; route choice 1 to the exact
  control or choice 2 to a local one-time business task. Choice 3 or no reply
  ends tracking. Any next round still requires a fresh standalone `loop` and
  all original plan, RED, permission, and stop gates.

Read detailed contracts only as needed:

- [loop-protocol.md](references/loop-protocol.md): activation, first-run UI,
  state, recovery, transfer, RED, execution, and closeout.
- [storage-adaptation.md](references/storage-adaptation.md): deterministic
  read-only storage preflight, strict-project evidence, recovery priority, and
  zero-creation stops.
- [host-adaptation.md](references/host-adaptation.md): local Codex adapter,
  capability grading, text fallback, and model best-effort rules.

This skill never authorizes GitHub, Issue, Release, credentials, production
automation, cloud/worktree creation, or unapproved destructive actions.
