"""Build a transparent Windows x64 folder distribution, entirely offline.

No PyInstaller, embedded archive, UPX or obfuscation is used. GPL-3.0.
See PORTABLE_BUILD.md for provenance, licensing gaps and launch instructions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

SOURCE = Path(__file__).resolve().parent
DEFAULT_RUNTIME = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python"
OLD_WORK = Path.home() / "Documents/Codex/2026-09-06/wox/work"
DEFAULT_OUTPUT = SOURCE.parents[1] / "releases/MeshConverter_ALPHA_1.0_Compatibility/MeshConverter"
TOP_RUNTIME_FILES = ("python.exe", "pythonw.exe", "python3.dll", "python312.dll",
                     "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt")
LIB_EXCLUDE = {"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter",
               "turtledemo", "ensurepip", "venv", "__phello__"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copied(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def requirements():
    result = []
    for line in (SOURCE / "requirements-runtime.txt").read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+)==([A-Za-z0-9_.+-]+)", line)
        if not match:
            raise ValueError("Runtime dependency must use an exact version: " + line)
        result.append(match.groups())
    return result


def runtime_copy(runtime, output):
    result = subprocess.run([str(runtime / "python.exe"), "-I", "-c", "import sys,json,struct;print(json.dumps({'version':sys.version,'version_info':list(sys.version_info[:3]),'bits':struct.calcsize('P')*8}))"],
                            capture_output=True, text=True, check=True)
    version = json.loads(result.stdout)
    if version["version_info"][:2] != [3, 12] or version["bits"] != 64:
        raise ValueError("This dependency set requires Python 3.12 x64")
    destination = output / "runtime"
    for name in TOP_RUNTIME_FILES:
        copied(runtime / name, destination / name)
    def ignore(directory, names):
        return [name for name in names if name in LIB_EXCLUDE or name.endswith((".pyc", ".pyo"))]
    shutil.copytree(runtime / "Lib", destination / "Lib", ignore=ignore)
    for file in (runtime / "DLLs").iterdir():
        if file.is_file() and not file.name.startswith("_test") and file.name not in {"_ctypes_test.pyd", "_tkinter.pyd", "tcl86t.dll", "tk86t.dll"}:
            copied(file, destination / "DLLs" / file.name)
    (destination / "python312._pth").write_text(".\nLib\nDLLs\n../vendor\n../app\nimport site\n", encoding="ascii")
    return dict(provider="Local Codex bundled runtime", input_directory=str(runtime),
                claimed_download_source=None, runtime=version,
                note="Copied locally; not claimed to be downloaded or certified by this builder from Python.org.",
                original_core_hashes={name: sha256(runtime / name) for name in TOP_RUNTIME_FILES},
                stdlib_exclusions=sorted(LIB_EXCLUDE), bytecode_precompilation=False)


def safe_relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
        raise ValueError("Unsafe archive member: " + name)
    return path


def install_wheel(wheel, vendor):
    """Unpack standard wheel contents; no package setup code is executed."""
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Wheel does not contain exactly one METADATA: " + str(wheel))
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        written = []
        for member in archive.infolist():
            relative = safe_relative(member.filename)
            if member.is_dir():
                continue
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Symlink inside wheel")
            parts = relative.parts
            if parts and parts[0].endswith(".data"):
                if len(parts) > 2 and parts[1] in ("purelib", "platlib"):
                    relative = PurePosixPath(*parts[2:])
                else:
                    continue  # No optional console scripts or build headers are needed.
            data = archive.read(member)
            target = vendor.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != data:
                raise ValueError("Conflicting dependency file: " + str(relative))
            target.write_bytes(data)
            written.append(relative.as_posix())
    return dict(name=metadata["Name"], version=metadata["Version"], source=str(wheel),
                source_sha256=sha256(wheel), format="wheel, unpacked as readable files",
                declared_license=metadata.get("License-Expression") or metadata.get("License"),
                requires_dist=metadata.get_all("Requires-Dist", []), installed_files=len(written))


def install_proxy_tools(wheels, appdeps, vendor):
    source = wheels / "proxy_tools-0.1.0.tar.gz"
    written = 0
    with tarfile.open(source, "r:gz") as archive:
        for member in archive.getmembers():
            relative = safe_relative(member.name)
            parts = relative.parts
            if len(parts) < 3 or parts[1] != "proxy_tools" or not member.isfile():
                continue
            target = vendor.joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as stream:
                target.write_bytes(stream.read())
            written += 1
        metadata = archive.extractfile("proxy_tools-0.1.0/PKG-INFO").read()
    # Retain the already-built metadata without executing setuptools or setup.py.
    dist_info = appdeps / "proxy_tools-0.1.0.dist-info"
    if not dist_info.is_dir():
        raise FileNotFoundError("Existing proxy_tools metadata not found: " + str(dist_info))
    shutil.copytree(dist_info, vendor / dist_info.name)
    return dict(name="proxy_tools", version="0.1.0", source=str(source), source_sha256=sha256(source),
                format="Python source extracted from cached source distribution", metadata_source=str(dist_info),
                declared_license="MIT (package metadata)", installed_files=written,
                license_gap="Cached source distribution has no standalone full license text; confirm upstream notice before public release.")


def vendor_copy(wheels, appdeps, output):
    vendor = output / "vendor"
    vendor.mkdir()
    packages = []
    for name, version in requirements():
        if name == "proxy_tools":
            packages.append(install_proxy_tools(wheels, appdeps, vendor))
            continue
        candidates = sorted(wheels.glob(name.replace("-", "_") + "-" + version + "-*.whl"))
        if len(candidates) != 1:
            raise ValueError(f"Expected exactly one cached wheel for {name}=={version}, found {len(candidates)}")
        package = install_wheel(candidates[0], vendor)
        if package["name"].replace("-", "_").lower() != name.replace("-", "_").lower() or package["version"] != version:
            raise ValueError("Wheel metadata does not match requirement")
        packages.append(package)
    return packages


def prune_windows_runtime(output):
    """Remove unused foreign-platform assets and build hooks, retaining licenses/metadata."""
    root=Path(output).resolve()
    relative_paths=(
        'vendor/webview/__pyinstaller',
        'vendor/webview/platforms/android',
        'vendor/webview/platforms/cef.py',
        'vendor/webview/platforms/cocoa.py',
        'vendor/webview/platforms/gtk.py',
        'vendor/webview/platforms/qt.py',
        'vendor/webview/lib/pywebview-android.jar',
        'vendor/webview/lib/WebBrowserInterop.x86.dll',
    )
    removed=[]
    for relative in relative_paths:
        path=root/relative
        if not path.exists():continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Refuse pruning outside package root')
        files=sorted(path.rglob('*')) if path.is_dir() else [path]
        for item in files:
            if item.is_symlink() or not item.resolve().is_relative_to(root):
                raise ValueError('Refuse pruning linked package files')
            if item.is_file():removed.append(dict(path=item.relative_to(root).as_posix(),bytes=item.stat().st_size,sha256=sha256(item)))
        if path.is_dir():shutil.rmtree(path)
        else:path.unlink()
    return dict(target='Windows x64 / Edge WebView2',removed=removed,
                removed_bytes=sum(item['bytes'] for item in removed),
                dependency_metadata_and_licenses_preserved=True,
                reason='Foreign-platform backends and packaging hooks are not used at runtime.')



def apply_vendor_patch(output):
    """Apply only the reviewed local source overlay; retain upstream metadata."""
    patch_root = SOURCE / 'vendor_patch'
    record = json.loads((patch_root / 'manifest.json').read_text(encoding='utf8'))
    required = {'webview/util.py', 'webview/platforms/edgechromium.py'}
    entries = record.get('files', [])
    if (record.get('patch_id') != 'private0516-mesh-bridge-20261007-v1'
            or record.get('upstream_package') != 'pywebview'
            or record.get('upstream_version') != '6.2.1'
            or len(entries) != len(required)
            or {item['path'] for item in entries} != required):
        raise ValueError('Missing/incompatible Mesh bridge patch manifest')
    checked = []
    for item in entries:
        relative = safe_relative(item['path'])
        source = patch_root.joinpath(*relative.parts)
        target = output / 'vendor' / Path(*relative.parts)
        # Validate the complete overlay before changing any installed file.
        if sha256(source) != item['patched_sha256']:
            raise ValueError('Local overlay hash mismatch: ' + item['path'])
        if sha256(target) not in {item['upstream_sha256'], item['patched_sha256']}:
            raise ValueError('Unexpected installed vendor baseline: ' + item['path'])
        checked.append((source, target))
    for source, target in checked:
        copied(source, target)
    copied(patch_root / 'manifest.json', output / 'VENDOR_PATCHES.json')
    copied(patch_root / 'LICENSE.pywebview.txt', output / 'licenses/pywebview-local-patch_LICENSE.txt')
    return record


def source_copy(output):
    """Copy only auditable source/assets; never traverse game input directories."""
    files = []
    for file in SOURCE.rglob("*"):
        if not file.is_file():
            continue
        relative = file.relative_to(SOURCE)
        if any(part in {"__pycache__", "build", "dist", ".git", ".venv"} for part in relative.parts):
            continue
        if relative.parts[0] not in {"havok", "tests", "vendor_patch"} and len(relative.parts) > 1:
            continue
        if file.suffix.lower() not in {".py", ".html", ".md", ".ico", ".cs", ".txt", ".json"} and file.name != "LICENSE":
            continue
        copied(file, output / "app" / relative)
        files.append(relative.as_posix())
    for name in ("LICENSE", "THIRD_PARTY.md", "PORTABLE_BUILD.md", "requirements-runtime.txt",
                 "README.md", "README_中文.md", "COMPATIBILITY_REPORT.md"):
        if (SOURCE / name).is_file():
            copied(SOURCE / name, output / name)
    return dict(directory=str(SOURCE), files=files, game_asset_files_copied=0,
                note="UI retains its pre-existing embedded font data and decorative wireframe; rights not cleared by this build.")


def compile_launcher(csc, output):
    build = output / "launcher-source"
    build.mkdir(exist_ok=True)
    copied(SOURCE / "Launcher.cs", build / "Launcher.cs")
    manifest = build / "app.manifest"
    manifest.write_text('''<?xml version="1.0" encoding="utf-8"?>
<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1">
 <assemblyIdentity version="1.0.0.0" name="private0516.MeshConverter"/>
 <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo>
</assembly>
''', encoding="utf8")
    command = [str(csc), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
               "/reference:System.Windows.Forms.dll", "/out:" + str(output / "MeshConverter.exe"),
               "/win32icon:" + str(SOURCE / "app.ico"), "/win32manifest:" + str(manifest), str(build / "Launcher.cs")]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError("C# compilation failed:\n" + completed.stdout + completed.stderr)
    return dict(compiler=str(csc), compiler_sha256=sha256(csc), source_sha256=sha256(SOURCE / "Launcher.cs"),
                output_sha256=sha256(output / "MeshConverter.exe"), output_bytes=(output / "MeshConverter.exe").stat().st_size,
                target="Ordinary x64 .NET Framework GUI executable", signed=False,
                embedded_program_archive=False, elevation="asInvoker", runtime_downloads=False)


def license_inventory(output, provenance):
    destination = output / "licenses"
    destination.mkdir(exist_ok=True)
    copied(output / "runtime/LICENSE.txt", destination / "Python-LICENSE.txt")
    copied(output / "LICENSE", destination / "Project-LICENSE.txt")
    records = []
    for package in provenance["dependencies"]:
        normalized = package["name"].replace("-", "_").lower()
        directories = [folder for folder in (output / "vendor").glob("*.dist-info") if folder.name.lower().replace("-", "_").startswith(normalized + "_")]
        texts = []
        for directory in directories:
            for file in directory.rglob("*"):
                if file.is_file() and file.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
                    target = destination / directory.name / file.relative_to(directory)
                    copied(file, target)
                    texts.append(dict(path=target.relative_to(output).as_posix(), sha256=sha256(target)))
        records.append(dict(name=package["name"], version=package["version"], license_texts=texts,
                            declared_license=package.get("declared_license"),
                            status="bundled_text_preserved" if texts else "full_text_missing_in_local_archive"))
    native_files = [dict(path=file.relative_to(output).as_posix(), sha256=sha256(file))
                    for folder in (output / "runtime", output / "vendor")
                    for file in folder.rglob("*") if file.is_file() and file.suffix.lower() in (".dll", ".pyd", ".exe")]
    result = dict(project_license="Existing GPL-3.0 license retained",
                  python_license=dict(path="licenses/Python-LICENSE.txt", sha256=sha256(destination / "Python-LICENSE.txt")),
                  dependencies=records, native_files=native_files,
                  unresolved=["STOP/Harmony embedded font distribution rights are unverified.",
                              "Decorative game-derived ambulance wireframe rights are unverified.",
                              "Additional redistribution notices for native CPython dependencies, Microsoft CRT and WebView2 SDK DLLs must be checked against the provider distributions.",
                              "proxy_tools source archive declares MIT but omits the standalone full license text."],
                  public_release_clearance=False)
    write_json(output / "LICENSE_INVENTORY.json", result)


def smoke(output):
    python = output / "runtime/python.exe"
    code = """import sys,json,importlib.metadata as m,ssl,sqlite3,multiprocessing
initial_sys_path=list(sys.path)
import webview,clr,pythonnet,clr_loader,cffi,pycparser,proxy_tools,bottle,typing_extensions
import converter,inspect_nif
print(json.dumps({'version':sys.version,'executable':sys.executable,'initial_sys_path':initial_sys_path,'sys_path_after_clr':sys.path,'isolated':sys.flags.isolated,'ssl':ssl.OPENSSL_VERSION,'sqlite':sqlite3.sqlite_version,'dependencies':{n:m.version(n) for n in ['pywebview','pythonnet','clr_loader','cffi','pycparser','proxy_tools','bottle','typing_extensions']}}))
"""
    with tempfile.TemporaryDirectory(prefix="mesh-portable-check-") as directory:
        process = subprocess.run([str(python), "-B", "-X", "utf8", "-c", code], cwd=directory,
                                 capture_output=True, text=True, encoding="utf8", errors="replace", timeout=60)
        if process.returncode:
            raise RuntimeError("Portable import check failed:\n" + process.stdout + process.stderr)
        imports = json.loads(process.stdout.splitlines()[-1])
        package = output.resolve()
        dotnet = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET"
        initial_isolated = all(Path(entry).resolve().is_relative_to(package) for entry in imports["initial_sys_path"])
        # pythonnet appends the system CLR directory when it loads .NET Framework.
        clr_paths_valid = all(Path(entry).resolve().is_relative_to(package) or Path(entry).resolve().is_relative_to(dotnet.resolve()) for entry in imports["sys_path_after_clr"])
        if not imports["isolated"] or not initial_isolated or not clr_paths_valid:
            raise RuntimeError("Runtime imports escaped the portable package")
        commands = {}
        for name in ("batch_nif.py", "corpus_inventory.py", "validate_samples.py"):
            result = subprocess.run([str(python), "-B", "-X", "utf8", str(output / "app" / name), "--help"], cwd=directory,
                                    capture_output=True, text=True, encoding="utf8", errors="replace", timeout=30)
            commands[name] = dict(exit_code=result.returncode, help_present="usage:" in result.stdout.lower(), stderr=result.stderr[-2000:])
            if result.returncode or "usage:" not in result.stdout.lower():
                raise RuntimeError("CLI check failed: " + name + "\n" + result.stdout + result.stderr)
        launcher = subprocess.run([str(output / "MeshConverter.exe"), "--cli", "--help"], cwd=directory,
                                  capture_output=True, text=True, encoding="utf8", errors="replace", timeout=30)
        if launcher.returncode or "usage:" not in launcher.stdout.lower():
            raise RuntimeError("Launcher CLI forwarding failed:\n" + launcher.stdout + launcher.stderr)
    return dict(passed=True, isolated_imports=imports, cli=commands,
                launcher_cli=dict(exit_code=launcher.returncode, forwarded_help=True),
                scope="Portable import and argument parsing only; native desktop integration is a separate test")


def manifest(output):
    files = sorted(file for file in output.rglob("*") if file.is_file() and file.name != "SHA256SUMS.txt")
    with (output / "SHA256SUMS.txt").open("w", encoding="utf8", newline="\n") as stream:
        for file in files:
            stream.write(sha256(file) + "  " + file.relative_to(output).as_posix() + "\n")
    return dict(files=len(files), bytes=sum(file.stat().st_size for file in files))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--wheels", type=Path, default=OLD_WORK / "build_wheels")
    parser.add_argument("--appdeps", type=Path, default=OLD_WORK / "appdeps")
    parser.add_argument("--csc", type=Path, default=Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe"))
    parser.add_argument("--sync-source", action="store_true")
    args = parser.parse_args(argv)
    output, runtime, wheels, appdeps, csc = (value.resolve() for value in (args.output, args.runtime, args.wheels, args.appdeps, args.csc))
    for protected in (SOURCE, runtime, wheels, appdeps):
        if output == protected or output.is_relative_to(protected) or protected.is_relative_to(output):
            parser.error("Output and build-input directories must be disjoint")
    if not csc.is_file():
        parser.error("C# compiler was not found")
    if args.sync_source:
        record = output / "BUILD_PROVENANCE.json"
        if not record.is_file():
            parser.error("--sync-source requires a package created by this builder")
        provenance = json.loads(record.read_text(encoding="utf8"))
        if provenance.get("format") != "transparent-mesh-converter-folder-v1":
            parser.error("Unrecognized package provenance")
    else:
        if output.exists():
            parser.error("Output already exists; use a new directory or --sync-source")
        output.mkdir(parents=True)
        provenance = dict(format="transparent-mesh-converter-folder-v1",
                          runtime=runtime_copy(runtime, output), dependencies=vendor_copy(wheels, appdeps, output))
    provenance["vendor_patches"] = apply_vendor_patch(output)
    pruning=prune_windows_runtime(output)
    if pruning["removed"] or "runtime_pruning" not in provenance:provenance["runtime_pruning"]=pruning
    provenance.update(updated_at=datetime.now(timezone.utc).isoformat(), source=source_copy(output),
                      launcher=compile_launcher(csc, output), runtime_requirements=requirements(),
                      packaging=dict(packer=None, obfuscation=False, embedded_archive=False, launch_downloads=False),
                      public_release_clearance=False)
    write_json(output / "BUILD_PROVENANCE.json", provenance)
    license_inventory(output, provenance)
    check = smoke(output)
    write_json(output / "PORTABLE_SMOKE_TEST.json", check)
    files = manifest(output)
    print(json.dumps(dict(output=str(output), smoke_passed=True, **files, launcher_bytes=provenance["launcher"]["output_bytes"],
                          public_release_clearance=False), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
