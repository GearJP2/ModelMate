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

### One-turn correlation probe — offline verification

From a normal Terminal logged in with a ChatGPT subscription, run:

```sh
python3 verify.py --run-live --probe-turn-correlation gpt-6.1-sol
```

The selected model must be in the account catalog and support low effort.
The verifier checks subscription quota, creates a private local scratch project
and one durable native thread, and sends at most one synthetic turn with a
random client message ID. Its local checkpoint stores the thread binding,
client message ID and account fingerprint before dispatch. After the sender
closes, a fresh connection verifies the same account and looks up full history
using that checkpoint, which has no native turn ID. A pass requires a single
completed turn with a matching user-message client ID and verified thread
identity and terminal status. Local scratch is temporary. The native thread
is retained. Reports include source hashes and omit client, account and native
IDs, prompts, history and scratch paths.

Success is exit 0 with `persistedTurnCorrelation: passed`,
`phase: complete` and `modelTurnsRequested: 1`. A failed or unverified result
exits 1 and the phase identifies where the check stopped. Record the installed
`codex --version` with the sanitized JSON. The probe simulates the missing
checkpoint field after a completed turn. It does not simulate loss of the
start response or verify active interruption.

### Persisted turn message ID — scoped LIVE_VERIFIED

The user ran the one-turn probe from source `59bc1f0` with Codex CLI
`0.171.0` and `gpt-6.1-sol`. It reported
`persistedTurnCorrelation: passed`, `phase: complete`, and
`modelTurnsRequested: 1`. Source hashes matched the reported runtime
`5bda823643d0e635cddfadf2ef393027484079c99a7e8a5199ed531c476c2768`
and verifier
`0fb92a5247c1f3a9d70051f1aca9b28a50ec6bc26f8522978720bfeba3269302`.

The runtime integration saves the UUID before dispatch and can reconcile a
uniquely correlated terminal turn on a known recheck thread. It records binding
and terminal status together without changing work attempts or restoring stale
tool evidence. Legacy reservations without a marker, ambiguous history, and
active turns without a saved native turn ID remain unresolved. Runtime
integration is offline-tested. Recovery after an actual lost turn/start reply
and active retained STOP still require live coverage.

To exercise the new recovery integration on a normal authenticated Terminal:

```sh
codex --version
python3 verify.py --run-live --probe-rechecks gpt-6.1-sol --simulate-lost-recheck-binding
```

This uses at most two synthetic turns. It retains the original probe scratch
and native threads. On an isolated copy, it drops the saved turn binding and
terminal result, then tests recovery with metadata RPCs only. A successful
run exits 0 and all four `missingBindingRecovery` checks report `passed`:
`nativeTerminalObserved`, `metadataReconciled`, `historicalResultOnly`, and
`sourceUnchanged`. The recovery phase requests zero model turns and leaves
the original checkpoint unchanged. This checks the missing-metadata path
after completion. A real dropped reply and active interruption are separate
conditions.

### Correlated terminal recovery with a missing turn ID — scoped LIVE_VERIFIED

The user ran the two-turn integration probe at `b9349f0` on Codex CLI
`0.171.0`, requesting `gpt-6.1-sol/low`. The reported runtime hash
`8a89cad64f094d4dcfe6e02b6752214c772e5240809e022cbb429081242bf482`
and verifier hash
`ea2290e522fd7c983ab5774ac65bc4896de91752c56c34cb51e8fd26eb74f3ed`
matched the checked-out source. The main seven checks passed. Each turn
completed with one command start, one completion, and zero command or cwd
mismatches. All four missing-binding recovery checks passed with terminal
status completed, zero recovery model turns, no native deletion, and no
retained recovery copy. The original synthetic scratch was retained.

A separate offline integration test now closes a fake native server before
it sends the turn/start reply. Recovery uses the original checkpoint and a
fresh connection. The fake history echoes the client ID from the dispatched
request. The test checks that the unknown operation gets one terminal
recovery record, with the work checkpoint intact and no replay or interruption.
Live coverage remains scoped to the isolated copy after a completed recheck.

### Active retained STOP probe update — offline verification

The STOP probe now initializes and account-checks its separate recovery
connection before confirming the synthetic recheck. This removes observer
startup from the interval between dispatch and status inspection. The
observer still validates fresh account and native binding state immediately
before requesting interruption. A pass requires an active observation,
an acknowledged scoped interrupt request and a separate terminal interrupted
observation. The fake-server test rejects a race where the turn is already
interrupted at the second read and no interrupt RPC is sent.

From a normal authenticated Terminal:

```sh
codex --version
python3 verify.py --run-live --probe-rechecks gpt-6.1-sol --stop-retained-recheck
```

This requests at most two synthetic model turns, authorizes interruption of
the probe-created recheck only, and retains the scratch and native threads.
A pass exits 0 with `activeRecheckObserved: passed`,
`stopRpcAcknowledged: true`, `nativeRecheckStopped: passed`,
`observedAfterStop: interrupted`, and intact checkpoint and sentinel checks.
An interrupted result before the RPC or a non-active initial observation
leaves this gate unverified. Return the sanitized JSON and CLI version.

### Prewarmed STOP live attempt and owner-side diagnostics

The user ran the prewarmed observer probe at `f864913` with Codex CLI
`0.171.0` and requested `gpt-6.1-sol/low`. The source hashes matched
runtime `b9c447c6b637f37fc65fa423d787a774bfc2a2c692583155a666f4b597861bd0`
and verifier `dc8383ebe10e572902d945b90a7dc28d8c257328f243328ba54748a176b35601`.
The independent observer returned `interrupted` before STOP. The scratch
checkpoint retained an unknown finish and its sentinel was intact. No
observer STOP was acknowledged. The result cannot determine whether the
owning App Server still had an active turn when the observer read history.

The same opt-in STOP command now reports `ownerStatusBeforeInspection` and,
when the independent observer does not see an active turn,
`ownerStatusAfterInspection`. These reads use the connection that started
the recheck and report only thread-state enums after validating identity.
If both owner reads are active while the outside observer reports
interrupted, the probe leaves the retained STOP gate unverified and its
existing cleanup can cancel the synthetic turn through the owner. That
cleanup does not count as an observer STOP. A stopped owner at the second
read leaves a timing race possible. The fake suite exercises disagreement
without changing the production recovery decision.

### Owner activation race in the retained STOP probe

The user ran source `76e6ad7` with Codex CLI `0.171.0` and requested
`gpt-6.1-sol/low`. The runtime hash
`fe8fa3d9db8a23860c96ea7ca972a4855012c715b0d2b99249675135b3e6e45a`
and verifier hash
`d57ba0c3c44da5c02fae5e3db9caa4621c70b7c15825092277c16abca58517be`
matched. The owner moved from `idle` before the inspection to `active`
afterward, while the independent observer reported `interrupted`.
The sentinel was intact. No independent STOP was acknowledged. This run
does not show how the independent observer reports a turn already active
before inspection.

The revised probe waits up to two seconds for owner activation before any
independent native thread or turn observation. It reports the initial owner
state and the last owner state before inspection. If activation is not
observed, it reports `owner_active_not_observed` and skips the independent
inspection and STOP. The offline probe tests cover delayed activation and
the bounded wait. The next live check uses the same opt-in STOP command.

### Separate App Servers disagree about an active recheck — scoped live observation

The user ran source `3fecef1` on Codex CLI `0.171.0`, requesting
`gpt-6.1-sol/low`. Hashes matched runtime
`fe8fa3d9db8a23860c96ea7ca972a4855012c715b0d2b99249675135b3e6e45a`
and verifier
`a52250f63da57855459dd1ed4a967844a44ee15838a7eaf2ed76e1d6df2225bf`.
The owner progressed from idle to active, and reported active both before
and after the independent observer reported interrupted. No observer STOP
was attempted. The retained checkpoint was UNVERIFIED and its last event
was a finish with interrupted status and no exit code after owner cleanup.
The scratch sentinel was intact. This establishes a disagreement in the
tested topology. It does not establish a general rule for all Codex threads
or verify the retained STOP path.

The installed CLI offers a Unix listener and a stdio proxy with a socket
override. A metadata-only smoke attempt used a temporary private socket,
with no managed daemon changes or model turns. In the sandbox the server
exited before creating a socket with a read-only-filesystem diagnostic.
In the approved run the socket appeared but neither proxy completed
initialize within its three-second deadline. This leaves shared-server
client initialization unverified. Before any further inference probe,
verify two clients can initialize on the same private server, including
its intended disconnect and approval ownership behavior. Repeat inference
against the current independent stdio topology only if new evidence
justifies it.

### Shared private App Server transport smoke and STOP probe

Codex's Unix listener speaks WebSocket. The CLI proxy forwards raw bytes;
newline-delimited JSON sent directly to the proxy never performed the
WebSocket handshake. The diagnostic bridge translates one stdio JSON record
to one WebSocket text message. See the upstream
[Unix transport implementation](https://github.com/openai/codex/blob/main/codex-rs/app-server-transport/src/transport/unix_socket.rs).

A local metadata-only smoke with Codex CLI 0.171.0 and Python websockets
16.0 confirmed that two bridge clients initialized concurrently. The
second client read account metadata, disconnected, and the first client
then completed its own account read. The temporary server was stopped and
zero model turns were requested. No daemon settings or default ModelMate
transport were changed. This proves basic shared connectivity, with live
interruption and active-turn permission routing still outside that smoke.

To check scoped interruption through a second connection to the same server,
use the new opt-in verifier mode. It requires Python with
`websockets.sync.client.unix_connect` available for the diagnostic bridge.

```sh
codex --version
python3 verify.py --run-live --probe-rechecks gpt-6.1-sol --stop-retained-recheck --shared-stop-server
```

The probe uses a temporary private Unix socket and requests up to two
synthetic model turns. It keeps read-only/on-request settings, and the
verification flow grants no tool approval. The socket server is cleaned up
at exit. Native threads and the synthetic project scratch are retained.
A pass requires `transport: shared_private_unix_websocket`,
`activeRecheckObserved: passed`, `stopRpcAcknowledged: true`,
`nativeRecheckStopped: passed`, `finalCheckpoint: passed`, and an intact
sentinel. This probe covers the shared-server topology only.

### Shared private App Server STOP — scoped LIVE_VERIFIED

The user ran source `b92db7b` on Codex CLI `0.171.0`, requesting
`gpt-6.1-sol/low`. The runtime hash
`fe8fa3d9db8a23860c96ea7ca972a4855012c715b0d2b99249675135b3e6e45a`
and verifier hash
`d42af0eff5ad5e2d4b9b6877a2c06a9a99178d2c0b4e50156da69a3c139f21e9`
matched the checkout. With transport `shared_private_unix_websocket`, the
owner and observer both reported active. The interrupt was acknowledged
and the observer then reported interrupted. All eight STOP probe checks
passed, including the final checkpoint and unchanged sentinel. The initial
turn had one matching command start and completion. Scratch was retained.

This is scoped to two connections on the same private server while the
owner remains connected. Production `--recover-recheck` opens an independent
App Server. Permission request ownership on shared transport, owner loss,
runtime adoption and the missing-thread-ID case remain open.

### Shared-server recheck owner disconnect probe — offline verification

The opt-in probe verifies the same native turn is active from the owner and
observer, then closes the owner connection without sending an interrupt.
It requires the saved operation to become unknown without command evidence.
The observer then reads the original binding. If it remains active, the
probe uses the explicit STOP authorization and requires an acknowledged
interrupt and observed terminal state. If it is already terminal, the
probe records historical recovery without sending STOP. Both paths check
that the work bindings, history, counters and sentinel are preserved.

```sh
codex --version
python3 verify.py --run-live --probe-rechecks gpt-6.1-sol --stop-retained-recheck --shared-stop-server --disconnect-recheck-owner
```

This uses at most two synthetic turns and the same diagnostic Python
WebSocket dependency. The output reports `observedAfterOwnerDisconnect`;
a pass requires `ownerDetachedWithUnknownCheckpoint`,
`postDisconnectStateObserved` and `finalCheckpoint` all to pass. An
immediately terminal observation establishes the status at that read;
it does not alone establish the cause. The server and parent workflow
client remain connected through recovery. The probe covers owner connection
loss only, not server loss, approval ownership or production transport.

### Shared-server owner disconnect with a surviving turn — scoped LIVE_VERIFIED

The user ran source `ee5bc76` on Codex CLI `0.171.0`, requesting
`gpt-6.1-sol/low`. The checkout matched runtime SHA-256
`fe8fa3d9db8a23860c96ea7ca972a4855012c715b0d2b99249675135b3e6e45a`
and verifier SHA-256
`e3091bee9a0cab0bdb281fdedf70f2f789b44b5978f6535d7b51d216bdeb98dc`.
All nine disconnect probe checks passed. The observer saw the exact
bound turn active both before and after the owner disconnected. It sent
STOP through the surviving connection, received acknowledgement, and
then observed interrupted status. The retained checkpoint was UNVERIFIED
with an unknown finish followed by an interrupted reconcile event.
The sentinel was intact.

This covers the surviving-active branch with the App Server and parent
workflow client still running. Shared-server approval routing and pending
approval behavior on connection loss remain unverified, as do server
loss and installed runtime recovery through a shared transport.

### Shared-server pending file approval probe — offline verification

The opt-in probe starts a new private shared App Server and at most one
synthetic turn in a temporary read-only scratch project. The turn requests
one patch to a synthetic marker. The owner must receive a pending file
approval bound to that thread and turn, while a second, passive recovery
client sees the bound turn active. The passive client uses metadata RPCs
and aborts if it receives a server request. The probe disconnects the owner
without replying, then observes the same turn for up to ten seconds through
the surviving client. It sends no approval response or interrupt and checks
that the marker remains absent. It retains no scratch files and does not
delete native history.

```sh
codex --version
python3 verify.py --run-live --probe-shared-approval gpt-6.1-sol
```

This mode requires the diagnostic Python WebSocket dependency. A pass
requires `ownerPendingApprovalObserved`, `passiveObserverSawActive`,
`terminalAfterOwnerDisconnect`, and `markerAbsent` to report `passed`.
A missing request, request delivered to the passive observer, or turn
that stays active leaves the gate unverified. This probe covers one file
approval with a passive reader. It does not exercise additional subscribed
clients, command approvals, user acceptance or installed runtime behavior.

### Turn with a pending file approval remains active after owner disconnect

The user ran source `da10207` on Codex CLI `0.171.0`, requesting
`gpt-6.1-sol`. The runtime SHA-256
`fe8fa3d9db8a23860c96ea7ca972a4855012c715b0d2b99249675135b3e6e45a`
and verifier SHA-256
`377a16c93c74305936249f765a4ff01f95510358d4b21621a0511c5a7cad4e5e`
matched. The owning client received the bound file approval, the passive
observer saw the turn active, and the scratch marker stayed absent. The
turn was still active after the owner disconnected and through the last
observation in the bounded window. Terminal status and the fate of the
pending request were unverified. The run did not send STOP.

An optional action now tests whether explicit STOP can settle that same
active approval turn. It requires the surviving observer to confirm the
same thread/turn is active after owner disconnect before sending one
scoped interrupt. Neither client sends an approval response.

```sh
codex --version
python3 verify.py --run-live --probe-shared-approval gpt-6.1-sol --stop-orphaned-approval
```

The run uses at most one synthetic turn. A pass requires all four
shared approval checks, `orphanStopAcknowledged: true`, and
`observedTerminalStatus: interrupted`. This tests one interruption
with a passive observer. It does not verify approval requests for other
tools or subscribed clients.

### STOP after a file approval owner disconnects — scoped LIVE_VERIFIED

The user ran source `00c742f` on Codex CLI `0.171.0`, requesting
`gpt-6.1-sol/low`. The runtime SHA-256
`fe8fa3d9db8a23860c96ea7ca972a4855012c715b0d2b99249675135b3e6e45a`
and verifier SHA-256
`9c21f0cb3ba5d8e5c1dd653b5bf62e409e7ac67cac0a87cb618b07cbf498e5ae`
matched the checkout. One synthetic turn was requested. The owner received
the bound file approval, and the passive observer saw the same turn active
before and after the owner disconnected. The observer's scoped STOP was
acknowledged and it observed `interrupted`. All four checks passed, including
absence of the marker. Neither connection sent an approval response.

This verifies one file-approval path with a passive metadata observer on a
shared private App Server. It does not establish where requests go with
additional subscribed clients, what happens after server loss, or whether
the installed standalone runtime can recover through this transport.

### Standard-library private Unix WebSocket transport spike

The isolated `recheck_transport.py` spike validates the private directory,
socket inode, Linux peer credentials and owned process group before using
an endpoint. It pins the peer across connections and tests the HTTP Upgrade,
masked client frames, fragmented text, control frames, limits, deadlines
and socket cleanup. A fake subprocess covers startup timeout and confirms
that leaving the context removes only its own temporary directory. The
restricted execution sandbox disallows binding Unix sockets. The socket
tests were run with approval outside it, without inference.

A metadata-only smoke against Codex CLI `0.171.0` initialized two clients
using the new standard-library transport on the same private server.
The second performed an `account/read` and disconnected. The first could
still read account metadata. The context stopped the temporary server.
No model turns were requested and no account fields were reported.

The transport is an isolated spike. The runtime still needs a selector and
JSON-RPC integration, including independent deadlines for simultaneous
owner and observer operations, before a runtime inference probe.

### Private WebSocket through the shared JSON-RPC reader

The optional WebSocket connection now uses the runtime's existing JSON
validation, request IDs, RPC allowlists and selector entry points. The
incremental frame reader retains incomplete frames between readiness
events. The fake-server checks cover an interleaved notification and RPC
reply, and an unexpected approval request on the recovery observer,
which fails closed without a reply. Stdio remains the default path.

A metadata-only smoke on Codex CLI 0.171.0 used the updated `Connection`
with two private WebSocket clients. Both initialized, the second read
account metadata and disconnected, and the first then read account
metadata. No model turn was requested. The runtime CLI has no shared
transport selection yet. The attached-workflow ownership and recovery
UI remain to be wired and verified.

### Experimental runtime shared rechecks — offline implementation

Folded the private transport into the single Python runtime and exposed it
only for explicit shared experimental recheck resume. Offline checks cover
STOP token cancellation and single use, rejection of a foreign observed
turn, and equality between the reconciled controller checkpoint and saved
ledger. The in-session observer has the recovery allowlist. No inference was
run and this increment does not claim live runtime STOP.

### Runtime-owned private recheck STOP probe — offline verification

This probe keeps the work connection on stdio and enables the runtime's
experimental private recheck server on the resumed workflow. It drives
consent and STOP through the real ChatShell command handlers and writes
reconciliation through the attached controller under the existing writer
lock. It deliberately closes the recheck client after observing an active
owner, verifies the checkpoint is unknown, inspects the same binding through
the runtime observer and confirms STOP. It tests single-use confirmation,
stale evidence and equality of the saved checkpoint with the in-memory
controller. The CLI's interactive timing and process-loss recovery remain
outside the probe.

```sh
codex --version
python3 verify.py --run-live --probe-rechecks gpt-6.1-sol --stop-retained-recheck --runtime-shared-recheck
```

The mode uses at most two synthetic turns, with no Python WebSocket package
required. A pass requires `transport: runtime_private_unix_websocket`,
`ownerDetachedWithUnknownCheckpoint: passed`, `stopRpcAcknowledged: true`,
`observedAfterStop: interrupted`, `stopConfirmationSingleUse: passed` and
`finalCheckpoint: passed`, as well as an intact sentinel. The probe retains
the scratch session and native threads.

### Runtime-owned private recheck STOP — scoped LIVE_VERIFIED

The user ran source `132d80c` on Codex CLI `0.171.0`, requesting
`gpt-6.1-sol/low`. Runtime SHA-256
`0220dd6693d44776d0fad24db439d687a3e21fdf1fa7b8892d48bd017d7b6367`
and verifier SHA-256
`ef6392d68d6b944b12defd67be71dda504a7886c97d10430fe57c6617adc18a1`
matched the checkout. All ten checks passed on
`runtime_private_unix_websocket`. The owner progressed from idle to active.
After the recheck client closed, the attached runtime showed the original
binding active, sent one explicitly confirmed STOP, received acknowledgement
and observed interrupted. The token could not be reused.

Local inspection of the retained synthetic checkpoint confirmed UNVERIFIED
with an unknown finish followed by an interrupted reconcile event. The
event held no command exit code or item ID, and the sentinel was intact.
This covers the attached controller and shell handlers for a synthetic
recheck on the runtime-owned server. Interactive Terminal timing, loss of
the workflow or server, and discovery with a missing thread ID remain open.

### P12 recovery observer connection loss — MOCK_VERIFIED

Added a regression at the attached native workflow boundary. A synthetic recheck
first loses its owner connection. The recovery observer then raises a connection
error during inspection. Both the on-disk record and controller checkpoint remain
unchanged, the operation stays unknown, evidence stays stale, and the observer is
closed. A subsequent inspection reports the same operation active without an
interrupt or second `turn/start`.

`python3 -m unittest discover -s tests -p test_native_recheck.py -v` passed all
41 tests. `git diff --check` passed. No runtime behavior changed and no live
inference was requested. This mocks observer failure; it does not prove recovery
after an actual server or workflow process dies. Next eligible P12 work: exercise
actual owned-server loss offline and verify retained unknown bindings on resume.

### P12 terminated owned listener and controller reopen — MOCK_VERIFIED

The new regression creates an unknown recheck through the synthetic stdio server,
then points attached recovery at a real private Unix listener owned by
`private_recheck_server`. It terminates that fake listener process and waits for
its exit before attempting recovery. Connecting to the remaining socket fails
with connection refused. The session record and attached controller checkpoint
remain unchanged. Closing and reopening the controller preserves the exact
unknown operation and stale evidence; the synthetic trace contains only the
original `turn/start`.

`python3 -m unittest discover -s tests -p test_native_recheck.py -v` initially
reported 41 passed and one socket-permission skip in the restricted sandbox.
The approved run outside that sandbox passed all 42 tests without skips.
`git diff --check` passed. Runtime code was unchanged, so the full suite was not
rerun. No Codex process or live inference was used. This verifies refusal of a
dead owned endpoint with an existing durable binding; it does not simulate a
WebSocket turn being interrupted by server death or prove live Codex recovery.
Next eligible P12 work: offline loss of the workflow process while a recheck is
active, including writer-lock release and preservation of its unknown outcome.

### P12 abrupt workflow writer exit — MOCK_VERIFIED

A subprocess attaches to a saved synthetic workflow, reserves a recheck and
persists its thread/turn bindings, then calls `os._exit(23)` without controller or
store cleanup. The parent verifies that exit and reopens the same session. The
writer lock is available again. The ledger retains `turn_bound/pending`, which
means the result is unresolved, with the original native binding, stale evidence
and unchanged work-attempt counters. Both a new recheck reservation and a new
workflow attempt are refused. The original work thread/turn remain unchanged.

`python3 -m unittest discover -s tests -p test_recheck_ledger.py -v` passed all
14 tests. `git diff --check` passed. No runtime code changed and no inference was
requested. This tests process exit while durable state is bound, with no running
native backend; it does not prove a live backend stops when its owner dies.
Next eligible P12 work: test an active WebSocket recheck losing its server in
the offline transport/controller integration, then obtain user-run live evidence
for the remaining process-loss cases.

### P12 active WebSocket disconnect — MOCK_VERIFIED

Two synthetic WebSocket integration tests attach a durable parent workflow and
start a real `NativeRecheckConnection` through its normal metadata preflight,
reservation and turn dispatch. After acknowledging `turn/start`, the server drops
the connection either before command events or after started/completed command
events reporting exit code 0, without reporting turn completion. The latter test
checks that the command observer actually received that successful exit code.

In both paths, draining reports disconnection, the parent persists an unknown
recheck with no command exit code, and the old evidence stays stale. Disk and
controller checkpoints match. Reopening keeps the original operation binding and
refuses a new workflow attempt. The server records exactly one `turn/start` and
no `turn/interrupt`. No raw prompt or command output is saved to the evidence docs.

The initial sandbox run skipped the socket tests. The approved
`python3 -m unittest discover -s tests -p test_recheck_transport.py -v` run passed
all 14 tests without skips. No runtime code changed and no live inference was
requested. These tests verify a synthetic server disconnect, not Codex process
termination or live orphan-turn cleanup. Next eligible P12 work is a scoped,
explicitly opt-in live server-loss verifier with synthetic inputs and retained
unknown bindings; running it will require a user-requested live command.

The complete offline suite, `python3 -m unittest discover -s tests -v`, passed
all 560 tests with socket permissions enabled and no skips. `git diff --check`
also passed. The earlier restricted run passed with socket tests skipped and
does not substitute for this result.

### P12 owned-server-loss verifier — MOCK_VERIFIED

The opt-in recheck probe accepts `--terminate-recheck-server` only with the full
live/runtime-shared recheck selection below. It reuses the synthetic initial
check and durable resume setup, observes the recheck owner active, then exits
only the runtime-owned private server context. It requires the server process
to have exited and the recheck client to report backend disconnection. Timeout,
an unrelated exception or an already completed turn cannot pass that check.

The probe verifies the exact operation/thread/turn binding is retained as
unknown with no exit code/item ID, evidence is stale, and the attached checkpoint
matches disk. After a fresh account/quota/catalog read through the work connection,
it releases the writer and reopens the controller. Both work dispatch and a new
recheck reservation must be blocked by the unresolved operation. Original work
steps, attempt history and native work binding must stay intact.

Offline fake-server tests cover successful evidence collection, failure to observe
an active owner, mandatory opt-in flags, report sanitization and a nonzero CLI exit
when any required result is unverified. The 29 recheck-probe tests passed.
The complete offline suite passed all 563 tests without skips with socket
permissions enabled. Compile checks for modelmate.py, doctor.py and verify.py,
and `git diff --check`, also passed.

User-run live command (at most two subscription turns, retained synthetic scratch
and native threads; use a currently available model supporting low effort):

```sh
codex --version
python3 verify.py --run-live --probe-rechecks gpt-6.1-sol \
  --stop-retained-recheck --runtime-shared-recheck --terminate-recheck-server
```

Here `--stop-retained-recheck` selects the existing delayed-command setup;
`--terminate-recheck-server` replaces the STOP RPC with owned-server shutdown.
A pass requires every `SERVER_LOSS_KEYS` check to report passed, including
`ownedServerExited`, `disconnectObserved`, `unknownCheckpoint`, `resumeBlocksReplay`
and `finalCheckpoint`. Keep CLI version and the returned source hashes with the
sanitized results. Do not commit raw reports or local session records.

This probe is not live-verified. Even a pass proves local unknown-state handling,
not remote turn termination or orphan cleanup after App Server loss. Inspect the
retained turn through Codex before deciding how to proceed; do not replay it.
Next eligible P12 work: user-run evidence for this exact verifier version and
scoped inspection of the retained native outcome, without another inference turn.

### P12 owned process-group cleanup after leader exit — MOCK_VERIFIED

An offline regression starts a fake private server and its child in the owned
process group. The child installs a SIGTERM-ignore handler before advertising
readiness. The test terminates and waits for the server leader, confirms the
child is still running, then exits the private server context. Before the fix,
the child survived that context and the test failed. The regression has its own
fallback cleanup so a failure does not leave the synthetic worker running.

`private_recheck_server` now sends SIGTERM to its owned group regardless of the
leader's exit state, waits for the leader with the existing deadline, and sends
SIGKILL to remaining group members. It still removes only its private temporary
directory. The 15 offline transport tests passed with socket permissions enabled.
The full `python3 -m unittest discover -s tests -v` run passed all 564 tests
without skips with sockets enabled. Compile checks and `git diff --check` passed.
No live inference was run.

This covers local descendants that remain in the owned process group. It does
not establish remote cancellation, descendants that deliberately leave that
group, or live Codex server-loss behavior. Next eligible P12 gate remains the
user-run `--terminate-recheck-server` command above against this updated runtime.

### P12 experimental shared CLI on terminal input — MOCK_VERIFIED

A subprocess test invokes `modelmate.main` with experimental shared-recheck resume
flags and a real pseudoterminal for stdin, capturing stdout/stderr through pipes.
It drives START, recheck preview and explicit confirmation through the actual CLI
and selector loop. Before START no backend starts; before recheck confirmation no
child starts. A synthetic recheck disconnect leaves the parent available for
status and recovery commands. Cancelling a STOP preview makes its token invalid;
a fresh preview permits one exact interrupt, and reusing that token is rejected.
Exit leaves an interrupted reconcile event without marking the workflow DONE.
The synthetic traces contain one recheck `turn/start`, no replay of the work turn,
and exactly one `turn/interrupt` for the retained recheck binding.

`python3 -m unittest discover -s tests -p test_recheck_ui.py -v` passed all 23
tests. The updated shared synthetic fixture was also checked with the native
recheck tests: all 42 passed with sockets enabled (the initial restricted run
skipped one socket test). `git diff --check` passed. The full suite was not rerun
because only tests/fixtures and docs changed; both consumers of the fixture passed.
This test substitutes stdio fake servers for WebSocket clients
and the private server context; real socket/process ownership has separate
transport tests. It does not prove interactive live Codex behavior, actual
WebSocket approval routing, or process-loss recovery. Runtime code is unchanged.
Next eligible P12 gate remains user-run server-loss evidence, followed by scoped
live interactive CLI verification.

### P10 explicit human source checks — MOCK_VERIFIED

Explicit-plan workflows now accept source checks through the existing opt-in
entry. `/verify-source CHECK RESULT URL "checked claim and finding"` records
human-reviewed source evidence only in CHECKING after confirmed turn completion.
It uses the controller's existing source provenance, URL and finding validation.
It performs no HTTP request or inference and does not treat the presence of a
URL as proof. The user is responsible for checking support for the stated claim.

`/revalidate-source STEP.CHECK RESULT URL "checked claim and finding"` explicitly
rechecks saved source evidence after restore. The URL must match the saved source
and the verdict must agree with the saved result. Unknown/disagreeing results
leave evidence stale; changing the URL cannot clear it. Another restore makes
the evidence stale again. Source verdicts cannot substitute for test/lint exit
codes or manual/rubric checks, and model text does not invoke the UI commands.
User-supplied URL/findings stay in local checkpoint metadata, never metrics.

New offline coverage checks native entry without dispatch, out-of-phase and
malformed commands, invalid URLs/empty findings, duplicate evidence, pass/fail/
unknown outcomes, explicit criterion acceptance and repeated restore/revalidation.
All 20 targeted workflow-entry tests passed. The complete offline suite passed
all 567 tests without skips with sockets enabled. Compile checks for runtime,
doctor and verifier, plus `git diff --check`, passed. No live inference or web
request was run. This is explicit human verification, not automatic source
retrieval, automatic fact checking, a passed G3 gate or full workflow release.
Next eligible P10 work: scoped live source-check workflow evidence; the pending
P12 live server-loss command remains a separate gate.

### P10 durable source checks across native resume — MOCK_VERIFIED

A native-protocol integration test records source evidence through the UI,
persists the first step, closes its backend and resumes the same durable workflow
with a second synthetic backend process. The first source finding returns stale.
The second step records its own source finding, and task completion stays blocked
until explicit revalidation of the first saved URL. Both work attempts remain at
one, source findings persist unchanged, and exactly two turns and one native
resume are observed. Neither source URL nor synthetic private finding appears
in any model-turn input captured by the fake server.

`python3 -m unittest discover -s tests -p test_native_resume.py -v` passed all
12 tests. `git diff --check` passed. Only a test and evidence docs changed, so
the full suite was not rerun. No HTTP request or live inference was run. This
proves the tested metadata-to-dispatch path, not a general private-context
isolation boundary. Live source-workflow and server-loss evidence remain open.

### P16 requirement coverage audit — release incomplete

RELEASE_CHECKLIST.md now maps all R01–R13 to their current implementation,
offline test files and outstanding implementation or live-evidence gaps. The
audit checked the actual fixed `/permissions` behavior, the workflow host's
unsupported-approval denial, explicit-plan entry, source commands and standalone
confirmed-query search, alongside existing test/evaluation records. It makes
workflow approval acceptance, automatic search integration, comparative routing
quality and remaining lifecycle gates visible rather than inferring completion
from the offline suite. P16 status is IN_PROGRESS for preparatory evaluation and
audit work; no dependency or release gate is marked passed.

Documentation-only audit: `git diff --check` passed. Referenced test files were
checked for existence; no tests, web lookup or inference were rerun for this
documentation change. Existing verification records retain their original scope.

### P09 patch preview identity and token invalidation — MOCK_VERIFIED

Inspection found that the manual native shell retained a usable approval token
after a file-change item's preview changed. Tokens now retain their original
thread/turn/item binding and displayed patch. New events that change or invalidate
the diff, reuse the item identity for another type, or complete the item decline
the pending request and expire its token immediately. Reverting to the old diff
does not revive the token. An unchanged repeated preview preserves one-use
approval. An additional check at decision time refuses mismatched cached patches.
Malformed change entries without a nonempty path and diff cannot supply a preview.

The regression covers changed diff, invalid changes, missing diff, changed item
type, completion and unchanged-repeat cases. It checks the exact decline/accept
response, one response only, stale-token rejection and non-revival after restoring
the original diff. A separate regression repeats a pending command request ID
with a changed command: the controller sends one decline, clears the visible
token and rejects any later attempt to accept it. All 15 `test_live.py` offline
tests passed. Compile checks and
`git diff --check` passed. No live inference ran and no workflow approval path was
enabled. Next eligible P09 work: reuse the hardened approval boundary in a gated
workflow adapter, retaining independent model/tool approvals and unsupported-path
denial; live permission matrix evidence remains required.
The full `python3 -m unittest discover -s tests -v` run passed all 570 tests
without skips with socket permissions enabled.

### P09 installed-schema patch updates and approval scopes — MOCK_VERIFIED

Inspected Codex CLI 0.171.0 using `codex --version` and
`codex app-server generate-json-schema --out /tmp/modelmate-p09-schema`.
This generated protocol descriptions without opening a model turn or reading an
account. The installed schema defines `item/fileChange/patchUpdated` with active
thread/turn/item IDs and replacement changes. The manual shell previously ignored
that event, so a real native patch update could leave its earlier token valid.
The event now uses the same preview validation and token invalidation as file
item starts. A changed patch is declined; a new request needs a new token and
shows the new diff. Foreign-turn updates do not mutate the active preview.

The same schema distinguishes command approvals from `writeStdin` and
`humanCommand`, opaque subcommand callbacks, nonlocal environments, managed-network
context and file-change `grantRoot` requests. These scopes are not represented by
the current command/diff UI and now decline explicitly without creating an
accept token. Normal accept-once handling remains available; no session or policy
amendment accept decision was added. Unknown server-request methods still stop.

All 18 `test_live.py` offline tests passed, covering native updates, re-preview,
foreign/malformed updates and each declined scope. Compile checks and
`git diff --check` passed. Source/schema checks are not live permission evidence.
The full offline suite passed all 573 tests with sockets enabled and no skips.
Workflow approval acceptance remains gated; no live inference was run. Next P09
work is integration using the explicitly supported command/file-change subset,
followed by the required live permission matrix.

### P09 durable controller tool-decision state — MOCK_VERIFIED

The controller now supports a distinct AWAITING_TOOL_APPROVAL state through
trusted host/UI APIs. A request belongs to a controller-owned attempt/step and
contains validated thread/turn/item/request IDs, command/file-change kind and
an exact action digest supplied by the trusted host. The host remains responsible
for validating and displaying the actual native action and calculating its digest.
This controller API is not exposed to model text or plan proposals.

Workflow checkpoint V3 retains the latest request's status and transition time
alongside the existing recheck ledger. It saves no approval token, raw command,
diff or credentials. Tokens are process-local and one-use. A matching explicit
tool decision is persisted before returning one accept/decline descriptor; it
does not send an RPC, execute anything, consume another attempt or create test
evidence. Model approval cannot answer the tool request. A changed native binding
or action digest expires the old token rather than allowing it to revive.

Pause, terminal observation and restore expire pending tokens. Restore retains
the binding for inspection and pauses the still-running attempt with unknown
outcome, so a historical approved status never restores a grant. A failed or
uncertain write exposes no usable token/accept descriptor and freezes the
controller until reopening. V1/V2 checkpoints remain readable and rechecks can
still append under V3; older runtimes reject the new version.

Nine focused `test_permissions.py` offline tests passed. The full offline suite
passed 581 tests without skips with sockets enabled; the final additional
uncertain-request-write test was then run in the nine-test targeted suite.
Compile checks and `git diff --check` passed. No live inference ran. Native
workflow requests still take the existing decline/stop path: no new execution
permission or public flag has been enabled. Next eligible P09 work is native/UI
adapter wiring using the hardened request subset, with live G2 proof still required.

### P09 workflow host and UI tool-decision wiring — MOCK_VERIFIED

WorkflowHost accepts an optional trusted tool-response callback. A native adapter
can offer a validated action only for the host's active thread/turn and running
controller attempt. The bounded, terminal-safe full preview is hashed by the host
and bound to the controller request. ChatShell reads that authoritative request,
obtains the unchanged host preview and displays it before exposing the tool token.
The native adapter is still responsible for validating the action's protocol
schema and ensuring the preview represents the exact executable action.

Tool `/approve`, `/decline` and `/pause` route through the host and durable
controller decision before a response callback. `--next` remains a model-choice
option and is rejected for tool approval. Model text cannot invoke the command,
and approval does not start another turn or create check evidence. Changed
preview or native binding expires the confirmation. A failed response pauses
with connection_lost and cannot be resent using the consumed token.

Cancel, exit, explicit pause, deadline expiry and disconnect attempt one decline
and one native interrupt. A real input-EOF/selector test confirms that an
interrupted event is observed before exit, without marking the task DONE. Other
focused tests cover preview-before-token order, stale and wrong tokens, model
output injection, exact one-use acceptance, unsafe previews, unsupported adapters,
bound-action changes and response-send failure. All 15 test_permissions.py tests
passed. Compile checks and `git diff --check` passed.

This is trusted-host/UI integration only. NativeWorkflowConnection still declines
server approval requests, and no public flag enables acceptance. No live inference
ran. Next eligible P09 work: connect the hardened native request subset to this
host/UI path under an explicit experimental gate, then obtain live G2 evidence.
The complete offline suite passed all 588 tests with sockets enabled and no skips.

### P09 opt-in native workflow approval adapter — MOCK_VERIFIED

`--experimental-tool-approvals` explicitly selects the supported native command/
file-change subset for work turns. Preview is offline, execute still requires
START, and each tool request needs its own exact UI decision. Manual chat and
the adapter share native request/scope validation and bounded patch caching.
Thread/turn/item/request IDs, controller attempt and action digest must match the
current native action and saved checkpoint before a single response is sent.
No session/policy-amendment accept decision or sandbox profile change was added.

Native patch updates and reused/completed item identities invalidate pending
actions. Duplicate request IDs decline once and stop; overlapping requests do
not replace the visible action. Unsupported scopes, missing previews, malformed
or foreign requests cannot obtain acceptance. The response handle is consumed
before send, so a failed send has unknown outcome and is not retried. Direct
close with a pending request attempts decline and interruption before cleanup.
Restored historical decisions never restore native handles or confirmation tokens.

The synthetic native server writes a test-owned marker only after receiving
accept and independently reading a matching approved decision from disk. Command
and patch cases show no marker before consent, one response after consent, and
no task completion from approval alone. Decline, close, patch changes, unsupported
scope, absent diff, duplicate IDs and foreign requests leave the marker absent.
Only matching completed command observations supply tool-check evidence.

All five native-permission integration tests, 18 manual approval tests and 21
workflow-entry tests passed. The full offline suite passed all 594 tests without
skips with sockets enabled. Final entry tests also checked CLI flag forwarding
and callback setup; compile checks and `git diff --check` passed. No live inference
was run. Fake-server effects do not prove live sandbox enforcement or G2.

Default workflow behavior remains decline-only. Recheck child connections do
not inherit this parent flag and still decline approvals. The supported work-turn
path is experimental and not live-verified. Next eligible P09 work: an explicitly
opt-in synthetic verifier covering real native accept/decline, changed actions,
EOF/cancel and sentinel preservation, followed by user-run live evidence.

### P09 scoped native command-approval verifier — MOCK_VERIFIED

Prepared an opt-in verifier with at most two synthetic turns in separate durable
scratch projects. The first case may accept exactly one registered printf command
that writes a random synthetic line to approval-marker.txt in that case's cwd.
The second case declines its corresponding command. It accepts the literal
command or the runtime's supported exact shell-argv wrapper, never rewritten
shell code. Unexpected command/cwd/kind, missing approval or additional requests
cannot produce a passing report and are not retried.

Before acceptance, the harness checks that the full bound preview was displayed,
the marker is absent, the sentinel/project file scope is intact, and no registered
command completion preceded consent. Its send tripwire allows accept only for
the explicitly armed request ID/digest and approved controller status. A second
use of the token must leave both the checkpoint and response count unchanged.
After acceptance it requires exact marker content, a matching native item and
observed exit code 0 on a completed turn. After decline it requires terminal
status, absent marker and intact sentinel. Historical decisions must match disk;
approval alone must not mark the task DONE.

Eight offline probe tests passed: success, missing approval, unexpected command,
early file effect, early command completion with absent marker, missing native
completion despite a marker, unarmed-accept blocking and CLI opt-in/partial-result
exit status. Fake processes simulate both sides; no installed Codex inference or
web request was run. Compile checks and `git diff --check` passed.
The complete offline suite passed all 602 tests with sockets enabled and no skips;
the focused verifier suite also passed after the final accept-tripwire checks.

User-run live command (up to two subscription turns; explicitly authorizes only
the bounded synthetic marker write above, then a denial; retains scratch and
native threads):

```sh
codex --version
python3 verify.py --run-live --probe-workflow-approvals gpt-6.1-sol
```

Use a current available model supporting low effort. Keep the CLI version and
returned runtime/verifier hashes with sanitized results. All seven
WORKFLOW_APPROVAL_KEYS checks must be passed for exit 0. Missing approvals may
reflect native sandbox-permitted behavior; they do not prove this approval path.
Do not expand permissions to force a pass or rerun inference merely for tests.

This is not live-verified. Even a pass covers only the registered command
accept/decline path, not patch approval, every G2 permission path, process-loss
recovery, interactive timing or a no-tools boundary. Raw traces, local IDs and
reports must not be committed. Next P09 gate: user-run results for this exact
verifier, followed by separately scoped patch/cancel/failure-path evidence.

### P09 native cancellation, process loss and shutdown input — MOCK_VERIFIED

Expanded the synthetic native handshake tests to cover cancel, exit, timeout,
disconnect and actual input EOF while a command approval is pending. Each sends
one decline and one interrupt, observes an interrupted terminal event, performs
no marker effect and sends no extra turn. Old tokens cannot be accepted later.

Killing the fake server while waiting reproduced a shared cleanup bug:
Connection.close raised BrokenPipeError again while closing buffered stdin and
stopped before closing output pipes. Shutdown now closes the raw input pipe
before its wrapper, discarding any unsent buffered action. A forked-reader test
keeps a synthetic reader alive after the server leader exits; it receives EOF
with zero bytes, rather than a late buffered action. All three pipes close.
The dead-server workflow reopens with its original running attempt unresolved,
the same attempt count, no restored permission and no replay.

A separate test loses the client result after an accept response was actually
written. The fake server performs the authorized file effect, while the client
pauses with connection_lost and cannot resend the consumed acceptance. This
explicitly does not claim that a connection error rolls back an accepted action.

All nine native-permission tests and nine protocol tests passed. Compile checks
and `git diff --check` passed. No live inference or network request was run; these
are local synthetic processes and test-owned effects. The shared close change
applies to diagnostics and both native transports' stdio callers. Next eligible
P09 gate remains the user-run command-approval verifier; live cancellation and
other G2 paths still need scoped evidence.
The complete offline suite passed all 607 tests with sockets enabled and no skips.

### P09 supported approval fields and installed CLI 0.172.0 schema — MOCK_VERIFIED

`codex --version` now reports 0.172.0. Generated its protocol descriptions with
`codex app-server generate-json-schema --out /tmp/modelmate-p09-schema-0172`.
Compared parsed JSON with the prior 0.171.0 descriptions: command/file approval
params and responses plus FileChangePatchUpdatedNotification match exactly.
This is schema inspection only, not a live account or permission check. Existing
0.171.0 live records retain their original version and scope.

The shared manual/workflow approval validator now rejects unknown top-level
request fields rather than ignoring a possible new permission scope. It checks
provided reason/timestamp/list metadata types and bounds. Legacy requests that
omit the newer timestamp remain supported. Patch changes require the supported
path/diff/kind fields, an add/delete/update kind, and valid optional update
move_path metadata; unknown or malformed kinds invalidate the cached preview.

The strict boundary exposed command/cwd fields incorrectly included in a fake
file-approval request. Fixed that fixture to match the real file-request schema
rather than expanding accepted fields. Tests cover an unknown additional write
permission, malformed metadata, unknown patch kinds and invalid rename metadata.
A positive known-metadata case confirms that the response is plain accept-once,
without choosing a proposed policy amendment or changing the read-only profile.
The native fake-server unknown-scope case leaves its file effect absent.

All 19 manual approval tests and nine native permission tests passed. Compile
checks and `git diff --check` passed. No live inference was run; the requested
user-run P09/G2 result remains pending. Next gate remains the scoped live command
approval verifier, with CLI version and source hashes recorded from that run.
The full offline suite passed all 608 tests with socket permissions enabled and
no skips. No inference evidence is inferred from the schema comparison or suite.

### P14 delayed work-turn metrics — MOCK_VERIFIED

Previously the metrics observer accepted only the most recently dispatched turn.
A delayed usage event for an earlier attempt was discarded after the next start.
It now keeps process-local measurement bindings for all work turns dispatched in
the current CLI session, routing usage, reroute and terminal observations to the
matching attempt. This does not alter controller evidence or permission grants.
Native IDs remain internal and are absent from measurement output.

The focused metrics suite passed eight tests, including a regression with two
bound turns: delayed usage and failed terminal update the earlier attempt,
duplicate terminal events count once, unknown/foreign bindings are ignored, and
the later attempt stays unknown. Compile checks passed. No live inference or
external network request was run. Elapsed time remains client-observed through
receipt of terminal status, not isolated model compute time. P14 remains open
for the missing telemetry and live evidence listed in RELEASE_CHECKLIST.md.
The complete offline suite passed all 609 tests with test-owned sockets enabled
and no skips. `git diff --check` passed.

### P09 scoped native patch-approval verifier — MOCK_VERIFIED

Prepared a separate opt-in mode using the existing durable approval harness:

```sh
codex --version
python3 verify.py --run-live --probe-workflow-patches MODEL
```

This command has not been run live. It requests at most two synthetic turns in
separate retained scratch projects. The first may accept one native file-change
request adding only approval-marker.txt with one random synthetic line and a
newline; the second declines its corresponding request. Commands are not
registered or requested by this patch probe. Sandbox-permitted activity is not
intercepted by this harness, so this is not a no-tools or general isolation test.

Before arming the existing accept tripwire, the verifier requires the complete
displayed preview to contain exactly one add change at the marker's relative or
exact absolute path, with no extra fields. Its diff must be exactly the new
content or that one line prefixed with plus. Other encodings, additional lines,
paths, changes, update/delete kinds or rename metadata cannot be accepted. These
are deliberately narrow recognized encodings, not a general patch parser or a
claim about all live Codex diff formats. Unexpected/unsupported previews stop
without retries or permission expansion.

File scope and sentinel checks precede consent. An already observed native file
completion also fails the pre-consent check even if no marker exists. Acceptance
must be followed by one completed native file item with the approved item ID and
matching changes, exact marker contents and a completed turn. File existence or
a model's claim alone cannot pass. Decline requires a terminal turn, absent marker
and no passing controller check. Both cases retain one-use token, durable decision
and no-automatic-DONE checks from the command probe. Reports omit the nonce,
paths and native IDs, retaining only source hashes and sanitized outcomes.

All 15 focused approval-probe tests passed against synthetic subprocesses.
Patch cases cover accept/decline, early file effects and native completion,
unexpected content, failed native completion despite a correct marker, matcher
boundaries, and CLI opt-in/mutual exclusion. Existing command-probe cases still
pass. Entry-point compile checks passed; no inference or external web request
was run. Next eligible evidence remains user-run command approval, followed by
this separate patch probe with the exact CLI version/runtime/verifier hashes.
Neither prepared probe satisfies the full live G2 matrix.

The first full offline run completed 616 tests with one recheck-probe error:
the owner-active observation reason was absent. Inspection found that a bounded
metadata RPC error could exit before the polling loop recorded that reason;
the exact underlying error from the first run was not captured. The helper now records the
unobserved reason before polling and removes it only on an observed active
owner. RPC errors still propagate, the original timeout is restored, and no
observer query or STOP success is implied. A deterministic exception regression
checks this behavior; all 30 focused recheck-probe tests passed after the fix.
The final full offline suite passed all 617 tests with test-owned sockets enabled
and no skips. Compile checks and `git diff --check` passed.

### P08/P10 explicit pre-start clarification answers — MOCK_VERIFIED

New workflow previews number their pending questions. Repeatable
`--clarification NUMBER=ANSWER` arguments can answer those questions before
controller creation. Every question needs exactly one nonempty bounded answer;
unknown or duplicate numbers, incomplete answers and an oversized resulting
goal fail before backend access. Answers may contain equals signs and Unicode.
Question/answer pairs are placed in question order in the effective goal and
the complete plan is revalidated. The original plan file is not rewritten.

This uses the existing plan schema and durable checkpoint. It does not revise
steps or success criteria, change the mode, grant tool/model permissions, or
generate a plan. Resume rejects the option before reading saved state. Answers
appear in the normal goal preview before START, reach subsequent work-turn goal
input and are retained as part of the effective plan in local metadata.
Unanswered plans remain CLARIFYING and cannot execute. Complete answers still
require START and the usual `/next` and approval gates.

All 26 focused workflow-entry tests passed. New cases cover numbered offline
preview, out-of-order answers, Thai text and embedded equals, invalid/partial
and oversized input, cancellation/EOF, resume rejection and CLI forwarding.
A synthetic native server receives the resolved goal and its checkpoint; an
answer requesting blanket approval produces no grants or tool-policy change.
The original source plan remains identical. Compile checks passed. No installed
Codex inference or external network request was run. Live clarification entry
and broader automated workflow behavior remain unverified.
The full offline suite passed all 622 tests with test-owned sockets enabled and
no skips. Compile checks and `git diff --check` passed.

### P13 confirmed search-result handoff — MOCK_VERIFIED

Standalone Wikipedia/SearXNG commands accept `--search-json`. Exact query
confirmation is still required; prompts and the token use stderr and stdout
receives one versioned JSON packet only after a successful search. The packet
contains the approved query, destination/provider and passive title/excerpt/URL
results. It includes no confirmation token or trailing input/history. Cancellation
emits no packet and performs no search. Export does not start a model turn.

A new workflow can import selected `--source-result FILE:NUMBER` candidates
before preview/START. JSON input is bounded to 32 KiB, rejects duplicate keys,
unknown fields/versions, malformed text/hosts and non-HTTP(S) or credential-bearing
URLs. Up to five results may be selected, numbered from one. Candidates become
explicitly labeled untrusted goal data in the effective plan, subject to the
existing 4096-character goal and complete-plan limits. Oversized context fails;
it is not silently truncated. Source plans, steps and criteria are unchanged.
Resume rejects the option rather than rewriting an existing plan.

Import neither searches nor follows any URL. Packets are not authenticated
provenance, source verification, evidence or permission grants. They may contain
injection text, which remains input data under the existing controller/permission
rules. Explicit source verdicts still require separate human `/verify-source`
checks. Hosted search remains disabled in work threads; this manual return path
does not enable automatic/private-context query generation or satisfy full G3.

All 13 web-policy and 30 workflow-entry tests passed. New cases check JSON-only
stdout, separate confirmation, cancellation, packet validation, selected-result
preview, malformed/oversized imports, EOF/START and resume/CLI restrictions.
The synthetic native entry test receives the chosen URL and injection text in
the work goal and durable checkpoint, with no grants, changed criteria or tool
policy. It excludes the unselected URL and forbids HTTP during import/dispatch.
Compile checks passed. No installed Codex inference, public HTTP lookup or live
G3 evidence was produced. Next P13 evidence is live export/import of a public
candidate and SearXNG validation; automatic isolation remains separate work.
The full offline suite passed all 630 tests with test-owned sockets enabled and
no skips. Entry-point compile checks and `git diff --check` passed.

### P12 terminal work-turn correlation after missing start binding — MOCK_VERIFIED

Default native work dispatch now sends its controller-reserved attempt ID as
clientUserMessageId. For durable workflows, that ID is persisted before turn/start.
Explicit recheck markers retain their existing override. The marker supports
metadata correlation, not remote idempotency or a license to replay a request.

Explicit native resume may recover a missing turn ID on a known work thread.
It requires complete full history of at most 100 turns, a latest terminal turn
with exactly one matching user item, no duplicate turn IDs or matching markers
in older history, and terminal/full metadata for all returned turns. Any cursor,
missing marker, malformed/ambiguous history or active turn remains unresolved.
The correlated ID/status must match the separately observed latest summary.
After thread resume and permission validation, another summary must still match
before the binding is saved. History is not printed or copied into local state.

The original attempt/counters are preserved. Native completion creates no fresh
test/source/manual pass or restored grant; normal evidence checks are still
needed. This does not discover a missing thread ID or widen the CLI's existing
manual/rubric/source versus experimental tool-check resume requirements.

All 16 focused native-resume tests passed. A fake server persists a turn and then
actually exits before sending the start reply. A new process recovers that same
attempt from the original checkpoint, with one total turn/start, no interrupt,
no check evidence and no additional attempt. A second-step malformed start reply
and failed native-binding write also recover the new turn, never the old one.
Unmatched markers leave disk unchanged; changed latest history after resume is
rejected before saving a binding. Helper tests reject incomplete, duplicated,
misordered, nonterminal and malformed metadata.

Two old rejection assertions were replaced with positive exact-binding and
counter/evidence assertions now that matching correlation is implemented; the
unmatched-marker rejection remains explicit. Compile checks passed. These are
synthetic process tests, not live inference evidence. The earlier scoped live
client-ID/recheck records do not prove this multi-turn work-resume path or current
CLI compatibility. Next eligible evidence is a separately scoped live lost-work
binding check; active/missing-thread and broader server-loss recovery stay open.
The full offline suite passed all 634 tests with test-owned sockets enabled and
no skips. Compile checks and `git diff --check` passed.

### P12 resume-only work-recovery verifier — MOCK_VERIFIED

Prepared an explicitly invoked, zero-new-turn diagnostic:

```sh
codex --version
python3 verify.py --probe-work-recovery SCRATCH
```

SCRATCH must be a successful two-turn `--probe-workflow-resume` result with the
new work-attempt markers (runtime `e46a1d2` or later). This command itself takes
no `--run-live`, and refuses combinations with live modes or another recovery
probe. Creating a fresh source remains a separate explicit two-subscription-turn
command: `python3 verify.py --run-live --probe-workflow-resume MODEL`.

The source must be a completed synthetic two-step manual-check workflow, one
attempt per step with no recheck/tool-approval ledger. The verifier reads it
without writing, validates the sentinel, and creates a private metadata copy.
Only on that copy, it moves the final attempt back to its reserved running
state, removes its native turn binding/check evidence and criterion coverage,
and retains all IDs, selections, counters and earlier history. The ordinary
native resume path must correlate the existing final turn and reach CHECKING.
This is a staged missing checkpoint field after completion, not actual live
reply loss. Fresh account/quota/catalog/permissions remain required.

A dedicated send allowlist permits metadata requests and thread/resume only;
turn/thread start, interrupt, delete and any server-request approval/error reply
are rejected before transport. Passing requires all five WORK_RECOVERY_KEYS:
nativeBindingRecovered, attemptPreserved, noFreshEvidenceOrGrants, noReplay and
sourceUnchanged. Earlier evidence must remain stale and the recovered attempt
must have no checks/grants/criterion coverage. Reports contain source hashes and
sanitized outcomes, not prompts, markers, account/native IDs or source paths.
Successful verification removes only the owned copy. Failure retains it and
prints its local path on stderr; original metadata and project remain untouched.

All 14 focused workflow-resume probe tests and seven existing recheck-recovery
probe tests passed. New tests exercise successful two-turn-copy recovery with
zero additional turn/start RPCs, unchanged source bytes, marker absence,
invented evidence detection, incomplete-source rejection, pre-transport mutation
tripwires and CLI exclusivity/partial-result exit status. The staging fixture
was corrected to use RUNNING step state under an active reservation and compare
canonical exported history rather than its internal check dictionaries; runtime
checkpoint validation was retained. Compile checks passed. No installed Codex
inference or connected account lookup was run. Live work recovery, actual process
loss, active interruption and missing-thread discovery remain unverified.
The full offline suite passed all 640 tests with test-owned sockets enabled and
no skips. Entry-point compile checks and `git diff --check` passed.

### P08 current-step revision command — MOCK_VERIFIED

The workflow UI now exposes the existing controller revision API as
`/revise-step FILE`. Its UTF-8 JSON file is bounded to 64 KiB, must be a nonempty
object, and accepts only objective/role/effort/reason fields. Duplicate keys,
unknown fields, invalid values, oversized input and unreadable files fail without
changing the controller. The UI copies the effective current plan and changes
only that step before the controller revalidates the complete proposal. Thus
prior clarification/source context in the goal is retained without requiring
users to recreate the full effective plan file.

The command dispatches nothing and grants no permissions. It invalidates old
model/plan approvals, retains baseline/criteria/structure/step IDs/counters, and
persists through the existing session attachment. Existing role bindings and a
fresh supported catalog selection remain required at `/next`. Any active attempt,
including a completed turn still awaiting check evaluation, prevents revision.
Finished tasks cannot be revised. Budget exhaustion still requires its explicit
extension choice; renaming or changing approach cannot create a fourth attempt.

All 24 focused UI tests passed. New cases exercise downgrade after a pending
model request with stale-token rejection, approved-plan invalidation, three failed
attempts followed by revision without a hidden retry, malformed/unknown/oversized
input, active-attempt rejection before file reading, and durable revision/restore
with the effective goal and identities unchanged. Paths with spaces and Thai
text work. A displayed model text containing the command does not execute it.
Compile checks passed. No installed Codex inference or external network request
was run. This exposes existing explicit-plan control; automatic workflow and live
revision evidence remain separate unfinished work.
The full offline suite passed all 645 tests with test-owned sockets enabled and
no skips. Entry-point compile checks and `git diff --check` passed.

### P07/P08 explicit current-step model selection — MOCK_VERIFIED

Workflow `/model` now displays the proposed current selection, existing role
bindings and last-known catalog. `/model ID [EFFORT]` selects an available bound
model for the current step only; omitted effort uses the catalog default. It
retains the current role if it already binds that ID, otherwise requires one
unambiguous role. Unbound IDs and ambiguous alternative roles require explicit
bindings/role revision instead of inferring quality from model names.

The controller validates the catalog, baseline and complete revised plan before
using its existing revision/persistence and manual step-grant mechanisms. Goal,
criteria, structure, baseline, IDs, counters and future step proposals remain
unchanged. It cannot remove required strong review or modify an active/finished
attempt. Selection does not dispatch work, buy quota, authorize tools or approve
the entire plan. Approve plan still requests its plan grant; the next strong step
still requests its own authorization. Native `/next` retains fresh admission.

The checkpoint stores the revised role/effort/reason proposal, not the ephemeral
grant or role-binding configuration. Restore resolves user-supplied bindings and
requires model approval anew. A reason string or displayed model command cannot
create consent. Old pending tokens expire when the proposal changes.

All 27 controller and 27 UI tests passed. New cases cover step-only consent across
two strong steps, unchanged baseline, independent plan approval, removed catalog
entries before dispatch, invalid/unbound/ambiguous selections, preserving a known
role when IDs alias, required strong-review enforcement, non-dispatch UI choice,
active-attempt rejection, stale-token expiry, selected effort and durable restore
without grants. Compile checks passed. No installed Codex inference or network
request was run; live manual selection and broader automation remain open.
The full offline suite passed all 652 tests with test-owned sockets enabled and
no skips. Entry-point compile checks and `git diff --check` passed.

### P16 C2 CLI authoring fixture and frozen acceptance — MOCK_VERIFIED

`examples/routing-pilot.py prepare --case cli` now creates two identical CLI
projects with an incomplete rows.py and public UTF-8 input containing a blank
row. C2 requires implementing --limit N while preserving default output, input
encoding, help description and error exits. The routed arm uses the existing
test-check suggestion (economy/low); the baseline binds strong/low. Standard
baseline and economy/strong bindings remain explicit and distinct. There is one
implementation step, not a supplied repair choice or a mandatory strong review.

The prepared native command binds the trusted checker hash. It reads a bounded
byte snapshot, checks that hash and executes that same snapshot; changing the
checker cannot replace acceptance with a model's report. The checker uses
isolated Python candidate invocations, two-second deadlines and bounded private
temporary stdout/stderr files. Child file-size caps never raise an existing
stricter host limit. Timeout stops without another candidate invocation. Fixed
checks cover default/zero/before-path/blank-row/over-limit output, negative and
noninteger limits, help, unknown options, missing files and unchanged input.
Reports contain booleans or sanitized error reasons, not candidate output.
This is not a hostile-code sandbox or proof of the full G2 permission boundary.

Preview is offline. CLI authoring execution requires both --execute and explicit
--experimental-tool-approvals, followed by the runtime's START/model/tool gates;
the helper never enables acceptance silently. The registered checker runs within
that approved native workflow, not a host-side scorer of model-authored code.
Before launching any pilot runtime, the helper compares its copy with the
current checkout. C2 also compares the checker, original candidate/input, plan
and commands with trusted regenerated fixtures, and rejects an arm that already
has state. It does not overwrite changed artifacts or restart a prior attempt.
Old prepared runtimes need their original matching checkout or a fresh pair.

Seven C2 tests and six existing routing-pilot tests passed. Tests use only
developer-written initial/reference/mutant programs: initial code fails the new
option, the audited reference passes all eleven booleans, and an off-by-one
mutant/input mutation fails. Checker replacement is blocked before executing its
marker write. Other cases verify identical arm inputs/commands, offline previews
in paths with spaces, explicit approval forwarding, stricter resource limits,
timeout non-replay, and artifact/state rejection before subprocess launch.
The first complete offline run passed 658 tests before the additional preflight
artifact guards were added; focused checks then passed with those guards and
bounded reads. Compile checks and `git diff --check` passed.

No model-authored C2 repair, live pair, inference or external request was run.
There is no C2 quality/quota result and no new trained routing rule. The real-task
calibration/held-out deliverable, live approval gates and broader G5 remain open.
The final full offline suite passed all 659 tests with test-owned sockets enabled
and no skips. Runtime/diagnostic/example compile checks and `git diff --check` passed.

### P12 terminal resume with missing/unknown check results — MOCK_VERIFIED

The experimental tool-check CLI previously rejected a cached active attempt unless
it was already completed with known test/lint results, preventing native terminal
reconciliation from handling missing check observations. That early rejection is
removed only behind the existing experimental recheck opt-in. Native resume still
requires fresh account/quota/catalog, the same project/thread, a matching terminal
turn or its validated correlation, and read-only/on-request permissions. Active
native work and unresolved recheck operations remain blocked. Default tool-check
resume is unchanged and still disabled.

Unknown evidence can now be retired through normal check evaluation as UNVERIFIED
history after restore. A stale known pass/fail still blocks evaluation until its
trusted matching revalidation. Unknown cannot be revalidated to pass, accepted as
criterion evidence, or advance the step. Evidence/attempt IDs, history and counters
are retained. A fresh explicitly started correction can later supply independent
trusted tool evidence under the same budget; it does not replace the old unknown.
The UI states that missing observations do not mean the command never ran and
asks the user to inspect effects before authorizing another attempt. Resume and
retirement themselves start no verification/model turn or replayed command.

All 28 persistence, 24 recheck-UI and 17 native-resume tests passed. Coverage includes
unknown verdict preservation, rejection of unknown-to-pass promotion, stale-known
gate retention, budget-preserving fresh evidence, cached unknown/missing checks,
cached running work confirmed terminal, and refusal of an actually active native
thread. A fake process exits after accepting a turn but before replying; the CLI
correlates that original work attempt, records no inferred check pass and retires
it UNVERIFIED, with one total turn/start and no interrupt. Model claims and manual
verification cannot turn a test check into a pass. The ledger-preservation test
selects the attempt by its ID because explicit continue choices precede it in
history; no controller validation was weakened to accommodate ledger ordering.

Compile checks and `git diff --check` passed. No live inference or connected
account call was made. Live missing-result recovery, real process/network loss
and broader G2/G4 gates remain unverified. New rechecks of unknown evidence and
changing a saved known verdict via revalidation remain unsupported.
The full offline suite passed all 663 tests with test-owned sockets enabled and
no skips. Entry-point compile checks and `git diff --check` passed.


### P13 local namespace capability probe (2026-11-25)

`python3 search_isolation_probe.py` completed with `capability_verified` on
Python 3.12.0 and bubblewrap 0.8.0. Exact probe SHA-256:
`af049813e126fead836cae96ac059c23be781d13a5db006896328d62914d1d01`.
All eleven boolean checks passed; `g3Passed` remained false. This used only
owned synthetic temporary files, no model/account calls and no HTTP requests.

The fixed worker receives only a public query via stdin and a read-only mount,
plus synthetic probe paths/FD number used to challenge the boundary. A sterile
environment is applied before launching bubblewrap, then reset inside it. The
private fixture FD is deliberately inheritable in the parent but closed at exec.
Private absolute/old-cwd paths and `/home` were unavailable, environment matched
explicit PATH/LC_CTYPE/PWD values, the public mount resisted writes, and a worker
write at the same absolute temporary path did not create a host file. The parent
independently checked marker absence and unchanged private/public input bytes.
No fixture bytes, paths, environment dumps or worker stderr enter the report.

`python3 -m unittest discover -s tests -p test_search_isolation_probe.py -v`
passed six tests, including the real local probe, missing utility, malformed or
wrong-type worker reports, timeout/launch failures and sterile launch settings.
On unsupported hosts the capability test accepts an explicitly unavailable
result; that result cannot pass the diagnostic or G3. There is no automatic
install, privilege fallback or retry. The fixed trusted worker uses bounded known
output; this script is not a runner for arbitrary code or web page instructions.

Scope limits: `/usr`, `/lib` and `/lib64` are broad read-only capability mounts,
not a reviewed minimal Python/TLS runtime allowlist. Network is deliberately
shared for eventual public search feasibility, but this probe sends no request
and does not establish egress restrictions. It does not test a hostile child,
credentialless TLS lookup, injection handling, process-loss cleanup, a second
host, or automatic query approval/integration. Runtime and hosted search policy
remain unchanged; G3 remains open. A minimal runtime mount/worker design and
independent denial/injection checks are the next eligible P13 work.


### P13 explicit runtime mount profile (2026-11-25)

The broad mounts used by the preceding capability spike have been removed from
`search_isolation_probe.py`. The current fixed profile mounts CPython 3.11,
its stdlib directory, the x86-64 dynamic loader, libc/libm/zlib/expat,
OpenSSL 3 libraries and a single system CA bundle at `/public-ca.pem` read-only.
Source symlinks are resolved before binding; destination paths remain fixed.
Missing profile files return `unsupported_runtime_profile`, without launching a
worker or falling back to broader mounts. No runtime dependency was added.

`python3 search_isolation_probe.py` passed thirteen checks with bubblewrap 0.8.0,
parent Python 3.12.0 and worker Python 3.11.2. Probe SHA-256:
`341466fb38cc3bc7eb7fa5f24354b4720f2e49de7e04c73513545d4ecb83c99b`.
The worker additionally imports HTTP/TLS stdlib modules, loads CA certificates
with hostname/certificate verification enabled, and verifies `/usr/bin/sh`,
`/usr/bin/env`, `/usr/local`, `/etc` and `/run` are absent. It makes no TLS
connection, DNS lookup, HTTP request, model call or account request.

All seven `test_search_isolation_probe.py` tests passed, including refusal of a
missing profile and launch-argument checks against broad mount fallback. Compile
and diff checks passed. Runtime/shared CLI behavior was untouched, so the full
suite was not rerun for this diagnostic-only increment.

This profile is deliberately specific to the tested host layout, not a portable
production mount detector. The stdlib directory remains a directory mount and
has not been reduced to a dependency closure. Certificate presence does not prove
successful HTTPS or working DNS; no resolver configuration is mounted. Shared
network is not an egress policy. Fixed trusted code checking selected hidden
paths does not prove resistance to arbitrary hostile code or prompt injection.
G3 remains open. Next: prepare and independently test the actual bounded search
worker and data-only result handling under reviewed mounts; keep automated
private-context search disabled until its required evidence exists.


### P13 consistent candidate URL validation (2026-11-25)

A regression test reproduced SearXNG accepting `:0`, `:99999` and nonnumeric ports
as candidates even though later JSON packet validation rejected them. A single
shared URL predicate now applies the packet constraints before selecting the
first five SearXNG candidates. Invalid entries are skipped; later valid entries
remain available for human display and packet export. Credentials, non-HTTP(S)
schemes, whitespace/control text and overlong URLs remain rejected. Valid explicit
ports remain supported. No candidate URL is fetched or treated as an instruction.

All 14 web-policy and 30 workflow-entry tests passed. Existing workflow tests
confirm injected source text reaches the goal as untrusted data without changing
steps/criteria, model grants or the default tool policy. This is offline evidence;
it does not establish arbitrary prompt-injection resistance, live SearXNG support
or G3 completion. No search worker or automatic search path was enabled.

The full offline suite passed all 671 tests in 135.547 seconds with no skips.
Runtime/diagnostic compile checks and `git diff --check` passed.


### P13 actual search runtime inside the local namespace (2026-11-25)

The probe mounts an owned byte snapshot of `modelmate.py` read-only at
`/modelmate.py` and loads it under a non-main name, without running its CLI.
It calls the actual Wikipedia search function, HTTPS transport/parser and packet
validator. Only the HTTPS peer is replaced by a fixed synthetic response; no
model, account, DNS, HTTP or TLS connection is made. The peer verifies bounded
response reads and records the single expected query-only request. The parent
checks the runtime snapshot remains unchanged and reports its SHA-256.

`python3 search_isolation_probe.py` passed seventeen boolean checks on the same
bubblewrap 0.8.0 / worker Python 3.11.2 profile. Tested runtime SHA-256:
`339f762d478763edc3b47b6181148d68708ac772ab05e59d846caa71823f42c1`;
probe SHA-256:
`8dd0af48a53d1396e14de272e336d178178daf8779911dd5412b52dc254694c6`.
An excerpt containing a synthetic Python write instruction remained exact
source text; its marker did not appear. An extra packet approval field was
rejected. Diagnostic audit instrumentation records and raises on socket creation,
process launch, system/exec and posix_spawn events during these parser calls.
This audit is intentionally test-only and is not claimed as a production security
boundary or exhaustive syscall policy. A deliberately modified worker attempting
`os.system` fails the probe, rather than returning capability-verified.

All nine probe tests passed, including a false check that cannot be promoted to
pass and the deliberate side-effect attempt. Existing unsupported-host paths
remain explicitly unverified. Compile and diff checks passed; the full suite was
not repeated because only diagnostic/tests/docs changed (last shared-runtime
suite: 671 tests passed). Runtime search behavior was unchanged.

This proves the existing search code can import and process this synthetic
response under the constrained filesystem profile. It does not prove a production
worker, real HTTPS/DNS, arbitrary hostile input resistance, process-loss cleanup,
or the whole G3 gate. Shared network and a stdlib directory mount remain scope
limits. Automated/private-context search stays disabled. The next P13 increment
must connect a bounded data-only worker protocol and independently verify its
input/output and failure handling before enabling any new search path.


### P13 bounded internal search worker protocol (2026-11-25)

`run_search_worker` in the one-file runtime reads at most 8193 bytes from a binary
input stream and rejects requests above 8192 bytes. The exact request fields are
`version`, `source`, `host`, `query`; existing strict packet validation with an
empty result list checks their values before dispatch. Duplicate keys, nonfinite
constants, invalid UTF-8/JSON, unknown fields and unsupported source/host values
cannot dispatch. The worker calls the existing Wikipedia or SearXNG function
with only the validated query/host. It validates the full resulting packet and
encodes at most 32768 bytes before writing any output. Search/validation failures
propagate without a partial result packet; caller owns process/error handling.

The namespace probe now calls this actual binary protocol with its synthetic
HTTPS peer, rather than calling the search function directly. All seventeen
capability checks passed. Tested runtime SHA-256:
`1051a4827f23318a0950b06b7d90a8ea8d865e3de6d8ba9e57383dfa729cd6c4`;
probe SHA-256:
`194bbd4f8f1c04d2c03c15466e452dd7008064312a64873bcb3d25e804a711cc`.
Six new protocol tests and nine probe tests passed, including query-only dispatch
for both sources, injection remaining text, rejection before dispatch, invalid
transport results and an otherwise valid oversized output emitting no bytes.

This internal function is currently called by diagnostics/tests only. It does
not itself grant consent or isolation, and no CLI bypass or automatic workflow
search has been added. The production parent must enforce query provenance and
required approval, restricted process launch, deadlines, output collection,
fresh request/response binding and sanitized failures. The present 8 KiB/32 KiB
limits bound message data, not remote latency or a hostile process's output.
Real DNS/TLS and full G3 isolation/injection/lifecycle gates remain open. No model,
account or network request was made by this increment's verification.

The full offline suite passed all 679 tests in 117.570 seconds, with no skips.
Runtime/probe compile checks and `git diff --check` passed.


### P13 parent-side response binding (2026-11-25)

`validate_search_worker_response` validates a caller-owned public request and a
binary worker packet of at most 32768 bytes. It rejects malformed/duplicate-key/
nonfinite/deep JSON, invalid UTF-8 and unsupported packet fields, using existing
strict source metadata validation. Version, source, host and query must all match
the caller's request exactly. A valid result for a different query/host/source
cannot be accepted for this request. The validator grants no permission/evidence
and makes no network/model call.

The namespace probe now transfers the actual result as a response string alongside
its boolean diagnostic checks. The parent separately applies response validation
against its own fixture request before accepting any successful capability report.
It rejects malformed/duplicate/oversized diagnostic envelopes (64 KiB ceiling),
wrong-type booleans and unexpected envelope fields. Returned response text is not
printed in the sanitized report. A test supplies all-true child booleans but a
mismatched query; the parent still returns unverified/invalid_worker_response.

The real namespace run passed eighteen checks with the unchanged host profile.
Runtime SHA-256:
`84c61762934745f43af30ee4a47f75e9e02198a258bca3e5f75a4043043c2a72`;
probe SHA-256:
`76c2c3f9b4e6d1b9062dae3ea09bfd9555446e6195e195992a70cea9e4071f51`.
Nine worker-protocol tests and ten isolation-probe tests passed. Compile/diff
checks passed. No HTTP/DNS/model/account call was made.

The exact field comparison binds request content, not freshness across two
identical requests. A production launcher must use one owned process per request,
accept results only from that process's successful completion, enforce collection
limits/deadlines and never replay unknown outcomes. This increment does not yet
implement that launcher or CLI activation. Diagnostic capture_output still trusts
the fixed test child to keep stdout bounded before the envelope length check;
it is not a hostile-worker streaming output limit. G3 remains open.

Full offline verification passed all 683 tests in 119.191 seconds with no skips.
The expanded ten-test diagnostic boundary set also passed separately.


### P13 bounded process collection and timeout cleanup (2026-11-25)

The namespace probe now uses runtime `run_search_process` instead of unbounded
`subprocess.run(capture_output=True)`. The collector validates input/limits before
launch, supplies at most 8 KiB public input from an anonymous temporary file,
clears the inherited environment except PATH, closes unrelated FDs and starts
one owned process session. A selector reads at most the output limit plus one
byte (32 KiB default, 64 KiB for this diagnostic envelope); overflow fails without
returning partial results. stderr goes directly to DEVNULL and is never captured.
A monotonic deadline covers stdout collection and waiting for exit, including a
process that closes stdout but continues running. There is no retry. On overflow,
timeout or interruption the collector sends SIGKILL to its owned process group
and waits for the leader. It returns an explicit exit code for the caller to
check before accepting any response; the probe rejects all nonzero codes.

Seven real local-process tests passed: bounded success/exact boundary/nonzero
exit, stderr flood without memory accumulation, stdout overflow, timeout with
stdout open or closed, a descendant holding stdout open, sterile environment and
private FD closure, and invalid limits not launching a process. The descendant
check polls only its test-owned child for up to two seconds because SIGKILL
handling is asynchronous; it observes disappearance or zombie state, not a
running process. Ten probe tests passed including timeout/launch/overflow failure
redaction. The actual namespace probe still passes eighteen capability checks.

Tested runtime SHA-256:
`63efaefea7c405e2cde2e84b3827a1a30eeecf7f667a7d8e473ab20af8ba6ad6`;
probe SHA-256:
`dd3e9e9570b6b4f748cf3d193ad52e4b3b135a098df7cb6ffd35c79c08a3d765`.
Compile and diff checks passed. No model, account or network call was made.

This helper accepts only a trusted caller-constructed launcher command and is not
a sandbox or approval gate. Process creation itself is not interruptible by the
selector deadline. A process group is not containment for hostile children that
create new sessions; successful children that close inherited pipes are not
independently inspected by this collector. The actual namespace/PID lifecycle
and approved parent-launch design still need evidence. The fixed bubblewrap
probe remains the only caller; no automatic/private-context search was enabled,
and G3 remains open. These limits supersede the preceding capture_output note.

Full offline verification passed all 690 tests in 105.281 seconds, with no skips.
Runtime/probe compile checks and `git diff --check` passed.


### P13 normal namespace exit with a detached descendant (2026-11-25)

The probe now runs a separate fixed lifecycle challenge after all parser/privacy
checks pass, using the same bubblewrap namespaces/mounts and bounded collector.
Inside the namespace the initial worker starts a Python descendant with
`start_new_session=True`. That descendant writes a readiness file only inside the
private tmpfs, retains inherited stdout and sleeps for five seconds. The initial
worker waits up to one second for readiness, verifies its child's session differs
from its own, emits an exact public readiness marker and exits without waiting
for or terminating that child. No host-writable mount or network call is used.

The parent requires zero exit status, that exact marker and EOF within at most
two seconds. Because the fixed sleeping descendant never closes stdout, EOF
before its five-second sleep expires demonstrates that it did not remain alive
holding the pipe after initial-worker exit. Its detached process session prevents
normal parent process-group cleanup from being mistaken for this normal-exit
namespace result; the collector never enters failure cleanup on a passing run.
This is a scoped observed behavior, not a claim about arbitrary hostile programs.

`python3 search_isolation_probe.py` passed all nineteen checks on bubblewrap
0.8.0 / worker Python 3.11.2. Probe SHA-256:
`66a59f6f802af87d9e303ed607161360001e284dd9258c3adfdd6327a4267e7e`.
Runtime SHA-256 remains:
`63efaefea7c405e2cde2e84b3827a1a30eeecf7f667a7d8e473ab20af8ba6ad6`.
All twelve probe tests passed, including refusing lifecycle timeout/launch/output
failures, missing readiness and nonzero exit even when earlier parser checks
were all true. Each challenge runs at most once; no failed launch is replayed.
The initial read-only exploratory run also returned promptly, before committing
this challenge to the diagnostic. No account/model/DNS/HTTP call was made.

Limitations: this adds normal-exit evidence for one detached child, not proof of
cleanup after parent/server/host death, arbitrary namespace escapes, hostile
resource exhaustion or clean installation on another host. If containment fails,
the fixed challenge child naturally exits after five seconds; no long-lived
fixture is intentionally left behind. A production approval-bound launcher and
real DNS/TLS evidence remain absent. G3 remains open and automated/private-context
search stays disabled. Runtime was untouched; full suite was not rerun for this
diagnostic-only change (last full suite: 690 tests passed).

All seven real-process collector tests also passed; probe compile and diff checks passed.


### P13 internal confirmation-bound parent launcher (2026-11-25)

`run_isolated_confirmed_search` wraps the existing exact SEARCH-token query UI.
EOF, cancellation, stale tokens and incomplete confirmation lines never call the
launcher or create its snapshots. Once confirmed, `run_isolated_search` validates
source/host/query and launches exactly one fixed `/usr/bin/bwrap` command; it
accepts no model-supplied command, mount, environment or approval fields.
Unsupported utility/runtime layouts fail without installation or fallback.

The parent creates an owned temporary runtime snapshot and a generated resolver
file, then mounts only those plus the fixed Python/TLS profile read-only. Host
cwd, project tree, credentials and session metadata are not mounted. Runtime and
probe now share SEARCH_MOUNTS. The CA bundle is also mounted at the worker's
default Python/OpenSSL certificate path, so default HTTPS certificate validation
loads trust without environment overrides. The parent reads at most 16 KiB of
resolver configuration and emits at most three unique numeric nameserver entries;
search domains, arbitrary options and comments are not copied. Unsupported or
malformed resolver configurations fail explicitly. Host configuration is unchanged.

The collector uses a fresh session, sterile environment/closed FDs, a 12-second
collection deadline, 32 KiB response ceiling and discarded stderr. Nonzero exit,
timeout, setup failure or invalid response cannot return results. No retry occurs;
a timed-out public query might already have been sent. On success the parent
requires the response's exact version/source/host/query binding and returns only
passive candidate records. Owned snapshots are removed after the process exits.
The internal callable assumes its caller has confirmed the query; only the wrapper
implements that consent UI. Neither callable is exposed as a CLI switch or used
by automatic workflow search yet.

Seven launcher tests passed, covering refusal before setup, exact confirmed query
forwarding without subsequent history, owned mount/snapshot construction and
cleanup, invalid/missing capabilities, failure/no-retry behavior, resolver data
minimization and the actual namespace launch. That real launch uses synthetic
resolver data and a fixed fake HTTPS peer; an audit hook prevents network socket
creation. It verifies hidden home/shell, private cwd, absence of a synthetic
credential environment value, only resolv.conf under /etc, unchanged public query,
loaded default TLS trust and injection text remaining source data. No real
resolver, model, account or network call is used by the tests. The standalone
capability probe still passes nineteen checks and all twelve probe tests pass.

Tested runtime SHA-256:
`b1f51f67baafbb91e5e22ea3df33d4ed1c639ce0dce89989200c8557825d741e`;
probe SHA-256:
`365b6502c8b54ebf5ff3149615009096be97368d6735f2c57e04c878aef02672`.
Runtime/probe compile and diff checks passed.

Remaining limits: explicit Debian-style x86-64 CPython 3.11/OpenSSL 3 layout,
shared network without egress enforcement, stdlib directory mount, no real
DNS/TLS/SearXNG verification, and incomplete parent/server-loss lifecycle evidence.
The fixed fake peer validates this path offline, not G3 as a whole. Automatic
private-context search and hosted web remain disabled. Next: review this concrete
launcher boundary and obtain the required scoped real-network/lifecycle evidence
before any user-facing activation; unsupported systems must continue to fail
closed rather than widening mounts or permissions.

Full offline verification passed all 699 tests in 104.128 seconds with no skips.
The strengthened seven-test launcher set also passed separately; compile and diff checks passed.


### P13 scoped live DNS/TLS verifier prepared, not executed (2026-11-25)

Explicit commands, to be run only when requested/authorized:

```sh
bwrap --version
python3 search_isolation_probe.py --live-wikipedia en
```

`th` selects the Thai endpoint instead. This is not a Codex/inference command and
requests zero model turns/account calls. The mode previews one fixed public query
(`Python programming language` for en, `ภาษาไพทอน` for th), host and fresh SEARCH
token on stderr. Exact interactive confirmation is required before setup/lookup;
EOF, cancellation, stale or incomplete tokens launch nothing. One confirmed
launcher call is allowed, without retry. Normal invocation without the flag still
runs only the offline namespace probe. Help is offline.

The live mode reuses the internal namespace launcher, its fixed mounts, fresh
process, bounded response and exact request binding. A successful scoped report
requires at least one result with canonical endpoint source URLs. It records
runtime/probe SHA-256, zero requested model turns, launch count and boolean checks,
but no query text, returned source title/snippet/URL, credentials or stderr trace.
Failures are unverified with a sanitized reason; interruption is explicitly
outcome-unknown and never triggers replay. `g3Passed` remains false even on scoped
success: this command cannot certify all isolation/injection/lifecycle evidence.
The bwrap version above should accompany a real report for version scope.

All seventeen diagnostic tests passed, including default/live routing, confirmed
query forwarding without following history, refusal before launch, sanitized
failure/invalid/empty results and one-launch/no-retry behavior. Tests use actual
file descriptors for the existing confirmation reader and mocked lookup results;
a mocked scoped success is NOT live evidence. The default real offline probe
still passed nineteen checks. Compile/diff checks passed. No live Wikipedia,
DNS/TLS, model or account request was made for this increment. Full suite was not
rerun for diagnostic-only changes; last full suite remains 699 tests passed.
Probe SHA-256: `6197c966b06a1d15c4ea74f13672fb8e8b44084af205093c3e9667aed2f6daad`.

Next eligible work: review the concrete launcher boundary and run the scoped
command only with explicit live authorization; continue parent/server-loss and
injection validation independently. SearXNG, automatic workflow search and full
G3/release gates remain open. The runtime CLI has not been activated by adding
this separate diagnostic entry point.


### P13 abrupt collector-parent death and negative control (2026-11-25)

The offline probe adds a fixed Python supervisor that calls the actual runtime
collector with the same bubblewrap namespace/mount policy. Its worker starts a
detached-session descendant, waits for child readiness, emits the known marker
and then sleeps for five seconds; that child also holds stdout and sleeps five
seconds. The supervisor's bounded read instrumentation announces readiness only
once the collector has received the worker marker. No process ID, FD number or
raw subprocess output is retained in the sanitized final report.

Before killing the supervisor, the outer harness opens the worker pipe's read
end through /proc on its still-owned supervisor process and verifies it is a FIFO.
It then SIGKILLs only the supervisor and requires its -SIGKILL exit plus EOF on
that independently held worker pipe within two seconds. It does NOT use EOF of
the supervisor's own stdout as evidence: that would close on supervisor death
even if its worker were still alive. The supervisor cannot run its Python finally
cleanup after SIGKILL; a passing observation therefore exercises the configured
parent-death/PID namespace behavior. No group-wide fallback kill is used to turn
a failed check into success.

The actual configured namespace passed this challenge, bringing the default
probe to twenty checks. A real negative control removes --die-with-parent from
only the challenged command; the worker pipe stays open beyond the deadline and
the report is unverified. This shows the harness distinguishes a surviving worker
from cleanup. A unit test also prevents false parent-death checks from being
promoted to a successful overall report. The fixed sleeping fixtures naturally
exit within five seconds if containment is absent; no long-lived fixture is
intentionally left behind. On hosts blocking access to the owned /proc FD, the
challenge stays unverified rather than requesting wider permissions.

All nineteen diagnostic tests passed in 4.033 seconds, including this real
negative control, the positive namespace run and the mocked live-mode refusal/
sanitization cases. Probe SHA-256:
`74586fec2f28abd03e38ce1b4bf9a11d5c7a13975c8f80c45c4439ab5735feca`.
Runtime remains at SHA-256:
`b1f51f67baafbb91e5e22ea3df33d4ed1c639ce0dce89989200c8557825d741e`.
Compile/diff checks passed. Runtime was untouched, so the full suite was not
repeated (last full suite: 699 tests passed). No live Wikipedia/DNS/TLS, account
or model call was made; the prepared explicit live command remains unexecuted.

This adds scoped evidence for abrupt parent-process loss with one ready worker
and detached descendant. It does not establish arbitrary namespace escape
resistance, host shutdown behavior, HTTP server loss behavior, broader native
workflow recovery, another host or complete G3. The separate prepared live
verifier, boundary review and remaining injection/activation requirements still
apply. Runtime CLI/automatic private-context search remain disabled.


### P13 proc filesystem boundary and deliberate leak control (2026-11-25)

The fixed diagnostic worker now challenges the owned private fixture through its
absolute path, `/proc/1/root` plus that path and `/proc/1/cwd/secret`. It also
checks that the host diagnostic parent's numeric PID is not present under the
worker's proc mount. The parent PID and synthetic paths are challenge metadata
only and are not copied into the sanitized report. These are targeted checks of
the tested PID/filesystem namespace, not proof about every possible proc entry.

All twenty-three default capability checks passed. A real negative control adds
a read-only bind of only the owned synthetic secret into the challenged namespace.
That control is unverified with direct private-file and proc-root checks both
false, showing that readable secrets cannot silently produce a passing report.
It changes no runtime mount policy and never prints the fixture bytes. Later
lifecycle challenges are skipped when the privacy checks have already failed.

The actual internal launcher test now creates a separate owned private fixture
outside the mounted runtime/resolver snapshots and actively attempts all three
file routes from its fixed fake-HTTPS worker. The reads fail under the launcher's
actual mounts as well. The injected test code knows this synthetic fixture path
only to challenge the boundary; normal worker input remains the query-only
protocol, with no private project path/history supplied. No real secret, prompt,
credential, account or network request is used.

All twenty diagnostic tests passed in 3.871 seconds, and all seven launcher tests
passed in 0.293 seconds. Probe SHA-256:
`85335a4c726e6da149f94e934ac5b606fa6adaa40886c1da8df869002409f05d`.
Runtime remains unchanged at:
`b1f51f67baafbb91e5e22ea3df33d4ed1c639ce0dce89989200c8557825d741e`.
Compile and diff checks passed; full suite was not repeated for diagnostic/test/
documentation-only changes (last full suite: 699 tests passed).

Boundary review at this revision:

| Boundary | Concrete enforcement/evidence | Remaining limitation |
| --- | --- | --- |
| Request | Exact UI confirmation before launcher setup; strict source/host/query-only schema | Automatic query provenance/entry is not enabled |
| Files/processes | Fixed read-only runtime/profile/resolver snapshots; fresh PID namespace; closed FDs; direct/proc leak control; scoped normal/parent-death challenges | Host-specific profile, stdlib directory mount and broader adversarial/host failure coverage remain |
| Result | Bounded collection, strict schema, exact parent-owned request binding; no result URL fetch or grant/evidence creation | No real DNS/TLS/SearXNG result yet; imported sources are not fact verification |

The review supports continuing scoped verification of this internal prototype;
it does not authorize activation or certify G3. Hosted web and automatic
private-context search remain disabled. Next eligible P13 evidence is the
prepared explicitly authorized live DNS/TLS command and the remaining adversarial
input/HTTP-failure checks; unrelated native lifecycle/release gates remain open.


### P13 adversarial HTTP response and connection failures (2026-11-25)

A regression test reproduced the shared HTTP JSON reader accepting duplicate
root/nested keys and nonfinite NaN/Infinity constants from remote responses.
`read_search_json` now reuses the existing strict duplicate-key/constant hooks
before returning a source payload. Hook failures become a generic source-specific
invalid-response error with no raw response/plan-parser text or exception chain.
Both Wikipedia and SearXNG use this reader; there is no alternate permissive path.

All seventeen web-policy tests passed. New cases include duplicate keys at root
and in a source result, NaN/Infinity in otherwise unused remote metadata,
request/getresponse/body-read failures, invalid encoding, deep/array JSON, a body
above 256 KiB and a valid body exactly at that limit. Disconnect/partial-response
errors produce sanitized class diagnostics, invoke the request only once and
close the connection. The existing 262145-byte bounded read and refusal to follow
redirects remain in place. Existing seven actual-launcher tests with a fake peer
also passed. Runtime/diagnostic compile and diff checks passed.

Tested runtime SHA-256:
`5b4408297ef5d4539ffbc92a5da098631a981e7411370c2f8b9d8ae9460533f1`.
These are offline parser/transport failure checks; no HTTP/DNS/account/model call
was made. The real-network command remains opt-in and unexecuted. They do not
establish all hostile-input or private-context search guarantees. G3, automatic
workflow activation and the broader release gates remain open.

Full offline verification passed all 710 tests in 113.991 seconds with no skips.
Runtime/diagnostic compile checks and `git diff --check` passed.


### P08/P10 experimental Auto advancement for new explicit plans (2026-11-25)

New explicit Auto workflows can opt into `--experimental-auto-advance`. The flag
is routed through workflow entry and the attached selector shell, not stored in
a checkpoint. Preview is offline; execution still requires --execute-workflow
and exact START. Resume and other modes are rejected; programmatic resume is
rejected before metadata access. The shell requires the matching bound host.
Default behavior remains manual /next and no extra classifier/model call exists.

A shell tick dispatches only when its current controller is READY with no active
attempt, while the shell is open/not stopping and mode remains Auto. The existing
host performs fresh account/quota/catalog/model gates and durable reservation;
no alternate dispatch or tool-grant path was added. Controller transitions stop
repeated ticks from starting another attempt. Checks still need explicit /check
and trusted evidence. Known failed checks may start a correction within the same
initial-plus-two budget. Unknown evidence, pending model/tool approval, pause,
unfinished native work and final criterion mapping cannot dispatch. The shell
does not call finish_task or infer a pass from model text.

Dispatch/preflight exceptions disable automatic advancement without retry; any
existing controller PAUSED reason is retained. An unknown quota snapshot pauses
without polling; explicit continue must pass a fresh admission before dispatch.
EOF/cancel/exit and switching away from Auto stop new automatic work. Neither
approval tokens nor tool policy are changed. Changing native permissions or
accepting a tool action still uses its independent existing gate.

All eleven new tests passed: default-off, once-only READY dispatch, two-step
progress after explicit trusted checks, initial-plus-two correction limit,
unknown evidence stopping, unknown quota retaining its reason/no poll retry,
explicit continue fresh admission, no replay after ambiguous dispatch, no opt-in
checkpoint persistence, closed/paused/other-mode states, CLI validation and
preview/missing START refusal before native process creation. The real selector
integration uses a fake native subprocess and user input pipe: it completes two
steps with exactly two turn/start calls, on-request native policy and accepted
command evidence; model text alone never advances it. Final task criteria are
still pending explicit mapping. No connected account/model/quota was used.

Final-source full offline verification passed all 721 tests in 134.749 seconds,
with no skips. Runtime entry-point compile and diff checks passed. Tested runtime
SHA-256: `162015800a77b1a4670629447a0c22770b1fda734834a747157151ae3b479802`.
Broader live mode/tool/cancellation/recovery gates, plain-prompt planning, automatic
check orchestration, comparative routing and complete release readiness remain
open. No connected account, live model or quota was used for these checks.


### P10 automatic evaluation of terminal test/lint attempts (2026-11-25)

The existing experimental Auto advancement flag now also selects the trusted
host check action when the controller is CHECKING, its active attempt is confirmed
completed and every declared check is test/lint. Each shell tick performs at most
one action. The host retains ownership of exact native command/cwd observations,
missing-result evidence and evaluation. The shell does not run a check command,
replay it, generate a verdict, accept model text or call finish_task. After known
pass/fail, a later tick may dispatch the next step/correction through the existing
fresh admission and unchanged budget. Missing observations retire UNVERIFIED and
cannot authorize a new attempt automatically.

Any manual/rubric/source check keeps explicit human verification and /check.
Failed/interrupted turns, pending model/tool approval, paused/closed/stopping
shells and final task criterion mapping remain ineligible. The flag is still
new-plan/Auto-only, explicit START opt-in, not restored and disabled by default.
Tool approvals and read-only/on-request native policy remain separate. No extra
model/verification turn or automatic command retry is introduced by evaluation.

All thirteen targeted Auto tests passed. The selector integration now drives two
steps to accepted tool evidence using a fake native subprocess without /next or
/check input, with exactly two turn/start calls. Additional cases cover mixed
human check kinds and failed/interrupted native completion. A model message
claiming every test passed and requesting DONE still yields UNVERIFIED when no
matching command observation exists. Initial plus two known-failure corrections
remain enforced, unknown quota still pauses and explicit continue still requires
fresh admission. Task criterion mapping remains explicit and no DONE is inferred
from step completion alone. No connected account/model/quota was used.

This supersedes the preceding milestone's explicit /check requirement only for
terminal all-tool-check steps. It is offline evidence, not proof that native
workflow acceptance or broader live automation/release gates passed. Plain-prompt
plan creation, human-check orchestration and scoped live mode/failure evidence
remain open. Runtime compile and diff checks pass.

Full offline verification passed all 723 tests in 136.620 seconds with no skips.
The final thirteen-test Auto set also passed separately. Runtime compile and diff
checks passed. Tested runtime SHA-256:
`18696966e103bfa014fc0d7e8a38dc2bbbaf3469f89fb02bae85100be805b45c`.


### P06 selected-model prompt-to-draft proposal entry (2026-11-25)

`--draft-plan NEW_FILE --model MODEL "prompt"` adds an explicit one-turn planning
entry, with optional --effort. No classifier or model-selection inference is
introduced: the caller chooses the planning model/effort. The original goal is
separate from fixed proposal/schema instructions and must be preserved exactly.
A minimal plan-step controller reuses native fresh account/quota/catalog/model
admission, read-only/on-request thread validation, hosted web disabling and
bounded native completion/interrupt behavior. START is required before backend
construction. Server-requested tool escalation is declined by the existing
default path. This does not claim all native sandbox-permitted tools are disabled;
the prompt's request to avoid tools is not permission enforcement.

The collector accepts exactly one bounded completed assistant item from the
matching native turn (not deltas, foreign items or duplicate completed items).
Terminal controller state and active completed attempt must agree before parsing.
The returned text must be an exact JSON plan accepted by validate_plan; no markdown
repair, retry or accepting a claimed success exists. Extra permission/command/
counter/status fields and changed goals cannot publish a draft. Clarifications
remain unresolved data. Future role/effort bindings are validated again when the
user separately enters the workflow; this draft grants none of them.

Validated output is limited to 64 KiB and published through an owned temporary
0600 snapshot, fsync and exclusive hard link into the requested new filename.
Existing files, symlinks and concurrent destination creation are not overwritten;
owned temporary directories are removed on publication failure. This is atomic
exclusive publication, not a claim of directory-fsync crash durability. No local
session, automatic handoff/task execution or resume is created by drafting. The
native planning thread is ephemeral; timeout/disconnect never causes replay.

All ten targeted tests passed using a real fake-native subprocess, never Codex
or a live model. Cases include one selected planning turn and exact valid file,
foreign/delta/duplicate-item filtering, invalid JSON/markdown/extra authority/empty
steps/changed goal, preserved clarifications, max-length goal, oversized output,
CANCEL/EOF/incomplete START before backend access, existing destination refusal,
unknown quota/API-key login/widened permissions blocking dispatch, a competing
publisher and connection loss with no second turn. Successful draft files have
0600 mode, and temporary snapshots are cleaned after publication failure. No
private real prompt, account, credential or trace is included in repository data.

Runtime entry-point compile and diff checks pass. This is implemented/offline
verified proposal capture only: plain-prompt automatic routing, clarification
interaction/handoff into a workflow, real output compatibility and broader live
planning/permission/quota/release gates remain open. No live inference was run.

Full offline verification passed all 733 tests in 146.391 seconds, with no skips.
Compile and diff checks passed. Tested runtime SHA-256:
`f97d26a2cbfbe7736bebd1334f3ff5312d67d8952e780d1de4ce634c2cf415a7`.


### P08/P10 interactive clarification before START (2026-11-25)

Executing a new explicit plan with unanswered clarifications and no supplied
--clarification arguments now collects answers interactively before constructing
any backend. It reads each UTF-8 line directly from the input FD without buffered
prefetch, with a 16 KiB encoded line bound and existing 4096-character answer /
effective-goal limits. EOF, incomplete lines or CANCEL stop without connecting.
Invalid UTF-8, empty/oversized answers and an oversized combined goal fail before
model access. There is no reprompt/retry/model-generated answer or inference.
Preview reads no input. Explicit answer flags still require every question once;
partial/duplicate/unknown flags remain errors. Resume behavior is unchanged.

Collected numbered answers enter the same existing validated effective-goal path
as argument answers. Steps, success criteria, role bindings, model/tool grants,
controller counters and original plan file remain unchanged. The answered plan
is previewed before a separate exact START confirmation. START used as an answer
cannot also authorize execution; cancellation at that later confirmation still
stops before backend construction. Questions/file contents and answer text remain
data, not authority to grant tools or accept evidence.

All five new tests passed using real input FDs: Thai multi-question answers,
no consumption of later confirmation/commands, EOF/incomplete-line/CANCEL paths,
invalid UTF-8/empty/oversized/combined-overflow answers, untouched offline preview,
and a fake-native execution receiving the answered effective goal with one total
turn/start. A malicious-looking answer requesting all tools creates no model
grant and changes no steps/criteria. Source plan bytes remain unchanged.
All thirty existing workflow-entry tests passed, including unanswered EOF stopping
and an answer of START still requiring a distinct execution confirmation. The
backend-forbidden guard in that test remains intact.

Runtime/diagnostic compile and diff checks pass. No live
account/model/quota or real prompt/credential was used. Interactive handling of
unknown terminal environments and broader live gates remain unverified. Draft
creation and this explicit workflow entry are still separate commands; automatic
plain-prompt handoff, routing/evaluation and complete release readiness remain open.

Final full offline verification passed all 738 tests in 135.119 seconds with no
skips. Runtime/diagnostic compile and diff checks passed. Tested runtime SHA-256:
`1134b4b997282d1b2ad68d42fd851c0248bf820365d9c6bc056f593a8a29dd8e`.


### P06/P08 two-phase planned workflow handoff (2026-11-25)

`--plan-workflow NEW_FILE --model PLANNER --role-model standard=WORK_MODEL "prompt"`
connects the existing draft and new-workflow paths. START first authorizes one
selected planning turn. Only a validated, exclusively published draft advances
to workflow preview. Without --execute-workflow no work backend is constructed.
With it, clarification is collected through the existing bounded input path and
execution requires a separate START after the effective plan/model/check preview.
The first confirmation does not grant the second phase. Cancelled/invalid drafting
never enters handoff; later cancellation/configuration failure preserves the draft
so the user can continue with --workflow without another planning turn.

Role binding parsing is shared with the existing workflow path. A valid explicit
standard work binding is required before planning, not inferred from the planning
model. Work gets a new controller, counters, baseline and grants; default Ask to
escalate and native read-only/on-request policy are unchanged. Other required roles,
checks/commands, model/effort/catalog and quota gates still validate before work
dispatch. A caller-owned expected goal must match the loaded draft before any
clarification/work backend. Preview and second START authorize the actual reviewed
steps/criteria; local file contents never grant permission or evidence.

The metadata-only --check-catalog contract remains restricted to explicit existing
--workflow files and cannot accidentally request a planning inference. Standalone
--draft-plan keeps its behavior. Future workflow metrics/quota observations cover
the workflow phase only, not the earlier planning turn; no total savings claim is
made. Source-result context, clarification flags and opt-in tool/Auto settings
continue through their existing new-workflow validators.

All seven handoff tests passed using real fake-native subprocesses: independently
selected strong planner and standard work model, question/answer handoff, empty
work grants and zero initial work attempts, exactly one planning plus one explicitly
started work turn, separate second START, cancelled/invalid drafting, preview-only
input preservation, work-binding rejection before planning, goal tampering and
catalog-only rejection. Ten draft, thirty workflow-entry and seventeen CLI tests
also passed. Runtime/diagnostic compile and diff checks passed. No connected account,
live model or quota was used.

This is an explicit experimental prompt-to-workflow flow, not default plain-prompt
automation or proof of the broader live planning/permission/recovery/evaluation
release gates. A draft may request roles/checks not supplied at invocation; that
configuration failure preserves the file instead of rerunning planning or inventing
bindings/commands. Native planning remains ephemeral without its own resume. Full
release readiness remains unproven.

Full offline verification passed all 745 tests in 142.340 seconds with no skips.
Runtime/diagnostic compile and diff checks passed. Tested runtime SHA-256:
`8810870f3bb33525ffe5e57c251e809f56005597d073eb42f83be4d120902467`.


### P10 user-approved criterion mapping for automatic completion (2026-11-25)

--criterion-map MAP_JSON is opt-in with experimental Auto advancement on a new
Auto workflow. Its 32 KiB version-1 JSON contains only version and criteria;
criteria must cover every declared success criterion exactly once, with nonempty
lists of unique canonical STEP.CHECK references. The loader rejects duplicate or
nonfinite JSON, invalid encoding, unknown fields/criteria, undeclared checks,
non-string refs and caller-supplied evidence IDs. No command, grant, verdict or
counter can be supplied. File errors stop before work backend construction.

The mapping is shown alongside the existing criterion/check preview before START
and frozen as immutable reference strings for the shell. This is the user's
assertion about which check covers each criterion, not model-inferred semantic
coverage. Later mutation of the caller's list or config file does not revise the
loaded mapping. Once all steps are accepted with no active attempt, an eligible
Auto tick disables further advancement and applies the existing /finish handler
once. That handler resolves current accepted check evidence IDs, and unchanged
controller.finish_task validates completeness, pass verdicts, staleness and
unresolved rechecks. The model creates no verdict or accepted evidence through
this mapping. Rejection cannot start a model/tool turn, replay work or loop retry.
Default/no-map behavior still waits for explicit /finish.

Mapping does not make human checks automatic, change permission/model grants or
extend correction budgets. It is not a checkpoint field or restored opt-in; normal
accepted criterion_evidence is persisted through the existing controller path.
Resume still cannot enable experimental Auto. The same option works for planned
workflow handoff only after draft validation and the separate execution preview/
START. Unknown/failed/missing/stale observations cannot satisfy the map.

Fifteen targeted Auto tests passed, including real selector/fake-native completion
of two steps with exactly two turns and no /next, /check or /finish input, once-only
mapping, immutable caller refs, missing evidence and forced restored/stale evidence
rejection. Seven criterion-map tests passed: strict schema/completeness/canonical
refs/JSON bounds, preview before backend access, option gating, forwarding through
actual workflow entry and invalid-map refusal before input/backend. All thirty
workflow-entry tests also passed. Runtime/diagnostic compile and diff checks pass.
No connected account, live model or quota was used.

This adds controller-validated automatic acceptance of an explicitly approved
criterion mapping. It does not establish that the chosen checks semantically
prove a real task, replace human source/rubric judgments, demonstrate live Auto
permission/recovery behavior or pass G5 evaluation. Broader live gates, default
plain-prompt automation and release readiness remain unproven.


The first full run exposed an existing cleanup-test race: reading an owned
exiting descendant's /proc stat can raise ESRCH (ProcessLookupError), not only
ENOENT (FileNotFoundError). That nested test helper now treats both genuine
absence errors as not running. Permission/parse failures remain failures, and
assertions requiring the child alive before cleanup and stopped afterwards are
unchanged. Runtime process cleanup was not modified. All fifteen real local
socket transport tests passed separately after this correction; the restricted
sandbox run that skipped them is not counted as verification.

Final-source full offline verification passed all 754 tests in 145.259 seconds,
with no skips. Seven map/preview tests also passed against the final wording.
Runtime/diagnostic compile and diff checks passed. Tested runtime SHA-256:
`8f157b77d23ca36bea8ac1f5c42e8444293853161aea43060ae7e4b2c9877646`.


### P14 observed total wall time for planned commands (2026-11-25)

The combined --plan-workflow command previously emitted only workflow-phase
timing, omitting its earlier planning phase from the user-visible time summary.
It now emits one additional timing report scoped to the current planned command:
planningWallSeconds, workflowWallSeconds and totalWallSeconds, with
includesUserWait true. Trusted monotonic markers bracket the planning call and
subsequent workflow entry/cleanup, covering both START confirmations, questions,
previews, native waiting and file/transport cleanup. The report contains no prompt,
path, native/account ID, token total or inferred actual model.

If planning is cancelled, fails or is interrupted before handoff, the observed
planning duration is still reported and workflowWallSeconds is null. If handoff
occurs but work is cancelled/fails/preview-only, its elapsed preview/wait/setup
phase is measured without claiming that a model ran. Values are finite, ordered
and rounded to milliseconds; invalid clocks fail rather than fabricating zero.
Output write/flush errors do not override the operation's return value or change
controller state. No model/metadata call is added for reporting.

Workflow native turn/usage measurements and --metrics-jsonl stay phase-scoped and
unchanged. This new combined wall report is Terminal output only, not a new JSONL
schema or combined planning token/dispatch estimate. Neither wall time nor a quota
change is interpreted as cost or savings. Existing observed/unknown telemetry
boundaries remain intact.

All twelve metrics tests and seven planned-workflow tests passed. New cases cover
known split/total durations, unfinished planning, invalid/nonfinite/reversed clocks,
report write failure and exactly one final command report for successful, cancelled
and invalid-draft paths. The fake-native two-phase flow checks that the two measured
phase durations sum to total within millisecond rounding tolerance. Compile and
diff checks pass. No connected account/model/quota was used.

Actual dispatch telemetry, combined planning usage, attribution to account quota,
comparative evaluation and broader live/release gates remain unverified. This is
implemented/offline-tested local clock reporting, not new live evidence.

Full offline verification passed all 758 tests in 143.964 seconds, with no skips.
Runtime/diagnostic compile and diff checks passed. Tested runtime SHA-256:
`3300379db176436587e0f163c95e05abdc5fcc747b1372d3af85a2d8dc9407a8`.


### P13 authorized isolated Wikipedia smoke, unverified (2026-11-26)

The user explicitly authorized the prepared one-shot command and entering its
fresh confirmation token:

```sh
python3 search_isolation_probe.py --live-wikipedia en
```

It ran once with the fixed public fixture query, exited 1 and reported
status=unverified, reason=isolated_lookup_failed, searchLaunches=1,
modelTurnsRequested=0 and g3Passed=false. No retry occurred. This is not a passed
DNS/TLS, result or isolation gate. The original generic worker failure does not
identify its exact failing layer, and is not proof of a completed remote request.
No account/model call was made, and no private prompt or source result is stored.

Exact attempted runtime SHA-256:
`3300379db176436587e0f163c95e05abdc5fcc747b1372d3af85a2d8dc9407a8`;
verifier SHA-256:
`85335a4c726e6da149f94e934ac5b606fa6adaa40886c1da8df869002409f05d`.
Observed local versions: bubblewrap 0.8.0, parent Python 3.12.0, worker Python
3.11.2. No live Codex CLI/version compatibility is inferred from this HTTP mode.

Separate local socket-creation probes made no bind/connect/DNS/send call and
observed PermissionError errno 1 (EPERM) for IPv4 stream and datagram sockets in
the current tool execution profile. This establishes a missing host capability
in that profile, not the exact original worker exception or a service outage.
Host/organization restrictions were not widened and no proxy/privileged fallback
was attempted. A normal Terminal may have different capabilities; its outcome
would need a separately scoped real run, not reuse of this failed result.

The updated diagnostic performs a no-connect TCP/UDP creation preflight after
exact confirmation. If neither tested IPv4/IPv6 family has both socket types, it
returns unverified/host_socket_capability_unavailable with zero search launches.
Every created descriptor is closed. A successful creation check alone cannot
verify routing, DNS, TLS or G3; the real lookup would still have to succeed.

All twenty-three diagnostic tests passed, including refusal before search launch,
no connect/bind/send/resolve in the capability test and explicit socket denial.
A separate direct call of only that local capability helper returned false with
zero network requests; it was not another lookup or invocation of live mode.
Updated verifier SHA-256:
`63eaaca040b610a3afedf0258fb390753468f6cc50ea595593f9b93f983f467d`.
Compile and diff checks passed. Runtime was untouched; full suite was not rerun
for this diagnostic-only increment (last full runtime suite: 758 tests passed).

Remaining P13 capability/evidence: an authorized environment allowing the
required socket creation and endpoint access, real isolated DNS/TLS/result
verification, live SearXNG and automatic query-provenance/handoff integration.
Neither the failed authorized smoke nor these offline checks satisfy full G3 or
release readiness. Hosted web/automatic private-context search remain disabled.


### P14 observed planning-turn usage without extra account reads (2026-11-26)

Drafting previously discarded native planning measurements even when the matching
turn had supplied token/reroute/terminal observations. The planning path now emits
a separate planning_turn report using the existing bounded native measurement
collector. Requested model/effort remains labeled requested; actual model is not
inferred from that selection. Reroutes and token snapshots are retained only when
matched to the native binding by the existing observer, with foreign/duplicate
observations filtered as before. Missing usage/terminal/elapsed observations stay
unknown rather than fabricated zero or success.

proposalSaved is set only after validated exclusive file publication and is
separate from native terminalStatus. A completed generation with invalid JSON can
therefore report completed plus proposalSaved false, with no task/grant created.
The report includes no goal, answer text, local path, account ID, native binding,
quota window or raw error. Native per-turn tokens are not summed across planning
and workflow, cached/reasoning fields are not added again, and no quota/cost or
savings estimate is made. Workflow JSONL and its existing scope remain unchanged;
planning metrics are Terminal output only.

The shared measurement method retains its previous default but accepts an explicit
include_quota=False path. Planning always uses that path after closing its native
transport: even a saved quota window cannot cause a reporting-time account read.
No extra metadata/model call or replay is introduced. Report serialization/write
failures cannot replace the original publication or failure result.

All fourteen draft tests, thirteen metrics tests and seven planned-workflow tests
passed. New fake-native cases cover absent usage, matching usage/reroute telemetry,
duplicate/foreign observation filtering, requested-versus-reported model distinction,
completed-but-invalid proposals, report I/O failure preserving the published file
and no account/rate-limit reads after the planning turn. A direct measurement test
also supplies a saved quota window while forbidding all RPC calls in no-quota mode.
Compile/diff checks passed. No live inference/account/quota call was made for this
increment; the prior authorized HTTP smoke was not repeated.

This reports available planning observations, not complete actual-dispatch proof,
combined task-token attribution, quota savings or live service compatibility.
G1/G4/G5 and broader live/release gates remain open.

Full offline verification passed all 766 tests in 121.080 seconds, with no skips.
Runtime/diagnostic compile and diff checks passed. Tested runtime SHA-256:
`a903c53a6371a44d6ecfca0702ab63fd097d4871f7fc741f9bd7318d66ce2d7f`.


### P10 cancel revokes Auto despite late native completion (2026-11-26)

A new regression reproduced a stop race in the experimental Auto scheduler:
/cancel requested interruption and set UI stopping, but a subsequent native
completed event cleared stopping and moved the attempt into CHECKING. The old
process Auto opt-in then permitted evaluation and a following attempt, contrary
to the user's stop. The controller's completed observation itself was valid;
rewriting it to interrupted or discarding known results would be incorrect.

The shared ChatShell workflow cancellation path now revokes automatic advancement
immediately. Exit, EOF and the selector's KeyboardInterrupt cancellation use the
same path. Valid UI-token negative tool/model/pause choices also revoke the
process opt-in before their existing response handlers. Invalid/stale tokens still
fail validation before any new opt-in mutation. This changes no native tool grant,
model policy, retry counter, controller terminal semantics or persistence schema.
Known completion/evidence remain available for explicit manual check/next/finish;
mode changes or ordinary continue do not silently restore the revoked opt-in.

Twenty Auto tests passed. New cases cover cancel while running followed by a
completed native turn, stopping before the first dispatch, stopping after accepted
steps but before criterion mapping, exit/EOF with late completion, invalid versus
valid pause tokens and declining a model escalation. The former race test failed
before the change and now observes only one dispatch, no step advancement and no
DONE after late completion. Existing quota-continue, correction-limit, unknown
and stale-evidence behavior remains covered. Twenty-seven workflow UI and nine
native-permission tests passed separately. Compile/diff checks passed; no live
model/account/quota or HTTP request was used.

This fixes process-local Auto continuation after explicit user stop. It does not
prove the native command was prevented from completing, roll back side effects,
implement planning-turn textual cancellation after START, or close the broader
live stop/process-loss/permission gates. The separate planning inspection exposed
this Auto race; planning proposal publication behavior was not changed.

Full offline verification passed all 771 tests in 119.391 seconds, with no skips.
Runtime/diagnostic compile and diff checks passed. Tested runtime SHA-256:
`79e1d9ee5f2994565f6970f04622c69c30771aa659cd220cda7f781ce008b76d`.

### P06/P10 conflicting completed assistant item (2026-11-26)

A fake native server emitted a valid planning JSON completion, then different
completed text with the same bound item ID before the turn terminal event.
The new regression failed before the fix: the backend silently discarded the
changed completion and published the first proposal. The shared backend now
stores a SHA-256 digest per displayed item and rejects a changed completion.
Exact duplicates still display once; the digest table is cleared per turn, so
reused IDs in later turns remain valid. Foreign bindings and post-terminal text
retain their existing filtering. No raw answer is added to error messages or
telemetry, and no grant, retry counter or completion verdict is inferred.

`PYTHONPATH=tests python3 -m unittest test_plan_draft test_native_workflow -q`
passed 34 tests. The regression verifies no draft publication, proposalSaved
false and only one turn/start. Existing tests cover exact duplicate filtering
and item ID reuse across turns. Runtime/diagnostic compilation and diff checks
passed. This is offline protocol validation, not live server evidence; no model,
account, quota or HTTP request was used. Runtime SHA-256:
`274a1ae81e0569c68c33b0750071d5203bfcd87774c7917824db4cd99bba5121`.

Full offline verification (`python3 -m unittest discover -s tests -v`) passed
all 772 tests in 121.004 seconds, with no skips.

### P06/P12 planning KeyboardInterrupt cancellation (2026-11-26)

Inspection found that planning closed its owned backend on KeyboardInterrupt
without requesting a native interrupt for an already bound active turn. Two
regressions failed before the change: no interrupt RPC was traced, and the
existing native stop method was never called. The planning entry now calls the
existing host cancel action before its existing cleanup, then re-raises the
original KeyboardInterrupt. CLI cancellation remains exit 130. A stop-request
failure cannot replace the cancellation or cause automatic replay.

`PYTHONPATH=tests python3 -m unittest test_plan_draft test_planned_workflow
test_metrics -q` passed 40 tests. New fake-server cases cover cancellation before
connect (no turn/interrupt), after a bound dispatch (one exact turn/interrupt),
failed interrupt (one attempt, original KeyboardInterrupt), and after an already
observed completion (no extra interrupt, no draft publication). The combined
CLI case verifies exit 130, no work handoff, no saved draft, null workflow timing
and preservation of the next phase's unread START. No asynchronous input reader
or command parser was added to planning, so handoff confirmations remain intact.

This is MOCK_VERIFIED only. Interrupt acknowledgement is not proof of remote
termination, and a lost/unreturned turn/start ID cannot be targeted by guessing.
Cancellation before publication prevents a new draft; an already published file
is not rolled back. There is no planning resume, textual cancellation after START,
or live stop evidence in this increment. No model/account/quota/HTTP request was
used. Compile/diff checks passed. Tested runtime SHA-256:
`c70fe79fa2e650ec1a5d74cef12ca386219d976d6b2e474399e16b3e0a63d1ca`.

Full offline verification (`python3 -m unittest discover -s tests -v`) passed
all 777 tests in 125.278 seconds, with no skips.

### P06/P12 bounded planning cancellation observation (2026-11-26)

The previous cancellation increment requested an interrupt but closed without
draining the resulting native terminal events. Two new regressions failed before
this change: a matching interrupted terminal event remained unobserved, and an
acknowledgement-only cancellation had no explicit unknown-outcome report.
After a successful host cancel request, planning now uses its existing native
reader and selector to wait up to five additional seconds for a matching terminal
event. The existing host validates thread/turn identity; no new inference,
recovery connection, retry, grant or persistence format is introduced.

`PYTHONPATH=tests python3 -m unittest test_plan_draft test_planned_workflow
test_metrics -q` passed 43 tests. A real fake-server subprocess emits a foreign
terminal event followed by the matching interrupted event only after interrupt;
the latter is observed and reported without publishing the draft. A second case
emits only the foreign event and an interrupt acknowledgement: the bounded wait
expires, native terminal telemetry remains null and cancellation reports unknown.
Both retain one turn/start and one interrupt request. An observation error after
draining also reports unknown rather than treating partial observations as a
confirmed stop, and the original KeyboardInterrupt remains the result. Existing
tests cover failed stop requests, repeated interruption, prior completion and
no work handoff. Compile/diff checks passed.

This is offline protocol evidence only. The reported terminal status is not a
work check verdict, and completed is not a claim that cancellation prevented
side effects. Missing/unreturned turn IDs, actual remote stopping and live loss
recovery remain unverified. No model/account/quota or HTTP request was used.
Tested runtime SHA-256:
`27f3568ed35d617a0fc7c04f0b0b79ee40ba1e8a320cee443e4274ea897b72f1`.

Full offline verification (`python3 -m unittest discover -s tests -v`) passed
all 780 tests in 120.884 seconds, with no skips.

### P16 release capability revalidation (2026-11-26)

At feature commit `e28be63`, `git status -sb` was clean and synchronized with
its remote branch. `codex --version` returned `codex-cli 0.172.0` (with a
read-only PATH-alias warning); no App Server or model was started. The runtime
SHA-256 remains `27f3568ed35d617a0fc7c04f0b0b79ee40ba1e8a320cee443e4274ea897b72f1`;
verifier SHA-256 is `9da8763da620333778ea00c579b814ba4ce902943933e6c5702e6ed7acbe429e`.

The Docker command resolves to a Desktop WSL wrapper, but
`docker version --format '{{.Server.Version}}'` exited 1 and reported that WSL
integration is not enabled for this distro. It returned no engine version.
This establishes an unavailable local route to a clean container test, not an
installation failure of ModelMate or proof that every possible external
environment is unavailable. No image was pulled, container launched, dependency
installed or host setting changed. Existing two-Python same-host installation
evidence remains scoped to that host; independent second-environment evidence
is still missing.

The current requirement checklist was reread against the actual CLI paths and
prepared probes. Default plain-prompt workflow entry and automatic search are
still unimplemented/gated; comparative model policy, live permission/loss/quota
evidence and real/held-out evaluation remain open. Offline planning cancellation
improvements do not close these release requirements. The prepared bounded
command approval probe is awaiting explicit authorization; no inference or HTTP
request was made. Documentation-only revalidation does not rerun the full suite
or alter the previous 780-test result.

### P09 user-run approval probe and redacted failure location (2026-11-27)

The user ran `python3 verify.py --run-live --probe-workflow-approvals gpt-6.1-sol`
with Codex CLI 0.172.0. Runtime SHA-256 matched
`27f3568ed35d617a0fc7c04f0b0b79ee40ba1e8a320cee443e4274ea897b72f1` and the
tested verifier matched
`9da8763da620333778ea00c579b814ba4ce902943933e6c5702e6ed7acbe429e`.
The result reported phase approve, diagnostic ProbeError, reportedModels null,
one approve case, and all seven WORKFLOW_APPROVAL_KEYS unverified. No decline
case was started. This is an unsuccessful live attempt, not a G2 pass.

Read-only inspection of the retained synthetic scratch found only the unchanged
sentinel in the approve project and no marker. The saved metadata contains a
native thread/turn binding, an interrupted history entry, no pending tool
request and PAUSED/outcome_unknown state. These are post-cleanup observations;
they do not identify the triggering exception, prove pre-consent isolation, or
establish the full permission/remote-stop gate. Scratch and native threads were
not deleted, resumed or replayed. No additional model, account or HTTP call was
made while investigating this result.

The verifier previously discarded the exception's source location and retained
only its class. It now reports fixed `probeStage` labels and the last trusted
modelmate.py/verify.py traceback frame as `diagnosticLocation` (file basename,
function, line). Raw error messages, traceback text, local variables, native IDs,
prompts and payloads remain excluded. The original failure location cannot be
reconstructed from the old JSON report; this change does not claim a root-cause
fix or alter permissions, decisions, turn limits or retries.

`PYTHONPATH=tests python3 -m unittest test_workflow_approval_probe test_verify -q`
passed 41 offline tests. New fake-server/connect-error cases prove stage/location
reporting, private-message/payload redaction, no acceptance of unsupported scopes
and no second case after failure. The full offline suite passed 782 tests in
50.092 seconds with no skips. Compile/diff checks passed. Updated verifier
SHA-256: `3ee3e27c75db2d37c6cfa39f8c24a3c8c7cc9e9989927e8544db24166b15d5e9`.
Runtime hash is unchanged. A further live run must be explicitly chosen and
consumes subscription quota again; no live retry was performed here.

### P09 experimental command metadata compatibility (2026-11-27)

The user independently ran the command approval probe again. Its runtime hash
was `27f3568ed35d617a0fc7c04f0b0b79ee40ba1e8a320cee443e4274ea897b72f1`
and verifier hash was
`3ee3e27c75db2d37c6cfa39f8c24a3c8c7cc9e9989927e8544db24166b15d5e9`.
All seven checks remained unverified in phase approve; probeStage was
await_approval. The new diagnosticLocation identified modelmate.py,
native_tool_request, line 3151: rejection of unknown approval fields. This is
stronger failure evidence, not a permission-gate pass. The report did not retain
the actual extra field names or values; those cannot be claimed from this JSON.

An offline export with installed Codex CLI 0.172.0,
`codex app-server generate-json-schema --experimental --out SCRATCH`, exposes
additionalPermissions and availableDecisions on CommandExecutionRequestApprovalParams.
The earlier non-experimental export omitted both. Their schema describes an
optional permission overlay and an optional ordered list of offered decisions.
No App Server inference, account call or live retry was used for this export.

The shared manual/workflow parser now recognizes these two command fields.
additionalPermissions must be null/absent; even an empty non-null object remains
unsupported. When availableDecisions is non-null, it must be a bounded list of
string/object alternatives containing plain accept and decline. Other offered
alternatives are inert: the client never selects acceptForSession or policy
amendments. Unknown fields, malformed lists, missing plain choices, callbacks,
stdin, managed-network, environment and session-root scopes remain rejected.
File-change requests gain no new fields. This fixes a demonstrated compatibility
gap; it does not prove that these were the only extra fields in the live request.

A fake-server regression with the schema's null overlay and mixed decision
alternatives failed before the fix at the same native_tool_request line as the
user's result. After the fix it completes the scoped accept and decline cases,
with responses exactly accept then decline. Manual tests also cover null metadata,
non-null overlays, missing choices, malformed/oversized lists and an unknown null
field, while preserving read-only UI state. `PYTHONPATH=tests python3 -m unittest
test_live test_native_permissions test_workflow_approval_probe -q` passed 46 tests.
Compile/diff checks passed. Runtime SHA-256 is now
`bbf5a71155e6e7863b9b3507dbdc5533e9946e11c391fdc7bc23a0871eedcc18`;
verifier hash is unchanged. No scratch deletion, native replay or live gate pass
is claimed. Any new live run is a separately chosen quota-consuming attempt.

Full offline verification (`python3 -m unittest discover -s tests -v`) passed
all 783 tests in 51.632 seconds, with no skips.

### P09 remaining unsupported scope and redacted scope names (2026-11-27)

The user ran the command approval probe with runtime SHA-256
`bbf5a71155e6e7863b9b3507dbdc5533e9946e11c391fdc7bc23a0871eedcc18`
and verifier SHA-256
`3ee3e27c75db2d37c6cfa39f8c24a3c8c7cc9e9989927e8544db24166b15d5e9`.
The result stayed in approve/await_approval with all seven checks unverified.
Its source location was native_tool_request line 3163, the combined unsupported
scope guard. This locates a later rejection than the previous unknown-field
failure; it does not identify which scope condition was true or pass G2.

Read-only checks of the retained synthetic checkpoint and its scoped native
artifacts did not recover the original App Server approval request. No raw
session logs, native IDs, account data or scratch paths are copied here. No new
App Server, model turn, native command or network request was started, and the
retained scratch/native threads were not resumed or replayed.

The previous guard combined kind, approvalId, environmentId,
networkApprovalContext, grantRoot and additionalPermissions into one ProbeError.
It now collects every rejected field name into a tuple on that same exception.
The predicates and error text are unchanged. The approval verifier emits
unsupportedApprovalScopes only for a bounded tuple of those six fixed names;
field values, messages, exception locals and payloads remain excluded. Invalid
diagnostic attributes are ignored. This provides the information required to
assess a supported adapter change instead of guessing which policy to relax;
no additional scope is accepted by this increment.

`PYTHONPATH=tests python3 -m unittest test_live test_native_permissions
test_workflow_approval_probe -q` passed 47 tests. The new fake-server case rejects
five simultaneous scope conditions, reports their names without private values,
sends no accept and starts no second case. Existing non-null overlay and manual
rejection tests still pass; a private/invalid exception attribute cannot appear
in the report. Compilation and diff checks passed. Updated runtime SHA-256:
`cd764b6cca6fc078d9a93554642a4ceeef1ec06a7fd250b55fdf3589e35eac11`;
updated verifier SHA-256:
`b57bbc6f3a9b98008834b0795b8f59826c57cbe8828acbfd427a84d408b4c423`.
The cause's exact scope remains unresolved until a report contains the scope
names; any further live attempt is separately chosen and consumes quota again.

Full offline verification (`python3 -m unittest discover -s tests -v`) passed
all 784 tests in 65.579 seconds, with no skips.

### P16 C7 frozen cleanup-review fixture (2026-11-27)

No approval-probe scratch directory newer than the current feature commit was
present at the start of this increment. P09 still needs the requested rejected
scope data. Independent offline work proceeded on the explicitly planned C7
evaluation case rather than replaying a live probe or weakening its policy.

`examples/routing-pilot.py prepare --case cleanup` prepares identical numbered
review snippets and criteria for routed/baseline arms, differing only in their
requested role. The snippet seeds path escape and late confirmation while
retaining a correct early RUNNING guard. The scorer requires exact boolean
verdicts and line evidence for all three properties. It rejects malformed,
duplicate, missing, extra, oversized and falsely typed answers. No submitted
Python or model text is executed by the grader. A shared duplicate-key hook
retains strict incident scoring as well; its error text is now case-neutral.

Each project also contains the same frozen cleanup.py source for file evidence.
Launch revalidates the frozen C7 source/plan and refuses an existing arm state, so a
changed fixture or partial prior attempt cannot silently start a fresh arm.
Previews remain offline. Live execution still requires explicit --execute and
the normal START/workflow actions, and the existing CLI-only native tool approval
flag cannot be used for this review case. Prompt instructions do not replace
native sandbox/permission enforcement. No runtime code or permission was changed.

`PYTHONPATH=tests python3 -m unittest test_routing_pilot test_cli_pilot -q` passed
18 tests. Five new C7 tests cover equivalent previews with no state, a trusted
answer plus wrong-verdict/evidence mutants, strict malformed/duplicate/oversized
rejection, execution/measurement flag forwarding, and frozen-plan/old-state
launch tripwires. All candidate answers are developer-authored synthetic data;
subprocess execution is mocked in the execute-path test. Compile/diff checks
passed. Pilot SHA-256:
`9ff558f766d9591c488fa52aed4c290802a9850e70320e348fd9c6390f848961`.
Runtime SHA-256 is unchanged:
`cd764b6cca6fc078d9a93554642a4ceeef1ec06a7fd250b55fdf3589e35eac11`.
No model, account, quota, HTTP or actual cleanup command was requested. C7 live
pairing, held-out quality, independent review and G5 remain open.

Full offline verification (`python3 -m unittest discover -s tests -v`) passed
all 789 tests in 52.473 seconds, with no skips.

### P16 C4 parser-refactor fixture and frozen API checks (2026-11-27)

The planned C4 evaluation now has an offline preparer: `examples/routing-pilot.py
prepare --case parser` generates identical records.py/totals.py inputs with
duplicated parsing, separate routed/baseline plans and a frozen checker outside
the candidate project. The task extracts record_fields.parse_fields and keeps
the original tuple/dict APIs and error behavior. The same input/version/check
and independent-review criteria apply to both arms.

The registered command uses the existing hash-bound bootstrap, now shared by
the CLI and parser cases. A changed checker cannot substitute a self-reported
pass. Initial files, plan, command specification and runtime are revalidated
before launch; an existing arm state cannot start a fresh attempt. Actual live
authoring still requires --execute plus explicit native tool-approval opt-in.
Other pilot cases gain no tool-approval capability. No runtime/provider/native
permission or grant logic was changed.

The frozen checker validates the extracted module and 29 child observations for
normal/Unicode/whitespace/signed/zero counts, wrong input, missing/extra colons,
empty names, negative/fraction/noninteger counts, aggregation/order, iterable
rows and unchanged list inputs. It compares exact trusted JSON encodings of
observed types/values/errors against fixed expectations, without accepting a
candidate verdict or exposing raw stdout/stderr. Each child is supervised with
a two-second deadline, bounded output and owned process-group cleanup while
preserving stronger host file limits. These are execution bounds, not a new
filesystem/network security boundary. Timeout/failed children stop unverified.

A separate rubric and task criterion require independent confirmation of shared
delegation, removed duplicate validation and no circular imports. A deliberate
unused-helper mutant passes the machine API checks and still needs that review;
API equality alone is not proof that a refactor happened. No model-generated
review or self-reported tests can supply that trusted rubric verdict.

`PYTHONPATH=tests python3 -m unittest test_parser_pilot test_cli_pilot
test_routing_pilot -q` passed 27 tests. Nine new C4 tests cover original behavior
versus extracted module, audited reference, tuple/list and int/float mutants,
wrong ordering/aggregation/input mutation, mandatory independent review, paired
previews, checker/fixture/state integrity, explicit execution flags, timeout,
failed-child/private-error handling and stronger resource limits. All candidate
programs are developer-authored; execute-path forwarding uses a mock. No model,
account, HTTP or subscription quota was requested. Compile/diff checks passed.

Pilot SHA-256: `f22c0f252be50b50abb495d26b662a6a7c1bc8362c0a8d142841eac40cc29bad`.
Checker SHA-256: `a2e50c928ac55c9c47595ec22aa83beff6d8532f4e4b41235b67f2192d0b8f3b`.
Runtime SHA-256 remains
`cd764b6cca6fc078d9a93554642a4ceeef1ec06a7fd250b55fdf3589e35eac11`.
C4 live pairing, independent candidate review, held-out quality and G5 remain open.

Full offline verification (`python3 -m unittest discover -s tests -v`) passed
all 798 tests in 93.212 seconds, with no skips.

### P16 C5 migration fixture and controlled write failures (2026-11-27)

`examples/routing-pilot.py prepare --case migration` now prepares identical
legacy input, store.py, schema requirements and hash-bound checks for both arms.
The task normalizes v1 items/name/count into v2 records/name/quantity, preserves
order/duplicate names, reads either version without writes, migrates old files
atomically and treats current files as byte/metadata-preserving no-ops. Invalid
data must fail before writing. The existing _publish hook provides the specified
single os.replace publication boundary for deterministic fault injection.

The checker verifies frozen-input integrity and 36 operation observations.
It injects a publish OSError and independently forces a real file-write OSError
using a temporary one-byte child soft file-size limit. Restoration preserves
the inherited hard limit. Trusted parent observations compare actual file bytes,
mode, inode/mtime, owned snapshot cleanup and exact expected return/error/call
metadata. Expected equivalent paths are normalized; symlinks and nonregular
data files are rejected before reads. Each worker has bounded time/output and
owned process-group cleanup. These bounds do not replace native permissions.

The implementation step is high risk and has a following Strong review step.
Its separate trusted rubric requires exclusive private same-directory snapshots,
flush/fsync before atomic publication, owned cleanup and no hidden retries.
A no-fsync reference mutant passes the finite machine cases, explicitly showing
why those checks alone cannot prove durability or complete the task. Strong's
review proposal requires trusted human source/evidence inspection before a pass.
Process crashes, concurrent writers, power loss and live native tool behavior
remain outside this offline evidence.

`PYTHONPATH=tests python3 -m unittest test_migration_pilot test_parser_pilot
test_cli_pilot test_routing_pilot -q` passed 37 tests. Ten new C5 tests exercise
baseline versus audited references (including equivalent relative paths), real
write/publish failures, destructive/truncation/retry/swallow/no-op/cleanup mutants,
the independent fsync-review requirement, paired previews, checker/input/state
integrity, explicit native execution flags, timeout/private-error handling,
stronger file limits and FIFO observation without blocking the parent. All
candidates are developer-authored; execution-flag forwarding is mocked. No live
Codex/account/inference/search request was made. Compile/diff checks passed.

Pilot SHA-256: `87e23ec98442a8e164d3f145bc52f5fe9b7dd4b3b4015afafc5839a55c824eb8`.
Checker SHA-256: `15684ec515f568a7a64dd52988de813188b3ba3006510fada7639dd33cd5e000`.
Runtime SHA-256 remains
`cd764b6cca6fc078d9a93554642a4ceeef1ec06a7fd250b55fdf3589e35eac11`.
The final full offline suite passed 808 tests in 91.391 seconds with no skips. C5
live paired quality, independent candidate review and G5 remain open.

### P16 C6 concurrent writer and controlled process-crash checks (2026-11-27)

`examples/routing-pilot.py prepare --case writer` prepares identical broken
writer.py and sample checkpoints, an external hash-bound checker and the same
criteria for both arms. The high-risk task uses a stable private sidecar flock
across read/modify/atomic publish, unique private snapshots, and no adoption or
deletion of other writers' orphans. Existing authoring opt-in, artifact integrity
and started-arm no-replay guards are reused. The runtime/permission policy is
unchanged; model execution was not requested.

The six machine checks cover frozen input, sequential read/increment behavior,
two writers coordinated at provided read/publish hooks, process loss before and
after publication, and invalid-input preservation. Kernel shared-lock probes
confirm exclusive locking and stable inode identity. The checker uses actual
owned Popen handles and requires liveness alongside ready markers. It sends
SIGKILL only to its own worker groups, validates committed files and lock release,
then starts a distinct declared operation only after known-state proof. Poisoned
orphan snapshots and a bystander file must remain untouched. Results are compared
with actual file data/metadata and fixed observations, not a candidate's verdict.

This demonstrates controlled local process-crash behavior of developer-written
references. It does not exercise real native App Server session loss, missing
turn identity, exactly-once request reconciliation or hardware power loss.
A no-fsync mutant passes the finite machine checks; a following Strong step and
trusted human rubric explicitly require source review of critical-section scope,
exclusive snapshots, fsync/publication ordering, ownership and remaining limits.
That rubric cannot be supplied by a model claim alone.

`PYTHONPATH=tests python3 -m unittest test_writer_pilot test_migration_pilot
test_parser_pilot test_cli_pilot test_routing_pilot -q` passed 48 tests. The final
C6-only rerun passed 11 tests. New cases exercise the broken writer versus an
audited reference; missing/shared/data-inode/early-released locks; sidecar unlink
and repeated publication; non-atomic overwrite; orphan adoption/wildcard cleanup;
the independent fsync review requirement; paired previews; artifact/state and
execution opt-in guards; stale-marker rejection; timeout/private-error handling
and stronger file limits. All candidates are developer-authored, and live-launch
forwarding uses a mock. No live Codex/account/inference/search request was made.
Compilation and diff checks passed.

Pilot SHA-256: `e35d8e732c118e03272c0ea1d52fc4fadde928a15718f387fc9209f950e64343`.
Checker SHA-256: `a15311d71b1d09d3228a7428f039f4224791519cea617971e568341578e4d0ce`.
Runtime SHA-256 remains
`cd764b6cca6fc078d9a93554642a4ceeef1ec06a7fd250b55fdf3589e35eac11`.
C6 live model pairing, independent candidate review, held-out evaluation and G5
remain open; no G2/P12 live recovery gate is advanced by this fixture.

Full offline verification (`python3 -m unittest discover -s tests -v`) passed
all 819 tests in 107.008 seconds, with no skips.
