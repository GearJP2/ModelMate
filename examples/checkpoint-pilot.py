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


def export_base(case_name, directory):
    fix, module, _, _ = CASES[case_name]
    revision = fix if case_name == "display-unknown" else fix + "^"
    archive = git_output("archive", revision)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(directory, filter="data")


    if case_name == "display-unknown":
        # Simulate a display regression while retaining the completed-attempt branch.
        runtime = directory / "modelmate.py"
        source = runtime.read_text(encoding="utf-8")
        warning = ("            else:\n"
                   "                write('มี attempt ค้างใน checkpoint; ผลปัจจุบันยังไม่ทราบ ห้าม replay อัตโนมัติ')\n")
        if source.count(warning) != 1:
            raise ValueError("Expected one unknown-attempt warning in the base revision.")
        runtime.write_text(source.replace(warning, ""), encoding="utf-8")
        (directory / "tests" / f"{module}.py").unlink()


def grade(case_name, patch):
    fix, module, selector, _ = CASES[case_name]
    with tempfile.TemporaryDirectory(prefix="modelmate-checkpoint-grade-") as scratch:
        root = Path(scratch)
        export_base(case_name, root)
        if patch:
            subprocess.run(
                ["git", "apply", "--include=modelmate.py", "-"],
                cwd=root, input=patch, check=True,
            )
        verifier = f"tests/{module}.py"
        (root / verifier).write_bytes(git_output("show", f"{fix}:{verifier}"))
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
    args = parser.parse_args()
    case = CASES[args.case]
    try:
        if args.command == "prepare":
            args.workspace.mkdir()
            export_base(args.case, args.workspace)
            print(case[3])
            return 0
        return grade(args.case, args.patch.read_bytes())
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(f"Checkpoint pilot could not complete: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
