# Verification evidence

## P00 — MOCK_VERIFIED

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -q`: 28 tests passed.
- `python3 -m py_compile doctor.py verify.py`: passed.
- `git diff --check`: passed.

Regression coverage:

- Fragmented JSONL notifications/results followed by EOF are consumed before
  reporting the closed stream. Unexpected response IDs are rejected.
- Missing, malformed, exhausted, boolean and multiple quota windows fail closed.
- Account identity must be supplied by each quota read and remain stable between
  turns. The backend's ordinaryUsageAllowed remains the authority for included
  usage; this is not independent credential or user-identity validation.
- Unknown/malformed approval requests and stale thread/turn requests are not
  answered. Diagnostic methods remain restricted to read-only RPCs.
- Turn deadline includes time waiting for turn/start; it is not renewed per event.
- Events arriving before the start RPC response are retained.
- Missing start response without a turn ID leaves outcome unknown, blocks retry,
  and retains the scratch directory. If turn/started supplies an ID, interruption
  can target that turn despite the lost response.
- Interrupt acknowledgement alone is insufficient: a matching terminal event is
  required before clearing active state and deleting scratch data.
- Interruption/cleanup errors preserve the original failure. Unconfirmed stop
  cannot produce a successful report.
- Recall success reports requested models separately from unknown reported models;
  actual model dispatch is not claimed as verified.

The test output includes intentional cleanup/interruption warnings from injected
failures. They are expected assertions, not live Codex failures.

Live inference: NOT RUN. G1–G4 remain unverified. No account identifiers or raw
account reports are recorded here. P00 still needs the designated lifecycle review
before being treated as release-ready. Next eligible offline task: P02. P01 needs
normal-terminal live evidence; no sandbox bypass has been added.


## P02 — MOCK_VERIFIED

Shared protocol and account inspection now live in `modelmate.py`; doctor and
verify import that code, and no protocol reader is duplicated. The base method
allowlist remains read-only; only the verification subclass permits live turns.
Runtime import creates no process, selector or network connection, even when only
modelmate.py is copied to a fresh directory. This is a runtime foundation, not a
finished chat CLI.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -q`: 34 tests passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.
- `python3 doctor.py --help` and `python3 verify.py --help`: passed without login.

Additional tests exercise invalid response envelopes (including boolean IDs),
unknown server requests, bounded receive buffers, a notification flood with a
fixed RPC deadline, single-file import isolation and shared-class identity.
Existing byte-fragmentation, interleaving, EOF, cancellation and process shutdown
regressions remain passing. Verification event storage retains its 10,000-event
limit; the receive buffer retains its 4 MiB limit.

Live inference: NOT RUN. G1–G4 are unchanged. Next eligible offline task: P04.
P01 still requires normal-terminal evidence; P03 still requires the permission
capability investigation before real tool execution can be exposed.


## P04 — MOCK_VERIFIED

Shared quota policy now lives in `modelmate.py`. `quota_decision` returns
allow/pause, a machine-readable reason, monotonic checked_at and account identity
for in-memory use. `refresh_quota` reads ChatGPT auth and quota for each new turn;
verify uses it rather than maintaining a duplicate policy. The compatibility
ensure_quota entry point validates a snapshot but does not start or authorize a
future turn by itself.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_quota.py -v`: 14 tests passed.
- `python3 -m unittest discover -s tests -v`: 48 tests passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- Doctor and verify help commands: passed without connecting to Codex.
- `git diff --check`: passed.

The JSONL subprocess tests record actual request methods and assert no turn/start
is transmitted for unknown/exhausted quota, missing identity, RPC failure,
closed connection or API-key auth. Further tests confirm every turn refreshes,
account changes stop the next turn, and an exhausted snapshot can recover only
through a new read. Pure tests cover multiple buckets, malformed values, credit
access and slow/stale refreshes. The P02 isolated-import subprocess test had a
missing patch import after cleanup; it is corrected and passing in this run.

Policy boundaries:

- A snapshot older than 15 seconds (including time spent refreshing), with a
  future/non-finite timestamp, is paused. Monotonic timestamps are process-local
  and must not be persisted as resumable grants.
- Without reliable model-to-bucket mapping every returned bucket must pass. This
  may conservatively pause even when another model would work. No guessed bypass.
- Reset time passing does not override exhausted/unknown status.
- Account identity is pinned from the first allowed quota response and compared
  thereafter. Backend validation of ordinaryUsageAllowed is still required; the
  local comparison is not an independent credential check.
- Credits absent/null in a response are not proof that no paid-credit facility
  exists. Known positive credit access pauses the diagnostic. Backend included
  usage permission and preflight are not a hard spending cap or reservation.
- No credit purchases, resets, API-key fallback or billing changes were added.

Live inference: NOT RUN. G1–G4 remain unverified. The full controller/session UI
will consume these decisions in later tasks; this task only implements quota
policy and integrates it into the existing verification turn path.
Next eligible offline task: P05 (model roles and effort policy).


## P05 — MOCK_VERIFIED (live role mapping pending)

Added shared catalog pagination, explicit model/effort selection, trusted role
resolution and a conservative change-comparison function in modelmate.py.
Doctor uses the shared catalog reader; verify uses the shared selection validator.
No second catalog parser or selection validator was introduced in the diagnostics.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_models.py -v`: 12 passed.
- `python3 -m unittest discover -s tests -q`: 60 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests cover pagination/cycles/invalid pages/duplicate IDs, hidden models,
unsupported/default/future effort, missing roles, explicit role bindings, catalog
changes on resume, manual selection and conservative escalation comparisons.
A selection does not mutate catalog or grant permissions. The future workflow
must refresh catalog on startup/resume and validate again; there is no resume UI
yet. Unknown comparisons require approval rather than guessed cost rankings.

Built-in MODEL_ROLE_POLICY is deliberately empty: no real model has completed
P01 live dispatch validation and reviewed role assignment. The role resolver
accepts trusted reviewed bindings or explicit user bindings; neither the model
classifier nor text in project files may supply that authority. Synthetic model
bindings in tests prove behavior, not production model quality.

EFFORT_ORDER defines an explicit conservative policy for familiar effort labels,
not measured token/quota consumption. Unknown labels are selectable only when
present in the catalog, and any comparison involving them requires approval.
Cross-model downgrade needs unambiguous trusted role mapping and non-increasing
effort; model role and effort comparisons never grant tool execution rights.

Live inference: NOT RUN. No performance, model availability, role quality or
quota-saving claims have been verified. Next eligible offline task: P06.


## P06 — IN_PROGRESS (offline plan pipeline MOCK_VERIFIED)

Implemented version-1 plan validation, proposal-to-role resolution and inert
classifier request preparation in modelmate.py. Unknown keys, duplicate JSON keys,
invalid enums, empty checks, non-finite JSON constants, oversized text/proposals
and more than 12 steps are rejected. High-risk proposals require a strong review
step with checks. Clarifications return no resolved execution selections.

The routing result is ready_for_approval, never authorization to execute. Only
trusted role mappings resolve model/effort pairs; proposal fields cannot grant
permissions, assign IDs, set retry counters or mark tests passed. This is schema
and policy validation, not proof that a model classified real task risk correctly.

Preparation refreshes catalog and quota and validates explicit classifier selection
and role bindings. User text is encoded as task data separate from classifier
instructions. Status/approval/unchanged-scope triggers cause no RPC. The controller
must supply those triggers; the model is not allowed to classify its own approval
reply as a new task. The input descriptor is not an RPC request.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_routing.py -v`: 14 passed.
- `python3 -m unittest discover -s tests -q`: 74 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Remaining integration: live classifier invocation and output collection are not
implemented because no supported no-tools execution boundary has been proven.
read-only sandbox alone can still permit shell reads; prompt instructions alone
cannot satisfy the P06 no-tools requirement. Preparation therefore explicitly
reports blocked_until_no_tools_boundary_verified and never sends turn/start.
No prompt-only enforcement or assumption that unknown tool calls cannot occur was
introduced. P03 must establish the boundary before exposing live classification.
P07's offline grant/mode logic can be developed using the validated proposals;
full P06 must not be marked DONE or LIVE_VERIFIED from these tests.

Live inference: NOT RUN. G1–G4 and actual task-quality evaluation remain pending.


## P07 — MOCK_VERIFIED (offline policy)

ModelApprovals holds a fresh task ID and a task-local standard-model baseline.
The default mode is ask_to_escalate. Auto returns the model selection and a short
reason; ask_to_escalate asks for strong initial selections, increases and unknown
comparisons; approve_plan asks for the full plan before allowing its model choices.
The output allow_model is only a model-policy decision, never a tool or quota grant.

Approvals bind to a digest of task identity, validated complete plan, resolved
model/effort choices and trusted role mapping. Step model approvals additionally
bind to controller step ID/index. Whole-plan approval covers all unchanged steps;
manual model approval covers only the named step and does not approve a plan.
Changed/invalid/unclear plans revoke old approvals, including when a plan later
changes back. Pending tokens cannot be replayed after context/mode changes.

Only explicit approve/decline/pause choices are accepted. Invalid choices, EOF-like
None and stale tokens never approve. Declines pause and offer revise-scope/model
or pause; the system does not silently upgrade. Grants remain process-memory only.
P08 must obtain these calls from actual human UI input; project/model text cannot
be used as authority to call answer or manual_select. P09 separately controls tools.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_modes.py -q`: 14 passed.
- `python3 -m unittest discover -s tests -q`: 88 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Coverage includes three-mode initial/escalation/downgrade matrix, plan/model/effort
changes, repeated questions, stale tokens, declines, task boundaries, step scopes,
manual choices, ambiguous comparisons and old-grant resurrection prevention.

No live inference or Terminal UI integration has been run. P06 live classifier
still awaits the proven no-tools boundary; P07 consumes only its offline validated
proposals. Next eligible task: P08 mock-driven Terminal shell, or independent P11
session metadata. G1–G4 remain unverified.


## P08 — IN_PROGRESS (Terminal shell MOCK_VERIFIED)

Added the single-file runtime entry point and a line-oriented Terminal shell.
The shipped entry point has no live backend: prompts receive an explicit
unavailable message, never simulated model output presented as actual inference.
No process/network connection is opened by default or --help.

One selector loop owns stdin, injected controller events, pending UI decisions
and shutdown state. There is no input worker thread. A trusted controller callback
is an internal test/integration seam, not an external replay or backend CLI option.
Model policy uses P07; approvals require the exact displayed token. Text such as
yes is not approval. Unknown slash commands are never submitted as prompts.
The UI filters control/direction characters and does not render reasoning events.
Unknown tool events fail closed. Ctrl+C/EOF clear pending requests and request
cancellation, waiting for confirmation before reporting stopped. Missing stop
confirmation expires after five seconds with outcome unknown (exit 130).

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_cli.py -v`: 13 passed.
- `python3 -m unittest discover -s tests -q`: 101 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

CLI subprocess checks cover --help with no executable Codex on PATH, initial Thai
prompt, piped blank/command input, concurrent controller text and status input,
EOF during approval and SIGINT during approval. The fake controller never calls
Codex. Policy tests cover stale tokens, changed modes, clarification invalidation,
manual selections, denial, cancellation deadlines and Terminal escape filtering.

Remaining integration: /permissions does not expand rights, /sessions and /delete
report unavailable, and /exit does not save a session yet. These depend on P03/P09,
P11/P12. Live classifier, stream turn IDs, real controller dispatch and actual
cancellation must be wired only after the relevant gates pass. This is not a
production agent or complete P08 delivery; pending commands are not counted as
working features. Next independent offline task: P11 local session persistence.
Live inference: NOT RUN. G1–G4 unchanged.


## Live connection attempt and P03 source investigation — 2026-11-17

P01 remains BLOCKED in this development sandbox. `codex login status` reports
ChatGPT login, but both `python3 doctor.py --timeout 10` and the new standalone
`python3 modelmate.py --doctor` fail before a protocol response. A separate startup
probe classifies stderr without printing raw logs: exit 1, SQLite initialization
failure, read-only filesystem error, no protocol response. No credentials were
copied and no permission bypass was attempted. No inference was requested.

The runtime now supports --doctor as an explicit connection-only entry point,
using the same inspected read-only protocol path. It rejects an initial prompt
in this mode, reports a failure as exit 1 and closes its child process. This is
not live conversational inference. Default chat remains offline.

P03 capability matrix (source inspection, not live enforcement proof):

| Path | Evidence | Current disposition |
| --- | --- | --- |
| Shell/exec | Tagged spec_plan.rs add_shell_tools checks ShellTool feature/model shell type | Candidate feature control; live behavior unverified |
| apply_patch | Tagged spec_plan.rs registers ApplyPatchHandler when model apply_patch_tool_type exists | No verified universal client no-tools override |
| Hosted search | Hosted search bypasses local tool hooks per official hook documentation | Disabled in private contexts; isolation still unproven |
| MCP/plugins/subagents/hooks | Separate feature/config surfaces exist | Full disable/bypass matrix not live verified |
| No-tools classifier | read-only permits some tools; prompt cannot enforce absence | Live classifier remains unavailable |

Tagged source inspected:
https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/tools/spec_plan.rs
(add_shell_tools and ApplyPatchHandler registration). An open upstream feature
request https://github.com/openai/codex/issues/60069 corroborates the no-tools
concern, but its report concerns an older alpha/Windows and is not proof of
behavior on this installation. The tagged code is the primary evidence here.

Checks:

- `python3 -m unittest discover -s tests -q`: 104 passed.
- `python3 -m py_compile modelmate.py`: passed.
- `python3 modelmate.py --doctor`: attempted, failed at local Codex startup.
- `git diff --check`: passed.

To complete P01, run --doctor in a normal Terminal where Codex can write its
runtime state, then run verify.py --run-live using model IDs that catalog actually
returns. The latter consumes subscription quota. Only sanitized results belong
in this file. P03 still needs lifecycle/security review and live evidence before
any claim that every action asks for approval or that classifier tools are absent.


## P01 — user-supplied live read evidence received 2026-11-17

The user supplied a successful diagnostic result generated on 2026-11-16 UTC
from their normal Terminal. This supersedes the account/catalog/quota part of
the earlier environment block; the development sandbox itself remains restricted.
Evidence source is the user's diagnostic output, not an independently reproduced
run here. The output does not identify which diagnostic entry point was used.

Verified at the time of that snapshot:

- Account type ChatGPT; Plus plan.
- Catalog and supported effort options returned successfully, including
  gpt-6.1-sol, gpt-6-astra and gpt-6-luna.
- ordinaryUsageAllowed true; primary and secondary usage windows returned.
- No reached-limit/spend-control flag and no additional credits reported.

No raw report, quota percentages, account identifiers or session IDs are stored.
This is historical evidence, not a reusable quota grant; refresh before inference.

Several catalog models also advertise ultra with automatic task delegation.
Catalog availability is not permission to delegate. Existing policy treats ultra
as an unknown comparative effort and requests approval, but this alone does not
prove delegation is disabled. Live classifier/tool execution remains gated by P03.
Use the verification harness's explicit low effort where catalog supports it;
do not enable ultra automatically from this report.

Still unverified: actual inference dispatch, model/effort changes, context recall,
command/patch denial and the complete permission/no-tools boundary. P01 remains
IN_PROGRESS, not fully LIVE_VERIFIED. Next live check, using the freshly returned
catalog IDs, is:

```bash
python3 verify.py --run-live --models gpt-6.1-sol gpt-6-astra
```

This consumes subscription quota and performs synthetic scratch-file denial checks.
A pass proves only the tested scenarios, not all tool paths or actual model dispatch
if the backend does not report it. An INCONCLUSIVE result is not a pass.

Documentation-only update: checked `git diff --check`; no inference or tests rerun.


## P01/P03 — user-supplied live harness evidence received 2026-11-17

Command reported by the user:

```bash
python3 verify.py --run-live --models gpt-6.1-sol gpt-6-astra
```

User-supplied result: contextRecall passed, commandDenial passed, patchDenial
passed. Requested models were gpt-6.1-sol and gpt-6-astra. reportedModels was null
and modelSwitch was explicitly unverified. No independent rerun was performed
inside the restricted development sandbox, and no thread/account IDs are stored.
The harness chooses low effort where catalog supports it, but this report does
not independently establish backend model or effort dispatch.

This advances the preceding pending evidence: a real turn sequence produced a
correct synthetic recall answer, and the harness observed matching denial events
with neither scratch marker present. P01 remains IN_PROGRESS because actual
model/effort dispatch is not reported. G1 has partial live evidence; it is not
fully verified. P03 now has two live denial scenarios; G2/G3 remain unproven.

These checks do not prove default ask-before-every-command behavior. The harness
explicitly requests approval for scratch writes inside a read-only sandbox.
Unapproved read commands, stdin continuation, MCP/plugins, hooks, subagents,
symlink/outside-project access and hosted tools still need boundary evidence.
Do not enable the live no-tools classifier or all-tool execution on this basis.

Next investigation: obtain trustworthy model/effort metadata if supported and
complete the tool-path enforcement matrix. No need to rerun this same pair solely
to reproduce an already supplied recall result. Luna/Terra availability from the
catalog is not a role-quality benchmark; they remain eligible for explicit
selection/testing without a claimed production role mapping.

Documentation-only checks: `git diff --check` passed. No new inference was run.


## P01/P03 — configuration evidence and read-command probe preparation

Inspected the installed 0.169.0 JSON schemas: Thread.model explicitly describes
configured state rather than per-turn execution telemetry. Thread settings
notifications carry model/effort but no turn ID; raw response completion carries
usage and IDs but no actual model field. The harness now records requested
selection and settings observations separately and leaves reportedModels unknown.
No self-identification prompt or guessed dispatch assertion was added.

Added a separate --probe-read-approval path: one synthetic printf turn, no handoff
rerun, no file reads/writes requested. It records command completion/denial by
matching actual tool item IDs internally, but reports only type/status/denial flag.
It never accepts an approval. A successful command without denial is a bypass
observation; no tool evidence is inconclusive. Neither result passes the gate.
Expanded the path-by-path matrix in docs/PERMISSIONS.md.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -q`: 112 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `python3 verify.py --help`: passed.
- `git diff --check`: passed.

Tests use JSONL subprocesses to exercise settings events before RPC replies,
missing metadata, wrong-thread/malformed metadata, and sanitized tool observations.
Probe classification tests distinguish execution, denial and inconclusive cases.
No raw tool command/output or thread/account identifiers are in evidence reports.

Live inference this round: NOT RUN. The previous user live result remains valid
only for its scenarios. The new read-command probe still needs user Terminal
execution; existing sandbox restrictions are unchanged. P03 remains IN_PROGRESS.


## P03 — negative live evidence received from user 2026-11-17

The user ran the new single-turn printf probe with gpt-6.1-sol requested at low.
Result: readCommandApproval executed_without_approval; a commandExecution item
completed with denialObserved false. No thread settings were observed; actual
model dispatch remains unknown. Evidence is user-supplied, not a local rerun.
No raw user/account/thread identifiers or tool output are stored here.

Conclusion: read-only + on-request in the tested configuration does not satisfy
R06 ask-before-every-command. This is a failing requirement check, not a passing
permission gate. It does not imply all shell commands bypass approval, and it does
not negate the earlier scratch-write denial results. The tested command only
printed a synthetic marker; no file read/write was requested.

The runtime still does not expose live tools. R06 has not been relaxed. Next
architecture decision requires user agreement if default permission semantics
change; otherwise enforcement must be developed and proved before P09 can ship.
Independent offline tasks remain possible while resolving the boundary.
Documentation-only check: git diff --check passed; no new inference was run.


## User-approved native permission policy and opt-in manual live chat

User explicitly selected option 1: use native Codex permission behavior.
This supersedes ask-before-every-command in R06. Default is read-only + on-request;
commands allowed by that sandbox need not ask. Required server approvals still
need human input. No automatic workspace-write/full-access or session-wide grant
was introduced. Stronger host/managed restrictions still apply. The earlier printf
result is an expected observation under the new policy, not a failure of new R06.
Historical evidence above refers to the policy in effect when recorded.

Implemented --live --model ID [--effort LEVEL] in the single-file runtime.
This path is manual-model chat, not automatic routing or the no-tools classifier.
It uses a ChatGPT-only/openai provider configuration, inspects catalog/auth,
creates one ephemeral read-only thread, and refreshes catalog/quota before each
new turn. Text during a known active turn uses turn/steer. Turn-start uncertainty
is not retried. Requested ultra delegation effort is not enabled.

The UI/backend share one owning selector loop. The existing protocol reader was
factored into pop_message/read_ready so synchronous diagnostics and asynchronous
live chat do not duplicate parsing or size limits. Async RPC IDs and deadlines
are correlated; disconnect/unknown result does not lead to automatic replay.
Model selection, inference dispatch and tool decisions remain distinct.

Command approvals display exact escaped command/cwd; file approvals require a
bounded preview captured from the corresponding fileChange item. Human approve
is a one-time accept, decline/pause do not approve. Missing previews, oversized
requests, overlapping requests and unsupported/stale request types are refused
or stop the session. Cancellation declines pending requests and waits for the
matching terminal event. Interrupt acknowledgement alone does not mean stopped.
Hosted search/apps/plugins/agents are requested disabled in this path, but a
universal no-tools/private-context isolation claim is not made.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_live.py -v`: 13 passed.
- `python3 -m unittest discover -s tests -q`: 125 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests cover native thread settings, fail-closed quota, exact one-time approvals,
missing/stale previews/tokens, stop confirmation, streamed-text deduplication,
completion-before-start-response ordering and delayed-start cancellation.
A subprocess integration runs the actual --live entry point against an injected
JSONL fake Codex server for two turns, with explicit accept then decline, verifying
one thread and renewed quota checks. This does not use real credentials/quota.

The new live-chat integration has NOT been run against the actual account here;
startup remains blocked by the development sandbox. The user's previous harness
results establish account/turn/denial behavior only for those scenarios.
P03/P08/P09 remain partial. No autosave/resume, automatic workflow or universal
support for permission/tool-input request types is claimed. Unsupported server
requests stop without granting rights. Next validation: a normal-terminal --live
chat with an explicitly selected available model and a harmless text prompt.


## Live second-turn failure — recovery and diagnostic changes

User reports that the first live text turn completed, then the second prompt
terminated with the generic transport/data error. The original output contains
no exception class/errno/stage, so the exact real-account root cause is unconfirmed.
No raw user conversation or account logs are stored.

Confirmed failure paths corrected:

- Catalog refresh/selection failure before inference used to terminate chat.
  It now pauses without sending that prompt, leaves the session open, and requires
  explicit user resubmission. It does not retry inference or weaken quota checks.
- Protocol stdout/stderr reads are nonblocking. A ready descriptor whose bytes
  were consumed by a synchronous preflight RPC can return EAGAIN without being
  treated as disconnect/fatal error or blocking the UI on stale readiness.
- Fatal errors report a local phase and safe exception class/errno, not raw paths,
  request payloads, credentials or exception messages from external libraries.

Offline validation:

- `python3 -m unittest discover -s tests -p test_live_recovery.py -v`: 3 passed.
- `python3 -m unittest discover -s tests -q`: 128 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

The regression uses a pseudo-terminal for Thai stdin and a JSONL fake Codex server,
with late usage notifications after completion and a deliberate second-prompt
catalog error. Three successful turns stay on one thread; the failed prompt never
appears in turn/start. Separate tests inject EAGAIN and verify diagnostics redact
exception payloads. These tests establish the corrected scenarios, not an exact
reproduction of the user's unknown underlying exception.

Actual-account retest: pending. If it still stops, use the new phase/class/errno
line to locate the failing operation; do not request raw secrets or full logs.
Git workflow now requires branch → detailed PR → checks/review → PR merge.


## P11 — MOCK_VERIFIED (local metadata storage API)

Implemented SessionStore in the single-file runtime. State uses XDG_STATE_HOME
(or ~/.local/state)/modelmate and a SHA-256 project key derived from canonical
real path. Controller-created session UUIDs name the files. Metadata schema v1
contains task/step/criteria/correction status and optional Codex thread ID, not
transcripts, credentials, quota grants or execution approvals. Goal/summary can
still be sensitive; this is private local storage, not encryption or redaction.

Directory/file permissions are restrictive (0700/0600). File descriptors use
O_NOFOLLOW; regular/private/single-link files are required. Project-directory fd
operations keep reads/replaces anchored if a pathname is later retargeted. Project
symlink aliases resolve to the same identity. Relative state-home values are
rejected rather than writing implicitly under the current working directory.

Nonblocking Linux flock rejects another writer and is held for the entire edit
context. Checkpoints require that lock; normal context exit saves atomically.
Locks remain as small files to avoid lock-inode races. Exceptions leave the last
completed checkpoint in place. Save writes a same-directory temporary file,
flushes/fsyncs it, replaces atomically and fsyncs the project directory. JSON that
is corrupt, has unknown fields/version or mismatched identity is not overwritten.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_sessions.py -v`: 19 passed.
- `python3 -m unittest discover -s tests -q`: 147 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests cover Thai/spaced paths, canonical project aliases, separate projects,
private permissions, corrupt/future-schema preservation, ID collision, invalid
metadata, symlink rejection, directory retargeting, failed replace, checkpoints,
exceptions, real subprocess lock contention and process death before replace.
A nested writer failure must not revoke the outer writer's lock ownership.

Scope/limits: storage primitives only. Existing live chat is still ephemeral and
has no autosave/resume integration; /sessions and /delete remain unavailable.
P12 must handle durable thread creation/resume and unknown in-flight outcomes
before exposing these commands. Saved mode/profile are hints, not automatic
restoration of grants. A directory-fsync failure after replace may mean the new
complete file is installed but durability is uncertain; no rollback is claimed.
An abrupt process death can leave an ignored .tmp file; no speculative cleanup
or schema migration framework was added. Actual power-loss and hardware storage
faults were not tested. No live inference was run. Next eligible task: P12 planning
and lifecycle integration, subject to its P10 dependency for workflow-specific state.

## P12 — manual chat lifecycle MOCK_VERIFIED; full task IN_PROGRESS

Manual live CLI now requests durable Codex threads and holds the per-session
writer lock for its entire attachment. Schema v2 adds a SHA-256 account identity
fingerprint, last known turn ID and deletion receipt state. No raw account ID,
credentials, transcript or approval grant is added. V1 remains readable; it is
not silently bound to the current account or resumed. Future versions are rejected.
The first prompt supplies a bounded goal/title; it can contain private text.

Checkpoints are written before turn/start and before accepting a tool decision.
Terminal events save UNVERIFIED/FAILED/PAUSED, never model-claimed task success.
Resume reads fresh account/catalog/quota and checks canonical project, thread ID,
provider, durability, runtime status, latest turn and effective native permissions.
An interrupted checkpoint remains outcome_unknown even if the backend reports a
completed turn. The user must inspect files/processes and acknowledge a fresh token
before sending new text. Nothing automatically replays the old prompt or command.
Existing correction counters survive; P10 workflow is not implemented by this task.

Deletion previews include root and spawned descendants, scanning active and archived
history with bounded pagination and all declared source kinds. Scope is read again
on exact, one-use confirmation. Separate descendant ModelMate records require their
own deletion first. Remote failure/unknown outcome keeps metadata and blocks new work
in that session. Confirmed remote success is checkpointed before local removal; an
ordinary local cleanup failure can retry without another remote delete. A missing
thread alone never proves successful deletion. No work files are removed or reverted.
Deleting the current session closes the chat. /cancel and new work expire delete tokens.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_lifecycle.py -v`: 18 passed.
- `python3 -m unittest discover -s tests -q`: 165 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests include an actual synthetic CLI exit/restart/resume/delete round trip, a
subprocess death after a RUNNING checkpoint, lock release, crash before/after tool
results, disconnect before turn response, wrong account/project, missing/legacy
thread, weakened resume permissions, correction counter preservation, exact/stale
tokens, changed subtree, active descendants, quota-exhausted deletion, partial
deletion and lost remote-deletion receipts. Existing multi-turn subprocess tests
now use temporary XDG state directories rather than the user's state directory.

Protocol reference: locally generated Codex v0.169.0 schemas for ThreadResume,
ThreadTurnsList, ThreadList and ThreadDelete, plus official request handler/tests:
[thread_delete.rs](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/app-server/src/request_processors/thread_delete.rs)
and [deletion tests](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/app-server/tests/suite/v2/thread_delete.rs).
Source/schema inspection and synthetic replies are not proof of live interoperability.

Limits: no real-account resume/delete inference was run. Native Codex state access
is still constrained in this development sandbox. The server has no expected-scope
delete parameter, so another client changing the subtree between the final read and
delete cannot be excluded. Remote success followed by a lost receipt can leave a
pending local record that requires explicit inspection; there is no automatic
missing-thread cleanup. A lost thread/start response can leave an unassociated
Codex thread; local metadata cannot recover its unknown ID. Filesystem fsync and
power-loss limits from P11 remain. P12 stays IN_PROGRESS until P10 workflow
integration and real-account evidence are available.

Suggested opt-in live check in a disposable project: open a manual live session,
send a synthetic recall marker, record only the local session ID privately, /exit,
reopen with --resume, ask for the marker, and then /delete plus its confirmation
token. Confirm the session disappears locally and in Codex, with a sentinel work
file unchanged. This uses subscription quota; do not commit prompts, IDs or traces.

### P12 opt-in session verification harness — MOCK_VERIFIED

Added `python3 verify.py --run-live --probe-sessions MODEL`. It reuses the runtime's
LiveChatConnection, SessionStore, ChatShell and confirmed-delete flow, with two
separate App Server processes and a private temporary project/state store. The
second prompt contains no recall marker. Both turns request low effort and pass
the ordinary account/catalog/quota checks. No API-key fallback or billing changes.

The explicit command authorizes automatic confirmation only when the preview
contains exactly the harness-created thread and scratch project, without any
descendants. A changed sentinel/extra file, failed recall, unexpected tool,
incomplete turn, delete failure or lingering history entry prevents a success
report. Success requires metadata removal, absence from both active and archived
listings across all declared source kinds, and an unchanged sentinel after deletion.
Runtime and verifier SHA-256 hashes identify the tested files. JSON output excludes
account identity, thread/session IDs, paths, prompts and recall markers.

Failure retains scratch metadata/files and prints the failed phase and scratch path
on stderr for local inspection. Active turns are interrupted with a bounded wait
before closing the connection and store; no retry or replay is performed. The
harness never accepts a tool approval. Native permitted tools can start before
observation, so detection is not a universal no-tools guarantee. Failed checks do
not automatically delete their remote thread. Do not commit retained scratch state.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_session_probe.py -v`: 10 passed.
- `python3 -m unittest discover -s tests -q`: 175 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests use real synthetic JSONL server subprocesses sharing temporary state across
reconnects. They cover exact-scope deletion, redacted reports, a second prompt
without the marker, recall/turn failures, descendants, failed deletion retaining
its checkpoint, non-appServer history listings, sentinel changes, unexpected tool
denial/interruption, timeout without replay, and opt-in/exclusive-mode validation.
The source-kind list is shared with the runtime's deletion scope enumeration.
No real inference was run during harness development. Subsequent user-run evidence
is recorded below; wider lifecycle/permission gates remain separate.

### P12 manual reconnect/recall/delete — scoped LIVE_VERIFIED

On 2026-11-17 the user ran, from their normal Terminal:

```bash
python3 verify.py --run-live --probe-sessions gpt-6.1-sol
```

Reported results: sessionResume, contextRecallAfterReconnect, confirmedDeletion,
localMetadataDeleted, threadAbsentFromListings and sentinelUnchanged all `passed`.
Requested model/effort: `gpt-6.1-sol` / `low`. Reported backend model remains null;
no actual-dispatch claim is made.

The supplied file hashes match the local files and PR #3 head `5647656` exactly:

- Runtime SHA-256: `b113e5be95fa51b5a27dc8404cbe50f0f056b09f9c110f28e64571d96334c80c`
- Verifier SHA-256: `6d90d9781067a994875351624580c656ca138de3bac8eb3bc86806f4cf707242`

Evidence source: the user's supplied sanitized JSON report; no additional inference
was run to record it. Account identity, thread/session IDs, prompts, paths and raw
traces are not stored here. This verifies two synthetic turns across separate
connections and one scratch-thread deletion with unchanged sentinel. It does not
verify crash recovery, all tool paths, automated workflow, actual backend dispatch
or complete service-side data erasure. P12 remains IN_PROGRESS for P10 integration
and remaining lifecycle evidence. The scoped manual-chat PR can now be assessed
for merge with its existing offline checks and these live results.

Documentation-only follow-up: file hashes matched; `git diff --check` passed.
No repeated inference or full test rerun was needed. Next work: workflow/controller
development under P10's permission gates, with live crash/tool-path checks tracked
separately rather than inferred from this happy-path result.

## P10 offline workflow controller — MOCK_VERIFIED; full task IN_PROGRESS

Added WorkflowController to the single-file runtime. It validates a fixed task
plan, creates task/step/attempt/evidence IDs, and owns step position, attempts and
cycles. A RUNNING snapshot reserves an attempt slot before dispatch; the returned
descriptor explicitly says `execution: not_dispatched` and grants no tool access.
The controller opens no connection, process or file and is not wired into ChatShell
or LiveChatConnection. P09/classifier gates are not bypassed to enable auto mode.

Host API and lifecycle:

- `request_attempt` checks a fresh timestamped quota snapshot with account pinning,
  resolves the supplied catalog/role bindings through ModelApprovals, and counts a
  slot only after model approval. All three model modes retain existing P07 rules.
- `answer_model` accepts exact UI tokens. `revise_step` can change only the current
  objective/role/effort/reason. It keeps step ID and budget, rejects changed task
  criteria/checks/structure and invalidates model grants/tokens immediately.
- `finish_attempt` accepts a host terminal event. Completion enters CHECKING;
  interruption pauses with unknown outcome; execution failure is FAILED. None
  of these events means that the task's checks passed.
- `record_check` binds evidence to the active attempt and exact check index.
  Observed integer exit codes determine test/lint results. Source checks require
  an HTTP(S) URL and a verified claim finding from the trusted source checker;
  URL presence is not treated as fact verification. Manual/rubric results must
  come from a trusted manual check. `model_review` is recorded as unknown and
  cannot turn a model assertion into a passed test or human/source verification.
- `evaluate_attempt` advances a fully checked step, offers a bounded correction
  after known failure, or marks incomplete/unknown checks UNVERIFIED. One initial
  attempt plus two corrections exhausts a step's cycle. A fourth attempt cannot
  start without the user's exact pause token and explicit continue choice.
- `answer_pause` retains old cycles and a user-choice/budget-extension ledger.
  It cannot resume an active unknown turn. `observe_quota` blocks new work when
  quota/account state is unsafe; the future executor must issue the native
  interrupt and feed back its terminal event. The pure controller does not do I/O.
- `finish_task` requires trusted checker coverage of every task success criterion
  using accepted evidence IDs from the current successful step attempts. Missing
  coverage is UNVERIFIED; fabricated/stale/failed-attempt evidence is rejected.
  Snapshots retain the criterion/evidence mapping and return defensive copies.

Shared plan validation now requires a strong review after the last high-risk
non-review step. A review before the risky work no longer satisfies the gate.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_workflow.py -v`: 23 passed.
- Additional routing regression rejects strong review before high-risk work.
- `python3 -m unittest discover -s tests -q`: 199 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Checks cover simple code, plan/implement/strong-review ordering, document rubric
and source checks, per-step correction budgets, explicit cycle extensions, rename
and scope-reset attacks, model/effort gate changes, stale tokens, paused checks,
quota exhaustion during work, unknown/stale/account-changed quota, missing models,
unknown/model-claimed checks, actual synthetic Python subprocess exit codes,
duplicate/stale evidence, criteria coverage, large Thai JSON plans without ASCII
re-encoding inflation, and no process creation by the core.

Limits: these are trusted in-process controller callbacks, not a security boundary
against Python callers. Production adapters must bind exit codes, terminal events,
manual choices and verified source findings to actual actions; feeding parsed model
JSON into these methods would violate the contract. Role bindings remain explicitly
supplied; no live model ranking is added. Clarification resolution, broader replan,
model/tool execution, automatic check adapters, CLI workflow commands, durable
workflow/ledger restore and live crash recovery are not implemented here. Do not
reset a task/controller on model request to evade its budget. No live inference
was run. Next work is the gated host adapter/CLI and persistence integration;
P10 and workflow-specific P12 remain IN_PROGRESS.

## P10/P12 durable workflow checkpoints — MOCK_VERIFIED

WorkflowController now has explicit checkpoint export/restore and optional trusted
persistence binding through `SessionStore.workflow`. Unattached controllers remain
in-memory and perform no I/O. The context holds the existing Linux session writer
lock for its entire lifetime and persists each transition before returning it to
the host. In particular, the reserved attempt is durable before the inert dispatch
descriptor is returned. Storage errors propagate; a host must stop instead of
dispatching after a failed write. Exiting the context closes that controller's
attachment; use a newly restored controller rather than continuing a stale object.

Session schema v3 extends v2 with a nested schema-v1 workflow checkpoint. It stores
the validated plan, original task/step IDs, attempts/cycles, active attempt, accepted
evidence, criterion coverage, user choices and budget-extension ledger. Original
model baseline and account fingerprint are retained. Approval grants, pending model
requests, approval/pause tokens, raw account ID and tool permissions are excluded.
Evidence result derivation is shared between newly observed and persisted checks.

Checkpoint validation replays ledger ordering, cycle extensions and attempt counters,
checks unique identities and exact field sets, matches evidence to the correct
attempt/check and rejects inconsistent result/exit-code pairs. A budget extension
requires its preceding explicit continue choice. Session summary fields must match
the workflow; deletion receipts may override the top-level deletion/pause state.
Save rejects task/step/baseline replacement, criterion/structure changes, ledger
truncation, active-attempt loss, status rollback and removal of existing evidence.
This detects corrupt/inconsistent state; it is not cryptographic protection from
the same local user deliberately rewriting an entire state file.

Restore requires a fresh allowed quota snapshot, matching account and a still
supported original baseline. Current catalog/role policy is supplied by the host.
Temporary model grants are rebuilt empty. Nonterminal workflows restore paused
with fresh tokens, not dispatches. Running attempts retain their IDs and consumed
slots and require a native terminal event before continuing. Completed attempts
can continue CHECKING after an explicit choice, without another model turn.
Exhausted budgets remain exhausted until an explicit new-cycle choice. Cached
DONE restores UNVERIFIED and preserves its historical evidence/coverage; the host
must inspect current files/processes and reassess evidence before asserting DONE.
FAILED/CLARIFYING retain their phase. No pending model/tool action is replayed.

V1/v2 records remain readable and unchanged by read/list operations. Only explicit
workflow attachment upgrades a bound v2 record to v3. Unbound/deleting sessions,
wrong accounts, unsafe quota and unknown existing manual outcomes cannot attach.
Manual LiveChatConnection resume rejects workflow records before any thread RPC,
so it cannot discard counters by treating them as ordinary chat. Confirmed deletion
of workflow metadata still follows the existing preview/token/remote-receipt flow.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_workflow_persistence.py -v`: 25 passed.
- `python3 -m unittest discover -s tests -q`: 224 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests include actual subprocess death both after reserving an attempt and after
recording an observed synthetic check result; both restore the original counters.
Other checks cover exhausted/extended cycles, user choices, pending approval/token
expiry, partial/out-of-order checks, multi-step/source evidence, terminal phases,
no raw account storage, unknown quota/account/catalog, corrupt/unsupported schema,
metadata/counter/evidence tampering, task/ledger/status rollback, disk failure before
dispatch, failed extension save, lock ownership, closed attachments, legacy reads,
manual-resume refusal and confirmed deletion. All fixtures/account IDs are synthetic.

Limits: this is the persistence/host API milestone, not a user-facing workflow CLI
or live executor. The existing trusted-callback contract still applies: metadata
cannot establish whether a host's manual/source finding or exit code is truthful,
or whether files have changed since evidence was collected. Native thread/turn
reconciliation must be wired by the future host adapter. These process-death tests
do not verify native Codex crash recovery or hardware power loss. Existing atomic
replace/fsync limits remain. Full checkpoints share the session's 1 MiB cap and
allow at most 4,096 ledger events; oversize fails without dropping history. No
credentials, transcript, network call or live inference was added. P10/P12 remain
IN_PROGRESS; next work is the explicit workflow UI/controller host integration,
with execution/check adapters and their permission gates still separate.

## P08/P10 workflow host UI — MOCK_VERIFIED

ChatShell and run_chat now accept an explicit WorkflowController and optional
trusted workflow_action callback. This is a host API milestone: the ordinary CLI
and `--live` paths remain manual, and no workflow loading flag is introduced.
Passing a native backend or legacy manual send callback alongside a workflow is
rejected, so existing native execution is not implicitly enabled for workflows.

The UI renders the plan, current step, cycle/attempt budget, planned model/effort,
active requested selection, per-check results and recorded criterion coverage.
Requested/planned models are not described as backend dispatch telemetry. All
display text uses the existing terminal-control filter. Ordinary text is not
forwarded into a classifier or executor while this prototype workflow UI is bound.

Host/UI contract:

- `/workflow` and `/status` read the bound controller without starting work.
- `/next` is allowed only in READY and sends `{action: next, task_id}` to the
  trusted callback. Without a host, no attempt is reserved. The host must obtain
  current quota/catalog/bindings and use the controller's request_attempt before
  any future dispatch. The UI ignores callback return values as completion claims.
- `/approve`, `/decline` and `/pause` route exact tokens to the current model gate;
  `/continue`, `/revise` and `/pause` route only matching workflow pause tokens.
  Approval and continuation never invoke next automatically. No tool grant is
  created. Revision requests pause for the host; they do not rewrite the plan.
- `/mode` uses a controller method that invalidates old grants/tokens, preserves
  budgets and persists the change when the controller is durably attached.
  Active/finished attempts cannot change mode. Unsupported manual session/model
  commands do not fall through to an unrelated backend.
- `/cancel`, Ctrl+C, `/exit` and EOF pause pending choices or request host cancellation
  for a running attempt. Host cancellation is attempted before persisting a running
  pause, so a storage failure cannot prevent the interrupt request. An acknowledgement
  alone never clears active state. A five-second unconfirmed-stop deadline exits
  with unknown outcome; the controller retains its active attempt/budget.
- A trusted host may signal `{type: workflow_changed, task_id}` after mutating its
  controller from a real terminal/check event. The signal carries no state or evidence
  fields. Foreign IDs, extra fields, replacement plans, legacy completed/stopped and
  tool approval events are rejected in workflow UI mode. Model text is display data.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_workflow_ui.py -v`: 17 passed.
- `python3 -m unittest discover -s tests -q`: 241 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Checks cover plan/status without execution, missing-host refusal, explicit model
approval, stale tokens on mode change, correction-limit choices and retained cycles,
no auto-next after approval, revision/pause, EOF during a synthetic running attempt,
terminal confirmation versus acknowledgement, unconfirmed timeout, cancellation on
storage failure, spoofed completion/foreign events, inert callback return values,
read-only permissions, refused native/manual mixing, terminal text filtering and
persisted UI choices. An actual synthetic subprocess runs the selector/EOF/event
path; no real Codex or inference is used.

Limits: callbacks and controller mutation remain trusted in-process APIs. This is
not a sandbox for arbitrary Python callbacks. Hosts must correctly report native
events, perform fresh preflight checks, bind actual check evidence and handle
disconnect/interrupt outcomes. No native workflow executor, check adapter, classifier,
clarification input, broad replan editor, workflow CLI loading/resume entry point or
automatic multi-step loop is added. P08/P10/P12 remain IN_PROGRESS. Next work is
the gated host/execution and explicit entry-point integration; source/mock evidence
must not be presented as live workflow verification.

## P10 workflow host and executor observations — MOCK_VERIFIED

Added WorkflowHost as the trusted adapter between WorkflowController, the injected
UI and transport callbacks. It has no built-in native transport, subprocess runner,
tool approval handler or CLI entry point. Existing native/manual mixing guards
remain in place. All checks below used synthetic callbacks/protocols, not Codex.

Dispatch contract:

- A host preflight callback returns the current quota snapshot/timestamp, catalog
  and reviewed role bindings. The controller's quota/account/model gates still run
  before a slot is consumed. Preflight failure pauses without dispatch. Ultra
  delegation remains unsupported and consumes no slot.
- The dispatch callback receives a defensive copy of the inert descriptor only
  after the controller's durable attempt checkpoint succeeds. It returns exactly
  a thread/turn identity before delivering events. Reentrant events must be queued
  by the transport; reused/invalid bindings and unknown start outcomes fail closed.
- Cancel invokes the trusted interrupt callback at most once for the known binding.
  An acknowledgement does not finish the attempt. Bound-turn timeout, disconnect
  or malformed protocol pauses with unknown outcome and never replays dispatch.
- A trusted recovery adapter can reconcile inspected identity/terminal status with
  the original active attempt, retaining its consumed slot. A completed cached
  attempt can continue checks without another model turn. Native inspection,
  current-file reassessment and account/source authenticity are host obligations;
  the adapter does not infer identity from model text or automatically reconnect.

Evidence contract:

- `configure_check` registers an exact host-reviewed command and absolute cwd for
  an existing test/lint criterion before the attempt. It grants no tool permission
  and does not run a command. The producer must enforce native sandbox/approval
  policy independently; current workflow approval requests interrupt/refuse rather
  than receiving accept.
- `observe_native` accepts only observations from the trusted executor channel.
  Matching thread/turn, command item identity, observed start, command and cwd are
  required. Unrelated successful commands and assistant text fill no checks.
- Identical duplicate completions are idempotent. Changed command/cwd/type, missing
  starts, conflicting results, repeated check invocations within one attempt and
  contradictory terminal events pause rather than silently accepting a later pass.
  Native tools may already have started before observation; this is not a no-tools
  sandbox or proof that all internal tool loops are bounded.
- `/check` records matched observations only after a confirmed completed turn, then
  evaluates that attempt. Declined/missing exit codes remain unknown; nonzero
  observed exits fail. Raw stdout/stderr, commands and cwd are not copied into
  evidence. Missing manual/source adapters leave UNVERIFIED rather than inventing
  findings. Task DONE still requires an explicit trusted criterion-coverage check.
- Transport bindings, approved check specifications and unrecorded observations
  are process-local. Recovery does not reuse another attempt's cached observations.
  Durable native thread/turn binding integration remains future work.

`run_chat(..., executor_stream=...)` multiplexes this channel only for an explicitly
bound WorkflowHost; it is separate from display-only model text and UI change
signals. The host drives same-task UI updates on the owning loop and has a bounded
turn deadline. Parse/EOF failures invalidate the host and request interruption.
No backend/model event can directly declare workflow DONE or grant tool access.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_workflow_host.py -v`: 25 passed.
- `python3 -m unittest discover -s tests -q`: 266 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Checks cover exact observations versus unrelated commands, foreign thread/turn IDs,
missing starts, changed metadata/types, duplicate/conflicting results, declined
checks, correction limits, explicit model approval/next, unknown start recovery,
cancel acknowledgement, timeout/disconnect without replay, unsupported tool approval,
stale binding/check-cache isolation, reentrant events, ultra refusal, fresh preflight,
and a durable checkpoint before the dispatch callback. Real synthetic subprocesses
exercise separate executor-pipe events, UI `/check`, EOF and invalid JSON. Raw
private-output markers never become evidence or Terminal output.

Limits: this is still a trusted in-process API and observation checker, not a
security boundary against arbitrary Python callbacks or dishonest producers.
Exact command matching does not prove the chosen command meaningfully tests a
criterion; the host must review specifications and source observations. Transport
callbacks must bound their own start RPC timeouts, enforce permissions and queue
events until binding. No model inference, live workflow or private-web gate was
run or marked passed. Native transport, durable native bindings, workflow loading
entry point, full tool approval/check adapters and classifier remain pending.
P08/P09/P10/P12 remain IN_PROGRESS.

### Local session/workflow inspection (2026-11-17, uncommitted working tree)

- `python3 -m unittest discover -s tests -p test_local_inspection.py -v`: 7 offline tests.
- ตรวจ missing store ไม่สร้าง directory; read-only mutations ไม่สร้าง lock;
  checkpoint bytes/mtime ไม่เปลี่ยน; project isolation, symlink/corrupt metadata
  ปฏิเสธโดยไม่แก้ไฟล์; CLI ใช้ได้เมื่อ PATH ไม่มี Codex และปฏิเสธ option ที่ชนกัน
- RUNNING แสดงผลปัจจุบัน unknown; DONE แสดงว่าเป็นผลเก่า ไม่คืน grants/token
  ไม่ restore controller ไม่ทดสอบ live inference หรือ native workflow execution

Publication preflight (2026-11-18): full offline suite 273/273 passed;
`python3 -m py_compile modelmate.py doctor.py verify.py` and
`git diff --check` passed. No live inference was run.

### PR #5 recovery evidence fix (2026-11-18)

Restored active and accepted step evidence is now stale in memory. The controller
blocks attempt evaluation and task completion until the trusted host explicitly
revalidates each saved check against a known matching current result. Terminal
reconciliation alone does not clear this requirement. Confirmations do not survive
another restore; persisted evidence/ledger are retained unchanged. Mismatched or
unknown results remain blocked; no implicit tool execution or model retry occurs.
Regression coverage checks partial-check recovery, terminal-only reconciliation,
restored DONE, rejected mismatches, and revalidation expiry after another restore.

Validation: 91 targeted workflow tests and 274/274 full offline tests passed.
Runtime/doctor/verifier compilation and `git diff --check` passed. No live inference.

### Experimental native workflow transport (2026-11-18)

- Schema inspection: installed `codex app-server generate-json-schema --out ...`
  ran locally without inference. Inspected thread/start response permission fields,
  turn/start response and turn/interrupt parameters; generated files remain outside repo.
- `tests/test_native_workflow.py`: 10 synthetic subprocess tests cover queued events
  before start response, exact requested model/effort, same-thread corrections,
  auth/quota/permission failures, approval decline+pause, missing turn ID/disconnect,
  duplicate dispatch rejection, unsupported recovery, bounded event queue and
  native stdout/stderr multiplexing through the real Terminal loop.
- Public native workflow CLI remains disabled. Host API uses ephemeral threads;
  durable native workflow recovery and approval acceptance are not implemented.
  No no-tools classifier or private-web boundary is claimed. Requested models are
  not backend dispatch telemetry. No live inference or quota was consumed.

Validation: 10 targeted native workflow tests and 284/284 full offline tests
passed; runtime/doctor/verifier compilation and `git diff --check` passed.

### PR #6 — assistant answer display regression (2026-11-18)

The native transport previously dropped assistant messages. Two new regression
tests failed against the old implementation (zero displayed answers), then passed
with completed-message forwarding. UI events carry text only after current
thread/turn checks. Per-turn item IDs suppress duplicate completions; deltas do not
repeat the answer. A new turn may reuse an item ID. Foreign and post-terminal
messages do not display. Terminal/bidi controls are filtered by existing ChatShell.

Text claiming tests passed or DONE leaves checks empty and the turn RUNNING until
an actual terminal event. No assistant text is copied into workflow checkpoints.
The subprocess Terminal-loop test now asserts that an answer is visible once.

Validation: 14 native workflow tests and 288/288 full offline tests passed;
`python3 -m py_compile modelmate.py doctor.py verify.py` and `git diff --check`
passed. No live inference was run.

### Native workflow opt-in verifier (2026-11-18)

Command: `python3 verify.py --run-live --probe-workflow MODEL` (requested effort low).
At most four synthetic turns; no inference without --run-live, no hidden retry.
Uses the real NativeWorkflowConnection/WorkflowHost/ChatShell path against Codex
only when explicitly opted in. It does not read the user's project for prompts.
Only the harness-created scratch sentinel is targeted by a write-denial test.
No tool approval acceptance or sandbox expansion is implemented.

Eight offline test methods use synthetic subprocess App Servers: four-turn happy
path, no approval (unverified), changed sentinel (failed), recall mismatch, cancel
race (unverified), timeout/failed turn without replay, auth rejection, and CLI
opt-in/exit behavior. Reports omit raw answers, nonce, account/thread IDs and paths;
include runtime/verifier hashes and requested selection with reportedModels null.
Scratch path appears only on stderr when inspection is required. Cleanup waits for
terminal confirmation where possible; uncertainty retains scratch and never retries.

The disconnect result covers a local host guard only. It does not verify dropped
network recovery, all command/patch/tool paths, backend dispatch or remote erasure.
Live results are recorded below. Auto routing and public native workflow CLI
remain gated; this narrow probe does not pass every native permission gate.

Validation: eight targeted workflow-probe tests and 296/296 full offline tests
passed; `python3 -m py_compile modelmate.py doctor.py verify.py` and
`git diff --check` passed. Help-only invocation without --run-live was checked.
No live inference was run.

### User-supplied native workflow live result (2026-11-18)

Historical pre-review report (partially superseded below). The user ran:
`python3 verify.py --run-live --probe-workflow gpt-6.1-sol`
and supplied the JSON report. All six checks reported passed: answerDisplay,
contextRecall, approvalDenial, sentinelUnchanged, cancel, disconnectGuard; phase
finished. Requested gpt-6.1-sol/low; reportedModels null. Process exit code was not
provided. This is user-supplied evidence, not an independent agent-run live test.

Runtime SHA-256: `d820c340a7d8cb2e7b1b431c7d41ed2aead539a8aebfb9d9f8fee31b3c36a914`
Verifier SHA-256: `e00dadc70142de5807488f0df43719aab44c563281f25ebdcb39a852b906c91f`
Both hashes match the local files at commit `326a819`.

Scope remains at most four synthetic turns in ephemeral threads. Disconnect guard
is local only; not network-drop recovery, all tool paths, backend dispatch telemetry
or service-side erasure. Public workflow CLI/auto routing and other permission/web
gates are not enabled by this result. The pasted Terminal output had an extra
`hello` before the JSON. No literal hello or matching print path was found in the
verifier; its origin and whether it was stdout, stderr or Terminal echo are unknown.

### PR #7 — verifier false-positive fixes (2026-11-18)

Review demonstrated two false positives: the old probe still passed when disconnect
was replaced with a no-op, and when ChatShell dropped text events. Both new
regression tests failed against the old verifier and passed after the fix.

Answer comparison now reads the text written by ChatShell during each text event,
not the event payload. Plan/status output is excluded. The disconnect probe resumes
the synthetic controller to READY after confirmed interruption, then checks that
submission is refused before preflight/dispatch. Both callbacks are replaced with
tripwires, so a broken guard cannot start a fifth live turn. A cancellation race
leaves disconnect unverified instead of testing from an unsuitable state.

The earlier user-supplied six-pass JSON remains recorded as historical output at
its exact hashes. Its answerDisplay and disconnectGuard claims are not accepted as
live verification of those capabilities. The fixed verifier requires new opt-in
live evidence; no new inference was run as part of this fix. Other earlier results
remain scoped to their original tested version and synthetic actions.

Validation: 10 targeted probe tests and 298/298 full offline tests passed;
runtime/doctor/verifier compilation and `git diff --check` passed.


### Fixed verifier — user-supplied live rerun (2026-11-18)

Scoped LIVE_VERIFIED: after the PR #7 fixes, the user ran
`python3 verify.py --run-live --probe-workflow gpt-6.1-sol` again and supplied
JSON with answerDisplay, contextRecall, approvalDenial, sentinelUnchanged, cancel
and disconnectGuard all passed; phase finished. Requested gpt-6.1-sol/low;
reportedModels null. Process exit code was not provided. Evidence was supplied by
the user, not independently rerun by the agent.

Runtime SHA-256: `d820c340a7d8cb2e7b1b431c7d41ed2aead539a8aebfb9d9f8fee31b3c36a914`
Verifier SHA-256: `acd3db1d9fe448165e90556fbe68d2c1626a418561dfa16ec3e76d58698a21cd`
Both match local files at commit `2679ca7`. This rerun supplies scoped evidence
for the corrected rendered-answer and READY-state disconnect tests; the earlier
verifier's false-positive claims remain superseded.

Scope: at most four synthetic turns in ephemeral threads. Disconnect guard is
local only, with preflight/dispatch tripwires. It does not verify network-drop
recovery, all tool paths, backend dispatch telemetry or service-side erasure.
No public native workflow CLI, auto routing, native recovery or private-web gate
is enabled by this result. This evidence update changes documentation only;
`git diff --check` passed; no additional inference was run by the agent.

### Explicit-plan CLI — offline increment (2026-11-18)

Seven new tests cover offline preview/cancel without backend startup, invalid or
oversized plans/bindings, unsupported checks/clarifications, CLI option conflicts,
manual evidence/criterion mapping, rejection of manual test/lint results, and a
real subprocess CLI loop with a fake native App Server. The loop confirms START
and subsequent /next input are both preserved, answer checks reach DONE only with
explicit accepted coverage, and the on-disk checkpoint validates as DONE.
No live inference run. Native workflow recovery and automatic routing remain gated.

Validation: seven targeted entry tests and 305/305 full offline tests passed;
runtime/doctor/verifier compilation and `git diff --check` passed.


### P14 local explicit-workflow statistics (2026-11-18)

Final CLI summary reports elapsedSeconds from preview start through session close
(including user wait), attempt count and distinct requested model/effort pairs.
reportedModels and tokenUsage are null, never estimated from prompts or plan roles.
The summary does not include task text, answers, account IDs or approval tokens.
Eight targeted entry tests, including statistics/count/clock checks and an actual
fake-server CLI exit summary, passed. Full offline suite: 306/306 passed; runtime,
doctor and verifier compilation plus git diff --check passed. No live inference.


### User-supplied explicit-plan CLI transcript and usability fix (2026-11-18)

User supplied a live explain-lists CLI transcript: confirmation, one native attempt,
answer display, explicit manual pass, accepted step evidence and final statistics
were observed. The user entered the literal EVIDENCE_ID placeholder; the controller
correctly rejected it. Final task criteria were not accepted; exit paused the task.
This is partial live evidence, not a successful DONE or native resume test. No
runtime/verifier hashes or process exit code were supplied. No raw transcript,
session IDs, evidence UUIDs or approval tokens are stored here.

Usability fix: /finish now accepts explicit STEP.CHECK refs (e.g. 1=1.1) resolving
only accepted completed-step evidence; UUID syntax remains supported. Placeholder
errors explain the reference form. Completed attempts display CHECKING for the
current step without changing the durable controller ledger. Successful host
/next and /check commands no longer render duplicate state blocks. No extra live
turn is required to reproduce or regression-test these UI changes.

Validation: 10 targeted workflow-entry tests and 308/308 full offline tests
passed; runtime/doctor/verifier compilation and git diff --check passed.
No additional live inference was run.


### User command/cwd test/lint bindings — offline increment (2026-11-18)

Ten new test methods cover config schema/size/duplicates/indices/cwd validation,
no execution while loading, required bindings before backend startup, CLI argument
wiring, exact command propagation into turn/start, accepted tool evidence saved to
checkpoint, failure budget exhaustion, successful unrelated commands remaining
UNVERIFIED, and registration for later test/lint steps. Native observations are
produced by fake App Server subprocesses, not actual command execution/inference.
User's earlier full-suite result (308 tests, OK confirmed in follow-up) supports
the prior runtime only; it does not verify this command-binding integration live.
No new live inference has been run. Runtime permissions remain read-only/on-request.

Validation: ten targeted command-binding tests and 318/318 full offline tests
passed. The sample command was also run locally: test_models.py 12/12 passed.
Runtime/doctor/verifier compilation, offline sample preview and git diff --check
passed. No new live inference or native command-tool live test was run.


### Early /check user feedback and deferred-check fix (2026-11-18)

User supplied a live command-check CLI transcript: /check arrived during RUNNING
and was rejected; turn later became CHECKING, but /finish was attempted without
another /check. No command evidence was accepted, and exit paused the workflow.
The assistant claimed 12 tests/exit 0, which is not sufficient trusted evidence.
This transcript is partial evidence only, not a completed command-check live test.
No raw session IDs, tokens or transcript are stored here; hashes were not supplied.

For tool-only steps, an explicit early /check now waits for the same attempt's
confirmed terminal event, then evaluates once. Duplicate requests do not add work;
UI text alone never triggers evaluation. Cancel/exit or paused/failed/foreign
attempt state clears the request. Manual/rubric still require explicit post-turn
verification. No new model turn or automatic /next is introduced.
Regression tests cover early/repeated /check, no extra dispatch, queued cancellation,
manual rejection and unrelated successful commands remaining UNVERIFIED.

Validation: 13 command-binding tests and 321/321 full offline tests passed;
runtime/doctor/verifier compilation and git diff --check passed. No live rerun.


### Confirmation input hardening (2026-11-18)

User reported visible START followed by cancellation before backend startup. The
transcript alone does not identify the raw bytes/cause; no inference occurred in
that reported path. The old byte reader rejects a leftover empty line and literal
bracketed-paste wrappers. The new shared reader skips empty newline-terminated
lines (never treating them as consent), accepts a complete single-line wrapper
around exact START, rejects EOF/invalid/incomplete/oversized input, and preserves
following workflow commands. A real pseudo-terminal subprocess test confirms blank
line + START + /next behavior; file-backed tests cover wrappers/CRLF and denials.
No claim is made that the user's Terminal cause has been conclusively reproduced.

Validation: 13 targeted workflow-entry tests and 324/324 full offline tests
passed; runtime/doctor/verifier compilation and git diff --check passed.
No live inference or new backend startup was required for the input tests.


### Live command-check UNVERIFIED and diagnostic/matcher increment (2026-11-18)

User supplied a later live transcript: backend completed and /check ran at CHECKING,
but the controller reported checks_unavailable/UNVERIFIED. Assistant text claimed
12 tests and exit 0, which is not trusted tool evidence. Final task remained paused;
no DONE or actual-dispatch claim is recorded. Raw command observations were not
retained in that build, so exact mismatch cause cannot be recovered from the pasted
transcript. The locally generated item schema has string command/cwd and integer
or null exitCode, but does not identify this run's actual values. No user IDs/tokens
or raw transcript are copied into this evidence record.

Matcher now supports a single explicit absolute bash/sh -c/-lc argv wrapper only
when its inner command equals the registered code literally, with identical cwd.
Extra argv, changed flags, different paths, chained/changed inner commands and
shell-token normalization are rejected. This does not prove the wrapper caused the
user's failure. Missing matches now record unknown tool evidence with bounded-field
counts (starts/completions/command mismatches/cwd mismatches) and show diagnostics
without raw commands/paths/output. No model text is interpreted as command evidence.

New tests cover accepted literal-inner wrappers, rejected extra commands/argv and
quoting changes, redacted unknown diagnostics persisted in checkpoints, and a
wrapped-command fake App Server through deferred /check to explicit final coverage.
Full offline suite 328/328 passed; runtime/doctor/verifier compilation and
`git diff --check` passed. No new live inference was run. Native command integration
remains not live-verified; a future single-turn run can distinguish missing events
from command/cwd mismatch without repeatedly guessing.


### Full-TTY confirmation regression (2026-11-18)

User's input-only check accepted typed START, but a later full CLI run again rejected
visible START before backend startup. Its raw bytes are unknown. An added full CLI
pseudo-terminal test reproduced rejection for bracketed paste containing START plus
an embedded newline; typed START passed. This demonstrates a receiver defect, not
proof that the user's exact input had those bytes.

Interactive sys.stdin/sys.stdout TTYs now activate standard-library readline and
use input(); non-TTY streams retain the bounded byte reader and no-read-ahead
behavior. Full CLI TTY tests stop at a stub backend constructor (no Codex process or
inference) and verify typed START and multiline paste reach that boundary, while
CANCEL never does. Invalid confirmation shows counts/flags only, never raw input.
Existing piped full CLI/fake App Server and EOF/invalid input tests remain in place.

Validation: 15 targeted workflow-entry tests and 330/330 full offline tests
passed; runtime/doctor/verifier compilation and git diff --check passed.
No new live inference was run.


### User-supplied successful command-check CLI run (2026-11-18)

Scoped LIVE_VERIFIED for the single-step test_models.py happy path. The user ran
the explicit-plan CLI with examples/check-model-policy.json, its separate command
bindings and requested gpt-6.1-sol/low. Transcript shows START accepted, one attempt,
backend terminal completion, /check accepting a pass test with tool evidence,
/finish mapping criterion 1 to ref 1.1, DONE and clean /exit retaining DONE.
The user did not use /verify to override the tool check. Reported models and token
usage remained null. Total session time includes user wait, not model-only latency.

This is user-supplied transcript evidence, not an independent agent-run live test.
No runtime hash, raw native events, disk checkpoint inspection or process exit code
was supplied. Local documentation baseline is fca9151 with runtime SHA-256
`7c3988d5dca5c52a30f65c58da7b67acbfee6baa0e91369008f20cbc2d7a22ae`;
these identify the local candidate, not an independently established hash of the
user's execution. Session IDs, evidence UUIDs, tokens and raw transcript are omitted.
The transcript does not establish whether shell wrapping caused earlier mismatches.

Scope excludes native recovery, all tools/permission paths, forced retry scenarios,
backend model dispatch telemetry and private-web isolation. These gates remain open.
The earlier zero-attempt startup/exit report also supports the TTY confirmation happy
path, without establishing the raw cause of past rejected input. No additional live
inference or rerun was performed by the agent. Documentation-only update; diff check
passed. Prior offline suite at this runtime: 330/330 passed.


### Durable workflow/recovery offline increment (2026-11-18)

New explicit CLI workflows use ephemeral=false; bare native host API calls and the
older workflow probe keep ephemeral=true. A schema-v3 checkpoint and writer lock
exist before thread/start; no implicit user-choice event is fabricated to bind a
thread. Attempt reservation clears the prior native turn ID atomically. Native ID
binding is saved only after a valid, non-reused turn/start response. Durable resume
reuses thread/read, thread/turns/list and thread/resume under existing native policy.

Eleven new native recovery tests run separate fake server processes with synthetic
persisted native state. They cover context through actual display writes, task/step
identity and counters, stale manual evidence requiring revalidation, missing model
grants, writer locks, active/interrupted turns, wrong account/project/provider,
old ephemeral threads, changed permission/history/preview data, unknown start and
native binding-save failure with no replay. CLI preview is read-only; execution
uses the saved plan. Earlier TTY tests now use an isolated state home before their
stub backend, since metadata setup precedes process startup.

Six new resume-probe tests cover two-turn reconnect/DONE, redacted retained scratch,
recall mismatch with no retry, dropped UI text, detecting a bypassed stale-evidence
gate, rejecting ephemeral recovery, and explicit live opt-in/exit status. The shared
answer-capture helper observes UI writes, preserving the existing verifier's checks.
The two-turn probe uses synthetic manual facts; it is not a no-tools security gate.

Public resume is limited to manual/rubric plans; no manual tool-result override.
Tool checks require new trusted observations and are not resumed through the CLI.
Durable scratch/native threads are retained by the new probe (no deletion claim).
No new live inference has been run; previous live reports apply only to their
recorded versions and scopes. New native resume is not yet LIVE_VERIFIED.

Validation: 11 targeted native-resume tests, 6 targeted resume-probe tests and
347/347 full offline tests passed. Runtime/doctor/verifier compilation, both CLI
help paths and git diff --check passed. No live inference or real native reconnect
was run by the agent. Resume command-check revalidation remains unsupported.


### Resume probe first-turn false failure and event classification fix (2026-11-18)

User reported phase first_turn with durableResume failed; reconnect was never
attempted. Supplied runtime SHA-256
`f3ee087dea800e552937ee9b1e8ba121ee31d2193d518797fc4e5278509fef4c`
and verifier SHA-256
`e8871f28ef9040dad46d8d217505c53e532e4228fb1f1537464509d2c200c36c`
match local c41a9bd files. Targeted retained scratch metadata was inspected read-only:
active attempt completed, native binding present, no accepted checks. Sentinel was
unchanged. Only the corresponding native rollout was read; it contains one assistant
output exactly ACK and no persisted function-call item. No raw rollout, nonce,
account/thread/session IDs or user scratch path is copied into this document.
A read-only native-history RPC inspection was unavailable in the agent environment;
no new turn or inference was requested.

The verifier incorrectly counted every non-agent/reasoning/plan started item as a
tool, including userMessage. The generated protocol schema identifies userMessage as
input metadata. A synthetic userMessage start reproduces the failure against the old
verifier, then passes after explicit metadata/tool classification. Actual tool items
still stop the prerequisite; future unknown item kinds are unverified and redacted.
Original V2 started-item counts were not persisted, so the exact event that tripped
that historical run is not independently recovered from the rollout.

Reports now include firstTurn/recallTurn diagnostics (terminal status, displayed
message count, exact-answer boolean and allowlisted item counts) and failureReason,
without answers, IDs or raw tool content. A first-turn prerequisite failure leaves
durableResume unverified rather than claiming reconnect failed. Sentinel status is
set to passed when the finally check succeeds, including an early return.
Eight targeted resume-probe tests and 349/349 full offline tests passed; compilation
and git diff --check passed. No live rerun; native resume remains not live-verified.


### Standalone runtime installation (2026-11-18)

Four new offline tests install only modelmate.py as executable sr in a path with
Thai/space characters, then run from a separate scratch project with isolated
Python-only PATH, no Codex and no repo imports. Help/preview succeed without state
creation. Quoted Bash alias preserves executable path and arguments. Missing Codex
produces actionable CLI/PATH guidance in doctor, manual live and workflow startup,
without a traceback or inference. Fake/real executable names other than codex retain
their existing FileNotFoundError behavior; missing plan errors are not reclassified.
Agent versions inspected locally: Python 3.12.0; Codex CLI 0.169.0 (version only).
No live inference, installed user binary or .bashrc mutation was performed.

Validation: four standalone artifact tests and 353/353 full offline tests passed;
runtime/doctor/verifier compilation and git diff --check passed. No live inference.


### User-supplied successful durable resume probe (2026-11-18)

Scoped LIVE_VERIFIED: the user ran
`python3 verify.py --run-live --probe-workflow-resume gpt-6.1-sol`
and supplied all five checks passed: durableResume, contextRecallAfterReconnect,
restoredEvidenceGate, finalCheckpoint and sentinelUnchanged; phase finished.
Both turns reported completed, one displayed exact expected answer, zero tool/
unknown item events, and started item counts userMessage=1, agentMessage=1.
Requested gpt-6.1-sol/low; reportedModels null; scratchRetained true. No process
exit code was supplied. This is user-provided evidence, not an independent agent-run
live test. The actual native scratch path and IDs are not copied into this document.

Runtime SHA-256: `6903eee04032a38ff057a726500dc02a7be54459d587225646dffad17313e780`
Verifier SHA-256: `1a939a05a226a67852e1f8f2d69f3904a5b6fb377ae55c12182e11093a3a668a`
Both hashes match local files at commit 0a9c86b. The diagnostics confirm userMessage
metadata is no longer miscounted as tool activity in this tested version.

Scope remains two synthetic manual-check turns across process reconnect. It does
not verify tool-check revalidation, crash/network recovery, a no-tools security
boundary, all permission paths or backend dispatch telemetry. Durable scratch/thread
remain retained, not deleted. Public tool-check resume and auto routing remain gated.
Documentation-only evidence update; git diff --check passed. No new agent inference.


## P03/P12 — standalone recheck capability decision, 2026-11-18

Decision: keep public test/lint resume and standalone command execution disabled.
The installed Codex 0.169.0 generated CommandExecParams schema supports argv, cwd,
sandboxPolicy and timeoutMs, but no approvalPolicy. A schema is not enforcement
evidence. The official [App Server documentation](https://developers.openai.com/codex/app-server/)
describes command/exec as standalone execution without a thread/turn; this could
avoid a model turn, but does not establish parity with native tool command rules.

The upstream [command execution request processor](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/command_exec_processor.rs)
inspected on this date selects effective sandbox permissions, builds ExecParams
with UseDefault and starts an execution request. That processor does not show a
command-rule decision or turn approval routing. This is a reason to withhold the
capability, not proof of a bypass in the installed binary: upstream main may differ
from 0.169.0, and downstream enforcement has not been demonstrated. Reading
configRequirements alone would not prove that every applicable command rule was
preserved. A user accepting a check plan cannot waive stronger host restrictions.

The existing RPC allowlist remains unchanged. An offline transport regression
asserts command/exec, command/exec/write and command/exec/terminate are refused
before send in diagnostic and native workflow connections. This proves only the
client gate; it does not test backend enforcement. No command executor, permission
override, local subprocess fallback, new model turn or quota-consuming probe was
introduced. Runtime and verifier hashes remain unchanged.

Next required proof: on the exact supported server version, demonstrate that a
harmless permitted command runs while the same harmless command under an applicable
deny rule is denied, and that approval-required commands cannot execute before the
native decision. Cover project configuration, stronger managed restrictions,
timeout/disconnect and no replay. Use synthetic fixtures without changing user
configuration. Until a supported path can establish these properties, do not add
a standalone executor or advertise zero-model-cost tool revalidation. If that
path becomes supported, reserve each recheck durably before execution and record
unknown outcomes without resetting correction budgets or silently retrying.

Offline validation: protocol tests 7/7 passed; full unittest discovery 354/354
passed; git diff --check passed. These checks do not close the native permission
gate described above.


## P03 — no-inference standalone policy probe, 2026-11-18

Added opt-in `python3 probe_policy.py --run`. No flag prints help without starting
Codex. The diagnostic creates its own private temporary directory and trusted
project config/rules, then removes only that directory on exit. It does not edit
real configuration, change HOME/CODEX_HOME, copy credentials or create threads.
The process-local trust override names only the synthetic project; managed/user
configuration remains loaded. Connection's optional cwd argument is used to start
the server in that project rather than merely passing a cwd to individual RPCs.

The installed CLI evaluates two explicit fixture commands with execpolicy check:
one allow and one forbidden. This utility evaluates policy without executing the
supplied command; see the official [rules documentation](https://developers.openai.com/codex/rules/).
Only after both decisions match, initialization succeeds and config/read confirms
the effective marker plus enabled project layer does the probe send command/exec.
It requests read-only with network disabled, bounded output and timeout, and uses
only two fixed printf argv vectors. No shell, user prompt, test suite or arbitrary
command is accepted. No account, catalog, quota, thread or turn request is sent.

The probe reports version, source/rule hashes and redacted stages/results. Exit 1
means the forbidden fixture command also executed; this prevents treating the path
as verified, but is not conclusive proof that server-side rules were loaded and
bypassed. Config visibility and a CLI rule decision do not prove server loading.
Exit 2 means prerequisites/execution remain unverified, including RPC errors:
unsupported methods, sandbox startup failure and genuine denial can look alike.
Neither result passes permission parity; only help returns 0 (interrupt returns
130). Unexpected approval requests are never accepted, and timeout/EOF/error never
triggers a retry. The runtime standalone command allowlist remains closed.

Agent-run installed CLI check on 2026-11-18: codex-cli 0.169.0; fixtureDecisions
matched; phase server_initialize; projectConfigObserved false; both native command
results unverified; process exit 2. Thus no command/exec request was sent. No new
inference was run. This does not establish a backend denial or a passed live gate.
Normal-terminal output is still needed to investigate this exact native path.
Even that narrow result cannot certify managed restrictions, approval timing,
crash recovery or permission parity; public tool-check resume stays disabled.

Offline validation: 10 policy-probe tests passed, including native fake-server
execution and command capture from the actual fixture cwd; full suite 365/365
passed. The shared transport also distinguishes a missing cwd from a missing
Codex executable. Compile checks for all four entry points and git diff --check
passed. No new dependency or model invocation was added.


## P03 — explicit config-read cwd correction, 2026-11-18

User-supplied normal-terminal report reached project_config on codex-cli 0.169.0:
fixtureDecisions matched, projectConfigObserved false, both commands unverified,
permissionParity unverified. Probe SHA-256
`058359457f1e7bfb6df9912828c770ae9f9e6e58e0bd8dc3e137e6d091a33aaf`
and runtime SHA-256
`bbe5871404ab2b4d675ed963a841d0688ca751b3c6acc3b6c81933bdbab4d057`
match d2d79c8. No native command was sent by that report's code path; no permission
gate passed and no inference was requested. No exit code was supplied.

The probe omitted cwd from config/read, whose installed schema explicitly supports
project resolution through that parameter. The upstream
[configuration reader](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/config_manager_service.rs)
passes this optional cwd into layer loading independently of server process cwd.
The diagnostic now sends the exact fixture cwd and retains every existing marker,
project identity and enabled-layer check. It additionally reports only five boolean
configEvidence fields: effective marker, layers shape, matching fixture layer,
enabled fixture layer, and enabled layer marker. No config values, paths, reasons
or private layer names are printed.

The fake server now withholds project config when cwd is omitted or wrong, so the
prior probe would fail the execution-path regression. Disabled layers, wrong
effective marker, foreign project path, missing layer marker and malformed layers
still stop before any command; diagnostic output is checked for synthetic private
values. Targeted tests 10/10 passed. Native success after this change remains
unverified; do not interpret this fix as established permission parity.
Full offline suite 365/365, probe compile and git diff --check also passed.


## P03 — trust override encoding correction, 2026-11-18

User report for probe SHA-256
`62604852662d2a30b59771b6e531c657dd85fad8b6f5cb8cba666038c8a4b63d`
(04fedbf) and unchanged runtime hash reached project_config. Boolean evidence:
layersPresent and fixtureLayerPresent true; fixtureLayerEnabled,
effectiveMarkerMatches and fixtureLayerMarkerMatches false. Thus discovery worked,
but the layer stayed disabled and no standalone commands were sent. This does not
identify the precise server-side disabled reason or prove managed-policy denial.

The probe had encoded its CLI trust override as a dotted key containing a quoted
path. Upstream [override handling](https://github.com/openai/codex/blob/main/codex-rs/config/src/overrides.rs)
splits key paths literally on dots, without parsing quoted TOML key segments.
Changed the override to a top-level projects inline-table value with one quoted
fixture path. This preserves path dots/Unicode/spaces without malformed key
segments. The change remains process-local and keeps the fixture layer enabled
check mandatory; it does not edit persistent trust or override managed policy.

Offline policy probe tests 11/11 passed, including dots/spaces/Thai in the actual
fake-server cwd. An agent-run no-inference check on installed Codex 0.169.0 accepted
the new override with execpolicy check and returned the expected forbidden rule
decision. Python 3.12 tomllib also confirmed the exact single project key/value;
tomllib is used only for this local check, not as a runtime dependency. Neither
check verifies native App Server project trust. Native result after this encoding
fix remains pending; permission parity and public tool rechecks remain gated.
Full offline suite 366/366, probe compile and git diff --check passed.


## P03 — completed standalone policy probe: negative evidence, 2026-11-18

User-supplied normal-terminal output for Codex 0.169.0 reached finished:
fixtureDecisions matched, projectConfigObserved true, baseline executed,
forbiddenCommand executed, permissionParity not_established_for_fixture. All five
configEvidence booleans were true. No process exit code was supplied; this code
path returns 1 deliberately, not a successful permission certification.

Probe SHA-256: `c4ec4ea5058c82bbe3d614b4337b3e1f24e1071f5a91fe6bba41acbf16e60dcb`
Runtime SHA-256: `bbe5871404ab2b4d675ed963a841d0688ca751b3c6acc3b6c81933bdbab4d057`
Rules SHA-256: `f5281513af1ea09f02da12d00caaa55d05ea59a1da5d8173d7f126df1e502c17`
Source hashes match local 630cc24. The synthetic rule hash matches prior runs.

This establishes that both fixed printf commands executed through command/exec
in this fixture, despite the separate CLI rule evaluation returning forbidden for
one of them and the project config layer being enabled. It does not establish
whether the standalone server loaded that rule, why it executed, or whether native
model tools/managed policies behave the same way. No model turn was requested.
Do not describe this as a universal Codex policy bypass or repeat the same probe
to seek a passing result. No private config, paths or raw traces were collected.

Decision: reject standalone command/exec as the current tool-revalidation backend.
Runtime allowlists and public test/lint resume restrictions remain unchanged.
The completed diagnostic is useful negative evidence, not a passed G2/P12 gate.
Next eligible work is a separately scoped native-tool verification-turn design:
explicit model/quota consent, existing native permissions, fresh observed command
evidence, durable reservation and unknown-outcome/no-replay handling, preserving
correction counters and stale-evidence checks. Such a path uses model quota and
must not be presented as zero-inference revalidation or started automatically.
This update changes documentation only; git diff --check passed. No repeated
native probe or additional inference was run by the agent.


## P06/P12 — classifier removal and durable recheck core, 2026-11-18

User removed separate decision models/classifiers from scope. Deleted the unused
CLASSIFIER_INSTRUCTIONS and prepare_classification function and their five
preparation tests; plan schema/routing/model approval tests remain. Offline prompt
guidance now names --live/--workflow without promising a future classifier. This
removes a dormant API, not an existing live classifier call.

Added controller-only reserve/advance/limit-choice APIs and a version-2 workflow
checkpoint ledger, with version-1 read compatibility. It records command/cwd
digests, selections, source evidence IDs, budgets and native binding phases without
raw commands/output. Session schema stays version 3. SessionStore rejects recheck
ledger rollback/rewrite under the existing writer lock. Persistence failures freeze
the controller; a saved unresolved reservation survives reopen and blocks dispatch.
Recheck reservations do not replace work native turn IDs or reset work attempts.

Thirteen offline tests use real private temporary SessionStore files and inject
save failures before and after atomic replacement, replay attempts, premature
bindings/results, bad quota/selection, schema mutation and budget extensions. They
cover changed commands/models across reconnect, unknown outcomes, immutable ledger
prefixes, backward compatibility, per-process stale-evidence confirmation and
separate metrics. A matching completion from a newly reserved operation can clear
its source stale evidence; saved or reconciled historical completion cannot.

Scope: state/persistence only. Native recheck event matching, model consent, UI
cancellation and retained-thread lifecycle are specified in NATIVE_RECHECK.md but
not connected. No new /recheck command or public tool-check resume is enabled.
No command/exec runtime permission or local executor was added. No live inference
was requested; the prior native happy-path evidence applies only to its recorded
source hashes, not to this new runtime. The next step is native adapter integration,
not another user-run live probe of this controller core.

Validation: targeted recheck tests 13/13 passed; full offline unittest suite 375/375
passed; compile checks for modelmate.py, doctor.py, verify.py and probe_policy.py,
and git diff --check passed. Five tests were removed with the deleted classifier;
existing routing/policy tests and the native mock scenarios still pass.


## P12 — native recheck transport, offline evidence, 2026-11-18

Added internal NativeRecheckConnection, using fresh account/catalog/quota and an
idle durable work-thread identity check before reserving a recheck. It starts a
different durable native thread with shared read-only/on-request options and checks
the returned permissions/project/provider. Only the parent ledger is persisted;
a transient one-check controller reuses WorkflowHost command/cwd/start/completion
matching. No classifier or model-based routing is involved. The caller must obtain
explicit consent for the supplied standard/low model and exact check specification.

The reservation, thread binding and turn reservation are on disk before the next
native RPC. The returned turn ID is saved before queued events are processed.
Parent work bindings/history/counters remain unchanged. A completed matching native
observation can revalidate its source evidence; missing/foreign/wrong-cwd/failed
checks and model pass claims cannot. Cancellation racing success, EOF, unknown
responses, timeout and failed saves do not create automatic retries. Unsupported
command/patch approvals are declined; unknown requests are not accepted. Closing
without confirmed termination leaves the recheck unresolved and the thread retained.

A late conflicting terminal observation can append unknown after a terminal ledger
record, restore the source stale flag and change DONE to UNVERIFIED. This preserves
the original terminal history instead of overwriting it. Cancel still sends the
known native interrupt after parent persistence failure. Thread/turn failures do
not borrow the work attempt's native binding. The RPC allowlist regression now also
covers this adapter: standalone command/exec remains unavailable.

Synthetic JSONL tests inspect the real SessionStore file when fake thread/start and
turn/start RPCs arrive, exercise exact/shell-wrapped commands, failed prerequisites,
changed quota/catalog/specification, approvals, repeats, late conflicts, cancellation,
disconnects and injected save failures. Filtered child events cannot finish the
parent workflow. These tests do not prove live enforcement, all tool paths,
service-side erasure or actual backend model dispatch. No live inference was run.

Public CLI recheck, terminal event-loop multiplexing, consent UX, retained-thread
reconciliation/deletion and a scoped live verifier are still pending. Do not open
public test/lint resume or advertise this as a completed native recovery feature.

Validation: full offline unittest suite 413/413 passed, including 38 new native
recheck transport cases; all four entry points compile; git diff --check passed.
The tests use synthetic servers and private temporary files, not the installed
account or live model inference. No user-run live test is required yet.


## P12 — experimental recheck CLI integration, 2026-11-19

Opt-in --experimental-rechecks enables known-result test/lint workflow resume;
default behavior remains blocked. Offline preview/CANCEL do not create a backend.
START restores the main native session. Recheck preview prints exact command/cwd
and requested standard/low selection; only its single-use confirmation starts the
separate native verification turn. Invalid/expired tokens, changed state/mode/spec,
model text, status queries and EOF never imply execution consent. The three-slot
recheck budget requires explicit continuation and does not reset work counters.

The Terminal selector registers child stdout/stderr dynamically alongside the work
backend and input. It processes cancellation/exit/EOF while the model waits, ignores
stale descriptors after replacement, and cleans up the child before the outer
workflow attachment is closed. Interrupt confirmation comes from a terminal event,
not an RPC acknowledgement. Parent completion still needs its normal continuation,
check and criterion coverage. The shared command-file validator now also validates
the in-memory bindings passed to the experimental UI.

Synthetic subprocess tests exercise the actual selector with a fake durable native
backend: preview does not launch a child, explicit confirmation rechecks and permits
parent completion, status/exit work while a child hangs, and EOF before confirmation
does not approve while EOF during a turn requests interruption. State/spec changes
invalidate consent. Known completed active checks can be configured without replay;
missing/unknown ones refuse experimental execution. Unresolved ledger entries block
resume, remain inspectable with native IDs, and cannot be erased through metadata
removal. This is a refusal to perform unscoped cleanup, not implemented deletion.

No live inference was run. Native reconciliation, scoped native-thread deletion,
full permission coverage and actual model dispatch remain unverified/unsupported.
The experimental path is not production-ready. Next is the scoped live verifier.

Validation: 18 new recheck UI/entry tests passed; full offline suite 431/431 passed;
all four entry points compile and git diff --check passed. Only fake native servers
and private temporary metadata were used, with no live model inference.


## P12 — opt-in recheck live verifier prepared, 2026-11-19

Added --probe-rechecks MODEL under the existing --run-live opt-in. It sends at most
two model turns: initial registered synthetic command evidence, then one recheck on
a separate durable thread after parent reconnect. It does not rerun the previous
manual-context probe. The harness exercises the real controller/SessionStore and UI
preview/confirmation commands, using native observed exit status rather than model
claims; its live scope excludes interactive Terminal timing (tested offline).

All seven report checks must pass for process exit 0: initialToolEvidence,
durableResume, restoredEvidenceGate, consentGate, nativeRecheck, finalCheckpoint,
sentinelUnchanged. Errors, absent/mismatched command evidence, expanded permissions
and declined approval never trigger another model attempt. An unrelated controller
error cannot be classified as a passed stale-evidence gate. Only one recheck budget
slot is used, and the parent's work counters/thread/turn bindings remain unchanged.

The report includes source SHA-256 hashes and requested model/low selection;
reportedModels is null. Commands, nonce, raw model text, native/account IDs and paths
are absent from JSON. Owned scratch location is printed separately on stderr;
scratch and native threads are retained, not deleted. This is not no-tools isolation,
all-permission enforcement, crash/network recovery, scoped deletion or dispatch
telemetry proof. No live inference was run by the agent.

Ten offline probe tests use three fake App Server processes sharing synthetic
thread history. They verify the two-turn limit, one reconnect/two separate durable
threads, initial failure stopping early, false model pass claims, mismatching/failed
rechecks, denied approval, permission expansion, confirmation refusal and unrelated
stale-gate errors. Runtime preflight now keeps the host catalog/policy fresh, fixing
an empty-catalog UI update after a recheck; a subprocess test verifies the next
explicit preview still works. The CLI flag forwarding path also has a regression.

Validation: 10 recheck-probe tests and 20 recheck UI/entry tests passed; full offline
suite 443/443 passed; all four entry points compile; git diff --check passed. These
are fake-server results, not live gate evidence. User-run the single --probe-rechecks
command to collect scoped evidence; do not repeat the older probes for this change.


## P12 — user-supplied native recheck happy path, 2026-11-19

Scoped LIVE_VERIFIED: user ran
`python3 verify.py --run-live --probe-rechecks gpt-6.1-sol` from a normal Terminal.
All seven checks passed: initialToolEvidence, durableResume, restoredEvidenceGate,
consentGate, nativeRecheck, finalCheckpoint and sentinelUnchanged; phase finished.
Both turns reported completed with started=1, completed=1, command_mismatches=0,
cwd_mismatches=0. Requested gpt-6.1-sol/low; reportedModels null; scratchRetained
true. No process exit code was supplied. This is user-provided evidence, not an
independent agent-run live test. The actual scratch path is not copied here.

Runtime SHA-256: `cbaa64bd7dec205848f92a05be4db68f35f826383fab577e177b701b8de58f3b`
Verifier SHA-256: `394cd606715796cc8c1833d1c9cba1040d03bcf86a4f3bdea992c02e20112064`
Both match local files at 732ac47. This verifies the bounded synthetic path through
initial native command evidence, durable reconnect, stale-evidence/consent gates,
a separate native recheck and final checkpoint with unchanged sentinel/work state.

It does not verify interactive Terminal timing, crash/network or unknown-outcome
recovery, scoped native-thread deletion, all permission paths, a no-tools boundary
or backend dispatch telemetry. Native threads and scratch remain retained. Default
tool-check resume remains disabled; the experimental opt-in is not production-ready.
No further run of this happy-path probe is needed. Next: explicit known-binding
reconciliation without replay; historical terminal observations must not clear
stale evidence. Documentation-only update, git diff --check passed; no new inference.


## P12 known-binding recheck recovery — MOCK_VERIFIED (2026-11-19)

Offline suite: `python3 -m unittest discover -s tests`: 469 passed.
`python3 -m py_compile modelmate.py doctor.py verify.py probe_policy.py` and
`git diff --check` passed. Coverage includes terminal reconciliation, stale evidence,
unchanged budgets/history, account/project/binding mismatches, exhausted quota,
STOP/PAUSE/EOF, acknowledgement without terminal confirmation, bounded polling,
atomic-save uncertainty, CLI dispatch and metadata-copy probe isolation. Recovery
RPC tests reject thread/model starts, resume, model listing and command/exec.

The agent attempted the metadata-only verifier against the retained successful
synthetic recheck scratch. Source unchanged passed; native terminal observation,
reconciliation and historical-result checks remain unverified: App Server did not
complete initialize in this environment (ProbeError, nativeRpc initialize). No new
model turn was requested and no native thread deleted; the isolated failure copy
was retained. No underlying network/authentication cause is established.

The user's ordinary Terminal should run `python3 verify.py
--probe-recheck-recovery SCRATCH` using the original successful probe directory,
without --run-live. This reads retained native metadata on a private checkpoint
copy. It does not test actual crash/network failure, active-turn interruption,
missing native-ID discovery, current command evidence or scoped deletion. Existing
live recheck evidence remains historical and version-bound; it does not certify
this new recovery path.


### Known-binding terminal recovery — scoped LIVE_VERIFIED (2026-11-19)

User-supplied Terminal output from `verify.py --probe-recheck-recovery SCRATCH`
at source commit `65d15f2` finished with all four checks passed:
`nativeTerminalObserved`, `metadataReconciled`, `historicalResultOnly`, and
`sourceUnchanged`. Observed terminal status was `completed`.

- modelTurnsRequested: 0
- nativeThreadsDeleted: false
- copyRetained: false (the owned successful metadata copy was removed)
- Runtime SHA-256: `6b3bd6a3a55536c620bedf3324e491930fed16152f7f8b7b971f2509b9ee24fc`
- Verifier SHA-256: `c08d71248c372f0b9b475b67d6c0681c36c7ca15e2e0316593328c1cff9051f3`

Both hashes match local source files at 65d15f2. This supersedes the pending
user-run metadata check above, without changing the earlier agent initialize
failure. Evidence covers terminal reconciliation on an isolated copy of a
successful synthetic recheck checkpoint: original metadata remained unchanged,
historical status did not become current test evidence, and no native start,
interrupt or delete request was made. No additional inference was requested.

It does not verify active interruption, missing-binding discovery, crash/network
recovery, current command evidence or scoped deletion. Recovery is not thereby
release-ready. Next eligible task: scoped native-thread cleanup with preview and
explicit confirmation. Documentation-only update; git diff --check passed.

## P12 scoped native cleanup — MOCK_VERIFIED (2026-11-19)

`python3 modelmate.py --delete-session SESSION_ID` previews one local session's
work root, ledger-bound recheck roots and spawned descendants across both native
listings. It opens no model turn. The existing chat deletion uses the same scope
and receipts. Exact confirmation with Enter is required. A fresh snapshot and
account check precede deletion; known active, foreign or ambiguously bound
threads block it. Acknowledged roots and any uncertain in-flight root are kept
in schema-v4 cleanup metadata until cleanup can be finalized. Legacy work-root
receipts are preserved. Work files are outside the deletion operation.

Targeted `test_recheck_recovery.py` passed 26 tests. Full offline discovery passed
475 tests, including independent roots, archived descendants, EOF, exact
confirmation, uncertain partial success, older receipts, and no inference
requests. All four Python entry points compile and `git diff --check` passed.

Installed Codex CLI `0.170.0` exited before answering a metadata-only
`initialize` attempt in the agent environment. No native deletion or inference
was attempted. Scoped deletion and active interruption remain live verification
gates. For cleanup, use the original successful synthetic recheck scratch in a
normal authenticated Terminal. Set `XDG_STATE_HOME` to its `state` directory,
run from its `project` directory, and use `--sessions` to get the local ID before
running `--delete-session SESSION_ID`. Review the preview before confirming.
For active interruption, use the existing opt-in `--probe-workflow MODEL`
verifier and look for `cancel: passed` from an interrupted terminal turn.
The probe can use up to four subscription turns.

### Active native workflow cancellation — scoped LIVE_VERIFIED (2026-11-19)

User Terminal output for `python3 verify.py --run-live --probe-workflow gpt-6.1-sol`
at `74dbba8` reported phase `finished` and all six checks passed:
`answerDisplay`, `contextRecall`, `approvalDenial`, `sentinelUnchanged`,
`cancel` and `disconnectGuard`. The verifier awards `cancel: passed` only
after observing an `interrupted` terminal status. Requested selection was
`gpt-6.1-sol/low`, with `reportedModels: null`.

- Runtime SHA-256: `260abf4f402d21f85ef060dee1caeeab16485d72e822de1c1355b94b5c2fe808`
- Verifier SHA-256: `0ceabddf14423eff33f2f8e042495c77defa196b0e9ef59672849032fe00e620`

Both hashes match the local source at `74dbba8`. Scope is the synthetic
ephemeral native workflow, including cancellation and a local disconnect
guard. Live scoped deletion, retained recheck STOP, interactive Terminal
timing and network-drop recovery remain open. No additional live request
was made during this documentation update.

## Workflow selection and preflight follow-up (2026-11-19)

The offline `--suggest-models` preview resolves role and effort from the
declared risk and checks, using explicit bindings. Auto, Ask to escalate and
Approve plan use the controller's existing approval gates. Whole-plan approval
displays the resolved selection for every step. Native startup checks the
current catalog before creating the thread. Model suitability and quota savings
are pending evaluation on real tasks.

A synthetic App Server changed quota, account and catalog state after native
workflow connection. The next attempt paused with the specific reason
(`quota_exhausted`, `quota_unknown`, `account_changed`, or
`catalog_unavailable`) and consumed no attempt slot or turn. Existing offline
cases cover read-only sandbox mismatch and native workflow approval decline.
The scoped user live approval-denial evidence above still applies to the
version and path recorded there.

### Scoped native deletion — scoped LIVE_VERIFIED (2026-11-19)

The user ran `--delete-session SESSION_ID` in the original successful synthetic
recheck scratch. The preview listed exactly two roots in that project, the work
thread and the independently bound recheck thread. Entering only `DELETE`
cancelled the first attempt. On a fresh preview, the exact new confirmation
produced the success message. The runtime reaches that message after it receives
a native delete acknowledgement for each root and removes local metadata.

A follow-up local `--sessions` check returned no saved session, and the verifier's
sentinel check passed. The follow-up checkout was `1fa2ce8`. The user transcript
did not include a runtime checksum or an independent post-delete native listing.
This evidence covers the successful two-root scope. Active rejection, archived
descendants and uncertain partial deletion remain offline-tested in this path.

### C1 paired routing pilot — MOCK_VERIFIED (2026-11-19)

The two offline previews resolved their respective standard/low and strong/low
bindings without creating session state. Five fixed boundary cases distinguish
the accepted answer from the other three candidates. Synthetic App Server runs
through the Terminal launcher approved each plan, dispatched exactly one turn
per arm at the expected requested selection and reached DONE. The offline
suite passed 479 tests. No subscription turns were requested. The user-run pair
and its comparison remain pending. See EVALUATION.md for commands and scope.

C1 partial live result: the user-run routed arm requested `gpt-6.2-sol/low`
once, reached CHECKING, and displayed a response that passed all five cases
in the local scorer. The user exited before recording the rubric in the
workflow, so its saved state is PAUSED. The initial baseline session exited
after approval and before dispatch, with zero attempts. The launcher printed
runtime SHA-256 `f6446317165ef09446736fbf7598d0ac5cee0b61fb3a98ad204eda55c10b1209`.
Paired scoring remains pending. Requested model is recorded without reported
dispatch telemetry or token usage.

C1 baseline follow-up: the user requested `gpt-6.2-astra/low` once, then
entered `/exit` while RUNNING before an answer appeared. Read-only inspection
of the local workflow checkpoint found the attempt's terminal status recorded
as `interrupted`. The task remained paused with no gradeable answer. Keep this
interruption separate from the earlier zero-attempt exit and from any subsequent
baseline run. The routed score remains 5/5. The pair has no baseline score yet.

C1 paired live result: the completed baseline run requested
`gpt-6.2-astra/low`, reached CHECKING and displayed the same answer as the
completed routed run. The independent scorer passed all five cases for each
arm. Both completed runs recorded one attempt, zero rechecks, and PAUSED
after exit before rubric entry. Earlier baseline exits remain recorded
separately. Both reports used the same runtime SHA-256, which matches the
checkout. `reportedModels` and `tokenUsage` were null. Recorded wall times
were 75.337 seconds (routed) and 43.694 seconds (baseline), including user
wait. The pair provides no attributable inference-time or quota comparison.

### Two-step economy pilot — MOCK_VERIFIED

Both offline previews and both copies of the supplied unittest fixture passed.
A fake App Server exercised the actual Terminal workflow and recorded
economy/low then strong/low for the routed arm, and strong/low twice for the
baseline. Both reached DONE with observed first-step test evidence and
separate consent for each strong step. The full existing offline suite passed
479 tests. An agent-side `--doctor` attempt exited before the App Server
initialized; no live turn was requested. The paired live result remains open.

Economy pilot routed live result: the user requested `gpt-6-luna/low` once
for the registered native test and recorded a passing tool check via
`/check`. The review requested `gpt-6.2-astra/low` only after explicit
model approval and a separate dispatch command. A missing-token approval
was rejected before that consent. The review's proposed final-index test
was independently verified against the staged function and a variant that
skips the final element. The three original cases passed against both.
Both attempts reached CHECKING. The workflow was paused on exit before
rubric entry for the second step. Two attempts and zero rechecks were
reported. Runtime SHA-256 matched the C1 runtime. The economy pilot baseline,
backend-reported models, and attributable quota observations are still open.

Economy pilot baseline partial result: the user requested one
`gpt-6.2-astra/low` turn for the registered test. The turn reached CHECKING
and the displayed answer reported a successful command. The user exited
before `/check`. Local checkpoint inspection confirmed a completed attempt
with zero recorded checks and no review attempt. The claim is insufficient
for the native test criterion. The paired result remains open.

Economy pilot baseline follow-up: the user captured a passing native tool
check for step one using one `gpt-6.2-astra/low` attempt. Exit occurred
between the two steps, before the review dispatch. The saved session passed
the offline experimental workflow resume preview. Its first-step tool
evidence is historical on resume. The experiment can still grade that
observed test outcome and a subsequent review separately, without using a
new test turn to mark the restored workflow DONE.

Economy pilot paired live result: the baseline resumed its existing checkpoint
and dispatched only its outstanding review after fresh model approval.
The baseline's recorded native test passed before resume. Both review
suggestions independently detected the final-element regression, while the
three original cases passed with and without that regression. Each graded
arm used two attempts with zero rechecks. The routed arm requested
`gpt-6-luna/low` then `gpt-6.2-astra/low`; the baseline requested
`gpt-6.2-astra/low` twice. Both exited before final rubric entry.
Earlier incomplete baseline attempts remain separate from the graded pair.
Model and token telemetry were null. The baseline review ran after a
reconnect, and its prior test was historical on resume. No inference-time
or quota comparison is supported by these observations.

### Native workflow usage measurements — MOCK_VERIFIED

Generated the App Server JSON schemas with installed Codex CLI 0.170.0.
The workflow summary reads matching `thread/tokenUsage/updated` snapshots
and counts observed terminal work turns once. It reports thread totals
as supplied and does not sum repeated counters or infer a reported model.
The opt-in quota read compares known windows for the same account. Synthetic
coverage exercises foreign and incomplete token updates, interrupted and
duplicate terminal observations, account mismatch, resets, missing windows,
and a matched pre/post window without an additional turn. The full offline
suite passed 484 tests. No subscription turns were run and the telemetry
fields have not been confirmed with a live account.

The telemetry smoke command in EVALUATION.md also passed end-to-end with a fake
App Server. Its printed summary contained one attempt, one timed terminal turn,
matching token counters, and the configured comparable quota delta. Local
`--doctor` for the live account again exited before initialization. No live
turn was requested by this check.

### One-turn workflow telemetry — scoped LIVE_VERIFIED

The user ran the list/tuple smoke test with `--measure-quota` in a fresh
scratch project. One requested `gpt-6.2-sol/low` attempt reached CHECKING.
The summary included one timed terminal turn, a matching work-thread token
snapshot with complete counters, and comparable primary and secondary quota
windows. Both windows showed no visible change at the reported resolution.
The CLI wall time included user wait and was reported separately from observed
turn time. A second `/next` while CHECKING was rejected without dispatch.
The user exited before entering the rubric, leaving the workflow paused.

This covers live metric availability on one work turn. `reportedModels`
remained null and unchanged displayed percentages do not establish zero
quota use. No account-level percentages, reset timestamps, or session IDs
are retained in this record.

Measured C3 partial live result: the baseline requested `gpt-6.2-astra/low`
once and its answer passed all five de-duplication cases. The live summary
contained token counters, one timed terminal turn, and two comparable quota
windows. The initial routed session exited before dispatch and reported zero
attempts and zero timed turns. It provides no paired measurement. Account
usage values, reset timestamps, and session IDs are omitted.

Measured C3 pair completed on runtime SHA-256
`92c07e0cff2575b0ee7b972bd7c6ee30026de31b5c4222e24a8cc5e22bc30c2e`,
matching the local runtime. The two gradeable turns passed the same five
checks and returned token counters, turn timing and matched quota windows.
The earlier zero-attempt routed session was excluded. See EVALUATION.md for
the comparison and its limitations. Account usage values and reset
timestamps are omitted.

### Workflow tool evidence autosave — MOCK_VERIFIED

A completed, exactly matched native command observation is now committed
with its terminal work attempt. The CLI can exit before `/check` without
losing that checkpoint evidence. The saved step still awaits evaluation.
Tests cover durable evidence through exit, duplicate terminal delivery,
the separation of observed and accepted evidence, and a queued check cleared
by cancel even if a completed terminal event arrives afterward. Resume still
treats saved evidence as historical. No live inference was requested.

The Terminal smoke path also checks `/approve TOKEN --next`, which explicitly
starts the approved step after fresh preflight. The synthetic CLI reached
CHECKING with one turn. After exiting before `/check`, offline
`--show-workflow` displayed the recorded passing test in the paused
checkpoint. Invalid and reused tokens did not dispatch. The agent-side
`--doctor` retry exited before initialize. A live user smoke remains open.

Run from the ModelMate checkout with a fresh state directory:

```bash
(
  cd "$HOME/Coding/Hobby/ModelMate" &&
  export XDG_STATE_HOME="$(mktemp -d)" &&
  python3 modelmate.py --workflow examples/check-model-policy.json \
    --check-commands examples/check-model-policy.commands.json \
    --workflow-mode approve_plan --role-model standard=gpt-6.2-sol \
    --execute-workflow &&
  SESSION_ID="$(python3 modelmate.py --sessions |
    awk 'length($1)==32 && $1 ~ /^[0-9a-f]+$/ { id=$1; n++ } END { if(n==1) print id; else exit 1 }')" &&
  python3 modelmate.py --show-workflow "$SESSION_ID"
)
```

Enter START, then `/next`, then the displayed `/approve TOKEN --next` line.
Wait until CHECKING and then exit without entering `/check`.
The final offline listing should contain `[pass] test`. Only the
approved turn uses a subscription turn.

### Tool evidence autosave and approval shortcut — scoped LIVE_VERIFIED

The user ran the one-turn smoke against the checkout containing `fd6c982`.
`/approve TOKEN --next` dispatched one requested `gpt-6.2-sol/low` turn.
The matched native test displayed a passing result before any `/check`.
A follow-up `/next` while CHECKING was rejected. After `/exit`, offline
`--show-workflow` displayed the passing evidence in the paused checkpoint.
The workflow had not evaluated that step. The transcript exposed an
inconsistent offline step label, corrected to CHECKING in the follow-up.
No runtime checksum was supplied with the user transcript.

The corrected viewer was checked offline on that same live smoke checkpoint.
It printed the overall PAUSED state, the step's CHECKING state, and the saved
passing test. The full offline suite passed 487 tests.

### Metadata-only native work-turn inspection — MOCK_VERIFIED

`--inspect-work-turn SESSION_ID` uses a read-only checkpoint and a metadata
RPC allowlist without interruption, execution, resume or deletion methods.
It checks account and project identity, the exact latest turn and the
cached terminal status. It prints counts of historical local checks without
upgrading their validity. A running checkpoint can retain the previous turn
ID across a crash gap and is reported unverified without native requests.
Synthetic tests exercised a latest turn with older history, mismatched turn
or status, and ambiguous running bindings. A metadata-only live attempt on
the workflow autosave smoke checkpoint stopped at App Server initialization
in the agent environment. No model turn was requested.

### Metadata-only native work-turn inspection — scoped LIVE_VERIFIED

The user ran the inspection on the retained autosave smoke checkpoint with
the runtime containing `ff95059`. The result was `terminal` /
`completed`, with one historical passing check, zero failed or unknown
checks, and `modelTurnsRequested: 0`. This confirms read-only inspection of
that known completed native work turn. The historical count does not
revalidate the current project files. The transcript did not include a
runtime checksum.

### Resume checkpoint preservation — MOCK_VERIFIED

Native workflow resume holds the session writer lock, inspects project and
thread identity, turn history, and returned permissions, then commits the
restored checkpoint. Rejected resumes preserve the original metadata
byte for byte. Fake App Server cases cover project, activity, ephemeral
state, provider, permission weakening, turn identity, malformed status
and missing history. The existing crash-gap protection continues to clear
the old turn ID atomically when reserving a new attempt. No native turn
was requested for this regression.

### Per-turn workflow measurements — MOCK_VERIFIED

The runtime includes one measurement row per dispatched work attempt in the
current CLI session. Each row records the requested selection and observed
terminal status and elapsed time. The optional token fields copy the native
`last` breakdown for the matching turn. They are last-response observations,
not estimates of full turn usage. The cumulative native thread snapshot is
still reported separately. A two-step fake server verified distinct model
selections and independent per-turn rows. Missing bindings and interrupted
turns preserve unknown fields as appropriate. Targeted checks and the full
offline suite passed 490 tests. No new live turn was requested.

### Private workflow metrics JSONL — MOCK_VERIFIED

Explicit `--metrics-jsonl FILE` appends one private summary record per
started CLI session. It does not retain prompts, responses, session
identifiers, or account quota observations. The Terminal summary is still
printed. Synthetic checks verify runtime CLI output, permission and
symlink rejection, repeated append, and rollback after a partial write.
The report does not make any additional native requests.

### Offline routing comparison

The pilot's `compare` subcommand reads a chosen baseline and routed metrics
record with no App Server use. Synthetic CLI cases verify exact deltas,
explicit selection in multi-row logs, and unknown deltas for incomplete
coverage or a missing latest token event. This tool compares observations
only. It does not infer quality or account quota savings from the logs.

### Work-turn model reroute observations — MOCK_VERIFIED

The installed App Server 0.170.0 schema exposes `model/rerouted` with thread
and turn IDs and source and target model IDs. The workflow records each
unique source/target transition only on its matching work turn and shares
those observations with the offline metrics comparison. It does not store
the reroute reason or infer model dispatch for all responses. Synthetic
tests cover duplicate notifications, foreign threads, unrelated turns,
and malformed model IDs. No live reroute was requested.

### Metadata-only workflow catalog preflight — MOCK_VERIFIED

`--check-catalog` checks an explicit new plan against ChatGPT login, quota,
and visible model/effort entries for the baseline and each step. The
transport uses the metadata-only connection. Offline fake App Server
cases cover ready, unavailable model, exhausted quota, and API-key login.
No thread, model turn, or ModelMate session is created. The check reports
catalog support and account quota as observed; it does not prove dispatch
or reserve quota.

### Dedicated Wikipedia query privacy — MOCK_VERIFIED

The standalone search takes a query from its own input, previews it with the
destination, and requires a fresh exact confirmation before one HTTPS request.
Offline tests cover refusal, EOF, stale input, exact query encoding, redirect
rejection, untrusted result content and source URLs. Work threads and their
native search settings are outside this path. An agent-side public lookup
failed at DNS before reaching Wikipedia. This evidence covers Wikipedia lookup
only. The broader search requirement remains open.

The release smoke installed only the runtime as an executable in a clean
scratch directory with spaces on Linux x86_64 under WSL2 (Python 3.12.0).
Help, explicit offline plan preview, and cancelled search worked without
creating ModelMate session state. See RELEASE_CHECKLIST.md for remaining
release gates.

The transport uses the documented MediaWiki search-pages endpoint and
public page identifiers for links.
[MediaWiki REST API reference](https://www.mediawiki.org/wiki/API:REST_API/Reference/en#Search_pages)

The user search smoke stopped with UnicodeDecodeError before the query preview.
The search now decodes one UTF-8 line at a time. A malformed query can be
re-entered and malformed confirmation cancels. Synthetic input reproduces
both a bad paste line followed by a valid Thai query and a valid query line
followed by invalid confirmation bytes. Neither malformed line is sent.

### Thai Wikipedia search — scoped LIVE_VERIFIED

The user ran the search after the input fixes through `c11c0d4`. The CLI
trimmed leading whitespace from a public Thai query, previewed the exact
outbound query and Thai Wikipedia destination, and returned five cited
sources after explicit confirmation. No model turn is involved in this
path. This live transcript covers Thai Wikipedia lookup. The English
endpoint, general-web integration, and cancellation privacy beyond the
offline tests are outside this live result.

### Confirmed general web search through SearXNG — MOCK_VERIFIED

The user supplies a trusted HTTPS SearXNG origin. The same separate query
confirmation accepts one UTF-8 line and submits only that text and the JSON
format parameter to the configured instance. Redirects are rejected and
source links are rendered as data. Tests cover cancellation without
connection, exact encoding, rejected destinations and invalid result
schemes. Live testing requires a configured instance that enables JSON.
The agent's metadata-only catalog preflight still stopped before App Server
initialization. No subscription turns were requested.

### Metadata-only workflow catalog preflight — scoped LIVE_VERIFIED

The user ran `--check-catalog` with the list/tuple example and reported
`state: ready`, `quotaReason: included_usage_available`, and
`modelTurnsRequested: 0`. Both the baseline and the only step found
`gpt-6.2-sol/low` available in the live catalog. The observation covers the
ready path at that moment. Admission failures remain covered by synthetic
tests. The transcript did not include a runtime checksum.

### Synthetic incident-analysis benchmark — MOCK_VERIFIED

The A1 pilot prepares equivalent model inputs and independent scratch state
for both arms. Offline previews requested distinct models without creating
sessions. The rubric accepted a grounded structured answer and rejected an
overstated cause and duplicate keys. No subscription turn was requested.

A1 partial live result: the routed arm requested `gpt-6.2-sol/low` once.
Its displayed JSON passed all four independent rubric fields. The baseline
was interrupted before START and had no metrics record. The launcher now
returns exit 130 for Ctrl+C without printing a traceback. A subprocess
smoke signal before START confirmed no state directory or model turn.

A1 paired live result: both completed arms reached CHECKING and their
identical answers passed all four rubric fields. Each had one timed work
turn. The private JSONL files were read back locally and the comparator
matched the user's output. The earlier baseline cancelled before START
was excluded. Runtime SHA-256
`35b5ab2598f64839e5f034dddbd593626c7877ced4ede3d8147af3f669065b24`
matched the checkout. See EVALUATION.md for aggregate token and timing
measurements. Account utilization and reset timestamps are omitted.

### First-pass outcome and acceptance time — MOCK_VERIFIED

Workflow metrics derive first-pass counts from evaluated first attempts.
Pending, interrupted, and unassessed attempts are tracked as unknown.
A subsequent successful retry does not erase the original failure.
Acceptance time is captured on DONE and excludes time spent in the CLI
after acceptance. Synthetic tests verified pending, failed-then-passed,
and durable CLI report cases. No new inference was requested.

### Offline quota admission and explicit recovery

The fake App Server exercises exhausted quota and missing admission evidence
at catalog preview, native workflow connect, and the preflight before dispatch.
The preview issues only metadata RPCs. Initial connect blocks before thread
creation. A preflight denial after connect leaves the attempt count at zero.
In the transient cases a second request while paused sends no turn. After an
explicit continue and a fresh allowed quota read, the next request sends one
turn on the existing thread. The test traces cover each RPC and assert the
thread and attempt counts. These checks exercise controller admission and do
not measure provider quota behavior.

### Scoped recovery and catalog checks on the current checkout

At source `1565766`, the metadata-only workflow catalog check returned
`ready` with `included_usage_available`, and found the requested
`gpt-6.2-sol/low` selection available. The report recorded zero model turns.
The command was `python3 -B modelmate.py --workflow examples/explain-lists.json
--role-model standard=gpt-6.2-sol --check-catalog`, using Codex CLI 0.170.0.
Runtime SHA-256 `35700a79821eb5c9f6faa7cc1159c1d0723ed7ec8c345eed06db307647338a38`.

The recovery CLI suite also checks the race where the turn completes after
the STOP prompt but before confirmation is processed. The fake App Server
reports a completed turn on the binding recheck. The CLI records completion
without sending an interrupt or starting another turn. Saved workflow checks
and step counters are preserved. This new case is offline evidence. Live
active STOP remains open.

### Scoped live STOP probe attempts

Codex CLI 0.170.0, runtime SHA-256
`35700a79821eb5c9f6faa7cc1159c1d0723ed7ec8c345eed06db307647338a38`.
Two opt-in synthetic runs each reached the retained recheck phase with
initial tool evidence, resume, stale evidence and consent checks passing.
The first observation was terminal after closing the source connections
(verifier SHA-256 `28c87e463f922b8f982506dd156f838a2efccc3ae6e242230a1d9a1d68ed6f5e`).
The second observed an interrupted terminal status before the recovery STOP,
with the source connections open and a bounded delay in the command
(verifier SHA-256 `8fd41db162e3ca09ebcdbe5208419cd6d1f3d8944d9f8a38a603d40b72bd7602`).
Neither run observed an active binding at that point. This leaves live
retained STOP unverified. Both sentinels remained unchanged.

### Live recovery CLI on retained interrupted recheck

At source `3b8042e` with Codex CLI 0.170.0, the production
`--recover-recheck` command was exercised with EOF on the retained synthetic
scratch from the first STOP probe. Recovery observed a terminal interrupted
turn for the known binding and returned 0. The checkpoint gained one
reconcile event with neither an exit code nor a command item. Its original
attempt count and sentinel were preserved. No model turn was requested.
The other scratch already held an interrupted finish event, and the same
CLI returned 0 with nothing unresolved. This verifies reconciliation and
the already-resolved path, while active STOP remains open.

### Missing native recheck bindings — Codex CLI 0.171.0 schema inspection

Generated both regular and experimental App Server bundles with
`codex app-server generate-json-schema [--experimental] --out DIR`.
Inspected request and response schemas alongside the recheck dispatch order
in `modelmate.py`. No App Server session or model turn was started.

- `turn_pending` has a saved native thread ID. The regular schema accepts
  `turn/start.clientUserMessageId` and exposes nullable
  `userMessage.clientId` in turn history. A new dispatch could use a
  controller-owned operation ID as a correlation value. The schema does
  not establish that the server echoes it in persisted history after
  reconnect. A synthetic probe must capture the exact match in
  `thread/turns/list` with `itemsView: full` after reconnect, using a local
  checkpoint that never received the turn ID. A missing or ambiguous match
  must leave recovery unresolved. Existing rechecks did not send this value.
- `reserved` can lack the thread ID because the start reply was lost.
  Neither generated bundle declares a per-request correlation ID on
  `thread/start`. The schema describes `threadSource` as analytics
  classification. A matching directory or timestamp cannot establish
  ownership. This phase still lacks a verified discovery mechanism.

P12 remains IN_PROGRESS. Active retained STOP still requires live evidence
of an active binding. No recovery or deletion policy changed.
