# Contributing

Thank you for helping improve CO-OP Loop. Keep changes small, explain the
behavioral reason, and preserve the evidence boundary.

## Before opening a change

1. Read the relevant runtime Skill instructions and references.
2. Describe the user-visible behavior, host assumptions, and authorization
   boundary affected by the change.
3. Keep private paths, local state, task identifiers, credentials, and internal
   governance material out of the candidate package.
4. Add or update focused tests for behavior changes.

## Validation

Run the Skill structure validator and scenario tests with Python bytecode
disabled. Record the exact source copy tested and the result. Do not claim
host compatibility from static inspection alone.

For storage changes, verify the read-only preflight, the seven-field contract,
strict-project behavior, legacy behavior, and zero-write/zero-task gates.

## Pull requests

Explain the smallest safe change, tests run, known limitations, and any
unverified host behavior. Do not include generated reports, local caches,
private state, or credentials. External publication, releases, and issue
closure remain separate authorization decisions.
