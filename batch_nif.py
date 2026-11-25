"""Mesh Converter 1.0: bidirectional local NIF batch entry point."""
import argparse
import json
import sys
from pathlib import Path
from converter import convert_file, BUILD, DIRECTIONS
from corpus_inventory import nif_files
from publication_guard import (absolute_path, default_mesh_report,
                               mesh_export_boundary, mesh_source_root, plan_mesh_paths)


def main():
    parser = argparse.ArgumentParser(description='Convert verified FO76/FO4 NIF structures.')
    parser.add_argument('input', type=Path, help='A NIF file or a mesh folder')
    parser.add_argument('output', type=Path, help='Mod export root, shared with Texture Converter, or its meshes folder')
    parser.add_argument('--direction', choices=tuple(DIRECTIONS), default='76-to-4')
    parser.add_argument('--reference', type=Path, help='Target game Meshes/resources directory or explicit skeleton.nif')
    parser.add_argument('--no-collision', action='store_true', help='Export the visual model without physics')
    parser.add_argument('--preflight', action='store_true', help='Check conversion without writing NIFs')
    reports = parser.add_mutually_exclusive_group()
    reports.add_argument('--report', type=Path, help='Write JSON to this new file (default: reports/ under the chosen root)')
    reports.add_argument('--no-report', action='store_true', help='Keep results on stdout only')
    args = parser.parse_args()

    try:
        source = absolute_path(args.input)
        output = absolute_path(args.output)
        base = mesh_source_root(source)
        boundary = mesh_export_boundary(output, base)
        if source != base:
            boundary.validate_source(source)
        report_path = None
        if not args.no_report:
            report_path = absolute_path(args.report) if args.report else default_mesh_report(output)
            report_boundary = mesh_export_boundary(report_path.parent, base) if args.report else boundary
            report_boundary.validate(report_path, must_be_absent=True)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    records = []
    counts = {'passed': 0, 'rejected': 0, 'skipped': 0}

    def emit(result):
        if report_path is not None:
            records.append(result)
        counts[result['status']] += 1
        print(json.dumps(result, ensure_ascii=True), flush=True)

    try:
        targets = plan_mesh_paths(nif_files(source), base, output)
    except (OSError, ValueError) as error:
        # Resolve every destination before writing; a partial listing cannot identify conflicts.
        emit(dict(input=str(source), status='rejected', error=f'{type(error).__name__}: {error}'))
        targets = {}
    if not targets and not counts['rejected']:
        parser.error('No .nif files found')
    if report_path is not None and any(output/relative == report_path for relative, _ in targets.values()):
        parser.error('Report path conflicts with a model destination')

    for path, (relative, ambiguous) in targets.items():
        try:
            if ambiguous:
                raise ValueError('Multiple source files map to the same game path: ' + str(relative))
            data = convert_file(path, output/relative, direction=args.direction, collision=not args.no_collision,
                                dry_run=args.preflight, reference_root=args.reference,
                                output_root=output, source_root=base)
            result = dict(input=str(path), status='passed', result=data)
        except FileExistsError as error:
            result = dict(input=str(path), status='skipped', error=str(error))
        except Exception as error:
            result = dict(input=str(path), status='rejected', error=f'{type(error).__name__}: {error}')
        emit(result)

    if report_path is not None:
        report = dict(build=BUILD, direction=args.direction, collision=not args.no_collision,
                      reference=str(args.reference) if args.reference else None, preflight=args.preflight,
                      game_verified=False, counts=counts, files=records)
        report_boundary.prepare_parent(report_path)
        with report_path.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2)
        report_boundary.validate(report_path)
    print(json.dumps({'report': str(report_path) if report_path else None, 'counts': counts}, ensure_ascii=True), flush=True)
    return 1 if counts['rejected'] else 0


if __name__ == '__main__':
    sys.exit(main())
