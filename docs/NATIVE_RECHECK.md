# Native tool revalidation — implementation contract

Status: durable controller ledger implemented/offline-tested; native transport and
CLI not connected, not an enabled runtime feature. User authorized this direction on
2026-11-18 after the standalone policy probe produced negative evidence.
Decision models/classifiers are outside the current scope.

## User flow

Resume preview lists stale test/lint checks, exact user-owned command/cwd bindings,
and requested model/effort. Restoring a session never starts inference or a check.
After explicit execution consent, `/recheck STEP.CHECK` requests one verification
turn for that check. The UI states that this consumes subscription quota and is
separate from manual `/revalidate`. There is no automatic batch, retry or escalation.
`/finish` stays blocked until all required saved evidence is current and accepted.

The first version uses the explicit `standard` role binding and supported low
effort, shown before consent. A changed binding requires fresh consent. It does not
infer a cheap model from its name or let a decision model select one. The existing
model policy still applies, independently of native tool permissions.

## Execution boundary

Use native thread/turn tools with the same read-only/on-request policy and stronger
host restrictions. Keep unsupported approval requests declined and pause. Do not
add command/exec, direct local subprocess execution, permission expansion or a
user-entered pass override for test/lint. Prompt instructions are guidance, not an
enforcement boundary; do not claim that a verification turn cannot use other tools.

Use a separate durable native thread for revalidation. Do not overwrite the work
thread's turn binding or let a late verification event finish a work attempt. Keep
all native thread identities in local metadata for inspection and scoped deletion;
do not silently delete retained threads or claim service-side erasure.

Reuse the existing exact command/cwd matcher and item start/completion checks.
Accept an exit code only for the current recheck's thread, turn and item, followed
by a confirmed completed turn. Repeated commands, changed identity, conflicting
completion, missing observations and nonterminal/disconnected turns cannot clear
stale evidence. Model prose is display text only. Failed/interrupted turns do not
make checks current even when earlier command output looked successful.

## Durable state and budget

Implemented: a versioned, append-only recheck ledger in the workflow checkpoint, preserving
read support for existing checkpoints. A reservation contains an operation ID,
source evidence ID, exact command/cwd digest, requested selection, cycle/number,
timestamp and native identities as they become known. No stdout, stderr, raw prompt
or credentials enter this ledger. Store commands in the user-owned binding file;
persist only their canonical digest in the reservation and validate again on use.

Write the reservation atomically while holding the parent session writer lock,
before thread/start. Persist the new thread identity before reserving turn/start;
persist the pending turn reservation before sending it. Store the returned turn
identity before processing queued events. Failed persistence aborts dispatch.
If a request may have reached the server but its binding was not saved, keep the
operation outcome unknown: never start another thread or replay it automatically.

Recheck attempts have their own initial-plus-two-corrections budget per source
evidence. Reservation consumes a slot, including failed starts. Ordinary resume,
model changes, command changes and file edits do not reset that budget. After three
slots, pause with continue/change-scope/pause choices; only a recorded explicit
continue opens another cycle. Work attempt counters and their history are unchanged.
An unresolved operation must be reconciled before any new recheck is reserved.

A matching known current result can clear that evidence's stale flag only in the
current process. A mismatch/unknown keeps it stale, preserves the new finding in
the recheck ledger and requires a user decision about further work. Every subsequent
restore makes accepted evidence stale again; a saved completed recheck is audit
history, never a reusable grant or proof that current files are unchanged.

## Required checks before exposing the CLI

1. Reservation/phase transitions persist before RPCs; injected save failures and
   unknown responses never replay. Older checkpoints load without granting checks.
2. Account/project/provider/quota/catalog and native permission checks are fresh;
   no quota, unavailable model or changed selection means no new turn.
3. Exact and supported shell-wrapped command observations work; foreign/late events,
   mismatched cwd, duplicate items and assistant pass claims cannot validate checks.
4. A completed native turn plus a matching observed check clears only its source
   evidence; failed/missing/mismatching results cannot finish the task.
5. Budgets survive reconnect and command/model changes. Explicit extensions have
   ledger evidence. Work counters/bindings remain unchanged.
6. UI cancel/EOF/interrupt stay responsive; unknown interruption blocks further
   dispatch. Reopen, inspect and delete understand retained recheck threads.
7. An opt-in synthetic live test exercises one stale test/lint check after reconnect
   with an unchanged sentinel. Report requested models separately from unknown
   actual dispatch; never certify all permission paths from this example.

Checkpoint version 1 remains readable; version 2 is written only once a recheck is
reserved. Older ModelMate builds cannot read version-2 checkpoints; do not downgrade
the runtime after creating one. No session files are migrated during plain reads.

Implementation order: checkpoint ledger and offline fault-injection tests (done), native
transport/observation handling, CLI integration, then the scoped live verifier.
Keep public tool-check resume disabled until those dependent pieces are complete.
