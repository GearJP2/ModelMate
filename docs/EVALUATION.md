# Model routing evaluation

The evaluation compares ModelMate's suggested routing with the same workflow
using one explicitly chosen strong model for every step. All proposed cases
below are synthetic. Freeze their inputs, checks and acceptance criteria
before requesting subscription turns.

## Cases

| Case | Task | Acceptance criteria |
| --- | --- | --- |
| C1 | Fix an off-by-one boundary in a list helper | Empty, singleton and end-index regression tests pass. |
| C2 | Implement an option in a small CLI | Added option works and existing input, help and exit codes stay compatible. |
| C3 | Add stable de-duplication to an importer | Order and handling of blank and duplicate rows match fixtures. |
| C4 | Refactor a parser across modules | Existing API and error cases pass the same fixture suite. |
| C5 | Migrate a local JSON schema | Old data loads, repeat migration is safe and failed writes preserve originals. |
| C6 | Repair a concurrent local writer | Contention and crash fixtures preserve the last valid checkpoint. |
| C7 | Review a file cleanup change | Correctly identify seeded scope and confirmation bugs with file evidence. |
| C8 | Implement behavior from an ambiguous request | Pause for the missing requirement before dispatch. Both arms then receive the same clarification. |
| A1 | Summarize a synthetic incident timeline | Timestamps, causal claims and uncertainties match the supplied record. |
| A2 | Compare options for a short project plan | Use the supplied constraints, identify trade-offs and cover every rubric item. |
| A3 | Edit installation instructions | A reviewer can install and run the example from a fresh directory with spaces in its path. |
| A4 | Write a short source-backed briefing | Each material claim has a supporting source and private fixture text stays out of search queries. Requires the web privacy gate. |

## Compare paired runs

1. Pin the repository, Codex and runtime version. Use separate clean project copies and fresh threads for each arm. Record actual available model IDs and supported effort levels before the comparison.
2. Keep the goal, inputs, step objectives, checks, permission policy and correction budget fixed. In the baseline, use the same strong model ID for every step and predeclare its effort policy. In the routed arm, use the same strong binding and predeclare the economy and standard bindings. Enable `--suggest-models` and record any user-approved change.
3. Alternate the order of paired runs. Apply the same clarification answers, approval decisions and independent acceptance checks to both. Treat rejected or paused cases as recorded outcomes. Keep missing measurements as unknown.
4. Score each completed pair against the frozen criteria using trusted test outputs or a human reviewer. Record pass rates, critical failures, corrections, active and wall time where available, and requested roles, models and efforts. Record backend telemetry only when reported.
5. If testing quota consumption, record sanitized before/after snapshots for the same eligible quota windows and note resets and concurrent use. A window delta affected by resets or concurrent clients cannot support a per-task savings claim. Report limitations and compare paired observations only where the measurement is attributable.

All critical checks must pass and routed quality must meet the baseline before
claiming equivalent quality. Report any observed consumption difference with
its denominator, paired sample count and scope. The table defines planned
cases. The C1 pilot result is recorded below. Quota savings remain unmeasured.

## Run the C1 pilot

`examples/routing-pilot.py` prepares a frozen runtime and two separate scratch
projects with separate session state. Both arms choose a repair for the same
synthetic off-by-one bug, with the same one-letter response format. The scorer
runs five fixed cases against trusted candidate expressions. No model-generated
code is executed. The scratch copies contain the plans and the runtime. This
pilot tests standard/low versus a distinct user-bound strong model at low
effort. It uses rubric evidence and does not exercise economy routing, worktree
writes, or quota savings.

From the checkout, list model IDs that expose low effort in your account:

```bash
python3 modelmate.py --doctor | python3 -c '
import json, sys
for model in json.load(sys.stdin)["models"]:
    if any(e.get("reasoningEffort") == "low" for e in model["supportedReasoningEfforts"]):
        print(model["model"])
'
```

Choose and keep the same two bindings across the pair. From the checkout:

```bash
PILOT="$PWD/examples/routing-pilot.py"
PAIR="$(python3 "$PILOT" prepare)"
read -r -p 'Standard model ID: ' STANDARD
read -r -p 'Strong model ID: ' STRONG
python3 "$PILOT" run "$PAIR" routed --standard "$STANDARD" --strong "$STRONG"
python3 "$PILOT" run "$PAIR" baseline --standard "$STANDARD" --strong "$STRONG"
```

The two previews are offline. For the live pilot, append `--execute` to the
routed command, then to the baseline command after finishing the routed arm.
In each arm enter `START`, then `/next`, approve that arm's printed token with
`/approve TOKEN`, and enter `/next` once more. This requests one subscription
turn per arm. After the answer appears and the workflow reaches `CHECKING`, run
`python3 "$PILOT" score LETTER` in another Terminal using the actual answer and
the same script path. Enter `/verify 1 pass` if all five cases passed, or
`/verify 1 fail` if a case failed. Then enter `/check`. On a passing run finish
with `/finish 1=1.1`. Use `/exit` to print the workflow statistics. Record a
failure, missing response or permission pause as observed, without replaying
the turn. Record both requested selections, score results and exit statistics.

### C1 result

The user-run pair scored 5/5 for both requested selections,
`gpt-6.2-sol/low` (routed) and `gpt-6.2-astra/low` (baseline), with one attempt
in each completed run. The initial baseline exits are recorded separately
in [VERIFICATION.md](VERIFICATION.md). The independent score was calculated
from the displayed answers. Both local workflows were paused after exit
before rubric entry. The comparison covers one synthetic repair-choice task.

## Two-step economy pilot

Prepare with `examples/routing-pilot.py prepare --case economy`. Run each arm
with the same three distinct low-effort bindings via `--economy`,
`--standard` and `--strong`. The supplied read-only fixture already contains
the patch. Both arms validate it with the same registered unittest command,
then propose a missing regression test. The routed arm requests economy/low
then strong/low. The baseline requests strong/low twice. Both use Ask to
escalate. Check that the routed first step starts directly and each strong
step waits for an explicit approval and another `/next`.

Use `/check` after the first step reaches CHECKING to capture actual native
command evidence. For step two, score the answer independently. A valid
example gives input with the target first appearing at the final index,
the correct expected index and why existing tests miss the boundary.
After that turn reaches CHECKING, record the verdict using `/verify 1 pass`
or `/verify 1 fail`, then `/check`. If both steps pass, use
`/finish 1=1.1 2=2.1` and `/exit`. An uninterrupted pair takes four requested
turns. Record failures as observed without automatically retrying.

This case exercises native test evidence and model switching on a staged
fixture. It measures neither patch authorship nor attributable quota usage.

### Two-step result

Both arms passed the observed native test and independent review criterion.
The routed arm used one economy request and one strong request. The baseline
used two strong requests, with its review dispatched after resuming the same
session. Both used low effort, two attempts and zero rechecks for the graded
pair. The result covers routing and approval on this staged fixture. Quota
savings remain unmeasured. See [VERIFICATION.md](VERIFICATION.md) for the
earlier incomplete baseline attempts and evidence scope.

### Measure the next live pair

For a fresh pair prepared from a runtime with metrics, add `--measure-quota`
to both executing `routing-pilot.py run` commands. Preserve each arm's report
and note concurrent account use or quota resets. Use `turnElapsedSeconds` and
`timedTurns` for the observed work turns, and keep CLI wall time separately.
An interrupted or resumed arm may have partial timing and a historical thread
token total. A missing or unchanged window percentage cannot establish the
arm's quota cost. The metadata read adds no model turn.

### One-turn telemetry smoke test

This check uses the short list/tuple example in a fresh scratch project.
Run from any Bash working directory with ModelMate at the given path:

```bash
REPO="$HOME/Coding/Hobby/ModelMate"
SMOKE="$(mktemp -d /tmp/modelmate-usage-smoke-XXXXXX)" &&
mkdir "$SMOKE/project" &&
(
  cd "$SMOKE/project" &&
  XDG_STATE_HOME="$SMOKE/state" python3 "$REPO/modelmate.py" \
    --workflow "$REPO/examples/explain-lists.json" \
    --role-model standard=gpt-6.2-sol \
    --execute-workflow --measure-quota
)
```

Enter `START` and then `/next` once. Wait for the answer and `CHECKING`
before entering `/exit`. This exercises reporting and does not require
rubric entry. Keep the `สถิติ workflow` line. Check that `attempts` and
`timedTurns` are both 1 and the turn duration is present. Record whether
the backend emits token counters and whether any quota windows are comparable.
An observed delta of zero is valid and cannot establish zero usage.

### Measured de-duplication pair (C3)

Run the baseline first for this pair. From any Bash working directory:

```bash
PILOT="$HOME/Coding/Hobby/ModelMate/examples/routing-pilot.py"
PAIR="$(python3 "$PILOT" prepare --case dedupe)" &&
python3 "$PILOT" run "$PAIR" baseline \
  --standard gpt-6.2-sol --strong gpt-6.2-astra --execute
```

Enter `START` and `/next` once. Wait for the letter and CHECKING, then
`/exit`. Run the same command with `routed` in place of `baseline` from
the same shell, keeping the same pair path. This case uses Auto for both arms,
and the launcher enables quota measurement for both. Use
`python3 "$PILOT" score --case dedupe LETTER` to score each answer. It tests
five fixed cases using trusted candidate expressions, including ordering and
duplicates after whitespace normalization. The case compares choices for a
staged importer defect and does not test patch authorship. Retain the answer
and summary from each arm. Quota window deltas can remain unchanged at the
reported resolution.

#### Measured C3 result

Both completed arms answered D and scored 5/5 with one timed attempt each.

| Arm | Requested model | Total tokens | Cached input subset | Observed turn seconds |
| --- | --- | ---: | ---: | ---: |
| Baseline | gpt-6.2-astra/low | 13,183 | 4,608 | 3.110 |
| Routed | gpt-6.2-sol/low | 13,232 | 0 | 2.068 |

The routed run reported 49 more tokens. The primary account window advanced
only during baseline observation, while the secondary window showed no visible
change across either observation. The cache difference, sequential run order
and account-level reporting prevent attributing those window changes to a
model or estimating quota savings. The user exited both completed turns
before rubric entry, so arm quality comes from independent scoring.

For a future paired run, set the output paths once, in the shell where
`PILOT` and `PAIR` were prepared:

```bash
PILOT="$HOME/Coding/Hobby/ModelMate/examples/routing-pilot.py"
BASELINE_LOG="$PAIR/baseline.jsonl"
ROUTED_LOG="$PAIR/routed.jsonl"
```

Append `--metrics-jsonl "$BASELINE_LOG"` to that pair's baseline launch
and `--metrics-jsonl "$ROUTED_LOG"` to the routed launch. The launcher
writes each file when its started workflow exits. Earlier runs without
the flag have only their Terminal summaries. Keep any quota observations
separately because the JSONL files contain timing and token counters.

Once both files exist, compare the pair offline from any working directory:

```bash
python3 "$PILOT" compare "$BASELINE_LOG" "$ROUTED_LOG"
```

When a file contains multiple runs, select the intended record with
`--baseline-row N` and/or `--routed-row N` (1-based). Pair runs with the same
frozen task and runtime. The command reports routed minus baseline for work
turn time, reported work-thread tokens and its cached-input subset. It
leaves incomplete timing, resumed runs with earlier attempts, and missing
latest token snapshots as null where applicable. Apply the case scorer or
rubric separately for quality. Account quota observations are not in the
JSONL records.

Inspect `observedModelReroutes` when comparing records. If Codex reported a
reroute for an arm, its measurements describe that arm as observed. A
requested model alone cannot establish which model processed every response.

### Measured incident-analysis pair (A1)

`prepare --case incident` freezes a synthetic checkout incident with
out-of-order event records and competing recovery explanations. The two arms
receive the same records and produce one JSON object. A deterministic rubric
checks chronological order, observed duration, causal uncertainty, and the
event supporting the competing explanations. The grader rejects duplicate keys.

Run the routed arm first for this case. Use `--execute --metrics-jsonl FILE`
for each arm and its own file within the prepared pair directory. The launcher
uses Auto and enables quota-window observations for both arms. After
`START`, submit `/next` once, wait for the answer and CHECKING, and exit.
Use `score --case incident` with the answer JSON and `compare` with the two
files. This case measures one analysis attempt per arm. It cannot establish
quota savings on its own.

#### Measured A1 result

Both completed arms scored 4/4 on the same structured incident answer
and each used one timed attempt. The pilot wrote both JSONL files and
the offline comparator reproduced the following measurements.

| Arm | Requested model | Total tokens | Cached input subset | Observed turn seconds |
| --- | --- | ---: | ---: | ---: |
| Routed | gpt-6.2-sol/low | 13,322 | 9,856 | 3.360 |
| Baseline | gpt-6.2-astra/low | 13,273 | 9,984 | 5.292 |

Routed reported 49 more tokens and its observed turn was 1.932 seconds
shorter. The secondary window showed no visible change for either arm;
there was no comparable primary window reported by the routed arm.
The cache differed and the runs were sequential. The two observations
do not establish a quota saving or a general latency advantage.

Compare `firstPassSteps` and `firstPassRate` for workflows that recorded
their checks. Unknown first attempts are shown separately. To compare
`timeToAcceptanceSeconds`, run both arms to DONE and record their rubric
and criterion coverage before exit. The timer includes user wait and
corrections in the CLI session and stops at acceptance. When a prior
attempt was made in another session, the comparison tool suppresses this
timing delta. Earlier pilots that exited before final assessment retain
their independent grades and have no in-workflow acceptance time.

## Historical workflow checkpoint cases (P16)

The first real-task pilot uses ModelMate's own checkpoint history. Both cases
ask for a focused checkpoint bug fix with an existing offline acceptance test.
The cases differ in impact. One changes the displayed status. The other must
preserve persisted data across a rejected resume.

| Set | Base revision | Task shown to the model | Independent acceptance check |
| --- | --- | --- | --- |
| Rule development | `e43bb08^` | A paused workflow whose backend turn has completed still shows its current step as running in checkpoint inspection. Show that step as checking and retain the saved check evidence. Preserve the paused workflow status. | `test_local_inspection.LocalInspectionTests.test_paused_completed_attempt_displays_as_checking_with_saved_evidence` from `e43bb08` |
| Evaluation | `f64ff7b^` | A rejected native workflow resume can rewrite the saved checkpoint. Preserve the checkpoint byte for byte on rejection, while keeping the current rejection checks and behavior for successful resumes. | `test_native_resume.NativeResumeTests.test_recovery_refuses_project_active_ephemeral_permission_and_turn_mismatch` from `f64ff7b` |

### Offline acceptance evidence

For each case, export the fix revision with `git archive`. In that temporary
tree, run the indicated test with `PYTHONPATH=.:tests python3 -B -m unittest
TEST_SELECTOR`, first with `modelmate.py` from the parent and then with
`modelmate.py` from the fix revision. The same test and supporting files are
used for both runs.

- `e43bb08^` failed the CHECKING assertion and `e43bb08` passed.
- `f64ff7b^` failed the byte comparison in all nine rejection scenarios and
  `f64ff7b` passed.

These are verifier checks. No model has attempted either historical task as
part of this pilot.

### Paired evaluation

Give each arm a fresh export of the same base revision and the same task text.
Keep repository history, the fix revision and the updated verifier outside the
agent workspace. Apply the candidate diff to a fresh evaluator tree and grade
it independently. Record pass, fail or unknown for each attempt. Use unknown
when the harness cannot run the verifier. Preserve the repo's tool permissions
and obtain explicit authorization before live inference.

Use the rule-development case to draft and freeze a routing rule before running
the evaluation case. The starting hypothesis is to try a smaller model on
display-only defects with an offline verifier. Persisted checkpoint changes
form a separate scope and require their own evidence before lowering the
starting model. Use the existing escalation mode and count all attempts when
comparing with strong-only. Log first and final verdict, strong requests,
corrections and time to acceptance. Record quota observations when available.
One case per set is enough to exercise the procedure. Estimates of quality or
quota savings require more independent cases.

Run the preparation and grading steps from the original checkout. Use a new
workspace for each arm and save its unified diff outside that workspace.

```sh
scratch=$(mktemp -d)
python3 examples/checkpoint-pilot.py prepare display "$scratch/display"
# Save the candidate's modelmate.py diff as "$scratch/candidate.patch".
python3 examples/checkpoint-pilot.py grade display "$scratch/candidate.patch" --trusted-patch
```

Use `resume` in place of `display` for the evaluation case. The grader
applies changes to `modelmate.py` and restores the selected historical
verifier from the fix revision. It runs candidate code under the caller's
permissions. Review the patch and use an appropriately isolated environment
before grading model-generated changes. Exit 0 means the test passed, exit 1
means unittest reported a failure or error, and exit 2 covers preparation or
execution errors caught by the wrapper. Inspect the test output to distinguish
a regression from an unavailable verifier.

Offline smoke run for both cases produced the expected assertion failures with
an empty patch and a passing test with the historical fix. Each prepared
workspace had no Git history.

### First live display pair

The user ran Codex CLI 0.170.0 with read-only tools and low reasoning effort
against separate exports of the display base. Both models proposed changing
the displayed step state for the matching completed attempt while keeping
the saved checkpoint and evidence intact.

| Requested model | Original patch | Regression check after format repair | CLI-reported tokens |
| --- | --- | --- | ---: |
| gpt-6.2-sol | Rejected as corrupt | Pass | 31,561 |
| gpt-6.2-astra | Rejected as corrupt | Pass | 8,825 |

The original patch files lacked a trailing newline. Adding it and using
`git apply --recount` in fresh base exports allowed both patches to apply.
The grader verified regenerated diffs without changing either proposed code
edit. Count both original deliveries as failed and both format-repaired
changes as passing. No additional model turn was used for the repair. Token
counts alone cannot establish subscription quota savings.

Freeze the candidate rule for the next evaluation. Start with Standard for
display-only checkpoint changes that have independent offline verification.
Keep the existing selection for persisted state changes. A patch formatting
error calls for local syntax validation before considering model escalation.
The resume case sits outside the display-only scope and can check that the
rule does not lower the model for that case. A separate unseen display case
is needed to test whether the proposed downgrade generalizes.

### Additional display evaluation case

Use `prepare display-unknown` and `grade display-unknown` with the same
arguments as `display`. This case removes the unknown-outcome warning from
the historical checkpoint renderer at `e43bb08`. It is a synthetic
regression based on existing behavior. The prepared workspace omits the
local-inspection verifier. The evaluator restores it from the pinned
revision and runs the entire local-inspection suite. The suite failed with
the warning removed and passed after restoring it. Keep the frozen routing
rule for this pair and request Standard versus Strong at the same effort.
Record first-delivery and format-normalized results separately as in the
first pair.
