# Native tool revalidation — implementation contract

Status: ledger, native transport, opt-in CLI and verifier implemented/offline-tested;
synthetic native recheck happy path user LIVE_VERIFIED on 2026-11-19 at 732ac47.
Known-binding recovery is offline verified; live recovery, interactive Terminal timing and scoped deletion remain pending.
User authorized this direction on
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
transport/observation handling (offline-tested), CLI integration (offline-tested),
then the scoped live verifier (offline-tested). Default tool-check resume stays disabled. Experimental
resume requires --experimental-rechecks in addition to --execute-workflow and START.
Do not call the experimental path live-verified or release-ready before its probe.

The internal NativeRecheckConnection starts one separate durable thread/turn after
the caller supplies an explicitly consented selection and exact check specification.
It exposes drain/tick/cancel for a future event loop, not a blocking model-wait loop.
A transient verification controller reuses WorkflowHost's existing command observer;
only the parent recheck ledger owns persisted state. Child workflow-change events
are filtered; the caller receives parent changes only after a ledger terminal event.

The adapter does not resume an unknown recheck thread or certify historical output
as current. Failed writes poison the parent; cancel still attempts the known native
interrupt even if persistence has failed. Closing without confirmed termination
records unknown and retains the thread. A late conflicting terminal event appends
an unknown outcome, restores the source stale flag and revokes parent DONE if needed.
These paths have synthetic transport tests, not live permission/recovery proof.

## Experimental CLI, 2026-11-19

Use --resume-workflow with an actual local session ID, explicit --role-model bindings,
the user-owned --check-commands file, --experimental-rechecks and --execute-workflow.
Without execute the preview remains offline; CANCEL/EOF do not start a backend.
START opens the native session but does not approve a verification turn.

- `/recheck 1.1` shows the exact binding and standard/low requested selection.
- `/confirm-recheck TOKEN` consumes that one-use confirmation and starts one turn.
  Changed workflow/mode/model bindings or check specification require a new preview.
- `/status`, `/cancel`, `/exit` and EOF are processed while the child turn waits.
  Exit waits for a terminal event or the existing bounded interruption deadline;
  no interrupt acknowledgement alone establishes that the turn stopped.
- `/recheck-budget 1.1 continue|revise_scope|pause` records a choice after three
  reservations; it never starts a turn. Model prose cannot invoke these commands.
- `/continue TOKEN`, `/check` and `/finish` still control the original workflow.
  Rechecks do not advance steps or mark the task done automatically.

Only known saved test/lint evidence can be rechecked. Completed active work with
missing/unknown tool checks is refused. Unresolved recheck operations block native
resume; --show-workflow remains available offline and displays retained thread/turn
IDs. Known-binding reconciliation without replay is available below; scoped native-thread deletion is not yet implemented. Local metadata removal refuses records containing rechecks, preserving
those native identities for later inspection/cleanup. Threads are retained even
after successful checks; there is no service-side erasure claim.

## Opt-in live verifier

`python3 verify.py --run-live --probe-rechecks MODEL` requests at most two model
turns, both with the explicitly selected model at low effort. First it observes a
registered synthetic printf command and saves the resulting accepted tool evidence.
It reconnects the parent, checks that stale evidence cannot finish the task, then
uses the UI preview/confirmation commands to start one separate native recheck.
Only matching current command evidence can permit the final checkpoint.

The report requires all seven checks passed for exit 0, with source hashes and
requested selection; reportedModels remains unknown. Partial/failed checks exit 1
and are never retried. Native threads and private scratch metadata are retained;
stderr identifies only the owned scratch directory. JSON reports omit command,
nonce, model prose, native/account IDs and local paths. This is a scoped happy-path
probe, not interactive Terminal timing, all permissions, unknown recovery or deletion
proof. Interactive input/event-loop behavior is currently checked offline.

## Known-binding recovery (offline verified)

`modelmate.py --recover-recheck SESSION_ID` holds the session writer lock and uses
only initialize/account/quota reads, thread/read, thread/turns/list and, following
explicit STOP, turn/interrupt. It never starts/resumes a thread or starts a model
turn. Account, project, provider, durable identity and latest single-turn history
must match the retained binding. Known exhausted quota permits metadata recovery;
unknown account/quota does not. Missing IDs remain unresolved without discovery.

An active turn offers STOP/PAUSE; EOF is not consent. STOP rechecks the displayed
binding and waits for an observed terminal status. An acknowledgement alone cannot
resolve the ledger. Terminal metadata appends a reconcile event with no command
exit code/item evidence; historical checks stay stale and counters/history remain
unchanged. Fresh rechecks still require their normal explicit consent. Older builds
that do not recognize reconcile reject that checkpoint rather than misread it.

`verify.py --probe-recheck-recovery SCRATCH` reads an existing successful synthetic
recheck probe and stages a lost terminal event in a private metadata copy. Its RPC
allowlist also removes turn/interrupt. No model turn, source mutation or native
thread deletion occurs. Success removes only the owned copy; failure retains it.
This does not prove active-stop behavior, crash/network recovery, missing-binding
discovery, current command results or scoped native cleanup.
