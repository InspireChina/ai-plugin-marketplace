"""Real filesystem replacement races at the public prototype ingest boundary."""
import os
from pathlib import Path
from uuid import uuid4

import pytest

from ai_sow_lite import _prototype, cli
from .test_inputs import sources_payload

SENTINEL = b'OUTSIDE_PACKAGE_SENTINEL'


def package_case(tmp_path):
    package = tmp_path / 'package'
    assets = package / 'assets'
    assets.mkdir(parents=True)
    (assets / 'own.txt').write_bytes(b'original package resource')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'sentinel.txt').write_bytes(SENTINEL)
    (outside / 'own.txt').write_bytes(SENTINEL)
    return package, assets, outside, tmp_path / 'project'


def ingest(project, package):
    return cli.execute(dict(protocol_version='1.0', request_id=str(uuid4()),
                            project_path=str(project), operation='ingest', payload=sources_payload(package)))


def same_directory(value, path, identity):
    if isinstance(value, int):
        snapshot = os.fstat(value)
        return (snapshot.st_dev, snapshot.st_ino) == identity
    return Path(value) == path


@pytest.mark.parametrize('window', ['assets-scan', 'root-scan', 'member-read'])
def test_replaced_ancestor_never_imports_outside_bytes(tmp_path, monkeypatch, window):
    package, assets, outside, project = package_case(tmp_path)
    target = package if window == 'root-scan' else assets
    state = target.stat()
    identity = (state.st_dev, state.st_ino)
    renamed = tmp_path / 'original-directory'
    swapped = []

    def replace_directory():
        target.rename(renamed)
        target.symlink_to(outside, target_is_directory=True)
        swapped.append(True)

    scan, read = os.scandir, _prototype._read

    def replace_before_scan(value):
        if not swapped and same_directory(value, target, identity):
            replace_directory()
        return scan(value)  # Real scandir results, backed by real files.

    def replace_before_read(path, *args, **kwargs):
        if not swapped and Path(path).name == 'own.txt':
            replace_directory()
        return read(path, *args, **kwargs)  # No fabricated bytes or stat results.

    with monkeypatch.context() as patch:
        if window == 'member-read':
            patch.setattr(_prototype, '_read', replace_before_read)
        else:
            patch.setattr(os, 'scandir', replace_before_scan)
            # The transparent wrapper accepts the same real fd API as scandir.
            patch.setattr(os, 'supports_fd', os.supports_fd | {replace_before_scan})
        reply = ingest(project, package)

    assert swapped, 'The real rename/symlink must occur at the tested boundary.'
    originals = project / '.ai-sow-lite/inputs/originals'
    leaked = [p.relative_to(project).as_posix() for p in originals.rglob('*')
              if p.is_file() and SENTINEL in p.read_bytes()]
    assert not leaked, (reply['ok'], reply['diagnostics'], leaked)
    assert (outside / 'sentinel.txt').read_bytes() == SENTINEL
    if reply['ok']:
        entry = reply['result']['input_refs'][0]
        copied = project / Path(entry['relative_path']).parent / 'resources/assets/own.txt'
        assert copied.read_bytes() == b'original package resource'
    else:
        assert reply['diagnostics'] and 'INTERNAL_ERROR' not in {d['code'] for d in reply['diagnostics']}
        assert reply['result'].get('input_refs', []) == []


@pytest.mark.parametrize('capability', ['scandir-fd', 'openat', 'statat', 'stat-nofollow',
                                        'O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'])
def test_missing_directory_boundary_capability_rejects_prototype(tmp_path, monkeypatch, capability):
    package, _, _, project = package_case(tmp_path)
    if capability.startswith('O_'):
        monkeypatch.delattr(os, capability)
    else:
        attr, function = {
            'scandir-fd': ('supports_fd', os.scandir),
            'openat': ('supports_dir_fd', os.open),
            'statat': ('supports_dir_fd', os.stat),
            'stat-nofollow': ('supports_follow_symlinks', os.stat),
        }[capability]
        monkeypatch.setattr(os, attr, getattr(os, attr) - {function})
    reply = ingest(project, package)
    assert not reply['ok'], reply
    assert 'OPERATION_UNSUPPORTED' in {d['code'] for d in reply['diagnostics']}, reply
    assert reply['result'].get('input_refs', []) == []
    assert not list((project / '.ai-sow-lite/inputs/originals').rglob('*'))


@pytest.mark.parametrize('member', ['root', 'directory', 'file'])
def test_opened_identity_must_match_pre_open_stat_and_handles_close(tmp_path, monkeypatch, member):
    package, assets, _, project = package_case(tmp_path)
    target = {'root': package, 'directory': assets, 'file': assets / 'own.txt'}[member]
    parent = target.parent.stat()
    parent_identity = (parent.st_dev, parent.st_ino)
    original = tmp_path / 'original-member'
    opened, swapped = [], []
    open_file = os.open

    def replace_before_open(path, flags, *args, **kwargs):
        directory_fd = kwargs.get('dir_fd')
        matches = (same_directory(directory_fd, target.parent, parent_identity) and Path(path).name == target.name
                   if directory_fd is not None else Path(path) == target)
        if matches and not swapped:
            target.rename(original)
            if member == 'file':
                target.write_bytes(SENTINEL)
            else:
                target.mkdir()
                (target / 'sentinel.txt').write_bytes(SENTINEL)
            swapped.append(True)
        descriptor = open_file(path, flags, *args, **kwargs)
        if matches or directory_fd in opened or Path(path) == package:
            opened.append(descriptor)
        return descriptor

    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', replace_before_open)
        patch.setattr(os, 'supports_dir_fd', os.supports_dir_fd | {replace_before_open})
        reply = ingest(project, package)
    assert swapped, 'Replace a real object only after its pre-open stat.'
    assert not reply['ok'] and 'PATH_UNSAFE' in {d['code'] for d in reply['diagnostics']}, reply
    assert reply['result'].get('input_refs', []) == []
    assert opened
    for descriptor in set(opened):
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_runtime_refusal_of_directory_fd_api_is_structured(tmp_path, monkeypatch):
    package, _, _, project = package_case(tmp_path)
    scandir = os.scandir

    def unsupported(path):
        if isinstance(path, int):
            raise NotImplementedError('fd scandir unavailable at runtime')
        return scandir(path)

    with monkeypatch.context() as patch:
        patch.setattr(os, 'scandir', unsupported)
        patch.setattr(os, 'supports_fd', os.supports_fd | {unsupported})
        reply = ingest(project, package)
    assert not reply['ok'] and 'OPERATION_UNSUPPORTED' in {d['code'] for d in reply['diagnostics']}, reply
    assert reply['result'].get('input_refs', []) == []
