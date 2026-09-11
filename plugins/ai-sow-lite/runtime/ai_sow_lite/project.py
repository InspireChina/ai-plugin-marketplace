"""Local identities and atomic storage. No professional workflow or Office calls.

Atomic-file and no-follow methods adapted from D00 commit 2fc8588 project_io;
Lite owns its paths/contracts. Ordinary local filesystems only, not a power-loss guarantee.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import stat
from uuid import UUID, uuid4

from .contracts import canonical_json_bytes, file_sha256, load_json, schema_validator
from .validation import diagnostic, project_file


class StorageError(ValueError):
    def __init__(self, code, message, path=None, preserved_paths=()):
        super().__init__(code)
        self.diagnostics = [diagnostic(code, path=path, message=message)]
        self.diagnostics[0]['preserved_paths'] = list(preserved_paths)


def safe_path(project, relative, area='.ai-sow-lite'):
    """Reject redirected components, including internal links and Windows reparse points."""
    project = Path(project).resolve()
    try:
        target = project_file(project, relative, area)
        current = project
        for part in Path(relative).parts:
            current = current / part
            try:
                snapshot = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(snapshot.st_mode) or getattr(snapshot, 'st_file_attributes', 0) & 0x400:
                raise ValueError('redirected component')
        return target
    except (ValueError, RuntimeError):
        raise StorageError('PATH_UNSAFE', '文件必须位于指定项目区域，不能通过链接重定向。') from None


def checked_json(project, relative, definition, area='.ai-sow-lite'):
    path = safe_path(project, relative, area)
    try:
        value = load_json(path)
        if list(schema_validator('artifacts', definition).iter_errors(value)):
            raise ValueError('schema')
        return value
    except (ValueError, UnicodeError):
        raise StorageError('VERSION_INCOMPATIBLE', '文件结构损坏或版本不兼容。', relative) from None


def file_ref(project, path):
    return dict(path=path.relative_to(Path(project).resolve()).as_posix(), sha256=file_sha256(path))


def fsync_directory(path):
    """Windows has no stdlib directory fsync. Unix errors are not silently ignored."""
    if os.name == 'nt':
        return False
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def atomic_bytes(path, raw, *, immutable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / ('.' + path.name + '-' + str(uuid4()) + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                os.link(temp, path)
            except FileExistsError:
                if path.read_bytes() != raw:
                    raise StorageError('IDENTITY_CONFLICT', '不可变身份已有不同内容；保留原件。') from None
        else:
            os.replace(temp, path)
        fsync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def write_json(project, relative, value, *, immutable=False):
    path = safe_path(project, relative)
    atomic_bytes(path, canonical_json_bytes(value), immutable=immutable)
    return file_ref(project, path)


def initialize(project: Path, project_type: str, template: Path):
    project = Path(project).resolve()
    if project_type not in ('new', 'existing'):
        raise StorageError('PROJECT_ID_CONFLICT', '必须明确项目类型。')
    record_path = safe_path(project, '.ai-sow-lite/project.json')
    raw = template.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if record_path.exists():
        record = checked_json(project, '.ai-sow-lite/project.json', 'project')
        if record['project_type'] != project_type or record['template_hash'] != digest:
            raise StorageError('PROJECT_ID_CONFLICT', '项目类型或固定模板身份冲突；未覆盖项目。')
    else:
        record = dict(schema_version='1.0', project_id=str(uuid4()), project_type=project_type, template_hash=digest)
    target = safe_path(project, f'.ai-sow-lite/template/{digest}/sow-template.xlsx')
    atomic_bytes(target, raw, immutable=True)
    write_json(project, '.ai-sow-lite/project.json', record, immutable=True)
    index = safe_path(project, '.ai-sow-lite/inputs/index.json')
    if not index.exists():
        originals = safe_path(project, '.ai-sow-lite/inputs/originals')
        if originals.exists() and any(originals.iterdir()):
            raise StorageError('EVIDENCE_MISSING', '已有原件但输入索引丢失；保留文件，不能重置成空登记。')
        write_json(project, '.ai-sow-lite/inputs/index.json', dict(schema_version='1.0', items=[]), immutable=True)
    return record


def request_area(request_id, entrypoint):
    try:
        if str(UUID(request_id)) != request_id or UUID(request_id).version != 4 or entrypoint not in ('generate', 'clarify'):
            raise ValueError('identity')
    except (ValueError, TypeError, AttributeError):
        raise StorageError('PROTOCOL_INVALID', '请求身份或入口不合法。') from None
    return f'.ai-sow-lite/work/{entrypoint}/{request_id}'


def ensure_request(project, request_id, entrypoint):
    area = request_area(request_id, entrypoint)
    other = 'clarify' if entrypoint == 'generate' else 'generate'
    if safe_path(project, request_area(request_id, other) + '/request.json').exists():
        raise StorageError('REQUEST_ID_CONFLICT', '同一请求不能改变入口。')
    marker = safe_path(project, area + '/request.json')
    checkpoint_path = safe_path(project, area + '/checkpoint.json')
    if not marker.exists() and not checkpoint_path.parent.exists():
        write_json(project, area + '/request.json', dict(schema_version='1.0', request_id=request_id,
                                                       entrypoint=entrypoint), immutable=True)
        checkpoint = dict(schema_version='1.0', request_id=request_id, entrypoint=entrypoint,
                          target_ids=[], activity_ids=[], coverage_cursor=None, additional_investigation_batches=0,
                          repair_batches=0, recovery_queries=0, operation_retries={}, candidate_path=None,
                          last_progress='', last_repair='', exit_reason=None)
        write_json(project, area + '/checkpoint.json', checkpoint)
        return checkpoint
    try:
        checkpoint = checked_json(project, area + '/checkpoint.json', 'checkpoint')
        if checkpoint['request_id'] != request_id or checkpoint['entrypoint'] != entrypoint:
            raise StorageError('REQUEST_ID_CONFLICT', '检查点身份与请求目录不同。')
        if any(checkpoint.get(k) is None for k in ('additional_investigation_batches', 'repair_batches')):
            raise StorageError('CHECKPOINT_UNKNOWN', '检查点计数未知。')
        return checkpoint
    except (FileNotFoundError, StorageError) as error:
        if isinstance(error, StorageError) and error.diagnostics[0]['code'] == 'REQUEST_ID_CONFLICT':
            raise
        # The marker is written before querying: a crash cannot silently grant another query.
        query_marker = safe_path(project, area + '/unknown-recovery.json')
        if not query_marker.exists():
            write_json(project, area + '/unknown-recovery.json', dict(schema_version='1.0', request_id=request_id), immutable=True)
            recover_request(project, request_id)
        raise StorageError('CHECKPOINT_UNKNOWN', '已查询恢复事实；计数仍不可用，停止且不按零重置。',
                           area + '/checkpoint.json', [area]) from None


def save_checkpoint(project, checkpoint):
    area = request_area(checkpoint['request_id'], checkpoint['entrypoint'])
    if list(schema_validator('artifacts', 'checkpoint').iter_errors(checkpoint)):
        raise StorageError('LOOP_LIMIT_REACHED', '检查点计数越界或结构不合法。')
    previous = checked_json(project, area + '/checkpoint.json', 'checkpoint')
    for key in ('additional_investigation_batches', 'repair_batches', 'recovery_queries'):
        old, new = previous.get(key), checkpoint.get(key)
        if (old is None and new is not None) or (old is not None and new is not None and new < old):
            raise StorageError('LOOP_LIMIT_REACHED', '不能重置已使用或未知的计数。')
    for key, count in previous.get('operation_retries', {}).items():
        if checkpoint.get('operation_retries', {}).get(key, -1) < count:
            raise StorageError('LOOP_LIMIT_REACHED', '不能重置已有操作重试计数。')
    return write_json(project, area + '/checkpoint.json', checkpoint)


@contextmanager
def commit_lock(project):
    """Nonblocking OS-owned lock; close/process exit releases the fixed lock region."""
    path = safe_path(project, '.ai-sow-lite/commit.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            acquire = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        elif os.name == 'posix':
            import fcntl
            acquire = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        else:
            raise StorageError('OPERATION_UNSUPPORTED', '此平台没有已实现的本地提交锁。')
        try:
            acquire()
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise StorageError('WRITE_BUSY', '项目提交锁正在使用；立即退出，不等待或自动重试。') from None
            raise
        try:
            yield
        finally:
            release()


def replace_current(root: Path, pointer: dict):
    temp = root / ('.current-' + str(uuid4()) + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(canonical_json_bytes(pointer))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, root / 'current.json')
    finally:
        temp.unlink(missing_ok=True)
    fsync_directory(root)


_CORE_FILES = {'model.json', 'pending-items.json', 'decisions.json', 'projection.json',
               'sow.xlsx', 'summary.md', 'pending-items.md'}


def _validate_manifest(manifest):
    if list(schema_validator('artifacts', 'manifest').iter_errors(manifest)):
        raise StorageError('VERSION_INCOMPATIBLE', '版本 manifest 结构不兼容。')
    area = f".ai-sow-lite/versions/{manifest['version_id']}"
    names = set()
    for ref in manifest['files']:
        path = Path(ref['path'])
        if path.parent.as_posix() != area or path.name in names:
            raise StorageError('VERSION_INCOMPATIBLE', '版本文件必须唯一且直属对应版本目录。')
        names.add(path.name)
    if not _CORE_FILES <= names or manifest['verification_ref'] not in manifest['files']:
        raise StorageError('VERSION_INCOMPATIBLE', '完整版本缺少必要文件或核验记录。')
    seen = {}
    for ref in manifest['dependencies']:
        path = ref['path']
        allowed = path == '.ai-sow-lite/project.json' or any(path.startswith('.ai-sow-lite/' + area + '/') for area in (
            'template', 'inputs/originals', 'inputs/readings', 'analysis/topics', 'analysis/observations',
            'analysis/registrations', 'versions'))
        if not allowed or (path in seen and seen[path] != ref['sha256']):
            raise StorageError('VERSION_INCOMPATIBLE', '依赖不能指向可变索引/work 或冲突摘要。')
        seen[path] = ref['sha256']
    if manifest['base_version_id'] is not None:
        base = f".ai-sow-lite/versions/{manifest['base_version_id']}/manifest.json"
        if base not in seen:
            raise StorageError('EVIDENCE_MISSING', '历史基线必须有摘要绑定的 manifest 依赖。')


def _verify_refs(project, refs):
    for ref in refs:
        path = safe_path(project, ref['path'])
        if file_ref(project, path) != ref:
            raise StorageError('EVIDENCE_MISSING', '实际文件字节与绑定摘要不同。', ref['path'])


def _read_manifest(project, pointer):
    """Verify pointer/manifest binding only; file and dependency bytes are not read."""
    if list(schema_validator('artifacts', 'current').iter_errors(pointer)):
        raise StorageError('VERSION_INCOMPATIBLE', 'current 指针结构无效。')
    relative = f".ai-sow-lite/versions/{pointer['version_id']}/manifest.json"
    _verify_refs(project, [dict(path=relative, sha256=pointer['manifest_hash'])])
    manifest = checked_json(project, relative, 'manifest')
    _validate_manifest(manifest)
    if manifest['version_id'] != pointer['version_id']:
        raise StorageError('VERSION_INCOMPATIBLE', 'manifest 与当前版本身份不同。')
    return manifest


def _read_version(project, pointer):
    manifest = _read_manifest(project, pointer)
    _verify_refs(project, manifest['files'] + manifest['dependencies'])
    return manifest


def read_current_manifest(project):
    """Narrow inspect seam, without the full apply/recover integrity check."""
    path = safe_path(project, '.ai-sow-lite/current.json')
    if not path.exists():
        return None, None
    pointer = checked_json(project, '.ai-sow-lite/current.json', 'current')
    return pointer, _read_manifest(project, pointer)


def read_current(project):
    pointer, manifest = read_current_manifest(project)
    if manifest is not None:
        _verify_refs(project, manifest['files'] + manifest['dependencies'])
    return pointer, manifest


def _find_applied(project, request_id):
    current, manifest = read_current(project)
    seen = set()
    while manifest is not None:
        version = manifest['version_id']
        if version in seen:
            raise StorageError('VERSION_INCOMPATIBLE', '历史基线链成环。')
        seen.add(version)
        if manifest['request_id'] == request_id:
            return current, manifest
        base = manifest['base_version_id']
        if base is None:
            break
        relative = f'.ai-sow-lite/versions/{base}/manifest.json'
        ref = next((r for r in manifest['dependencies'] if r['path'] == relative), None)
        if ref is None:
            raise StorageError('EVIDENCE_MISSING', '历史基线没有摘要绑定。')
        manifest = _read_version(project, dict(version_id=base, manifest_hash=ref['sha256']))
    return current, None


def cancel_request(project, request_id, entrypoint):
    """Record a cancellation already observed locally. Does not capture host UI events."""
    area = request_area(request_id, entrypoint)
    return write_json(project, area + '/cancelled.json', dict(schema_version='1.0', request_id=request_id,
                     entrypoint=entrypoint), immutable=True)


def _check_cancelled(project, request_id, entrypoint):
    area = request_area(request_id, entrypoint)
    if safe_path(project, area + '/cancelled.json').exists():
        raise StorageError('REQUEST_CANCELLED', '已观察到本请求取消；迟到候选不能生效。', preserved_paths=[area])


def recover_request(project: Path, request_id: str):
    paths = []
    cancelled = False
    for entrypoint in ('generate', 'clarify'):
        area = request_area(request_id, entrypoint)
        if safe_path(project, area).exists():
            paths.append(area)
        cancelled |= safe_path(project, area + '/cancelled.json').exists()
    try:
        current, applied = _find_applied(project, request_id)
        if applied is not None:
            paths.append(f".ai-sow-lite/versions/{applied['version_id']}")
            return dict(state='applied', applied_version=applied['version_id'], preserved_paths=paths,
                        diagnostics_ref=None)
    except (StorageError, OSError) as error:
        # Read-only: no repair of current, no orphan activation, no invented empty state.
        issues = error.diagnostics if isinstance(error, StorageError) else [diagnostic(
            'IO_FAILED', message='当前版本或历史依赖不可读取，未修改现有文件。')]
        return dict(state='incompatible', applied_version=None, preserved_paths=paths,
                    diagnostics_ref=None, diagnostics=issues)
    return dict(state='cancelled' if cancelled else 'draft', applied_version=None,
                preserved_paths=paths, diagnostics_ref=None)


def _applied_result(project, manifest, current, idempotent):
    relative = f".ai-sow-lite/versions/{manifest['version_id']}/manifest.json"
    return dict(applied_version=manifest['version_id'], manifest_ref=file_ref(project, safe_path(project, relative)),
                workbook_ref=next(ref for ref in manifest['files'] if Path(ref['path']).name == 'sow.xlsx'),
                idempotent=idempotent, current_version=current['version_id'])


def _same_intent(applied, manifest):
    if applied['intent_digest'] != manifest['intent_digest']:
        raise StorageError('REQUEST_ID_CONFLICT', '请求 ID 已封存不同业务意图。')


def _prepare_version(project, prepared_directory, manifest, area):
    """Make and fsync a complete snapshot outside the short commit lock."""
    _validate_manifest(manifest)
    directory = safe_path(project, Path(prepared_directory).relative_to(Path(project).resolve()).as_posix(), area)
    versions = safe_path(project, '.ai-sow-lite/versions')
    versions.mkdir(parents=True, exist_ok=True)
    if directory.stat().st_dev != versions.stat().st_dev:
        raise StorageError('IO_FAILED', '准备目录与 versions 必须在同一文件系统。')
    staging = safe_path(project, area + '/.prepared-' + str(uuid4()))
    staging.mkdir()
    for ref in manifest['files']:
        name = Path(ref['path']).name
        source = safe_path(project, (directory / name).relative_to(Path(project).resolve()).as_posix(), area)
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise StorageError('EVIDENCE_MISSING', '准备文件与 manifest 摘要不同。', ref['path'])
        atomic_bytes(staging / name, raw, immutable=True)
    atomic_bytes(staging / 'manifest.json', canonical_json_bytes(manifest), immutable=True)
    _verify_refs(project, manifest['dependencies'])
    fsync_directory(staging)
    return staging


def _install_version(project, staging, manifest):
    target = safe_path(project, f".ai-sow-lite/versions/{manifest['version_id']}")
    if target.exists():
        actual = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file() and not p.is_symlink()}
        expected = {p.name: p.read_bytes() for p in staging.iterdir()}
        if len(actual) != len(list(target.iterdir())) or actual != expected:
            raise StorageError('IDENTITY_CONFLICT', '已有版本目录内容不同，不能覆盖。')
        import shutil
        shutil.rmtree(staging)
    else:
        os.rename(staging, target)
        fsync_directory(target.parent)
    return target


def _commit_version(project, request_id, entrypoint, prepared_directory, manifest, expected_current):
    """Common storage primitive. Caller must perform business/delivery validation first.

    Unit tests exercise this primitive with controlled bytes, never as Office certification.
    It is not exposed as a CLI bypass.
    """
    project = Path(project).resolve()
    area = request_area(request_id, entrypoint)
    if manifest['request_id'] != request_id:
        raise StorageError('REQUEST_ID_CONFLICT', '准备包请求身份不一致。')
    current, applied = _find_applied(project, request_id)
    if applied is not None:
        _same_intent(applied, manifest)
        return _applied_result(project, applied, current, True)
    ensure_request(project, request_id, entrypoint)
    _check_cancelled(project, request_id, entrypoint)
    if current != expected_current or (entrypoint == 'generate' and expected_current is not None):
        raise StorageError('BASE_STALE', '当前版本与期望基线不同；保留草案。', preserved_paths=[area])
    if manifest['base_version_id'] != (expected_current['version_id'] if expected_current else None):
        raise StorageError('BASE_STALE', 'manifest 基线与期望指针不同。')
    intent_path = area + '/intent.json'
    intent = dict(schema_version='1.0', request_id=request_id, entrypoint=entrypoint,
                  intent_digest=manifest['intent_digest'], expected_current=expected_current)
    if safe_path(project, intent_path).exists():
        if load_json(safe_path(project, intent_path)) != intent:
            raise StorageError('REQUEST_ID_CONFLICT', '请求 ID 已封存不同业务意图或基线。')
    else:
        write_json(project, intent_path, intent, immutable=True)
    staging = _prepare_version(project, prepared_directory, manifest, area)
    pointer = dict(version_id=manifest['version_id'], manifest_hash=file_sha256(staging / 'manifest.json'))
    result = None
    try:
        with commit_lock(project):
            current, applied = _find_applied(project, request_id)
            if applied is not None:
                _same_intent(applied, manifest)
                return _applied_result(project, applied, current, True)
            if load_json(safe_path(project, intent_path)) != intent:
                raise StorageError('REQUEST_ID_CONFLICT', '封存意图已变化。')
            _check_cancelled(project, request_id, entrypoint)
            if current != expected_current:
                raise StorageError('BASE_STALE', '锁内当前版本与期望基线不同。')
            if file_sha256(staging / 'manifest.json') != pointer['manifest_hash']:
                raise StorageError('EVIDENCE_MISSING', '准备 manifest 摘要已变化。')
            for ref in manifest['files']:
                if file_sha256(safe_path(project, (staging / Path(ref['path']).name).relative_to(project).as_posix(), area)) != ref['sha256']:
                    raise StorageError('EVIDENCE_MISSING', '准备文件摘要已变化。')
            _verify_refs(project, manifest['dependencies'])
            _install_version(project, staging, manifest)
            _check_cancelled(project, request_id, entrypoint)
            # The result can be constructed before activation; no subsequent log is authority.
            result = dict(applied_version=manifest['version_id'],
                          manifest_ref=dict(path=f".ai-sow-lite/versions/{manifest['version_id']}/manifest.json", sha256=pointer['manifest_hash']),
                          workbook_ref=next(r for r in manifest['files'] if Path(r['path']).name == 'sow.xlsx'),
                          idempotent=False, current_version=manifest['version_id'])
            replace_current(safe_path(project, '.ai-sow-lite'), pointer)
    except Exception:
        # os.replace may have succeeded before directory flush/unlock/response failed.
        try:
            visible = checked_json(project, '.ai-sow-lite/current.json', 'current')
            if result is not None and visible == pointer:
                _read_version(project, visible)
                return result
        except (OSError, StorageError):
            pass
        raise
    finally:
        if staging.exists():
            import shutil
            shutil.rmtree(staging)
    try:
        return _applied_result(project, manifest, pointer, False)
    except Exception:
        # Activation has already succeeded. Response/log construction is not authority.
        return result


def _verify_delivery(project, prepared):
    """I1.3 seam: executable verifier, never an Agent-authored success flag.

    workbook.verify_prepared(project, prepared) -> {diagnostics: [...]} must
    independently recheck final workbook/projection/Office verification and their
    bindings. It runs outside the commit lock and must not activate or recalculate.
    """
    from importlib import import_module
    try:
        workbook = import_module('.workbook', __package__)
        verifier = workbook.verify_prepared
    except (ModuleNotFoundError, AttributeError):
        error = StorageError('OPERATION_UNSUPPORTED', 'I1.3 实际 Office/投影核验器尚未接入，不能应用准备包。')
        error.diagnostics[0]['target']['field'] = 'verification_ref'
        raise error from None
    report = verifier(project, prepared)
    if (not isinstance(report, dict) or set(report) != {'diagnostics'} or
            not isinstance(report['diagnostics'], list) or any(
                list(schema_validator('artifacts', 'diagnostic').iter_errors(d)) for d in report['diagnostics'])):
        raise StorageError('WORKBOOK_INVALID', '工作簿核验器没有返回有效诊断合同。')
    if report['diagnostics']:
        error = StorageError('WORKBOOK_INVALID', '实际工作簿核验未通过。')
        error.diagnostics = report['diagnostics']
        raise error


def apply_prepared(project: Path, request_id: str, payload):
    """Public apply: full candidate recheck, real I1.3 verifier, then common storage."""
    from .validation import check_candidate
    from .contracts import semantic_digest
    from .changes import checks_match, seal_confirmation, confirmation_files
    if list(schema_validator('protocol', 'apply_payload').iter_errors(payload)):
        raise StorageError('PROTOCOL_INVALID', '应用字段不符合合同。')
    entrypoint = payload['entrypoint']
    if (entrypoint == 'generate') != (payload['plan_path'] is None):
        raise StorageError('SCOPE_EXCEEDED', 'Clarify 需要具体确认方案；Generate 不接受 Clarify 方案。')
    project = Path(project).resolve()
    area = request_area(request_id, payload['entrypoint'])
    current, applied = _find_applied(project, request_id)
    path = safe_path(project, payload['prepared_path'], area)
    application_path = safe_path(project, area + '/application.json')
    if applied is not None and not path.exists():
        # Lost transient work is safe only for the exact, previously sealed invocation.
        if application_path.exists() and load_json(application_path) == payload:
            return _applied_result(project, applied, current, True)
        raise StorageError('REQUEST_ID_CONFLICT', '无法将此调用绑定到已应用请求意图；请 recover 查询事实。')
    prepared = checked_json(project, payload['prepared_path'], 'prepared', area)
    if prepared['expected_current'] != payload['expected_current']:
        raise StorageError('BASE_STALE', '准备包与调用的期望指针不同。')
    for ref in [prepared['candidate_ref'], prepared['check_ref'], prepared['verification_ref'], *prepared['files']]:
        safe_path(project, ref['path'], area)
        _verify_refs(project, [ref])
    candidate_path = safe_path(project, prepared['candidate_ref']['path'], area)
    candidate = checked_json(project, prepared['candidate_ref']['path'], 'candidate', area)
    if candidate['entrypoint'] != entrypoint or candidate['base_version_id'] != (payload['expected_current']['version_id'] if payload['expected_current'] else None):
        raise StorageError('CANDIDATE_INVALID', '候选入口或基线与应用调用不同。')
    if applied is not None and entrypoint == 'clarify':
        if not application_path.exists() or load_json(application_path) != payload or prepared['version_id'] != applied['version_id']:
            raise StorageError('REQUEST_ID_CONFLICT', '已应用请求不能改用不同方案或准备包。')
        archived = {Path(r['path']).name: r for r in applied['files']}
        for name, relative in [('plan.json', payload['plan_path']), ('prepared.json', payload['prepared_path']),
                               ('candidate.json', prepared['candidate_ref']['path'])]:
            if file_sha256(safe_path(project, relative, area)) != archived[name]['sha256']:
                raise StorageError('REQUEST_ID_CONFLICT', '已应用意图对应的文件字节已变化。')
        return _applied_result(project, applied, current, True)
    saved_check = checked_json(project, prepared['check_ref']['path'], 'check', area)
    report = check_candidate(project, candidate_path, 'full', (saved_check.get('plan_ref') or {}).get('path'))
    # A delivered Generate may be retried after Clarify appended input registrations.
    # Its immutable history and semantic intent remain authoritative; the old mutable
    # index snapshot is only a pre-application check, not a reason to reject that fact.
    if not report['valid_for_render'] or (applied is None and not checks_match(project, saved_check, report)):
        error = StorageError('CANDIDATE_INVALID', '候选或实际依赖与完整检查记录不一致。')
        if entrypoint == 'clarify' and report['diagnostics']:
            error.diagnostics = report['diagnostics']
        raise error
    confirmation = seal_confirmation(project, payload['plan_path'], candidate_path) if entrypoint == 'clarify' else None
    if confirmation:
        source = confirmation['input_record']
        confirmation['dependencies'].append(dict(path=source['relative_path'], sha256=source['content_hash']))
    intent = dict(entrypoint=entrypoint, candidate_digest=report['candidate_digest'])
    if confirmation:
        intent.update(plan_digest=confirmation['digest'], base_version_id=candidate['base_version_id'])
    digest = semantic_digest(intent)
    if applied is not None:
        _same_intent(applied, dict(intent_digest=digest))
        return _applied_result(project, applied, current, True)
    if current != payload['expected_current'] or (entrypoint == 'generate') != (current is None):
        raise StorageError('BASE_STALE', '当前完整版本与应用基线不同。')
    ensure_request(project, request_id, entrypoint)
    _check_cancelled(project, request_id, entrypoint)
    if prepared['template_hash'] != candidate['template_hash']:
        raise StorageError('EVIDENCE_MISSING', '准备包与候选模板身份不同。')
    files = {Path(ref['path']).name: ref for ref in prepared['files']}
    if len(files) != len(prepared['files']) or not _CORE_FILES <= files.keys():
        raise StorageError('WORKBOOK_INVALID', '准备包缺少完整文件或有重名文件。')
    for name, key in [('model.json', 'model_path'), ('pending-items.json', 'pending_items_path'), ('decisions.json', 'decisions_path')]:
        if files[name]['sha256'] != file_sha256(safe_path(project, candidate[key], area)):
            raise StorageError('CANDIDATE_INVALID', '输出业务 JSON 必须与候选原字节相同。')
    _verify_delivery(project, prepared)
    # Recheck original bytes after the external verifier, before snapshotting.
    _verify_refs(project, [prepared['candidate_ref'], prepared['check_ref'], *report['dependencies']])
    if confirmation:
        _verify_refs(project, [confirmation['plan_ref'], confirmation['shown_plan_ref'], *confirmation['dependencies']])
    # Snapshot exact validated bytes before taking the lock. Do not bind mutable indexes/work.
    version = prepared['version_id']
    directory = safe_path(project, area + '/.delivery-' + str(uuid4()))
    directory.mkdir()
    final_files = []
    for name, ref in [*files.items(), ('verification.json', prepared['verification_ref'])]:
        raw = safe_path(project, ref['path'], area).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise StorageError('EVIDENCE_MISSING', '核验后准备文件字节已变化。')
        atomic_bytes(directory / name, raw, immutable=True)
        final_files.append(dict(path=f'.ai-sow-lite/versions/{version}/{name}', sha256=ref['sha256']))
    from .inputs import input_index
    adopted_inputs = [e for e in input_index(project)['items'] if e['input_version_id'] in candidate['input_version_ids']]
    raw = canonical_json_bytes(dict(schema_version='1.0', items=adopted_inputs))
    atomic_bytes(directory / 'input-records.json', raw, immutable=True)
    final_files.append(dict(path=f'.ai-sow-lite/versions/{version}/input-records.json', sha256=hashlib.sha256(raw).hexdigest()))
    if confirmation:
        for name, raw in confirmation_files(project, confirmation, prepared['candidate_ref']['path'],
                                             payload['prepared_path'], version).items():
            atomic_bytes(directory / name, raw, immutable=True)
            final_files.append(dict(path=f'.ai-sow-lite/versions/{version}/{name}', sha256=hashlib.sha256(raw).hexdigest()))
    dependencies = [ref for ref in report['dependencies'] if not ref['path'].startswith('.ai-sow-lite/work/')
                    and ref['path'] not in ('.ai-sow-lite/inputs/index.json', '.ai-sow-lite/current.json')]
    if confirmation:
        dependencies.extend(confirmation['dependencies'])
    for entry in adopted_inputs:
        relative = (Path(entry['relative_path']).parent / 'reading-ref.json').as_posix()
        if safe_path(project, relative).exists():
            reading_ref = checked_json(project, relative, 'file_ref')
            dependencies.append(reading_ref)
            reading = checked_json(project, reading_ref['path'], 'reading')
            dependencies.extend(e['file_ref'] for e in reading['excerpts'])
    for topic in candidate['topic_version_ids']:
        relative = f'.ai-sow-lite/analysis/topics/{topic}/registration-ref.json'
        if safe_path(project, relative).exists():
            dependencies.append(checked_json(project, relative, 'file_ref'))
    manifest = dict(schema_version='1.0', version_id=version, request_id=request_id, base_version_id=candidate['base_version_id'],
                    intent_digest=digest, candidate_digest=report['candidate_digest'], files=final_files,
                    input_version_ids=candidate['input_version_ids'], topic_version_ids=candidate['topic_version_ids'],
                    evidence_ids=candidate['evidence_ids'], dependencies=list({r['path']: r for r in dependencies}.values()),
                    template_hash=prepared['template_hash'], projection_version=prepared['projection_version'],
                    office_identity=prepared['office_identity'], verification_ref=next(r for r in final_files if r['path'].endswith('/verification.json')))
    write_json(project, area + '/application.json', payload, immutable=True)
    return _commit_version(project, request_id, entrypoint, directory, manifest, payload['expected_current'])
