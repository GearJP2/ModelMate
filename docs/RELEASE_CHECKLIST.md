# Release evidence checklist

ModelMate remains an experimental CLI. Each release gate needs evidence
for the particular path, client version and platform being shipped. See
[VERIFICATION.md](VERIFICATION.md) for the dated test records.

| Gate | Evidence available | Remaining |
| --- | --- | --- |
| G1 account and dispatch | Live metadata-only catalog preview, requested-model paths, context recall and scoped resume | Reported dispatch telemetry is incomplete. |
| G2 permissions and lifecycle | Scoped live native workflow denial, interruption, metadata inspection, recheck recovery, scoped deletion and attached runtime-owned STOP after recheck client loss. Experimental workflow accept-once and its bounded verifier have offline evidence only. | Obtain the scoped command accept/decline verifier result, then separately verify patch approvals, live cancellation/failure paths, server/process-loss recovery and interactive CLI timing. |
| G3 private search | Live Thai Wikipedia lookup and offline general search through a configured SearXNG endpoint | Live SearXNG instance validation. Hosted search remains disabled in work threads. |
| G4 quota and billing | Offline admission and explicit recovery from exhausted or unknown quota. Live telemetry with observed account windows | Live exhausted/unknown admission paths and version-specific billing guarantees. |
| G5 evaluation | Scored C1, C3, A1 and the two-step economy pilot. Three checkpoint display pairs graded with original and format-repaired outcomes. | Expand independent task coverage and establish a defensible quota signal before estimating savings or enabling the trial rule by default. |
| R13 installation | Standalone runtime on WSL2 with Python 3.11 and 3.12, including installation into a path containing spaces | Independent clean installation on a second environment and release packaging after required gates pass. |

## Requirement coverage audit

This is a map of implementation evidence and outstanding work, not a passed
release checklist. Test files describe offline coverage; scoped live evidence
must be read with its exact version and limitations in VERIFICATION.md. Recent
source-check changes have offline evidence only. No new live test was run for
this audit.

| Requirement | Current implementation / offline evidence | Missing implementation or release proof |
| --- | --- | --- |
| R01 subscription only | ChatGPT/provider validation and quota admission; test_doctor.py, test_quota.py, test_live.py | G4 account/billing limitations remain; preflight is not a service spending cap. |
| R02 continuous chat / initial prompt / help | Manual live shell and offline help; test_cli.py, test_live.py, test_standalone.py | Plain prompt does not create an automatic workflow. Explicit manual selection and explicit-plan entry remain the available paths. |
| R03 code, analysis, planning, documents | Plan kinds, native checks, manual/rubric and explicit human source checks; test_workflow_entry.py, test_native_workflow.py, test_native_resume.py | Complete the independent evaluation set across task types; live source-check workflow is unverified. |
| R04 suitable model per step | Explicit role bindings, supported efforts and optional risk/check-based suggestions; test_models.py, test_routing.py, test_modes.py | Validated comparative model policy and broader held-out task evaluation; trial display rule remains experimental. No separate decision classifier is required. |
| R05 three model approval modes | Auto, Ask to escalate and Approve plan with scoped/stale grants; test_modes.py, test_workflow_ui.py | Broader live mode/routing failure evidence; Auto currently still needs explicit `/next` for each workflow step. |
| R06 tool permissions | Manual native UI plus experimental workflow accept-once subset, fixed read-only/on-request defaults and unsupported-request denial; test_live.py, test_permissions.py, test_native_permissions.py | Default workflow still declines approvals; opt-in native workflow acceptance has offline evidence only. Full live G2 permission matrix remains open. `/permissions` reports the fixed policy; it does not change the sandbox profile. |
| R07 correction budget | Controller owns initial attempt plus two corrections, explicit extensions and durable counters; test_workflow.py, test_workflow_persistence.py, test_recheck_ledger.py | Broader live correction/recovery paths; no model-generated counter or test claim can satisfy the controller. |
| R08 strong review only where needed | Risk/review validation, role bindings and scoped escalation; test_routing.py, test_workflow.py, test_modes.py | Comparative quality evidence for the bound roles and complex/high-risk real tasks. |
| R09 local sessions / resume / delete | Atomic project-local storage, locks, native bindings, reconciliation and scoped deletion; test_sessions.py, test_lifecycle.py, test_native_resume.py, test_recheck_recovery.py | Live runtime/server-loss and interactive shared-recheck recovery evidence; missing native thread ID discovery remains unsupported. |
| R10 private web search / citations | Separate confirmed-query Wikipedia/SearXNG commands and explicit human source verdicts; test_web_policy.py, test_workflow_entry.py | Search is not integrated as an automatic workflow step. Live SearXNG and the full G3 isolation/injection evidence remain open; hosted search stays disabled. Human source verification is not automatic fact checking. |
| R11 quota pause / fresh reset check | Fresh admission per controller turn, unknown/exhausted pause and explicit recovery; test_quota.py, test_native_workflow.py | Live exhausted/unknown paths and account-specific applicable bucket evidence. No timed automatic restart or bypass is implemented. |
| R12 honest time / actual model / usage | Local timing, requested selections, observed telemetry and unknown fields; test_metrics.py, test_native_workflow.py | Actual dispatch telemetry remains incomplete; quota observations cannot establish savings without attributable paired measurements. |
| R13 one-file Linux/WSL2 runtime | Standalone install/help/offline preview/missing-Codex/quoted alias checks; test_standalone.py | Complete target-environment release verification after G1–G4 and relevant failure gates pass. |

Next work must close these gaps or obtain the specific missing live evidence.
Adding offline tests alone cannot complete the plan, and a green suite does not
authorize enabling gated workflow approvals, automatic search or a release.

## Run without subscription turns

- Run the full offline suite and compile entry points.
- Install the runtime into a fresh user-local scratch directory and verify help,
  offline preview, and missing-Codex behavior on the target platform.
- From a normal authenticated Terminal, run the catalog preview described in
  [USAGE.md](USAGE.md).
- For the Wikipedia smoke, use a public test query, cancel the first preview,
  and confirm a second. Check the destination and cited links in the result.

## Live checks with explicit opt-in

The next prepared P09 check is
`python3 verify.py --run-live --probe-workflow-approvals MODEL` from a normal
authenticated Terminal. It uses at most two subscription turns and may accept
one bounded synthetic marker write, then declines the second case. Record the
CLI version, runtime/verifier hashes and all seven check results. Missing
approval requests are inconclusive; do not widen permissions to obtain them.
See the scoped verifier record in [VERIFICATION.md](VERIFICATION.md) before
running it. This check has not yet supplied live evidence. Installed CLI
0.172.0 has matching inspected approval schemas, which does not carry forward
the live compatibility evidence recorded for 0.171.0.

Keep release evidence sanitized. Record the runtime and Codex version plus
the specific result, avoiding account identifiers, session logs and quota
screenshots in the repository. Use the known scoped probes before running
any new permission or recovery scenario. Follow the frozen
[evaluation protocol](EVALUATION.md) for the remaining paired cases.
