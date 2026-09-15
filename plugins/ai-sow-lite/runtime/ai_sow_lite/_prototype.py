"""Bounded physical prototype packages and immutable supplied observations.

No execution, browser discovery, dependency installation or semantic judgments.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from uuid import uuid4

from .contracts import canonical_json_bytes, schema_validator, strict_json_loads
from .project import StorageError, atomic_bytes, checked_json, file_ref, safe_path, write_json

MAX_MEMBERS = 2048  # Includes directories, even empty ones.
MAX_DEPTH = 16
MAX_BYTES = 50 * 1024 * 1024
MAX_OBSERVATION_BYTES = 1024 * 1024
MAX_ATTACHMENTS = 64
TEXT_SUFFIXES = {'.html', '.htm', '.js', '.mjs', '.css', '.json', '.svg', '.md', '.markdown', '.txt'}
READER_VERSION = 'lite-prototype-v1'
LIMITATIONS = ['仅枚举资源并读取可解码源码；未执行原型或观察浏览器状态。',
               '二进制资源只保留原字节；源码、模拟数据和本地成功不能证明真实后端或生产能力。']


def _name(value):
    pure = PurePosixPath(value)
    if (not value or pure.is_absolute() or str(pure) != value or '..' in pure.parts or
            value == '.' or any(c in value for c in ('\\', ':')) or
            any(ord(c) < 32 for c in value) or len(value.encode('utf-8')) > 1024):
        raise StorageError('PATH_UNSAFE', '资源名必须是规范包内相对路径；不能含跳转、冒号或控制字符。')
    return value


def _read(path, limit=MAX_BYTES, *, dir_fd=None, snapshot=None):
    """Open regular bytes only; a FIFO must never block, links must never be followed."""
    before = snapshot if snapshot is not None else os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or getattr(before, 'st_file_attributes', 0) & 0x400:
        raise StorageError('PATH_UNSAFE', '资源或附件必须是普通文件，不能使用链接或特殊文件。')
    if before.st_size > limit:
        raise StorageError('RESULT_TOO_LARGE', '资源或附件超过读取体积上限；请缩小所提供范围。')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), dir_fd=dir_fd)
    with os.fdopen(descriptor, 'rb') as stream:
        actual = os.fstat(stream.fileno())
        if not stat.S_ISREG(actual.st_mode) or (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino):
            raise StorageError('PATH_UNSAFE', '资源读取期间身份发生变化。')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > limit:
        raise StorageError('RESULT_TOO_LARGE', '资源或附件超过读取体积上限；请缩小所提供范围。')
    if (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise StorageError('INPUT_UNAVAILABLE', '资源读取期间字节发生变化；请使用稳定副本。')
    return raw


@contextmanager
def _directory(path, snapshot, *, dir_fd=None):
    """Pin the checked directory itself; descendants only open relative to this fd."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        actual = os.fstat(descriptor)
        if (not stat.S_ISDIR(actual.st_mode) or getattr(actual, 'st_file_attributes', 0) & 0x400 or
                (snapshot.st_dev, snapshot.st_ino) != (actual.st_dev, actual.st_ino)):
            raise StorageError('PATH_UNSAFE', '原型目录打开期间身份发生变化；请使用稳定目录副本。')
        yield descriptor
    finally:
        os.close(descriptor)


def read_package(path):
    """Enumerate and open members through verified directory fds, never ancestor paths."""
    if (os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd or
            os.stat not in os.supports_follow_symlinks or os.scandir not in os.supports_fd or
            not all(getattr(os, flag, 0) for flag in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_NONBLOCK'))):
        raise StorageError('OPERATION_UNSUPPORTED', '此平台缺少原型目录 fd/no-follow 安全读取能力；不能登记原型包。')
    root = Path(path).absolute()
    state = root.lstat()
    if not stat.S_ISDIR(state.st_mode) or getattr(state, 'st_file_attributes', 0) & 0x400:
        raise StorageError('PATH_UNSAFE', '原型须提供实际目录资源包，不能使用链接。')
    members, contents, total = 0, {}, 0

    def visit(directory_fd, prefix):
        nonlocal members, total
        with os.scandir(directory_fd) as entries:
            for item in entries:
                members += 1
                name = _name(prefix + item.name)
                if members > MAX_MEMBERS or len(PurePosixPath(name).parts) > MAX_DEPTH:
                    raise StorageError('RESULT_TOO_LARGE', f'原型包超过{MAX_MEMBERS}成员或{MAX_DEPTH}层上限；请提供较小资源包。')
                snapshot = os.stat(item.name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(snapshot.st_mode) or getattr(snapshot, 'st_file_attributes', 0) & 0x400:
                    raise StorageError('PATH_UNSAFE', f'包内成员不能使用链接：{name}。')
                if stat.S_ISDIR(snapshot.st_mode):
                    with _directory(item.name, snapshot, dir_fd=directory_fd) as child_fd:
                        visit(child_fd, name + '/')
                elif stat.S_ISREG(snapshot.st_mode):
                    raw = _read(item.name, MAX_BYTES - total, dir_fd=directory_fd, snapshot=snapshot)
                    total += len(raw)
                    contents[name] = raw
                else:
                    raise StorageError('PATH_UNSAFE', f'包内成员不是普通文件或目录：{name}。')

    try:
        # O_NOFOLLOW applies to the explicit root too; /var's ancestor OS alias is allowed.
        with _directory(root, state) as root_fd:
            visit(root_fd, '')
    except NotImplementedError:
        raise StorageError('OPERATION_UNSUPPORTED', '此平台不能执行原型目录 fd/no-follow 读取；不能登记原型包。') from None
    if not contents:
        raise StorageError('INPUT_UNAVAILABLE', '原型包没有普通资源文件；请提供包含入口和资源的目录。')
    resources = [dict(path=name, sha256=hashlib.sha256(contents[name]).hexdigest()) for name in sorted(contents)]
    return resources, contents


def resource_ref(entry, resource):
    area = str(PurePosixPath(entry['relative_path']).parent)
    return dict(path=area + '/resources/' + _name(resource['path']), sha256=resource['sha256'])


def checked_package(project, entry):
    """Verify the canonical manifest and every retained member, including unused assets."""
    area = f".ai-sow-lite/inputs/originals/{entry['input_version_id']}"
    try:
        resources = entry['resources']
        names = [_name(r['path']) for r in resources]
        if (entry['relative_path'] != area + '/manifest.json' or not resources or
                names != sorted(set(names)) or len(resources) > MAX_MEMBERS):
            raise ValueError('manifest identity')
        manifest = safe_path(project, entry['relative_path'], area)
        raw = _read(manifest)
        if raw != canonical_json_bytes(resources) or hashlib.sha256(raw).hexdigest() != entry['content_hash']:
            raise ValueError('manifest bytes')
        root = safe_path(project, area + '/resources', area)
        observed, contents = read_package(root)
        if observed != resources:
            raise ValueError('resource bytes or members')
        return raw, [dict(path=entry['relative_path'], sha256=entry['content_hash']),
                     *[resource_ref(entry, r) for r in resources]], contents
    except (OSError, KeyError, ValueError) as error:
        if isinstance(error, StorageError) and error.diagnostics[0]['code'] == 'RESULT_TOO_LARGE':
            raise
        raise StorageError('EVIDENCE_MISSING', '原型清单或资源缺失、变化、越界或重定向；请恢复对应不可变版本。', entry['relative_path']) from None


def source_lines(contents, locator):
    name = locator.get('path')
    if not name or _name(name) not in contents:
        raise StorageError('EVIDENCE_MISSING', '原型文本定位必须精确给出已登记包内路径。')
    if Path(name).suffix.lower() not in TEXT_SUFFIXES:
        raise StorageError('FORMAT_UNSUPPORTED', '此资源只保存字节；请选择可直接读取的 HTML/JS/CSS/JSON/SVG 或文本源码。')
    try:
        raw = contents[name]
        if b'\x00' in raw:
            raise UnicodeError('binary')
        lines = raw.decode('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8').splitlines(keepends=True)
    except UnicodeError:
        raise StorageError('INPUT_UNAVAILABLE', '资源不能按 UTF-8 严格解码；原字节保留，不能声称已读内容。', name) from None
    start, end = locator['start_line'], locator['end_line']
    if not 1 <= start <= end <= len(lines):
        raise StorageError('EVIDENCE_MISSING', '原型文本行范围超出实际资源。', name)
    return lines[start - 1:end]


def ingest_package(project, index, source):
    resources, contents = read_package(source['source_path'])
    raw = canonical_json_bytes(resources)
    digest = hashlib.sha256(raw).hexdigest()
    for region in source['use_regions']:
        if region['material_type'] not in source['material_types'] or region['use'] not in source['uses']:
            raise StorageError('CANDIDATE_INVALID', '用途区域必须属于所声明的角色与用途。')
        for locator in region['locators']:
            if locator['kind'] != 'text_lines':
                raise StorageError('EVIDENCE_MISSING', '目录包用途登记仅接收精确源码 text_lines 定位；观察在分析中采用。')
            source_lines(contents, locator)
    logical = source['input_id']
    if logical is not None and not any(e['input_id'] == logical for e in index['items']):
        raise StorageError('INPUT_ID_CONFLICT', '指定 input_id 未登记；首次登记必须为 null。')
    entry = next((e for e in index['items'] if e['format'] == 'prototype' and e['content_hash'] == digest and
                  logical in (None, e['input_id'])), None)
    if entry is None:
        identity = str(uuid4())
        area = f'.ai-sow-lite/inputs/originals/{identity}'
        entry = dict(input_version_id=identity, input_id=logical or str(uuid4()), content_hash=digest,
                     relative_path=area + '/manifest.json', format='prototype', resources=resources,
                     material_types=[], uses=[], use_regions=[])
        for resource in resources:
            target = resource_ref(entry, resource)
            atomic_bytes(safe_path(project, target['path'], area), contents[resource['path']], immutable=True)
        atomic_bytes(safe_path(project, entry['relative_path'], area), raw, immutable=True)
        index['items'].append(entry)
    checked_package(project, entry)
    for key in ('material_types', 'uses', 'use_regions'):
        entry[key].extend(v for v in source[key] if v not in entry[key])
    return entry


def reading(project, entry):
    checked_package(project, entry)
    area = f".ai-sow-lite/inputs/originals/{entry['input_version_id']}"
    registration = area + '/reading-ref.json'
    if safe_path(project, registration).exists():
        ref = checked_json(project, registration, 'file_ref', area)
        data = checked_json(project, ref['path'], 'reading', '.ai-sow-lite/inputs/readings')
        if (file_ref(project, safe_path(project, ref['path'])) != ref or data['input_version_id'] != entry['input_version_id'] or
                data['content_hash'] != entry['content_hash'] or data['adapter_version'] != READER_VERSION or
                data.get('directory_ref') != dict(path=entry['relative_path'], sha256=entry['content_hash']) or
                data['options'] != {} or data['excerpts'] != []):
            raise StorageError('EVIDENCE_MISSING', '原型 reading 与清单或来源身份不一致。')
        return ref
    identity = str(uuid4())
    data = dict(schema_version='1.0', read_id=identity, input_version_id=entry['input_version_id'],
                content_hash=entry['content_hash'], adapter_version=READER_VERSION, options={}, excerpts=[],
                directory_ref=dict(path=entry['relative_path'], sha256=entry['content_hash']))
    ref = write_json(project, f'.ai-sow-lite/inputs/readings/{identity}/reading.json', data, immutable=True)
    write_json(project, registration, ref, immutable=True)
    return ref


def _ref_bytes(project, ref, area, limit=MAX_BYTES):
    try:
        raw = _read(safe_path(project, ref['path'], area), limit)
        if hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('digest')
        return raw
    except (OSError, ValueError):
        raise StorageError('EVIDENCE_MISSING', '观察记录或附件缺失、摘要变化、越界或重定向。', ref['path']) from None


def _observation(raw):
    try:
        record = strict_json_loads(raw)
        if list(schema_validator('artifacts', 'observation').iter_errors(record)):
            raise ValueError('schema')
        if len(record['attachments']) > MAX_ATTACHMENTS or len(record['resource_refs']) > MAX_MEMBERS:
            raise ValueError('members')
        for key in ('attachments', 'resource_refs'):
            paths = [r['path'] for r in record[key]]
            if len(paths) != len(set(paths)):
                raise ValueError('duplicate refs')
        return record
    except (ValueError, UnicodeError):
        raise StorageError('EVIDENCE_MISSING', '观察记录结构无效、附件超过64项或引用重复；请提供现有 observation 合同。') from None


def attachment_refs(record):
    area = f".ai-sow-lite/analysis/observations/{record['observation_id']}/attachments"
    return [dict(path=f"{area}/{n}/{_name(PurePosixPath(r['path']).name)}", sha256=r['sha256'])
            for n, r in enumerate(record['attachments'])]


def _observation_resources(project, record, inputs):
    entry = inputs.get(record['input_version_id'])
    if entry is None or entry['format'] != 'prototype':
        raise StorageError('EVIDENCE_MISSING', '观察必须绑定已登记并采用的原型 input_version_id。')
    _, dependencies, _ = checked_package(project, entry)
    for ref in record['resource_refs']:
        if ref not in dependencies[1:]:
            raise StorageError('EVIDENCE_MISSING', '观察资源引用不属于此原型版本或摘要不同。', ref['path'])
    return dependencies


def checked_observation(project, ref, inputs):
    raw = _ref_bytes(project, ref, '.ai-sow-lite/analysis/observations', MAX_OBSERVATION_BYTES)
    record = _observation(raw)
    area = f".ai-sow-lite/analysis/observations/{record['observation_id']}"
    if ref['path'] != area + '/observation.json':
        raise StorageError('EVIDENCE_MISSING', '观察路径与 observation_id 不一致。')
    registration = checked_json(project, area + '/registration-ref.json', 'file_ref', area)
    if registration != ref:
        raise StorageError('EVIDENCE_MISSING', '观察摘要与不可变登记不同。')
    dependencies = _observation_resources(project, record, inputs)
    total = 0
    for attachment in attachment_refs(record):
        total += len(_ref_bytes(project, attachment, area, MAX_BYTES - total))
        dependencies.append(attachment)
    return raw, record, [ref, file_ref(project, safe_path(project, area + '/registration-ref.json')), *dependencies]


def register_observations(project, refs, inputs, work_area):
    """Preflight all supplied records before copying; preserve original JSON bytes.

Attachment source refs stay in the original record. Their immutable copy locations
are derived from observation_id + original ordered attachment index + basename.
"""
    normalized, pending, identities = [], [], {}
    for ref in refs:
        if ref['path'].startswith('.ai-sow-lite/analysis/observations/'):
            raw, record, _ = checked_observation(project, ref, inputs)
        else:
            raw = _ref_bytes(project, ref, work_area, MAX_OBSERVATION_BYTES)
            record = _observation(raw)
            _observation_resources(project, record, inputs)
        area = f".ai-sow-lite/analysis/observations/{record['observation_id']}"
        stable = dict(path=area + '/observation.json', sha256=ref['sha256'])
        previous = identities.get(record['observation_id'])
        if previous is not None and previous != stable:
            raise StorageError('IDENTITY_CONFLICT', '同一 observation_id 不能登记不同原字节。')
        identities[record['observation_id']] = stable
        exists = safe_path(project, stable['path'], area).exists()
        if exists:
            if _read(safe_path(project, stable['path'], area), MAX_OBSERVATION_BYTES) != raw:
                raise StorageError('IDENTITY_CONFLICT', '同一 observation_id 已有不同原字节；不能覆盖。')
            checked_observation(project, stable, inputs)
        else:
            copies, total = [], 0
            for original, target in zip(record['attachments'], attachment_refs(record)):
                content = _ref_bytes(project, original, work_area, MAX_BYTES - total)
                total += len(content)
                copies.append((target, content))
            pending.append((stable, raw, copies))
        if stable not in normalized:
            normalized.append(stable)
    for stable, raw, copies in pending:
        area = str(PurePosixPath(stable['path']).parent)
        for target, content in copies:
            atomic_bytes(safe_path(project, target['path'], area), content, immutable=True)
        atomic_bytes(safe_path(project, stable['path'], area), raw, immutable=True)
        write_json(project, area + '/registration-ref.json', stable, immutable=True)
    return normalized


def observation_excerpt(project, entry, locator):
    area = f".ai-sow-lite/analysis/observations/{locator['observation_id']}"
    try:
        ref = checked_json(project, area + '/registration-ref.json', 'file_ref', area)
        raw, record, dependencies = checked_observation(project, ref, {entry['input_version_id']: entry})
        if record['observation_id'] != locator['observation_id']:
            raise ValueError('identity')
        if 'attachment' in locator and locator['attachment'] not in [r['path'] for r in record['attachments']] + [r['path'] for r in attachment_refs(record)]:
            raise ValueError('attachment not listed')
        return raw, record, dependencies
    except (OSError, ValueError):
        raise StorageError('EVIDENCE_MISSING', '观察未登记、输入版本不匹配、附件缺失或定位无效。') from None


def topic_observations(project, refs, topic):
    """Retain the observations of this topic's adopted input versions when splitting."""
    return [ref for ref in refs if _observation(_ref_bytes(
        project, ref, '.ai-sow-lite/analysis/observations', MAX_OBSERVATION_BYTES))['input_version_id'] in topic['input_version_ids']]


def registered_observations(project, registration, topic):
    """Expected observation refs of a topic, derived only from its registration.

    Never reads the record being verified. The observation store is keyed by
    observation_id, which the observation bytes themselves carry, so a content
    digest names exactly one immutable copy; selection then applies the same
    adopted-input rule registration applied when it split the topic.
    """
    if not registration['observations']:
        return []
    required = {ref['sha256'] for ref in registration['observations']}
    store = safe_path(project, '.ai-sow-lite/analysis/observations')
    owned = {}
    if store.exists():
        for directory in sorted(store.iterdir()):
            if not directory.is_dir():
                continue
            area = f'.ai-sow-lite/analysis/observations/{directory.name}'
            try:
                held = checked_json(project, area + '/registration-ref.json', 'file_ref', area)
            except (OSError, ValueError):
                # An unfinished/invalid lookup entry cannot establish provenance.
                # Any required digest still missing below will refuse the proof.
                continue
            if held['sha256'] not in required:
                continue
            if held['path'] != area + '/observation.json':
                raise StorageError('EVIDENCE_MISSING', '观察登记引用与其身份目录不一致。')
            record = _observation(_ref_bytes(project, held, area, MAX_OBSERVATION_BYTES))
            if record['observation_id'] != directory.name:
                raise StorageError('EVIDENCE_MISSING', '观察副本与其身份目录不一致。')
            owned[held['sha256']] = (held, record['input_version_id'])
    expected = []
    for ref in registration['observations']:
        if ref['sha256'] not in owned:
            raise StorageError('EVIDENCE_MISSING', '登记声明的观察缺少对应不可变副本。')
        stable, input_version = owned[ref['sha256']]
        if input_version in topic['input_version_ids'] and stable not in expected:
            expected.append(stable)
    return expected


def topic_dependencies(project, version, analysis):
    """Bind stored split topics to the original registration without retaining a mutable index."""
    area = f'.ai-sow-lite/analysis/topics/{version}'
    try:
        index = checked_json(project, '.ai-sow-lite/analysis/index.json', 'analysis_index')
        refs = [ref for ref in index['items'] if ref['path'] == area + '/analysis.json']
        if len(refs) != 1:
            raise ValueError('topic registration')
        _ref_bytes(project, refs[0], area)
        registration_path = area + '/registration-ref.json'
        registration = checked_json(project, registration_path, 'file_ref', area)
        original = strict_json_loads(_ref_bytes(project, registration, '.ai-sow-lite/analysis/registrations'))
        if list(schema_validator('artifacts', 'analysis').iter_errors(original)):
            raise ValueError('analysis schema')
        # The observation set is derived from the registration, never taken from the
        # record under test: a subset check accepts a record with observations removed.
        if (analysis['evidence'] != original['evidence'] or len(analysis['topics']) != 1 or
                analysis['topics'][0] not in original['topics'] or
                analysis['observations'] != registered_observations(project, original, analysis['topics'][0])):
            raise ValueError('split provenance')
        return [refs[0], registration, file_ref(project, safe_path(project, registration_path, area))]
    except (OSError, ValueError, KeyError):
        raise StorageError('EVIDENCE_MISSING', '分析主题未登记、原字节变化或与原始分析来源不一致。', area + '/analysis.json') from None
