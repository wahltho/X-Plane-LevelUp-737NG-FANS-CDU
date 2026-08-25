from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchlib import PatchError, apply_obj8_fans_labels, decode_rgba_png
from z_Install import _preflight_sources


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


class SourcePreflightTests(unittest.TestCase):
    def test_missing_source_hash_is_limited_to_exact_text_replacements(self) -> None:
        with tempfile.TemporaryDirectory(prefix="levelup-fans-cdu-preflight-") as temporary:
            aircraft_root = Path(temporary)
            relative = "objects/test.bin"
            path = aircraft_root / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(b"test")
            manifest = {
                "targets": [
                    {
                        "operation": "sparse-bytes-v1",
                        "relativePath": relative,
                    }
                ]
            }

            with self.assertRaisesRegex(PatchError, "Missing source hash validation"):
                _preflight_sources(aircraft_root, manifest)


class Obj8PatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (
            "A\n"
            "800\n"
            "OBJ\n"
            "POINT_COUNTS 1 0 3 3\n"
            "VT 0 0 0 0 0 1 0 0\n"
            "IDX 0\n"
            "IDX 0\n"
            "IDX 0\n"
            "TRIS 0 3\n"
        ).encode()
        moved = struct.pack("<3I", 0, 0, 0)
        self.spec = {
            "format": "obj8-fans-label-switch-v1",
            "source": {
                "vertexCount": 1,
                "indexCount": 3,
                "pointCountsLine": "POINT_COUNTS 1 0 3 3",
            },
            "moveIndexRangesToEnd": {
                "ranges": [[0, 3]],
                "sha256": hashlib.sha256(moved).hexdigest(),
            },
            "replaceFinalDraw": {
                "old": "TRIS 0 3",
                "newLines": ["TRIS 0 6"],
            },
            "addedVertices": ["VT 1 0 0 0 0 1 1 0"],
            "addedIndices": [1, 1, 1],
            "result": {
                "vertexCount": 2,
                "indexCount": 6,
                "pointCountsLine": "POINT_COUNTS 2 0 6 6",
            },
        }

    def test_installed_result_is_idempotent(self) -> None:
        installed = apply_obj8_fans_labels(self.source, self.spec)

        self.assertEqual(installed, apply_obj8_fans_labels(installed, self.spec))

    def test_modified_installed_geometry_is_rejected(self) -> None:
        installed = apply_obj8_fans_labels(self.source, self.spec)
        modified = installed.replace(
            b"VT 1 0 0 0 0 1 1 0",
            b"VT 1 0 0 0 0 1 0 1",
        )

        with self.assertRaisesRegex(PatchError, "incomplete or modified"):
            apply_obj8_fans_labels(modified, self.spec)


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
        self.assertEqual("0.1.5", state["packageVersion"])

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
        separator = b"" if installed_tablet.endswith((b"\r", b"\n")) else b"\r\n"
        unrelated = separator + b"-- changed after install\r\n"
        (self.aircraft_root / TARGETS[0]).write_bytes(installed_tablet + unrelated)

        self.run_installer("uninstall")
        self.assertTrue((self.aircraft_root / TARGETS[0]).read_bytes().endswith(unrelated))
        self.assertEqual(
            self.original_hashes[TARGETS[0]],
            hashlib.sha256(
                (self.aircraft_root / TARGETS[0]).read_bytes().replace(unrelated, b"")
            ).hexdigest(),
        )
        self.assertEqual(
            {relative: self.original_hashes[relative] for relative in TARGETS[1:]},
            {relative: sha256(self.aircraft_root / relative) for relative in TARGETS[1:]},
        )
        self.run_installer("check")

    def test_compatible_tablet_variant_is_installed_and_restored(self) -> None:
        tablet = self.aircraft_root / TARGETS[0]
        original = tablet.read_bytes()
        eol = b"\r\n" if original.count(b"\r\n") > 0 else b"\n"
        separator = b"" if original.endswith((b"\r", b"\n")) else eol
        tablet.write_bytes(original + separator + b"-- unrelated Zibo version change" + eol)
        original_hash = sha256(tablet)

        self.run_installer("check")
        self.run_installer("install")
        self.assertIn("unrelated Zibo version change", tablet.read_text(encoding="utf-8"))
        self.run_installer("uninstall")
        self.assertEqual(original_hash, sha256(tablet))

    def test_modified_tablet_patch_block_is_rejected_without_writes(self) -> None:
        tablet = self.aircraft_root / TARGETS[0]
        source = tablet.read_bytes()
        old = b'line_g[1] = "                       MCDU ---------"'
        new = b'line_g[1] = "                       MCDU BLOCKED--"'
        self.assertEqual(1, source.count(old))
        tablet.write_bytes(source.replace(old, new))
        before = {relative: sha256(self.aircraft_root / relative) for relative in TARGETS}
        result = self.run_installer("check", expected=1)
        self.assertIn("LevelUp FANS CDU tablet selector", result.stderr)
        self.assertEqual(before, {relative: sha256(self.aircraft_root / relative) for relative in TARGETS})


if __name__ == "__main__":
    unittest.main()
