"""Approved output boundaries shared by CLI, worker and GUI publication.

This is path-based hardening, not a handle-relative filesystem sandbox.  An
untrusted process able to rename ancestors concurrently can still race a final
check and the existing converter writers.  Keep output trees under the user's
control; never claim this eliminates adversarial TOCTOU races.
"""
import os
import stat
from pathlib import Path

_REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
_WINDOWS_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    prefix + digit for prefix in ('COM', 'LPT') for digit in '123456789¹²³'
}


def absolute_path(value):
    """Preserve lexical ancestors so reparse points are checked before resolve."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or '\x00' in raw:
        raise ValueError('Invalid empty or NUL-containing path')
    if os.name == 'nt' and raw.replace('/', '\\').startswith(('\\\\?\\', '\\\\.\\')):
        raise ValueError('Windows device paths are not supported')
    path = Path(os.path.abspath(raw))
    if os.name == 'nt':
        for part in path.parts[1:]:
            if (':' in part or part.endswith((' ', '.'))
                    or part.split('.')[0].rstrip(' ').upper() in _WINDOWS_RESERVED):
                raise ValueError('Device names, alternate streams and ambiguous Windows paths are not supported')
    return path


def _is_reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & _REPARSE_POINT)


def _within(path, root):
    return path == root or path.is_relative_to(root)


class OutputBoundary:
    """Fail closed on escaped paths, reparse ancestors and observed replacements."""

    def __init__(self, output_root, source_root):
        self.output_root = absolute_path(output_root)
        self.source_root = absolute_path(source_root)
        self._directories = {}
        self._check_directory(self.source_root, required=True)
        self._check_directory(self.output_root)
        self._source_canonical = self.source_root.resolve(strict=True)
        self._output_canonical = self.output_root.resolve(strict=False)
        if (_within(self._output_canonical, self._source_canonical)
                or _within(self._source_canonical, self._output_canonical)):
            raise ValueError('Source and approved output directories must be separate')

    def _check_directory(self, directory, required=False):
        """lstat each existing ancestor; remember identities for this operation."""
        for path in (*reversed(directory.parents), directory):
            try:
                info = path.lstat()
            except FileNotFoundError:
                if required or path in self._directories:
                    raise ValueError('Approved directory disappeared: ' + str(path))
                return
            if _is_reparse(info):
                raise ValueError('Symlink/junction/reparse directories are not allowed: ' + str(path))
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError('Path ancestor is not a directory: ' + str(path))
            identity = (info.st_dev, info.st_ino)
            previous = self._directories.setdefault(path, identity)
            if previous != identity:
                raise ValueError('Approved directory was replaced: ' + str(path))

    def _roots(self):
        self._check_directory(self.source_root, required=True)
        self._check_directory(self.output_root)
        if (self.source_root.resolve(strict=True) != self._source_canonical
                or self.output_root.resolve(strict=False) != self._output_canonical):
            raise ValueError('Approved directory resolution changed')

    def validate(self, value, must_be_absent=False):
        path = absolute_path(value)
        if path == self.output_root or not path.is_relative_to(self.output_root):
            raise ValueError('Output is outside the approved directory: ' + str(path))
        self._roots()
        self._check_directory(path.parent)
        resolved = path.resolve(strict=False)
        if (not resolved.is_relative_to(self._output_canonical)
                or _within(resolved, self._source_canonical)):
            raise ValueError('Output escaped its approved boundary: ' + str(path))
        try:
            info = path.lstat()
        except FileNotFoundError:
            return path
        if _is_reparse(info):
            raise ValueError('Reparse output files are not allowed: ' + str(path))
        if must_be_absent:
            raise FileExistsError('Output already exists; original preserved: ' + str(path))
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Output is not a regular file: ' + str(path))
        return path

    def validate_source(self, value):
        source = absolute_path(value)
        self._roots()
        if not source.is_relative_to(self.source_root):
            raise ValueError('Source file is outside the approved source directory')
        self._check_directory(source.parent, required=True)
        info = source.lstat()
        if _is_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError('Source must be a regular non-reparse file')
        if not source.resolve(strict=True).is_relative_to(self._source_canonical):
            raise ValueError('Source resolution escaped its approved directory')
        return source

    def prepare_parent(self, value):
        path = self.validate(value, must_be_absent=True)
        for directory in (*reversed(path.parent.parents), path.parent):
            try:
                directory.lstat()
            except FileNotFoundError:
                self._check_directory(directory.parent, required=True)
                try:
                    directory.mkdir()
                except FileExistsError:
                    pass
            self._check_directory(directory, required=True)
        return self.validate(path, must_be_absent=True)

    def publish(self, staged, target):
        """Same-directory atomic publication, never replace an existing target."""
        staged = self.validate(staged)
        target = self.validate(target, must_be_absent=True)
        if staged.parent != target.parent or staged == target:
            raise ValueError('Staged output must be a distinct file beside its target')
        info = staged.lstat()
        if not stat.S_ISREG(info.st_mode) or _is_reparse(info) or info.st_nlink != 1:
            raise ValueError('Staged output must be a regular file with one link')
        self.validate(staged)
        self.validate(target, must_be_absent=True)
        if os.name == 'nt':
            os.rename(staged, target)  # Windows refuses an existing destination.
        else:
            os.link(staged, target)  # POSIX rename would overwrite.
            self.cleanup(staged)
        self.validate(target)
        return target

    def cleanup(self, staged):
        """Never follow a changed boundary to delete a leftover staging file."""
        if staged is None:
            return False
        try:
            staged = self.validate(staged)
            if not (staged.name.startswith(('.mesh-converter-', '.nifshift-'))
                    and staged.suffix == '.tmp'):
                return False
            info = staged.lstat()
            if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
                return False
            self.validate(staged)
            staged.unlink()
            return True
        except (OSError, ValueError):
            # If a directory changed, leave the file for manual inspection.
            return False