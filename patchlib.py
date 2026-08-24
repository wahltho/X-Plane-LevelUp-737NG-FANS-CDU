#!/usr/bin/env python3
"""Restricted patch operations used by the LevelUp FANS CDU installer."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PatchError(RuntimeError):
    """Raised when a patch precondition or integrity check fails."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PatchError(f"Expected a JSON object in {path}")
    return value


def split_text_bytes(data: bytes) -> tuple[list[str], str, bool]:
    crlf_count = data.count(b"\r\n")
    lf_only_count = data.count(b"\n") - crlf_count
    eol = "\r\n" if crlf_count > lf_only_count else "\n"
    has_final_eol = data.endswith((b"\n", b"\r"))
    text = data.decode("utf-8", errors="strict")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if has_final_eol and lines and lines[-1] == "":
        lines.pop()
    return lines, eol, has_final_eol


def join_text_bytes(lines: list[str], eol: str, has_final_eol: bool) -> bytes:
    text = eol.join(lines)
    if has_final_eol:
        text += eol
    return text.encode("utf-8")


def _find_sequence(lines: list[str], sequence: list[str]) -> list[int]:
    if not sequence:
        raise PatchError("Empty text replacement sequence")
    width = len(sequence)
    return [i for i in range(len(lines) - width + 1) if lines[i : i + width] == sequence]


def apply_exact_text_replacements(data: bytes, spec: dict[str, Any]) -> bytes:
    if spec.get("format") != "exact-text-replacements-v1":
        raise PatchError("Unsupported text patch format")
    lines, eol, has_final_eol = split_text_bytes(data)
    for replacement in spec.get("replacements", []):
        old = replacement["oldLines"]
        new = replacement["newLines"]
        old_matches = _find_sequence(lines, old)
        new_matches = _find_sequence(lines, new)
        name = replacement.get("name", "unnamed replacement")
        if len(old_matches) == 1 and not new_matches:
            start = old_matches[0]
            lines[start : start + len(old)] = new
        elif not old_matches and len(new_matches) == 1:
            continue
        else:
            raise PatchError(
                f"{name}: expected exactly one old block or one installed block; "
                f"found old={len(old_matches)}, installed={len(new_matches)}"
            )
    return join_text_bytes(lines, eol, has_final_eol)


def remove_exact_text_replacements(data: bytes, spec: dict[str, Any]) -> bytes:
    if spec.get("format") != "exact-text-replacements-v1":
        raise PatchError("Unsupported text patch format")
    lines, eol, has_final_eol = split_text_bytes(data)
    for replacement in reversed(spec.get("replacements", [])):
        old = replacement["oldLines"]
        new = replacement["newLines"]
        old_matches = _find_sequence(lines, old)
        new_matches = _find_sequence(lines, new)
        name = replacement.get("name", "unnamed replacement")
        if len(new_matches) == 1:
            start = new_matches[0]
            lines[start : start + len(new)] = old
        elif not new_matches and len(old_matches) == 1:
            continue
        else:
            raise PatchError(
                f"{name}: expected exactly one installed block or one old block; "
                f"found installed={len(new_matches)}, old={len(old_matches)}"
            )
    return join_text_bytes(lines, eol, has_final_eol)


def _parse_obj8(data: bytes) -> tuple[list[str], list[str], list[int], list[str], str, bool]:
    lines, eol, has_final_eol = split_text_bytes(data)
    try:
        point_counts_index = next(i for i, line in enumerate(lines) if line.startswith("POINT_COUNTS "))
        vertex_start = next(i for i, line in enumerate(lines) if line.startswith("VT "))
        index_start = next(i for i, line in enumerate(lines) if line.startswith("IDX"))
    except StopIteration as exc:
        raise PatchError("OBJ8 structure is missing POINT_COUNTS, VT or IDX data") from exc

    command_start = index_start
    indices: list[int] = []
    while command_start < len(lines) and lines[command_start].startswith("IDX"):
        parts = lines[command_start].split()
        if parts[0] not in ("IDX", "IDX10"):
            raise PatchError(f"Unsupported OBJ8 index directive: {parts[0]}")
        indices.extend(int(value) for value in parts[1:])
        command_start += 1

    prefix = lines[:vertex_start]
    vertices = lines[vertex_start:index_start]
    commands = lines[command_start:]
    if point_counts_index >= len(prefix):
        raise PatchError("OBJ8 POINT_COUNTS is outside the header")
    return prefix, vertices, indices, commands, eol, has_final_eol


def _serialize_obj8_indices(indices: list[int]) -> list[str]:
    lines: list[str] = []
    complete = len(indices) // 10 * 10
    for offset in range(0, complete, 10):
        lines.append("IDX10 " + " ".join(str(value) for value in indices[offset : offset + 10]))
    for value in indices[complete:]:
        lines.append(f"IDX {value}")
    return lines


def apply_obj8_fans_labels(data: bytes, spec: dict[str, Any]) -> bytes:
    if spec.get("format") != "obj8-fans-label-switch-v1":
        raise PatchError("Unsupported OBJ8 patch format")
    prefix, vertices, indices, commands, eol, has_final_eol = _parse_obj8(data)
    source = spec["source"]
    if len(vertices) != source["vertexCount"] or len(indices) != source["indexCount"]:
        raise PatchError(
            f"Unexpected OBJ8 counts: vertices={len(vertices)}, indices={len(indices)}"
        )

    move = spec["moveIndexRangesToEnd"]
    positions: list[int] = []
    for offset, count in move["ranges"]:
        if offset < 0 or count <= 0 or offset + count > len(indices):
            raise PatchError("OBJ8 classic CDU label index range is invalid")
        positions.extend(range(offset, offset + count))
    if positions != sorted(set(positions)):
        raise PatchError("OBJ8 classic CDU label index ranges overlap or are unordered")
    position_set = set(positions)
    moved = [value for index, value in enumerate(indices) if index in position_set]
    moved_hash = sha256_bytes(struct.pack(f"<{len(moved)}I", *moved))
    if moved_hash != move["sha256"]:
        raise PatchError("OBJ8 classic CDU label index range does not match")

    expected_draw = spec["replaceFinalDraw"]["old"]
    if not commands or commands[-1] != expected_draw:
        raise PatchError(f"Expected final OBJ8 draw command {expected_draw!r}")

    result_vertices = vertices + spec["addedVertices"]
    kept = [value for index, value in enumerate(indices) if index not in position_set]
    result_indices = kept + moved + spec["addedIndices"]
    result = spec["result"]
    if len(result_vertices) != result["vertexCount"] or len(result_indices) != result["indexCount"]:
        raise PatchError("OBJ8 result counts do not match patch declaration")

    point_count_matches = [i for i, line in enumerate(prefix) if line.startswith("POINT_COUNTS ")]
    if len(point_count_matches) != 1 or prefix[point_count_matches[0]] != source["pointCountsLine"]:
        raise PatchError("Unexpected OBJ8 POINT_COUNTS declaration")
    prefix[point_count_matches[0]] = result["pointCountsLine"]
    result_commands = commands[:-1] + spec["replaceFinalDraw"]["newLines"]
    result_lines = prefix + result_vertices + _serialize_obj8_indices(result_indices) + result_commands
    return join_text_bytes(result_lines, eol, has_final_eol)


def apply_sparse_bytes(data: bytes, spec: dict[str, Any]) -> bytes:
    if spec.get("format") != "sparse-bytes-v1":
        raise PatchError("Unsupported sparse byte patch format")
    if len(data) != spec["sourceSize"] or sha256_bytes(data) != spec["sourceSha256"]:
        raise PatchError("Sparse byte patch source does not match")
    result = bytearray(data)
    for hunk in spec["hunks"]:
        payload = base64.b64decode(hunk["data"], validate=True)
        offset = hunk["offset"]
        end = offset + len(payload)
        if offset < 0 or end > len(result):
            raise PatchError("Sparse byte patch hunk is outside the source file")
        result[offset:end] = payload
    output = bytes(result)
    if len(output) != spec["resultSize"] or sha256_bytes(output) != spec["resultSha256"]:
        raise PatchError("Sparse byte patch result failed its integrity check")
    return output


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_up and distance_left <= distance_upper_left:
        return left
    if distance_up <= distance_upper_left:
        return up
    return upper_left


def decode_rgba_png(data: bytes) -> tuple[int, int, bytes, list[int], list[tuple[bytes, bytes]]]:
    if not data.startswith(PNG_SIGNATURE):
        raise PatchError("Not a PNG file")
    chunks: list[tuple[bytes, bytes]] = []
    position = len(PNG_SIGNATURE)
    while position < len(data):
        if position + 12 > len(data):
            raise PatchError("Truncated PNG chunk")
        length = struct.unpack(">I", data[position : position + 4])[0]
        chunk_type = data[position + 4 : position + 8]
        payload = data[position + 8 : position + 8 + length]
        crc = data[position + 8 + length : position + 12 + length]
        if len(payload) != length or len(crc) != 4:
            raise PatchError("Truncated PNG payload")
        expected_crc = binascii.crc32(chunk_type + payload) & 0xFFFFFFFF
        if struct.unpack(">I", crc)[0] != expected_crc:
            raise PatchError(f"PNG CRC mismatch in {chunk_type.decode('ascii', errors='replace')}")
        chunks.append((chunk_type, payload))
        position += 12 + length
        if chunk_type == b"IEND":
            break

    try:
        header = next(payload for chunk_type, payload in chunks if chunk_type == b"IHDR")
    except StopIteration as exc:
        raise PatchError("PNG has no IHDR chunk") from exc
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", header)
    if (depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
        raise PatchError("Only non-interlaced 8-bit RGBA PNG files are supported")

    compressed = b"".join(payload for chunk_type, payload in chunks if chunk_type == b"IDAT")
    raw = zlib.decompress(compressed)
    bytes_per_pixel = 4
    stride = width * bytes_per_pixel
    expected_size = height * (stride + 1)
    if len(raw) != expected_size:
        raise PatchError("Unexpected decompressed PNG size")

    rows: list[bytes] = []
    filters: list[int] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        if filter_type not in range(5):
            raise PatchError(f"Unsupported PNG filter {filter_type}")
        for index in range(stride):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + up) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (row[index] + _paeth(left, up, upper_left)) & 0xFF
        rows.append(bytes(row))
        filters.append(filter_type)
        previous = row
    return width, height, b"".join(rows), filters, chunks


def encode_rgba_png(
    width: int,
    height: int,
    pixels: bytes,
    filters: list[int],
    chunks: list[tuple[bytes, bytes]],
) -> bytes:
    stride = width * 4
    if len(pixels) != height * stride or len(filters) != height:
        raise PatchError("PNG encoder input size mismatch")
    # Filter 0 keeps encoding platform-independent and avoids a second
    # 67-million-byte Python predictor pass during installation.
    filtered_rows = [
        b"\x00" + pixels[row_index * stride : (row_index + 1) * stride]
        for row_index in range(height)
    ]
    compressed = zlib.compress(b"".join(filtered_rows), level=9)

    output = bytearray(PNG_SIGNATURE)
    wrote_idat = False
    for chunk_type, payload in chunks:
        if chunk_type == b"IDAT":
            if wrote_idat:
                continue
            payload = compressed
            wrote_idat = True
        output.extend(struct.pack(">I", len(payload)))
        output.extend(chunk_type)
        output.extend(payload)
        output.extend(struct.pack(">I", binascii.crc32(chunk_type + payload) & 0xFFFFFFFF))
    if not wrote_idat:
        raise PatchError("PNG has no IDAT chunk")
    return bytes(output)


def apply_png_rgba_region(data: bytes, spec: dict[str, Any]) -> bytes:
    if spec.get("format") != "png-rgba-region-v1":
        raise PatchError("Unsupported PNG patch format")
    width, height, pixels, filters, chunks = decode_rgba_png(data)
    if [width, height] != spec["dimensions"]:
        raise PatchError("PNG dimensions do not match")
    if sha256_bytes(pixels) != spec["sourcePixelSha256"]:
        raise PatchError("PNG source pixels do not match")

    x, y, region_width, region_height = spec["region"]
    if x < 0 or y < 0 or x + region_width > width or y + region_height > height:
        raise PatchError("PNG patch region is outside the image")
    region = zlib.decompress(base64.b64decode(spec["rgbaZlibBase64"], validate=True))
    if len(region) != region_width * region_height * 4:
        raise PatchError("PNG patch region payload has an unexpected size")

    result = bytearray(pixels)
    source_stride = width * 4
    region_stride = region_width * 4
    for row in range(region_height):
        destination = (y + row) * source_stride + x * 4
        source = row * region_stride
        result[destination : destination + region_stride] = region[source : source + region_stride]
    result_pixels = bytes(result)
    if sha256_bytes(result_pixels) != spec["resultPixelSha256"]:
        raise PatchError("PNG patch result pixels failed their integrity check")
    return encode_rgba_png(width, height, result_pixels, filters, chunks)


def apply_operation(data: bytes, operation: str, payload: dict[str, Any]) -> bytes:
    operations = {
        "exact-text-replacements-v1": apply_exact_text_replacements,
        "obj8-fans-label-switch-v1": apply_obj8_fans_labels,
        "sparse-bytes-v1": apply_sparse_bytes,
        "png-rgba-region-v1": apply_png_rgba_region,
    }
    try:
        handler = operations[operation]
    except KeyError as exc:
        raise PatchError(f"Unsupported operation: {operation}") from exc
    return handler(data, payload)
