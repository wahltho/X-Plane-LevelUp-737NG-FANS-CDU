from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchlib import decode_rgba_png


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY_ROOT / "z_Install.py"
TARGETS = (
    "plugins/xlua/scripts/B738.tablet/B738.tablet.lua",
    "objects/737_cockpit_ovhd2.obj",
    "objects/737cockpit_overhead2.dds",
    "objects/737cockpit_overhead2_LIT.dds",
    "objects/737cockpit_overhead2_NML.png",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InstallerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        upstream = os.environ.get("LEVELUP_UPSTREAM_ROOT")
        reference = os.environ.get("LEVELUP_FANS_REFERENCE_ROOT")
        if not upstream or not reference:
            raise unittest.SkipTest(
                "Set LEVELUP_UPSTREAM_ROOT and LEVELUP_FANS_REFERENCE_ROOT for integration tests"
            )
        cls.upstream = Path(upstream)
        cls.reference = Path(reference)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="levelup-fans-cdu-test-")
        self.aircraft_root = Path(self.temporary.name) / "737NG Series Test"
        for relative in TARGETS:
            source = self.upstream / relative
            destination = self.aircraft_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self.original_hashes = {
            relative: sha256(self.aircraft_root / relative) for relative in TARGETS
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_installer(self, action: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                action,
                "--aircraft-root",
                str(self.aircraft_root),
            ],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(expected, result.returncode, msg=result.stdout + result.stderr)
        return result

    def test_check_install_verify_and_uninstall(self) -> None:
        self.run_installer("check")
        self.assertEqual(
            self.original_hashes,
            {relative: sha256(self.aircraft_root / relative) for relative in TARGETS},
        )

        self.run_installer("install")
        self.run_installer("verify")
        self.run_installer("install")
        state = json.loads(
            (self.aircraft_root / ".levelup-fans-cdu-patch/state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sha256(REPOSITORY_ROOT / "package-manifest.json"), state["manifestSha256"])
        self.assertEqual("0.1.1", state["packageVersion"])

        tablet = (self.aircraft_root / TARGETS[0]).read_text(encoding="utf-8")
        self.assertIn("BEGIN LEVELUP_FANS_CDU_SELECTOR", tablet)
        self.assertIn("BEGIN LEVELUP_FANS_CDU_TYPE_SWITCH", tablet)
        self.assertIn("B738DR_cpdlc = 2", tablet)
        self.assertIn("B738DR_cpdlc = 1", tablet)

        obj = (self.aircraft_root / TARGETS[1]).read_text(encoding="utf-8")
        self.assertIn("ANIM_show 0.000000 0.500000 laminar/B738/fmc_type", obj)
        self.assertIn("sim/cockpit2/gauges/indicators/compass_heading_deg_mag", obj)
        self.assertNotIn("sim/flightmodel/position/mag_psi", obj)

        for relative in TARGETS[2:4]:
            self.assertEqual(sha256(self.reference / relative), sha256(self.aircraft_root / relative))

        _, _, installed_pixels, _, _ = decode_rgba_png(
            (self.aircraft_root / TARGETS[4]).read_bytes()
        )
        _, _, reference_pixels, _, _ = decode_rgba_png((self.reference / TARGETS[4]).read_bytes())
        self.assertEqual(hashlib.sha256(reference_pixels).digest(), hashlib.sha256(installed_pixels).digest())

        installed_tablet = (self.aircraft_root / TARGETS[0]).read_bytes()
        (self.aircraft_root / TARGETS[0]).write_bytes(installed_tablet + b"-- changed after install\r\n")
        result = self.run_installer("uninstall", expected=1)
        self.assertIn("Installed file was changed after installation", result.stderr)
        (self.aircraft_root / TARGETS[0]).write_bytes(installed_tablet)

        self.run_installer("uninstall")
        self.assertEqual(
            self.original_hashes,
            {relative: sha256(self.aircraft_root / relative) for relative in TARGETS},
        )
        self.run_installer("check")

    def test_modified_source_is_rejected_without_writes(self) -> None:
        tablet = self.aircraft_root / TARGETS[0]
        tablet.write_bytes(tablet.read_bytes() + b"-- third-party change\r\n")
        before = {relative: sha256(self.aircraft_root / relative) for relative in TARGETS}
        result = self.run_installer("check", expected=1)
        self.assertIn("Unsupported or modified source file", result.stderr)
        self.assertEqual(before, {relative: sha256(self.aircraft_root / relative) for relative in TARGETS})


if __name__ == "__main__":
    unittest.main()
