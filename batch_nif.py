"""Mesh Converter ALPHA 1.0: bidirectional local NIF batch entry point."""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from converter import convert_file, BUILD, DIRECTIONS
from corpus_inventory import nif_files
from publication_guard import OutputBoundary, absolute_path

def main():
    parser=argparse.ArgumentParser(description='Convert verified FO76/FO4 NIF structures. Materials/textures are separate.')
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--direction',choices=tuple(DIRECTIONS),default='76-to-4')
    parser.add_argument('--reference',type=Path,help='Target game Meshes/resources directory or explicit skeleton.nif')
    parser.add_argument('--no-collision',action='store_true',help='Explicit visual-only output; physics is not preserved')
    parser.add_argument('--preflight',action='store_true',help='Read-only conversion checks; no NIF outputs')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    try:
        source=absolute_path(args.input);output=absolute_path(args.output)
        if not source.exists():parser.error('Input does not exist')
        base=source if source.is_dir() else source.parent
        boundary=OutputBoundary(output, base)
        if source.is_file():boundary.validate_source(source)
        report_path=absolute_path(args.report) if args.report else output/('mesh-converter-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.json')
        # An explicit --report approves its parent separately, never the source tree.
        report_boundary=OutputBoundary(report_path.parent, base) if args.report else boundary
        report_boundary.validate(report_path, must_be_absent=True)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    records=[];counts={'passed':0,'rejected':0,'skipped':0}
    for path in nif_files(source):
        destination=output/path.relative_to(base)
        try:
            data=convert_file(path,destination,direction=args.direction,collision=not args.no_collision,
                              dry_run=args.preflight,reference_root=args.reference,
                              output_root=output,source_root=base)
            result=dict(input=str(path),status='passed',result=data)
        except FileExistsError as error:result=dict(input=str(path),status='skipped',error=str(error))
        except Exception as error:result=dict(input=str(path),status='rejected',error=f'{type(error).__name__}: {error}')
        records.append(result);counts[result['status']]+=1
        print(json.dumps(result,ensure_ascii=True),flush=True)
    if not records:parser.error('No .nif files found')
    report_boundary.prepare_parent(report_path)
    report=dict(build=BUILD,direction=args.direction,collision=not args.no_collision,
                reference=str(args.reference) if args.reference else None,preflight=args.preflight,
                game_verified=False,counts=counts,files=records)
    report_boundary.validate(report_path, must_be_absent=True)
    with report_path.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=True,indent=2)
    report_boundary.validate(report_path)
    print(json.dumps({'report':str(report_path),'counts':counts},ensure_ascii=True),flush=True)
    return 1 if counts['rejected'] else 0

if __name__=='__main__':sys.exit(main())
