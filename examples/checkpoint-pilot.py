"""Prepare checkpoint pilot tasks and grade trusted patches offline."""
import argparse
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


REPO = Path(__file__).resolve().parents[1]
CASES = {
    "display": (
        "e43bb08",
        "test_local_inspection",
        "LocalInspectionTests.test_paused_completed_attempt_displays_as_checking_with_saved_evidence",
        "A paused workflow whose backend turn has completed still shows its current "
        "step as running in checkpoint inspection. Show that step as checking and "
        "retain the saved check evidence. Preserve the paused workflow status.",
    ),
    "display-unknown": (
        "e43bb08",
        "test_local_inspection",
        None,
        "Checkpoint inspection omits the warning for an active attempt whose outcome "
        "is unknown. Restore the Thai warning, including the instruction against "
        "automatic replay. Preserve the completed-attempt message and read-only behavior.",
    ),
    "display-evidence": (
        "e43bb08",
        "test_local_inspection",
        None,
        "Read-only checkpoint inspection shows [pending] even for saved check "
        "results. Show saved results with their literal tags [pass], [fail], "
        "or [unknown], and use [pending] only for a check without saved evidence. "
        "Keep the saved workflow status and the historical-data notice.",
    ),
    "resume": (
        "f64ff7b",
        "test_native_resume",
        "NativeResumeTests.test_recovery_refuses_project_active_ephemeral_permission_and_turn_mismatch",
        "A rejected native workflow resume can rewrite the saved checkpoint. Preserve "
        "the checkpoint byte for byte on rejection, while keeping the current "
        "rejection checks and behavior for successful resumes.",
    ),
}


def git_output(*args):
    return subprocess.check_output(["git", *args], cwd=REPO)


DISPLAY_REGRESSIONS = {
    "display-unknown": (
        "            else:\n"
        "                write('มี attempt ค้างใน checkpoint; ผลปัจจุบันยังไม่ทราบ ห้าม replay อัตโนมัติ')\n",
        "",
    ),
    "display-evidence": (
        "write('  [' + checked.get(number, {}).get('result', 'pending') + '] '",
        "write('  [pending] '",
    ),
}


def export_base(case_name, directory):
    fix, module, _, _ = CASES[case_name]
    regression = DISPLAY_REGRESSIONS.get(case_name)
    revision = fix if regression else fix + "^"
    archive = git_output("archive", revision)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(directory, filter="data")

    if regression:
        runtime = directory / "modelmate.py"
        source = runtime.read_text(encoding="utf-8")
        original, replacement = regression
        if source.count(original) != 1:
            raise ValueError(f"Expected one mutation target for {case_name}.")
        runtime.write_text(source.replace(original, replacement), encoding="utf-8")
        (directory / "tests" / f"{module}.py").unlink()


EVIDENCE_BADGE_TEST = """
    def test_saved_fail_and_unknown_badges(self):
        for exit_code, label in ((1, 'fail'), (None, 'unknown')):
            with self.subTest(label=label):
                store, sid = self.create()
                controller = WorkflowController(json.dumps(PLAN), CATALOG, POLICY)
                with store.workflow(sid, QUOTA, time.monotonic(), CATALOG, POLICY,
                                    controller=controller):
                    dispatch = controller.request_attempt(QUOTA, time.monotonic(), CATALOG, POLICY)
                    controller.finish_attempt(
                        dispatch['dispatch']['attempt_id'], 'completed',
                        tool_observations={0: {'item_id': 'check', 'exit_code': exit_code}},
                    )
                    controller.pause()
                before = self.snapshot()
                self.assertIn(f'[{label}] test:', self.inspect(sid))
                self.assertEqual(before, self.snapshot())

"""


def grade(case_name, patch, *, repair_format=False):
    fix, module, selector, _ = CASES[case_name]
    with tempfile.TemporaryDirectory(prefix="modelmate-checkpoint-grade-") as scratch:
        root = Path(scratch)
        export_base(case_name, root)
        if patch:
            apply = ["git", "apply", "--include=modelmate.py"]
            if repair_format:
                apply.append("--recount")
                if not patch.endswith(b"\n"):
                    patch += b"\n"
            subprocess.run([*apply, "-"], cwd=root, input=patch, check=True)
        verifier = f"tests/{module}.py"
        verifier_source = git_output("show", f"{fix}:{verifier}").decode("utf-8")
        if case_name == "display-evidence":
            anchor = "    def test_saved_done_is_only_historical_evidence("
            if verifier_source.count(anchor) != 1:
                raise ValueError("Expected one insertion point in the pinned verifier.")
            verifier_source = verifier_source.replace(anchor, EVIDENCE_BADGE_TEST + anchor)
        (root / verifier).write_text(verifier_source, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-B", "-c",
             "import sys, unittest; sys.path.insert(0, 'tests'); unittest.main(module=None)",
             module if selector is None else f"{module}.{selector}"],
            cwd=root, timeout=60,
        ).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("case", choices=CASES)
    prepare.add_argument("workspace", type=Path, help="new directory for one arm")
    grader = commands.add_parser("grade")
    grader.add_argument("case", choices=CASES)
    grader.add_argument("patch", type=Path, help="reviewed patch against the case base")
    grader.add_argument("--trusted-patch", action="store_true", required=True,
                        help="confirm the patched Python code may execute locally")
    grader.add_argument("--repair-format", action="store_true",
                        help="add a final newline and recount diff hunk lines")
    args = parser.parse_args()
    case = CASES[args.case]
    try:
        if args.command == "prepare":
            args.workspace.mkdir()
            export_base(args.case, args.workspace)
            print(case[3])
            return 0
        return grade(args.case, args.patch.read_bytes(), repair_format=args.repair_format)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(f"Checkpoint pilot could not complete: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
