#!/usr/bin/env python3
"""Install and manage the LevelUp 737NG 3D FANS CDU patch."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from patchlib import (
    PatchError,
    apply_operation,
    decode_rgba_png,
    exact_text_replacement_states,
    load_json,
    remove_exact_text_replacements,
    sha256_bytes,
    sha256_path,
)


PACKAGE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = PACKAGE_ROOT / "package-manifest.json"
STATE_DIRECTORY = ".levelup-fans-cdu-patch"
STATE_FILENAME = "state.json"


def _safe_relative_path(value: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or not posix.parts or ".." in posix.parts:
        raise PatchError(f"Unsafe relative path in manifest: {value!r}")
    return Path(*posix.parts)


def _load_manifest() -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    if manifest.get("schemaVersion") != 2:
        raise PatchError("Unsupported package manifest schema")
    return manifest


def _validate_payloads(manifest: dict[str, Any]) -> None:
    declared = {item["path"]: item for item in manifest["payloads"]}
    referenced = {target["payload"] for target in manifest["targets"]}
    if set(declared) != referenced:
        raise PatchError("Manifest payload declarations do not match target references")
    for relative, metadata in declared.items():
        path = PACKAGE_ROOT / _safe_relative_path(relative)
        if not path.is_file():
            raise PatchError(f"Missing patch payload: {relative}")
        if path.stat().st_size != metadata["size"] or sha256_path(path) != metadata["sha256"]:
            raise PatchError(f"Patch payload integrity check failed: {relative}")


def _state_path(aircraft_root: Path) -> Path:
    return aircraft_root / STATE_DIRECTORY / STATE_FILENAME


def _load_state(aircraft_root: Path) -> dict[str, Any] | None:
    path = _state_path(aircraft_root)
    if not path.exists():
        return None
    return load_json(path)


def _target_path(aircraft_root: Path, target: dict[str, Any]) -> Path:
    return aircraft_root / _safe_relative_path(target["relativePath"])


def _preflight_sources(aircraft_root: Path, manifest: dict[str, Any]) -> None:
    for target in manifest["targets"]:
        path = _target_path(aircraft_root, target)
        if not path.is_file():
            raise PatchError(f"Required LevelUp file is missing: {target['relativePath']}")
        supported = target.get("sourceSha256")
        if supported is None:
            if target["operation"] != "exact-text-replacements-v1":
                raise PatchError(
                    f"Missing source hash validation for: {target['relativePath']}"
                )
            continue
        actual = sha256_path(path)
        if actual not in supported and target["operation"] not in (
            "obj8-fans-label-switch-v1",
            "png-rgba-region-v1",
        ):
            raise PatchError(
                f"Unsupported or modified source file: {target['relativePath']}\n"
                f"  actual: {actual}\n"
                f"  supported: {', '.join(supported)}"
            )


def _transform_targets(aircraft_root: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    transformed: dict[str, bytes] = {}
    for target in manifest["targets"]:
        relative = target["relativePath"]
        source = _target_path(aircraft_root, target).read_bytes()
        payload = load_json(PACKAGE_ROOT / _safe_relative_path(target["payload"]))
        result = apply_operation(source, target["operation"], payload)
        expected = target.get("resultSha256")
        if expected is not None and sha256_bytes(result) != expected:
            raise PatchError(f"Generated result hash mismatch for {relative}")
        transformed[relative] = result
    return transformed


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _verify_state(aircraft_root: Path, state: dict[str, Any], manifest: dict[str, Any]) -> None:
    if state.get("packageId") != manifest["packageId"]:
        raise PatchError("Installed state belongs to a different package")
    for item in state.get("files", []):
        path = aircraft_root / _safe_relative_path(item["relativePath"])
        if not path.is_file():
            raise PatchError(f"Installed file is missing: {item['relativePath']}")
        target = next(
            target for target in manifest["targets"]
            if target["relativePath"] == item["relativePath"]
        )
        operation = target["operation"]
        payload = load_json(PACKAGE_ROOT / _safe_relative_path(target["payload"]))
        if operation == "exact-text-replacements-v1":
            current = path.read_bytes()
            states = exact_text_replacement_states(current, payload)
            if all(state in ("installed", "legacy") for state in states):
                continue
        elif operation == "png-rgba-region-v1":
            _, _, pixels, _, _ = decode_rgba_png(path.read_bytes())
            if sha256_bytes(pixels) == payload["resultPixelSha256"]:
                continue
        elif sha256_path(path) == item["installedSha256"]:
            continue
        if operation != "exact-text-replacements-v1":
            raise PatchError(
                f"Installed file was changed after installation: {item['relativePath']}\n"
                f"  actual: {sha256_path(path)}\n"
                f"  expected: {item['installedSha256']}"
            )
        raise PatchError(
            f"Installed FANS CDU blocks are missing or modified in: {item['relativePath']}"
        )


def command_check(aircraft_root: Path, manifest: dict[str, Any]) -> int:
    state = _load_state(aircraft_root)
    if state is not None:
        _verify_state(aircraft_root, state, manifest)
        print(f"Installed and verified: {state['packageId']} {state['packageVersion']}")
        return 0
    _validate_payloads(manifest)
    _preflight_sources(aircraft_root, manifest)
    _transform_targets(aircraft_root, manifest)
    print(f"Ready to install {manifest['packageId']} {manifest['packageVersion']}")
    print(f"Validated {len(manifest['targets'])} source files; no files were changed.")
    return 0


def _installed_release_is_current(aircraft_root: Path, state: dict[str, Any], manifest: dict[str, Any]) -> bool:
    if state.get("packageVersion") != manifest["packageVersion"]:
        return False
    for target in manifest["targets"]:
        if target["operation"] != "exact-text-replacements-v1":
            continue
        payload = load_json(PACKAGE_ROOT / _safe_relative_path(target["payload"]))
        current = _target_path(aircraft_root, target).read_bytes()
        if any(state != "installed" for state in exact_text_replacement_states(current, payload)):
            return False
    return True


def command_install(aircraft_root: Path, manifest: dict[str, Any]) -> int:
    state = _load_state(aircraft_root)
    if state is not None:
        _verify_state(aircraft_root, state, manifest)
        if _installed_release_is_current(aircraft_root, state, manifest):
            print(f"Already installed and verified: {state['packageId']} {state['packageVersion']}")
            return 0
        print(
            f"Upgrading {state['packageId']} {state['packageVersion']} "
            f"to {manifest['packageVersion']}: removing the earlier release first."
        )
        command_uninstall(aircraft_root, manifest)
    _validate_payloads(manifest)
    _preflight_sources(aircraft_root, manifest)
    transformed = _transform_targets(aircraft_root, manifest)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    state_root = aircraft_root / STATE_DIRECTORY
    backup_root = state_root / "backups" / timestamp
    backup_root.mkdir(parents=True, exist_ok=False)
    state_files: list[dict[str, Any]] = []
    for target in manifest["targets"]:
        relative = target["relativePath"]
        source = _target_path(aircraft_root, target)
        backup = backup_root / _safe_relative_path(relative)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)
        state_files.append(
            {
                "relativePath": relative,
                "originalSha256": sha256_path(source),
                "installedSha256": sha256_bytes(transformed[relative]),
            }
        )

    replaced: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix="fans-cdu-stage-", dir=state_root) as temporary_name:
            staging_root = Path(temporary_name)
            staged: dict[str, Path] = {}
            for target in manifest["targets"]:
                relative = target["relativePath"]
                destination = _target_path(aircraft_root, target)
                temporary = staging_root / _safe_relative_path(relative)
                temporary.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(transformed[relative])
                os.chmod(temporary, stat.S_IMODE(destination.stat().st_mode))
                staged[relative] = temporary
            for target in manifest["targets"]:
                relative = target["relativePath"]
                destination = _target_path(aircraft_root, target)
                os.replace(staged[relative], destination)
                replaced.append(destination)

        state_document = {
            "schemaVersion": 1,
            "packageId": manifest["packageId"],
            "packageVersion": manifest["packageVersion"],
            "manifestSha256": sha256_path(MANIFEST_PATH),
            "installedAtUtc": datetime.now(timezone.utc).isoformat(),
            "backupRelativePath": backup_root.relative_to(aircraft_root).as_posix(),
            "files": state_files,
        }
        _write_json_atomic(_state_path(aircraft_root), state_document)
    except Exception:
        for target in manifest["targets"]:
            relative = target["relativePath"]
            backup = backup_root / _safe_relative_path(relative)
            destination = _target_path(aircraft_root, target)
            if backup.exists():
                shutil.copy2(backup, destination)
        raise

    print(f"Installed {manifest['packageId']} {manifest['packageVersion']}.")
    print(f"Backup: {backup_root}")
    print("Restart X-Plane before testing the aircraft.")
    return 0


def command_verify(aircraft_root: Path, manifest: dict[str, Any]) -> int:
    state = _load_state(aircraft_root)
    if state is None:
        raise PatchError("The FANS CDU patch is not installed")
    _validate_payloads(manifest)
    _verify_state(aircraft_root, state, manifest)
    print(f"Verified {state['packageId']} {state['packageVersion']} ({len(state['files'])} files).")
    return 0


def command_uninstall(aircraft_root: Path, manifest: dict[str, Any]) -> int:
    state = _load_state(aircraft_root)
    if state is None:
        raise PatchError("The FANS CDU patch is not installed")
    _verify_state(aircraft_root, state, manifest)
    backup_root = aircraft_root / _safe_relative_path(state["backupRelativePath"])
    for item in state["files"]:
        target = next(
            target for target in manifest["targets"]
            if target["relativePath"] == item["relativePath"]
        )
        if target["operation"] == "exact-text-replacements-v1":
            continue
        backup = backup_root / _safe_relative_path(item["relativePath"])
        if not backup.is_file() or sha256_path(backup) != item["originalSha256"]:
            raise PatchError(f"Backup integrity check failed: {item['relativePath']}")

    state_root = aircraft_root / STATE_DIRECTORY
    with tempfile.TemporaryDirectory(prefix="fans-cdu-restore-", dir=state_root) as temporary_name:
        staging_root = Path(temporary_name)
        staged: dict[str, Path] = {}
        rollback: dict[str, Path] = {}
        for item in state["files"]:
            relative = item["relativePath"]
            temporary = staging_root / _safe_relative_path(relative)
            temporary.parent.mkdir(parents=True, exist_ok=True)
            target = next(
                target for target in manifest["targets"]
                if target["relativePath"] == relative
            )
            current = aircraft_root / _safe_relative_path(relative)
            if target["operation"] == "exact-text-replacements-v1":
                payload = load_json(PACKAGE_ROOT / _safe_relative_path(target["payload"]))
                temporary.write_bytes(
                    remove_exact_text_replacements(current.read_bytes(), payload)
                )
                os.chmod(temporary, stat.S_IMODE(current.stat().st_mode))
            else:
                backup = backup_root / _safe_relative_path(relative)
                shutil.copy2(backup, temporary)
            staged[relative] = temporary
            rollback_file = staging_root / "installed" / _safe_relative_path(relative)
            rollback_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current, rollback_file)
            rollback[relative] = rollback_file
        try:
            for item in state["files"]:
                relative = item["relativePath"]
                os.replace(staged[relative], aircraft_root / _safe_relative_path(relative))
        except Exception:
            for item in state["files"]:
                relative = item["relativePath"]
                rollback_file = rollback[relative]
                if rollback_file.exists():
                    shutil.copy2(rollback_file, aircraft_root / _safe_relative_path(relative))
            raise

    for item in state["files"]:
        target = next(
            target for target in manifest["targets"]
            if target["relativePath"] == item["relativePath"]
        )
        if target["operation"] == "exact-text-replacements-v1":
            continue
        restored = aircraft_root / _safe_relative_path(item["relativePath"])
        if sha256_path(restored) != item["originalSha256"]:
            raise PatchError(f"Restore verification failed: {item['relativePath']}")
    _state_path(aircraft_root).unlink()
    print(
        f"Uninstalled {state['packageId']} {state['packageVersion']}; "
        "removed owned Lua blocks and restored dedicated visual assets."
    )
    print("Restart X-Plane before loading the aircraft.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("check", "install", "verify", "uninstall"),
        help="Operation to perform",
    )
    parser.add_argument(
        "--aircraft-root",
        required=True,
        type=Path,
        help="Path to the LevelUp 737NG Series aircraft root",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    aircraft_root = args.aircraft_root.expanduser().resolve()
    if not aircraft_root.is_dir():
        print(f"ERROR: Aircraft root does not exist: {aircraft_root}", file=sys.stderr)
        return 2
    try:
        manifest = _load_manifest()
        commands = {
            "check": command_check,
            "install": command_install,
            "verify": command_verify,
            "uninstall": command_uninstall,
        }
        return commands[args.action](aircraft_root, manifest)
    except (PatchError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
