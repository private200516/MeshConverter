"""Isolated NIF conversion regression runner. GPL-3.0; see LICENSE.

Samples are file references only. Input assets are never copied into the source
tree. Dry-run success, output validation and in-game testing are distinct stages.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_records(manifest):
    path = Path(manifest)
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError as exc:
                        raise ValueError(f"Invalid JSONL line {line_number}") from exc
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        yield from data
    elif "signatures" in data:
        for signature, entry in sorted(data["signatures"].items(), key=lambda item: (-item[1]["files"], item[0])):
            if entry["representatives"]:
                yield dict(entry["representatives"][0], signature=signature,
                           corpus_files_with_signature=entry["files"])
    else:
        yield from data.get("results", data.get("cases", []))


def load_cases(*, manifest=None, input_root=None, limit=300):
    """Accept baseline JSON/JSONL, inventory summary, plain paths or input tree."""
    if bool(manifest) == bool(input_root):
        raise ValueError("Exactly one of manifest and input_root is required")
    if limit < 0:
        raise ValueError("limit must be nonnegative (0 means all)")
    if input_root:
        from corpus_inventory import nif_files
        root = Path(input_root).resolve()
        if not root.exists():
            raise FileNotFoundError(root)
        base = root if root.is_dir() else root.parent
        records = (dict(path=str(path), relative_path=str(path.relative_to(base))) for path in nif_files(root))
    else:
        records = _manifest_records(manifest)
    result, seen = [], set()
    for record in records:
        if isinstance(record, str):
            record = {"path": record}
        source = record.get("path", record.get("input"))
        if not source:
            continue
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = (Path(manifest).resolve().parent if manifest else Path(input_root).resolve()) / path
        path = path.resolve()
        identity = os.path.normcase(str(path))
        if identity in seen:
            continue
        seen.add(identity)
        case = {key: record[key] for key in ("signature", "relative_path", "corpus_files_with_signature", "family") if key in record}
        case["path"] = str(path)
        if "status" in record:
            case["baseline_status"] = record["status"]
        result.append(case)
        if limit and len(result) >= limit:
            break
    if not result:
        raise ValueError("No input cases selected")
    return result


def run_process(command, timeout):
    """One isolated child per file; a native crash cannot stop the whole batch."""
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return dict(status="timeout", stage="worker", category="timeout", error=f"Exceeded {timeout:g} seconds")
    if result.returncode:
        return dict(status="worker_error", stage="worker", category="worker_crash",
                    returncode=result.returncode, error=result.stderr[-4000:] or result.stdout[-4000:])
    try:
        record = json.loads(result.stdout.splitlines()[-1])
        if not isinstance(record, dict) or "status" not in record:
            raise ValueError("Missing worker status")
        return record
    except (ValueError, IndexError):
        return dict(status="worker_error", stage="worker", category="worker_protocol",
                    error="Worker did not return a final JSON result", stdout=result.stdout[-2000:], stderr=result.stderr[-2000:])


def _category(exc, stage):
    if stage.startswith("output") or stage == "independent_nifly":
        return "output_validation"
    if isinstance(exc, FileExistsError):
        return "write_conflict"
    if isinstance(exc, (ValueError, AssertionError)):
        return "rejected_input_or_unsupported_feature"
    if isinstance(exc, OSError):
        return "io_error"
    return "internal_error"


def _independent_nifly(path, directory, expected_bs, expected_shapes):
    directory = Path(directory).resolve()
    if directory.name.lower() == "pyn":
        directory = directory.parent
    sys.path.insert(0, str(directory))
    from pyn.pynifly import NifFile
    native = NifFile(str(path))
    expected_game = {130: "FO4", 155: "FO76"}[expected_bs]
    if native.game != expected_game:
        raise ValueError(f"Nifly identifies target as {native.game}, expected {expected_game}")
    shapes = [dict(name=shape.name, vertices=len(shape.verts), triangles=len(shape.tris)) for shape in native.shapes]
    if len(shapes) != len(expected_shapes):
        raise ValueError("Nifly and built-in reader disagree about shape count")
    expected_counts = sorted((shape["vertices"], shape["triangles"]) for shape in expected_shapes)
    native_counts = sorted((shape["vertices"], shape["triangles"]) for shape in shapes)
    if expected_counts != native_counts:
        raise ValueError("Nifly and built-in reader disagree about vertex/triangle counts")
    return dict(status="passed", game=native.game, shapes=shapes,
                scope="Independent native parser and geometry counts; rendering and game behavior are untested")


def execute_job(job):
    """Executed inside the child only, after the parent has hashed its input."""
    stage = "engine_import"
    report = dict(status="rejected", stage=stage)
    try:
        from converter import convert_file
        stage = "conversion"
        if not job["dry_run"]:
            Path(job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        result = convert_file(job["path"], job["destination"], direction=job["direction"],
                              collision=job["collision"], dry_run=job["dry_run"],
                              reference_root=job.get("reference_root"))
        report["conversion_result"] = result
        if job["dry_run"]:
            report.update(status="dry_run_passed", stage="dry_run", category="passed",
                          validation_scope="Read-only conversion preflight; output has not been written or validated")
            return report
        target = Path(job["destination"])
        stage = "output_header"
        from corpus_inventory import inspect_header
        header = inspect_header(target)
        expected_bs = 130 if job["direction"] == "76-to-4" else 155
        if header["bs"] != expected_bs:
            raise ValueError(f"Target BS version {header['bs']} does not match expected {expected_bs}")
        report["output_header"] = header
        stage = "output_validate"
        from inspect_nif import Nif
        output = Nif(target)
        validate = getattr(output, "validate", None)
        if not callable(validate):
            raise ValueError("Nif.validate is unavailable; output cannot be reported as structurally validated")
        validation = validate()
        if validation is False:
            raise ValueError("Nif.validate returned False")
        report["output_validation"] = validation
        stage = "output_shapes"
        from convert_preserved import shape
        shapes = []
        for index, type_index in enumerate(output.indices):
            kind = output.types[type_index]
            if kind in ("BSTriShape", "BSSubIndexTriShape", "BSMeshLODTriShape", "BSDynamicTriShape"):
                metadata = shape(output, index)
                shapes.append(dict(block=index, type=kind, vertices=metadata["vertices"], triangles=metadata["triangles"]))
        report["output_shapes"] = shapes
        if job.get("nifly_dir"):
            stage = "independent_nifly"
            report["independent_nifly"] = _independent_nifly(target, job["nifly_dir"], expected_bs, shapes)
        else:
            report["independent_nifly"] = dict(status="not_run", reason="No --nifly-dir supplied")
        report.update(status="output_validated", stage="complete", category="passed",
                      output_sha256=sha256(target), output_bytes=target.stat().st_size,
                      validation_scope="Output container, built-in reference validation and geometry structure; no in-game test")
    except Exception as exc:
        report.update(status="rejected" if stage == "conversion" else "validation_failed",
                      stage=stage, category=_category(exc, stage), error_type=type(exc).__name__,
                      error=str(exc) or type(exc).__name__)
    return report


def run_case(case, index, output, options):
    started = time.monotonic()
    source = Path(case["path"])
    tag = hashlib.sha256(str(source).encode("utf8")).hexdigest()[:12]
    destination = Path(output) / "converted" / f"{index:05d}-{tag}" / source.name
    report = dict(case, index=index, destination=str(destination), profile=options)
    before = None
    try:
        before = sha256(source)
        report["source_sha256_before"] = before
        job = dict(options, path=str(source), destination=str(destination))
        job_path = Path(output) / "jobs" / f"{index:05d}-{tag}.json"
        with job_path.open("x", encoding="utf8") as stream:
            json.dump(job, stream, ensure_ascii=False)
        report.update(run_process([sys.executable, str(Path(__file__).resolve()), "--worker", str(job_path)], options["timeout"]))
    except Exception as exc:
        report.update(status="worker_error", stage="source_read", category="io_error", error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            after = sha256(source)
            report["source_sha256_after"] = after
            report["source_unchanged"] = before is not None and before == after
            if before is not None and before != after:
                report.update(status="source_changed", stage="source_hash_after", category="source_integrity", error="Source contents changed during this case")
        except OSError as exc:
            report.update(source_unchanged=False, source_integrity_error=str(exc))
            if before is not None:
                report.update(status="source_changed", stage="source_hash_after", category="source_integrity", error="Source could not be read after the case")
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input-root", type=Path)
    inputs.add_argument("--manifest", type=Path)
    parser.add_argument("--direction", choices=("76-to-4", "4-to-76"), default="76-to-4")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path, help="New, non-existing report/output directory outside all inputs")
    parser.add_argument("--mode", choices=("dry-run", "convert"), default="dry-run")
    parser.add_argument("--limit", type=int, default=300, help="Number of selected cases; 0 means all")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-collision", action="store_true")
    parser.add_argument("--nifly-dir", type=Path, help="Optional existing PyNifly io_scene_nifly or pyn directory for independent output parsing")
    args = parser.parse_args(argv)
    if args.worker:
        print(json.dumps(execute_job(json.loads(args.worker.read_text(encoding="utf8"))), ensure_ascii=True, default=str))
        return 0
    if not args.output or not (args.input_root or args.manifest):
        parser.error("--output and one of --input-root/--manifest are required")
    if not 1 <= args.workers <= 16 or args.timeout <= 0:
        parser.error("--workers must be 1..16 and --timeout must be positive")
    try:
        cases = load_cases(manifest=args.manifest, input_root=args.input_root, limit=args.limit)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    output = args.output.resolve()
    if args.input_root and output.is_relative_to(args.input_root.resolve()):
        parser.error("Output must be outside the input tree")
    if args.reference and output.is_relative_to(args.reference.resolve()):
        parser.error("Output must be outside the reference tree")
    if any(output == Path(case["path"]).resolve() or output.is_relative_to(Path(case["path"]).resolve().parent) for case in cases):
        parser.error("Output must be outside every input's containing directory")
    if output.exists():
        parser.error("Output directory already exists; choose a new directory")
    output.mkdir(parents=True)
    (output / "jobs").mkdir()
    options = dict(direction=args.direction, collision=not args.no_collision,
                   dry_run=args.mode == "dry-run", reference_root=str(args.reference.resolve()) if args.reference else None,
                   timeout=args.timeout, nifly_dir=str(args.nifly_dir.resolve()) if args.nifly_dir else None)
    results = []
    with (output / "results.jsonl").open("x", encoding="utf8") as stream, ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = [pool.submit(run_case, case, index, output, options) for index, case in enumerate(cases)]
        for future in as_completed(tasks):
            record = future.result()
            results.append(record)
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            if len(results) % 25 == 0 or len(results) == len(cases):
                print(json.dumps(dict(completed=len(results), selected=len(cases), statuses=dict(Counter(result["status"] for result in results)))), flush=True)
    summary = dict(created_at=datetime.now(timezone.utc).isoformat(), profile=options,
                   selection=dict(manifest=str(args.manifest.resolve()) if args.manifest else None,
                                  input_root=str(args.input_root.resolve()) if args.input_root else None, limit=args.limit),
                   selected_cases=len(cases), status_counts=dict(Counter(result["status"] for result in results)),
                   category_counts=dict(Counter(result.get("category", "unknown") for result in results)),
                   source_unchanged=all(result.get("source_unchanged") is True for result in results),
                   comparison_counts=dict(Counter(f'{result.get("baseline_status", "not_recorded")} -> {result["status"]}' for result in results)),
                   validation_scope="Only the selected paths under the recorded profile. No compatibility rate extrapolation and no in-game validation.",
                   results=sorted(results, key=lambda result: result["index"]))
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf8")
    print(str(output / "summary.json"))
    return 0 if all(result["status"] in ("dry_run_passed", "output_validated") for result in results) and summary["source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
