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
