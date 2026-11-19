"""Offline checks for the historical checkpoint preparation and grader."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
PILOT = REPO / "examples" / "checkpoint-pilot.py"


class CheckpointPilotTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)

    def run_pilot(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(PILOT), *map(str, args)],
            cwd=self.scratch, capture_output=True, text=True, timeout=20,
        )

    def test_saved_evidence_case_hides_verifier_and_grades_reference(self):
        workspace = self.scratch / "work"
        prepared = self.run_pilot("prepare", "display-evidence", workspace)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertFalse((workspace / ".git").exists())
        self.assertFalse((workspace / "tests" / "test_local_inspection.py").exists())
        for label in ("pass", "fail", "unknown", "pending"):
            self.assertIn(f"[{label}]", prepared.stdout)

        patch = self.scratch / "candidate.patch"
        patch.touch()
        rejected = self.run_pilot("grade", "display-evidence", patch, "--trusted-patch")
        self.assertEqual(rejected.returncode, 1, rejected.stderr)
        self.assertIn("label='fail'", rejected.stderr)
        self.assertIn("label='unknown'", rejected.stderr)

        reference = self.scratch / "reference.py"
        reference.write_bytes(subprocess.check_output(
            ["git", "show", "e43bb08:modelmate.py"], cwd=REPO,
        ))
        diff = subprocess.run(
            ["diff", "-u", "--label", "a/modelmate.py", workspace / "modelmate.py",
             "--label", "b/modelmate.py", reference],
            capture_output=True, timeout=20,
        )
        self.assertEqual(diff.returncode, 1, diff.stderr)
        patch.write_bytes(diff.stdout)
        accepted = self.run_pilot("grade", "display-evidence", patch, "--trusted-patch")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_format_repair_preserves_original_patch(self):
        patch = self.scratch / "candidate.patch"
        raw = subprocess.check_output(
            ["git", "diff", "e43bb08^", "e43bb08", "--", "modelmate.py"], cwd=REPO,
        ).rstrip(b"\n")
        patch.write_bytes(raw)

        original = self.run_pilot("grade", "display", patch, "--trusted-patch")
        self.assertEqual(original.returncode, 2, original.stderr)
        repaired = self.run_pilot(
            "grade", "display", patch, "--trusted-patch", "--repair-format",
        )
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(patch.read_bytes(), raw)
