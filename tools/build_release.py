#!/usr/bin/env python3
"""Build a deterministic LevelUp FANS CDU patch release archive."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = (
    ".gitignore",
    "LICENSE",
    "README.md",
    "package-manifest.json",
    "patches/737_cockpit_ovhd2.obj.json",
    "patches/737cockpit_overhead2.dds.sparse.json",
    "patches/737cockpit_overhead2_LIT.dds.sparse.json",
    "patches/737cockpit_overhead2_NML.png.region.json",
    "patches/B738.tablet.lua.json",
    "patchlib.py",
    "tests/__init__.py",
    "tests/test_installer.py",
    "tools/make_patch_payloads.py",
    "z_Install.py",
)
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def main() -> int:
    manifest = json.loads((ROOT / "package-manifest.json").read_text(encoding="utf-8"))
    version = manifest["packageVersion"]
    prefix = f"X-Plane-LevelUp-737NG-FANS-CDU-v{version}"
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive_path = destination / f"{prefix}.zip"

    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        directory = zipfile.ZipInfo(f"{prefix}/", date_time=ZIP_TIMESTAMP)
        directory.external_attr = (0o40755 & 0xFFFF) << 16
        archive.writestr(directory, b"")
        for relative in PACKAGE_FILES:
            source = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            info = zipfile.ZipInfo(f"{prefix}/{relative}", date_time=ZIP_TIMESTAMP)
            mode = 0o755 if relative in {"z_Install.py", "tools/make_patch_payloads.py"} else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(
        f"{digest}  {archive_path.name}\n",
        encoding="ascii",
        newline="\n",
    )
    print(archive_path)
    print(checksum_path)
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
