#!/usr/bin/env python3
"""Generate redistribution-safe deltas from owned LevelUp source and reference files."""

from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchlib import (  # noqa: E402
    apply_obj8_fans_labels,
    apply_png_rgba_region,
    decode_rgba_png,
    load_json,
    sha256_bytes,
)


ASSET_PATHS = (
    "objects/737_cockpit_ovhd2.obj",
    "objects/737cockpit_overhead2.dds",
    "objects/737cockpit_overhead2_LIT.dds",
    "objects/737cockpit_overhead2_NML.png",
)


def make_tablet_patch() -> dict[str, Any]:
    return {
        "format": "exact-text-replacements-v1",
        "replacements": [
            {
                "name": "LevelUp FANS CDU tablet selector",
                "oldLines": [
                    "\t\tif B738DR_b737_variant < 0 then",
                    "\t\t\tline[1] = \"  CDU                      /\"",
                    "\t\t\tif B738DR_fmc_type == 0 then",
                    "\t\t\t\tline_g[1] = \"                       MCDU          \"",
                    "\t\t\t\tline_s[1] = \"                            FANS MCDU\"",
                    "\t\t\telse",
                    "\t\t\t\tline_g[1] = \"                            FANS MCDU\"",
                    "\t\t\t\tline_s[1] = \"                       MCDU          \"",
                    "\t\t\tend",
                    "\t\telse",
                    "\t\t\tline[1] =   \"  CDU                      /\"",
                    "\t\t\tline_g[1] = \"                       MCDU ---------\"",
                    "\t\tend",
                ],
                "newLines": [
                    "\t\t-- BEGIN LEVELUP_FANS_CDU_SELECTOR",
                    "\t\tline[1] = \"  CDU                      /\"",
                    "\t\tif B738DR_fmc_type == 0 then",
                    "\t\t\tline_g[1] = \"                       MCDU          \"",
                    "\t\t\tline_s[1] = \"                            FANS MCDU\"",
                    "\t\telse",
                    "\t\t\tline_g[1] = \"                            FANS MCDU\"",
                    "\t\t\tline_s[1] = \"                       MCDU          \"",
                    "\t\tend",
                    "\t\t-- END LEVELUP_FANS_CDU_SELECTOR",
                ],
            },
            {
                "name": "LevelUp FANS CDU type switch",
                "oldLines": [
                    "\tif cmd == 1 and B738DR_b737_variant < 0 then",
                    "\t\tif B738DR_fmc_type == 0 then",
                    "\t\t\tB738DR_fmc_type = 1",
                    "\t\telse",
                    "\t\t\tB738DR_fmc_type = 0",
                    "\t\t\tif B738DR_cmu ~= 0 and B738DR_cpdlc == 2 then",
                    "\t\t\t\tB738DR_cpdlc = 1",
                    "\t\t\tend",
                    "\t\tend",
                ],
                "newLines": [
                    "\t-- BEGIN LEVELUP_FANS_CDU_TYPE_SWITCH",
                    "\t-- The CDU type only selects the hardware variant; the CPDLC",
                    "\t-- protocol (NONE / ATN B1 / FANS) stays a separate user choice.",
                    "\tif cmd == 1 then",
                    "\t\tif B738DR_fmc_type == 0 then",
                    "\t\t\tB738DR_fmc_type = 1",
                    "\t\telse",
                    "\t\t\tB738DR_fmc_type = 0",
                    "\t\tend",
                    "\t-- END LEVELUP_FANS_CDU_TYPE_SWITCH",
                ],
                "legacyNewLines": [
                    [
                        "\t-- BEGIN LEVELUP_FANS_CDU_TYPE_SWITCH",
                        "\tif cmd == 1 then",
                        "\t\tif B738DR_fmc_type == 0 then",
                        "\t\t\tB738DR_fmc_type = 1",
                        "\t\t\tif B738DR_cmu ~= 0 then",
                        "\t\t\t\tB738DR_cpdlc = 2",
                        "\t\t\tend",
                        "\t\telse",
                        "\t\t\tB738DR_fmc_type = 0",
                        "\t\t\tif B738DR_cmu ~= 0 then",
                        "\t\t\t\tB738DR_cpdlc = 1",
                        "\t\t\tend",
                        "\t\tend",
                        "\t-- END LEVELUP_FANS_CDU_TYPE_SWITCH",
                    ]
                ],
            },
            {
                "name": "LevelUp FANS CDU CPDLC selection",
                "oldLines": [
                    "\telseif cmd == 20 then",
                    "\t\tif B738DR_cmu ~= 0 then",
                    "\t\t\tif B738DR_cpdlc == 0 then",
                    "\t\t\t\tB738DR_cpdlc = 1",
                    "\t\t\telseif B738DR_cpdlc == 1 and B738DR_fmc_type ~= 0 then",
                    "\t\t\t\tB738DR_cpdlc = 2",
                    "\t\t\telse",
                    "\t\t\t\tB738DR_cpdlc = 0",
                    "\t\t\tend",
                    "\t\tend",
                ],
                "newLines": [
                    "\t-- BEGIN LEVELUP_FANS_CDU_CPDLC_SELECTION",
                    "\t-- NONE -> ATN B1 -> FANS -> NONE, independent of the CDU type.",
                    "\telseif cmd == 20 then",
                    "\t\tif B738DR_cmu ~= 0 then",
                    "\t\t\tif B738DR_cpdlc == 0 then",
                    "\t\t\t\tB738DR_cpdlc = 1",
                    "\t\t\telseif B738DR_cpdlc == 1 then",
                    "\t\t\t\tB738DR_cpdlc = 2",
                    "\t\t\telse",
                    "\t\t\t\tB738DR_cpdlc = 0",
                    "\t\t\tend",
                    "\t\tend",
                    "\t-- END LEVELUP_FANS_CDU_CPDLC_SELECTION",
                ],
            },
        ],
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_obj(data: bytes) -> tuple[list[str], list[int], list[str]]:
    lines = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    vertex_start = next(i for i, line in enumerate(lines) if line.startswith("VT "))
    index_start = next(i for i, line in enumerate(lines) if line.startswith("IDX"))
    command_start = index_start
    indices: list[int] = []
    while command_start < len(lines) and lines[command_start].startswith("IDX"):
        indices.extend(int(value) for value in lines[command_start].split()[1:])
        command_start += 1
    return lines[vertex_start:index_start], indices, lines[command_start:]


def make_obj_patch(source: bytes, reference: bytes) -> tuple[dict[str, Any], bytes]:
    source_vertices, source_indices, source_commands = parse_obj(source)
    reference_vertices, reference_indices, _ = parse_obj(reference)
    move_count = 192
    added_index_count = 192
    if reference_vertices[: len(source_vertices)] != source_vertices:
        raise RuntimeError("Reference OBJ does not preserve the upstream vertex prefix")
    added_vertices = reference_vertices[len(source_vertices) :]
    kept_reference = reference_indices[: len(source_indices) - move_count]
    moved_reference = reference_indices[len(source_indices) - move_count : len(source_indices)]
    added_indices = reference_indices[-added_index_count:]
    removed_positions: list[int] = []
    kept_cursor = 0
    for index, value in enumerate(source_indices):
        if kept_cursor < len(kept_reference) and value == kept_reference[kept_cursor]:
            kept_cursor += 1
        else:
            removed_positions.append(index)
    moved = [source_indices[index] for index in removed_positions]
    if kept_cursor != len(kept_reference) or moved != moved_reference or len(moved) != move_count:
        raise RuntimeError("Reference OBJ index delta is not the expected FANS label transform")
    ranges: list[list[int]] = []
    if removed_positions:
        start = previous = removed_positions[0]
        for index in removed_positions[1:]:
            if index == previous + 1:
                previous = index
            else:
                ranges.append([start, previous - start + 1])
                start = previous = index
        ranges.append([start, previous - start + 1])
    if source_commands[-1] != "TRIS 44289 9012":
        raise RuntimeError("Unexpected upstream OBJ final draw command")

    spec = {
        "format": "obj8-fans-label-switch-v1",
        "source": {
            "pointCountsLine": "POINT_COUNTS 19444 0 0 53301",
            "vertexCount": len(source_vertices),
            "indexCount": len(source_indices),
        },
        "result": {
            "pointCountsLine": "POINT_COUNTS 19524 0 0 53493",
            "vertexCount": len(reference_vertices),
            "indexCount": len(reference_indices),
        },
        "moveIndexRangesToEnd": {
            "ranges": ranges,
            "sha256": sha256_bytes(struct.pack(f"<{len(moved)}I", *moved)),
        },
        "addedVertices": added_vertices,
        "addedIndices": added_indices,
        "replaceFinalDraw": {
            "old": "TRIS 44289 9012",
            "newLines": [
                "TRIS 44289 8820",
                "ANIM_begin",
                "ANIM_show 0.000000 0.500000 laminar/B738/fmc_type",
                "ANIM_hide 0.500000 1.000000 laminar/B738/fmc_type",
                "TRIS 53109 192",
                "ANIM_end",
                "ANIM_begin",
                "ANIM_hide 0.000000 0.500000 laminar/B738/fmc_type",
                "ANIM_show 0.500000 1.000000 laminar/B738/fmc_type",
                "TRIS 53301 192",
                "ANIM_end",
            ],
        },
    }
    result = apply_obj8_fans_labels(source, spec)
    expected_lines = reference.decode("utf-8").replace("sim/flightmodel/position/mag_psi", "sim/cockpit2/gauges/indicators/compass_heading_deg_mag").splitlines()
    if result.decode("utf-8").splitlines() != expected_lines:
        raise RuntimeError("Generated clean OBJ differs from the FANS reference beyond the excluded compass change")
    return spec, result


def make_sparse_patch(source: bytes, result: bytes) -> dict[str, Any]:
    if len(source) != len(result):
        raise RuntimeError("Sparse byte patches require equal source and result sizes")
    changed = [index for index, pair in enumerate(zip(source, result)) if pair[0] != pair[1]]
    ranges: list[tuple[int, int]] = []
    if changed:
        start = end = changed[0]
        for index in changed[1:]:
            if index <= end + 33:
                end = index
            else:
                ranges.append((start, end + 1))
                start = end = index
        ranges.append((start, end + 1))
    return {
        "format": "sparse-bytes-v1",
        "sourceSize": len(source),
        "sourceSha256": sha256_bytes(source),
        "resultSize": len(result),
        "resultSha256": sha256_bytes(result),
        "hunks": [
            {"offset": start, "data": base64.b64encode(result[start:end]).decode("ascii")}
            for start, end in ranges
        ],
    }


def make_png_patch(source: bytes, reference: bytes) -> tuple[dict[str, Any], bytes]:
    width, height, source_pixels, _, _ = decode_rgba_png(source)
    reference_width, reference_height, reference_pixels, _, _ = decode_rgba_png(reference)
    if (width, height) != (reference_width, reference_height):
        raise RuntimeError("PNG dimensions differ")
    changed = [index // 4 for index in range(0, len(source_pixels), 4) if source_pixels[index : index + 4] != reference_pixels[index : index + 4]]
    if not changed:
        raise RuntimeError("PNG reference has no pixel changes")
    xs = [index % width for index in changed]
    ys = [index // width for index in changed]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
    if (x0, y0, x1, y1) != (1600, 12, 1936, 92):
        raise RuntimeError(f"Unexpected normal-map delta rectangle: {(x0, y0, x1, y1)}")
    region = bytearray()
    stride = width * 4
    for row in range(y0, y1):
        region.extend(reference_pixels[row * stride + x0 * 4 : row * stride + x1 * 4])
    spec = {
        "format": "png-rgba-region-v1",
        "sourceSha256": sha256_bytes(source),
        "sourcePixelSha256": sha256_bytes(source_pixels),
        "resultPixelSha256": sha256_bytes(reference_pixels),
        "dimensions": [width, height],
        "region": [x0, y0, x1 - x0, y1 - y0],
        "rgbaZlibBase64": base64.b64encode(zlib.compress(bytes(region), level=9)).decode("ascii"),
    }
    result = apply_png_rgba_region(source, spec)
    return spec, result


def update_manifest(repository_root: Path, results: dict[str, tuple[str, bytes, bytes]]) -> None:
    manifest_path = repository_root / "package-manifest.json"
    manifest = load_json(manifest_path)
    payloads = []
    for relative, (payload_path, source, result) in results.items():
        target = next(item for item in manifest["targets"] if item["relativePath"] == relative)
        target["payload"] = payload_path
        if target["operation"] == "exact-text-replacements-v1":
            target.pop("sourceSha256", None)
        else:
            target["sourceSha256"] = [sha256_bytes(source)]
        if target["operation"] == "sparse-bytes-v1":
            target["resultSha256"] = sha256_bytes(result)
        else:
            target.pop("resultSha256", None)
    for target in manifest["targets"]:
        payload_path = repository_root / target["payload"]
        payloads.append(
            {
                "path": target["payload"],
                "size": payload_path.stat().st_size,
                "sha256": sha256_bytes(payload_path.read_bytes()),
            }
        )
    manifest["payloads"] = payloads
    write_json(manifest_path, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    output = repository_root / "patches"
    output.mkdir(parents=True, exist_ok=True)

    obj_source = (args.upstream_root / ASSET_PATHS[0]).read_bytes()
    obj_reference = (args.reference_root / ASSET_PATHS[0]).read_bytes()
    obj_spec, obj_result = make_obj_patch(obj_source, obj_reference)
    obj_payload = output / "737_cockpit_ovhd2.obj.json"
    write_json(obj_payload, obj_spec)

    results: dict[str, tuple[str, bytes, bytes]] = {
        ASSET_PATHS[0]: (obj_payload.relative_to(repository_root).as_posix(), obj_source, obj_result)
    }
    for relative in ASSET_PATHS[1:3]:
        source = (args.upstream_root / relative).read_bytes()
        reference = (args.reference_root / relative).read_bytes()
        spec = make_sparse_patch(source, reference)
        payload = output / (Path(relative).name + ".sparse.json")
        write_json(payload, spec)
        results[relative] = (payload.relative_to(repository_root).as_posix(), source, reference)

    png_relative = ASSET_PATHS[3]
    png_source = (args.upstream_root / png_relative).read_bytes()
    png_reference = (args.reference_root / png_relative).read_bytes()
    png_spec, png_result = make_png_patch(png_source, png_reference)
    png_payload = output / (Path(png_relative).name + ".region.json")
    write_json(png_payload, png_spec)
    results[png_relative] = (png_payload.relative_to(repository_root).as_posix(), png_source, png_result)

    tablet_relative = "plugins/xlua/scripts/B738.tablet/B738.tablet.lua"
    tablet_payload = output / "B738.tablet.lua.json"
    from patchlib import apply_exact_text_replacements  # noqa: PLC0415

    tablet_source = (args.upstream_root / tablet_relative).read_bytes()
    tablet_spec = make_tablet_patch()
    write_json(tablet_payload, tablet_spec)
    tablet_result = apply_exact_text_replacements(tablet_source, tablet_spec)
    results[tablet_relative] = (
        tablet_payload.relative_to(repository_root).as_posix(),
        tablet_source,
        tablet_result,
    )

    update_manifest(repository_root, results)
    for relative, (payload, _, result) in results.items():
        print(f"{relative}: {payload} -> {sha256_bytes(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
