# Release evidence checklist

ModelMate remains an experimental CLI. Each release gate needs evidence
for the particular path, client version and platform being shipped. See
[VERIFICATION.md](VERIFICATION.md) for the dated test records.

| Gate | Evidence available | Remaining |
| --- | --- | --- |
| G1 account and dispatch | Live metadata-only catalog preview, requested-model paths, context recall and scoped resume | Reported dispatch telemetry is incomplete. |
| G2 permissions and lifecycle | Scoped live native workflow denial, interruption, metadata inspection, recheck recovery, scoped deletion and attached runtime-owned STOP after recheck client loss. Experimental workflow accept-once and its bounded verifier have offline evidence only. | Obtain the scoped command accept/decline verifier result, then separately verify patch approvals, live cancellation/failure paths, server/process-loss recovery and interactive CLI timing. |
| G3 private search | Scoped legacy live Thai Wikipedia lookup; internal isolated launcher, bounded protocol, proc/lifecycle leak controls and fake-peer validation have offline evidence | The 2026-11-26 isolated English smoke was unverified; separate socket-creation probes found EPERM in the current execution profile. Real isolated DNS/TLS, live SearXNG, query-provenance/automatic integration and full G3 remain open. Hosted search stays disabled in work threads. |
| G4 quota and billing | Offline admission and explicit recovery from exhausted or unknown quota. Live telemetry with observed account windows | Live exhausted/unknown admission paths and version-specific billing guarantees. |
| G5 evaluation | Scored C1, C3, A1 and the two-step economy pilot. Three checkpoint display pairs graded with original and format-repaired outcomes. C2 CLI authoring, C4 parser-refactor, C5 JSON-migration, C6 concurrent-writer, C7 cleanup-review, C8 two-phase clarification, A2 project-planning and A3 installation-documentation fixtures/checkers are prepared with offline evidence only. | Run the prepared pairs with independent review, expand real/held-out task coverage and establish a defensible quota signal before estimating savings or enabling the trial rule by default. |
| R13 installation | Standalone runtime on WSL2 with Python 3.11 and 3.12, including installation into a path containing spaces | Independent clean installation on a second environment and release packaging after required gates pass. |

## Requirement coverage audit

This is a map of implementation evidence and outstanding work, not a passed
release checklist. Test files describe offline coverage; scoped live evidence
must be read with its exact version and limitations in VERIFICATION.md. Recent
source-check changes have offline evidence only. No new live test was run for
this audit.

2026-11-26 revalidation at `e28be63`: installed Codex reports 0.172.0. The
current planning cancellation path requests one known-turn interrupt, waits up
to five additional seconds for a matching terminal event, and reports unknown
on missing/invalid observations; its evidence is offline only (780 tests passed
at the recorded runtime hash). This does not transfer legacy live evidence to
the current source. Docker's WSL integration is unavailable in this distro, so
`docker version --format '{{.Server.Version}}'` exited 1 without reaching an
engine. No second clean environment was provisioned or tested. Enabling host
integration, installing dependencies or widening native permissions was not
attempted. The next prepared permission probe still needs explicit live-command
authorization; no subscription turn was requested by this revalidation.

| Requirement | Current implementation / offline evidence | Missing implementation or release proof |
| --- | --- | --- |
| R01 subscription only | ChatGPT/provider validation and quota admission; test_doctor.py, test_quota.py, test_live.py | G4 account/billing limitations remain; preflight is not a service spending cap. |
| R02 continuous chat / initial prompt / help | Manual live shell, selected-model --draft-plan plus two-phase --plan-workflow entry and numbered or interactive pre-start clarification answers for explicit plans; test_cli.py, test_live.py, test_standalone.py, test_workflow_entry.py | Plain prompt does not create an automatic workflow. Draft generation is an explicit opt-in planning turn; explicit --plan-workflow now hands off after separate preview/START; default plain-prompt entry remains manual. Explicit manual selection and explicit-plan entry remain available; the clarification entry has offline evidence only. |
| R03 code, analysis, planning, documents | Plan kinds, native checks, manual/rubric and explicit human source checks; test_workflow_entry.py, test_native_workflow.py, test_native_resume.py | Complete the independent evaluation set across task types; live source-check workflow is unverified. |
| R04 suitable model per step | Explicit role bindings, supported efforts and optional risk/check-based suggestions; test_models.py, test_routing.py, test_modes.py | Validated comparative model policy and broader held-out task evaluation; trial display rule remains experimental. No separate decision classifier is required. |
| R05 three model approval modes | Auto, Ask to escalate and Approve plan with scoped/stale grants; test_modes.py, test_workflow_ui.py | Broader live mode/routing failure evidence; Default Auto still needs `/next`; new explicit Auto plans can opt into experimental READY-attempt advancement after START (test_auto_advance.py). This has offline evidence only; terminal all-test/lint steps can evaluate existing native evidence automatically; mixed human checks still require trusted input. Optional user-approved --criterion-map resolves accepted IDs for final completion; without it /finish remains explicit. |
| R06 tool permissions | Manual native UI plus experimental workflow accept-once subset, fixed read-only/on-request defaults and unsupported-request denial; test_live.py, test_permissions.py, test_native_permissions.py | Default workflow still declines approvals; opt-in native workflow acceptance has offline evidence only. Full live G2 permission matrix remains open. `/permissions` reports the fixed policy; it does not change the sandbox profile. |
| R07 correction budget | Controller owns initial attempt plus two corrections, explicit extensions and durable counters; test_workflow.py, test_workflow_persistence.py, test_recheck_ledger.py | Broader live correction/recovery paths; no model-generated counter or test claim can satisfy the controller. |
| R08 strong review only where needed | Risk/review validation, role bindings and scoped escalation; test_routing.py, test_workflow.py, test_modes.py | Comparative quality evidence for the bound roles and complex/high-risk real tasks. |
| R09 local sessions / resume / delete | Atomic project-local storage, locks, native bindings, terminal work-turn correlation after a lost start binding, unknown-check retirement as UNVERIFIED, reconciliation and scoped deletion; test_sessions.py, test_lifecycle.py, test_native_resume.py, test_recheck_recovery.py | Work-turn correlation and missing/unknown-check resume have offline evidence only. Live runtime/server-loss and interactive shared-recheck recovery evidence remain open; missing native thread ID discovery remains unsupported. |
| R10 private web search / citations | Separate confirmed-query Wikipedia/SearXNG commands, internal fixed-profile isolated launcher with local boundary evidence, selectable JSON result handoff into a new workflow goal, and explicit human source verdicts; test_web_policy.py, test_workflow_entry.py | Result handoff has offline evidence only; search is not an automatic workflow step. Real isolated DNS/TLS was not verified in the current restricted profile; live SearXNG and the full G3 isolation/injection/integration evidence remain open; hosted search stays disabled. Imported candidates and human source verification are not automatic fact checking. |
| R11 quota pause / fresh reset check | Fresh admission per controller turn, unknown/exhausted pause and explicit recovery; test_quota.py, test_native_workflow.py | Live exhausted/unknown paths and account-specific applicable bucket evidence. No timed automatic restart or bypass is implemented. |
| R12 honest time / actual model / usage | Local timing, separate/combined planning-workflow wall time, separate observed planning-turn usage/reroutes, requested selections and unknown fields; test_metrics.py, test_native_workflow.py | Actual dispatch telemetry remains incomplete; quota observations cannot establish savings without attributable paired measurements. |
| R13 one-file Linux/WSL2 runtime | Standalone install/help/offline preview/missing-Codex/quoted alias checks; test_standalone.py | Complete target-environment release verification after G1–G4 and relevant failure gates pass. |

Next work must close these gaps or obtain the specific missing live evidence.
Adding offline tests alone cannot complete the plan, and a green suite does not
authorize enabling gated workflow approvals, automatic search or a release.

## Completion audit — 2026-11-27

Checked the task/dependency table, P13/P15/P16 acceptance criteria, the R01–R13
coverage map, CLI dispatch and current source hashes at `db20887`. Installed
Codex still reports 0.172.0 and the local interpreter is Python 3.12.0. The latest
full offline run passed 841 tests at this runtime; subsequent checks here were
read-only. No inference, HTTP lookup, account query or permission expansion was
performed. Historical live evidence is not transferred to current paths by
matching a CLI version or passing the offline suite.

Eleven of the twelve named synthetic evaluation cases now have prepared pilots
or previously recorded scoped results. Preparation is not a completed paired
evaluation. A4 remains unprepared for live execution because its private-search
dependency is still open; supplied/mock source excerpts would not prove that
private text stayed out of a real search context.

| Work still required | Dependency / evidence needed before completion |
| --- | --- |
| P09 command approval compatibility | The user-run probe progressed from environmentId to the availableDecisions guard. Exact `local` remains the only supported explicit environment. Plain accept plus decline or cancel is now supported; controller denial uses cancel only when decline is absent. Current-runtime live results remain unverified; command success does not pass patch or failure/loss paths. |
| P01/P03/P08/P10/P12 current native integration | Current-version dispatch observations plus live mode, patch, cancellation, disconnect/process-loss and interactive timing evidence. Existing prepared probes cover particular bounded paths, not the whole matrix. |
| P06/P08 default entry and P10 automatic execution | Plain-prompt entry still dispatches manual chat; explicit planning/plan handoff and experimental Auto advancement exist. Default automatic workflow behavior remains implementation work gated by native permission dependencies, not something a documentation or pilot change completes. |
| P13 and A4 | Real isolated DNS/TLS and SearXNG evidence, query-provenance handling and automatic integration with private-file/history and injection checks. The current profile denied sockets; a normal capable environment must supply actual evidence without widening native permissions or replaying the previous attempt. Keep gated search disabled. |
| P04/P12/R11 and G4 | Live unknown/exhausted quota admission/recovery and applicable billing-limit evidence. Offline synthetic quota cases cannot establish service spending guarantees. |
| P16 quality and routing policy | Execute prepared pairs with independent acceptance; obtain authorized real-task examples with frozen rubric and separate calibration/held-out sets. No such held-out dataset is supplied by the public pilots. Do not mine PR history into a benchmark or invent quality/quota savings. |
| P15 release installation | A genuinely independent clean target environment, then final packaging/user-guide validation after relevant gates. Two Python versions on this host and A3's temporary example installation are not that evidence. |

There is no release-completion verdict. At this audit's revision the next native
diagnosis was the pending user-run scope report, not a guessed exception or an
automatic quota-consuming probe. The historical audit's runtime SHA-256 was
`cd764b6cca6fc078d9a93554642a4ceeef1ec06a7fd250b55fdf3589e35eac11`;
verifier SHA-256 is
`b57bbc6f3a9b98008834b0795b8f59826c57cbe8828acbfd427a84d408b4c423`.

## Run without subscription turns

- Run the full offline suite and compile entry points.
- Install the runtime into a fresh user-local scratch directory and verify help,
  offline preview, and missing-Codex behavior on the target platform.
- From a normal authenticated Terminal, run the catalog preview described in
  [USAGE.md](USAGE.md).
- For the Wikipedia smoke, use a public test query, cancel the first preview,
  and confirm a second. Check the destination and cited links in the result.

## Live checks with explicit opt-in

The 2026-11-27 user-run command probe on Codex 0.172.0 returned ProbeError in
the approve phase with all seven checks unverified. Its original exception
location was not captured; the cause is unresolved. The updated verifier now
includes `probeStage` and source-only `diagnosticLocation` for errors. That
change has offline evidence only. A new run uses subscription quota again and
must be explicitly chosen; the original attempt is not replayed automatically.

The next prepared P09 check is
now updated for two experimental optional command fields found in the installed
0.172.0 schema. Only null additionalPermissions is supported; non-null overlays
remain gated. Explicit availableDecisions must offer plain accept and decline;
session/policy alternatives are not selected. This compatibility fix has offline
evidence only. The second user-run attempt located the previous unknown-field
rejection but did not pass any of the seven live checks.

Run the scoped check as
`python3 verify.py --run-live --probe-workflow-approvals MODEL` from a normal
authenticated Terminal. It uses at most two subscription turns and may accept
one bounded synthetic marker write, then declines the second case. Record the
CLI version, runtime/verifier hashes and all seven check results. Missing
approval requests are inconclusive; do not widen permissions to obtain them.
See the scoped verifier record in [VERIFICATION.md](VERIFICATION.md) before
running it. This check has not yet supplied passing live evidence. Installed CLI
0.172.0 has matching inspected approval schemas, which does not carry forward
the live compatibility evidence recorded for 0.171.0.

The next user-run attempt at runtime bbf5a711 passed optional-field parsing but
stopped at the unsupported-scope guard, with all seven checks unverified. Its
report cannot distinguish which scope was present. The verifier now reports
`unsupportedApprovalScopes` using fixed field names only; values/IDs remain
redacted. This diagnostic addition changes no approval policy and has offline
evidence only. Do not remove scope guards or widen permissions to obtain a pass.

The 2026-11-28 user-run probe at runtime cd764b6c now identifies only
`environmentId` as unsupported; all seven checks stayed unverified. The shared
parser supports exact literal `local`, whose reserved local identity is defined
in upstream's environment manager, and shows it in the command preview. Missing
or null remains compatible; every other value is still rejected, as are network,
callback and additional permission scopes. The result does not reveal whether
the actual environment was local. This compatibility change is offline-tested
only and does not change environment selection or native permission policy.
Any new live probe is a separately chosen quota-consuming run, not a replay.

The next user-run probe at runtime dc4d2ac7 stopped at the availableDecisions
guard instead of a scope guard. All seven checks remain unverified and the
actual choices are not in that report. The current parser supports plain accept
with either decline (deny/continue) or cancel (deny/interrupt), preferring decline
when both are offered. It displays the denial decision and preserves a durable
declined controller verdict. The verifier accepts an observed cancelled denial
only with its existing file, terminal, durable and single-use checks. No session
or policy grant is selected. If plain accept or a supported denial is missing,
the new `offeredApprovalDecisions` diagnostic exposes only recognized enum names,
never arbitrary response text or unknown values. This change has offline
evidence only; the actual live request may still be unsupported.

A separate patch check is prepared as
`python3 verify.py --run-live --probe-workflow-patches MODEL`. It uses at most two
subscription turns and may accept one new synthetic marker file, then declines
the second case. It recognizes only a single literal-line addition in plain
content or added-line encoding; unsupported diff encodings cannot obtain
acceptance. Like the command probe, it retains scratch/native threads and has
offline evidence only. It does not replace the command check or prove broader
G2 coverage.

Keep release evidence sanitized. Record the runtime and Codex version plus
the specific result, avoiding account identifiers, session logs and quota
screenshots in the repository. Use the known scoped probes before running
any new permission or recovery scenario. Follow the frozen
[evaluation protocol](EVALUATION.md) for the remaining paired cases.
