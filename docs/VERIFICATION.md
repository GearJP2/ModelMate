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
