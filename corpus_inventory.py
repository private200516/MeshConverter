"""Read-only, bounded-memory inventory of modern Bethesda NIF containers.

This checks the container directory, not geometry, animation or game compatibility.
No input file is modified. Large block payloads are skipped, never loaded.
GPL-3.0; see LICENSE.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import time


class HeaderError(ValueError):
    """A truncated, unsupported or inconsistent NIF header."""


class _Reader:
    MAX_HEADER = 64 * 1024 * 1024

    def __init__(self, stream, size):
        self.stream = stream
        self.size = size

    def read(self, length):
        if length < 0 or self.stream.tell() + length > self.size:
            raise HeaderError("truncated file")
        if self.stream.tell() + length > self.MAX_HEADER:
            raise HeaderError("header exceeds 64 MiB safety limit")
        data = self.stream.read(length)
        if len(data) != length:
            raise HeaderError("short read")
        return data

    def number(self, fmt):
        return struct.unpack("<" + fmt, self.read(struct.calcsize("<" + fmt)))[0]

    def skip(self, length):
        if length < 0 or self.stream.tell() + length > min(self.size, self.MAX_HEADER):
            raise HeaderError("invalid header field length")
        self.stream.seek(length, os.SEEK_CUR)

    def export_string(self):
        self.skip(self.number("B"))

    def sized_string(self, limit, keep=False):
        length = self.number("I")
        if length > limit:
            raise HeaderError("string exceeds safety limit")
        if keep:
            return self.read(length).rstrip(b"\0").decode("utf-8", errors="strict")
        self.skip(length)

    def numbers(self, fmt, count):
        # At most 16 KiB of untrusted directory bytes are resident at a time.
        item_size = struct.calcsize("<" + fmt)
        while count:
            take = min(count, 4096)
            for (value,) in struct.iter_unpack("<" + fmt, self.read(take * item_size)):
                yield value
            count -= take


def _categories(types):
    result = []
    if any("Skin" in kind for kind in types):
        result.append("skinned")
    if any("Particle" in kind or "PSys" in kind for kind in types):
        result.append("particles")
    if any(any(word in kind for word in ("Controller", "Interpolator", "Sequence")) for kind in types):
        result.append("animation")
    if any(kind.startswith("bhk") for kind in types):
        result.append("physics")
    if any("TriShape" in kind or "TriStrips" in kind for kind in types):
        result.append("geometry")
    if "BSEffectShaderProperty" in types:
        result.append("effect_shader")
    if "BSLightingShaderProperty" in types:
        result.append("lighting_shader")
    return result or ["other"]


def inspect_header(path):
    """Return header metadata or raise HeaderError; payload validity is untested.

    The supported header schema is 20.2.0.7, little endian, Bethesda User 12,
    BS 83..155. Other variants are explicitly reported as unsupported schemas.
    """
    path = Path(path)
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        magic = stream.readline(256)
        if not magic.endswith(b"\n") or not magic.startswith((b"Gamebryo File Format", b"NetImmerse File Format")):
            raise HeaderError("not a recognized NIF header")
        reader = _Reader(stream, size)
        version = reader.number("I")
        endian = reader.number("B")
        user = reader.number("I")
        blocks = reader.number("I")
        bs = reader.number("I")
        version_name = ".".join(str((version >> shift) & 255) for shift in (24, 16, 8, 0))
        if (version, endian, user) != (0x14020007, 1, 12) or not 83 <= bs <= 155:
            raise HeaderError(f"unsupported header schema: version={version_name}, endian={endian}, user={user}, bs={bs}")
        if blocks > 1_000_000:
            raise HeaderError("block count exceeds safety limit")
        reader.export_string()
        if bs > 130:
            reader.number("I")
        else:
            reader.export_string()
        reader.export_string()
        reader.export_string()
        type_count = reader.number("H")
        if type_count > 4096:
            raise HeaderError("block type count exceeds safety limit")
        declared_types = [reader.sized_string(4096, keep=True) for _ in range(type_count)]
        counts = Counter()
        for index in reader.numbers("H", blocks):
            if index >= type_count:
                raise HeaderError("block type index outside type table")
            counts[declared_types[index]] += 1
        payload_bytes = sum(reader.numbers("I", blocks))
        strings = reader.number("I")
        max_string_length = reader.number("I")
        if strings > 1_000_000 or max_string_length > 1_048_576:
            raise HeaderError("string table exceeds safety limits")
        for _ in range(strings):
            reader.sized_string(1_048_576)
        groups = reader.number("I")
        if groups > 1_000_000:
            raise HeaderError("group table exceeds safety limit")
        reader.skip(groups * 4)
        header_bytes = stream.tell()
        footer_offset = header_bytes + payload_bytes
        if footer_offset + 4 > size:
            raise HeaderError("declared block payload extends beyond file")
        stream.seek(footer_offset)
        root_count = struct.unpack("<I", stream.read(4))[0]
        footer_bytes = size - footer_offset
        if root_count > 1_000_000 or 4 + root_count * 4 > footer_bytes:
            raise HeaderError("truncated or excessive footer roots")
        # Validate root references in chunks, without applying the header budget.
        remaining = root_count
        while remaining:
            take = min(remaining, 4096)
            data = stream.read(take * 4)
            if len(data) != take * 4:
                raise HeaderError("truncated footer")
            if any(root < -1 or root >= blocks for (root,) in struct.iter_unpack("<i", data)):
                raise HeaderError("footer root reference outside block table")
            remaining -= take
        types = sorted(counts)
        signature_data = {"version": version_name, "endian": endian, "user": user, "bs": bs, "types": types}
        signature = hashlib.sha256(json.dumps(signature_data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:20]
        return dict(signature_data, signature=signature, size=size, block_count=blocks,
                    declared_types=declared_types, type_counts=dict(sorted(counts.items())),
                    string_count=strings, group_count=groups, header_bytes=header_bytes,
                    payload_bytes=payload_bytes, footer_bytes=footer_bytes,
                    trailing_bytes=footer_bytes - 4 - 4 * root_count,
                    categories=_categories(types))


def nif_files(root):
    """Yield paths without following directory symlinks or building a file list."""
    root = Path(root)
    if root.is_file():
        if root.suffix.lower() == ".nif":
            yield root
        return
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".nif"):
                    yield Path(entry.path)


def inventory(root, records, representatives=3, progress_every=1000):
    """Write incremental JSONL to an already-open stream; return aggregate data."""
    root = Path(root).resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    base = root if root.is_dir() else root.parent
    summary = dict(root=str(root), total_files=0, parsed_files=0, errors=0,
                   total_bytes=0, signatures={}, error_examples=[])
    versions, types, type_blocks, categories, folders, errors = (Counter() for _ in range(6))
    started = time.monotonic()
    for path in nif_files(root):
        summary["total_files"] += 1
        relative = str(path.relative_to(base))
        record = {"path": str(path), "relative_path": relative}
        try:
            metadata = inspect_header(path)
            record.update(metadata, status="header_parsed")
            summary["parsed_files"] += 1
            summary["total_bytes"] += metadata["size"]
            version_key = f'{metadata["version"]}/User{metadata["user"]}/BS{metadata["bs"]}'
            versions[version_key] += 1
            types.update(metadata["types"])
            type_blocks.update(metadata["type_counts"])
            categories.update(metadata["categories"])
            folders.update([Path(relative).parts[0] if len(Path(relative).parts) > 1 else "."])
            signature = metadata["signature"]
            entry = summary["signatures"].setdefault(signature, dict(
                version=version_key, types=metadata["types"], categories=metadata["categories"],
                files=0, total_bytes=0, representatives=[]))
            entry["files"] += 1
            entry["total_bytes"] += metadata["size"]
            entry["representatives"].append(dict(path=str(path), relative_path=relative, size=metadata["size"]))
            entry["representatives"].sort(key=lambda item: (item["size"], item["relative_path"].lower()))
            del entry["representatives"][representatives:]
        except (OSError, ValueError, struct.error, UnicodeError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            record.update(status="error", error=message)
            summary["errors"] += 1
            errors[message] += 1
            if len(summary["error_examples"]) < 100:
                summary["error_examples"].append(record.copy())
        records.write(json.dumps(record, ensure_ascii=False) + "\n")
        if progress_every and summary["total_files"] % progress_every == 0:
            records.flush()
            print(json.dumps(dict(event="progress", root=str(root), files=summary["total_files"],
                                  errors=summary["errors"], signatures=len(summary["signatures"])), ensure_ascii=False), flush=True)
    records.flush()
    summary.update(version_file_counts=dict(versions), type_file_counts=dict(types.most_common()),
                   type_block_counts=dict(type_blocks.most_common()), category_file_counts=dict(categories),
                   folder_file_counts=dict(folders.most_common()), error_counts=dict(errors),
                   distinct_signatures=len(summary["signatures"]), elapsed_seconds=round(time.monotonic() - started, 3),
                   validation_scope="Container headers and directories only; block payloads and game compatibility are NOT validated.")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New summary JSON path; adjacent .jsonl contains every file")
    parser.add_argument("--representatives", type=int, default=3)
    parser.add_argument("--progress-every", type=int, default=1000)
    args = parser.parse_args(argv)
    if not 1 <= args.representatives <= 10:
        parser.error("--representatives must be 1..10")
    source = args.input.resolve()
    output = args.output.resolve()
    if output == source or (source.is_dir() and output.is_relative_to(source)):
        parser.error("Output must be outside the input directory")
    records_path = output.with_suffix(".jsonl")
    if output == records_path or output.exists() or records_path.exists():
        parser.error("Output summary or JSONL already exists; choose new paths")
    output.parent.mkdir(parents=True, exist_ok=True)
    with records_path.open("x", encoding="utf-8") as records:
        summary = inventory(source, records, args.representatives, args.progress_every)
    summary["created_at"] = datetime.now(timezone.utc).isoformat()
    summary["records_path"] = str(records_path)
    with output.open("x", encoding="utf-8") as target:
        json.dump(summary, target, ensure_ascii=False, indent=2)
    print(json.dumps(dict(event="complete", summary=str(output), files=summary["total_files"],
                          errors=summary["errors"], signatures=summary["distinct_signatures"]), ensure_ascii=False))
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
