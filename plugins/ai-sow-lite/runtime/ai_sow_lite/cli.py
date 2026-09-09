"""One request envelope for actual registration, inspection, checking and storage."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
from uuid import UUID

from .contracts import canonical_json_bytes, load_json, schema_validator
from .validation import check_candidate, diagnostic, project_file
from .project import StorageError


def _response(request, *, result=None, diagnostics=None, ok=False):
    identity = request.get('request_id') if isinstance(request, dict) else None
    try:
        if not isinstance(identity, str) or UUID(identity).version != 4 or str(UUID(identity)) != identity:
            identity = None
    except ValueError:
        identity = None
    operation = request.get('operation') if isinstance(request, dict) else None
    if operation not in ('ingest', 'inspect', 'check', 'render', 'apply', 'recover'):
        operation = None
    return dict(ok=ok, request_id=identity, operation=operation,
                result=result or {}, diagnostics=diagnostics or [])


def _failure(request, code, message, field=None):
    return _response(request, diagnostics=[diagnostic(code, field=field, message=message)])


def _execute(request):
    if isinstance(request, dict) and request.get('protocol_version') not in (None, '1.0'):
        return _failure(request, 'VERSION_INCOMPATIBLE', '未知协议版本。', 'protocol_version')
    if list(schema_validator('protocol').iter_errors(request)):
        return _failure(request, 'PROTOCOL_INVALID', '请求信封或操作字段不符合合同。')
    operation, payload = request['operation'], request['payload']
    if operation == 'apply' and payload:
        from .project import apply_prepared
        return _response(request, result=apply_prepared(Path(request['project_path']).resolve(), request['request_id'], payload), ok=True)
    if operation == 'ingest' and 'entrypoint' in payload:
        if list(schema_validator('protocol', 'ingest_payload').iter_errors(payload)):
            return _failure(request, 'PROTOCOL_INVALID', '输入登记字段不符合合同。')
        if payload['kind'] == 'sources':
            from .inputs import ingest_sources
            result = ingest_sources(Path(request['project_path']).resolve(), request['request_id'], payload)
            return _response(request, result=result, ok=not result['failures'], diagnostics=result['failures'])
        from .inputs import ingest_analysis
        return _response(request, result=ingest_analysis(Path(request['project_path']).resolve(), request['request_id'], payload), ok=True)
    if operation in ('inspect', 'recover') and payload:
        if list(schema_validator('protocol', operation + '_payload').iter_errors(payload)):
            return _failure(request, 'PROTOCOL_INVALID', '查询字段不符合合同。')
        project = Path(request['project_path']).resolve()
        if operation == 'inspect':
            from .inputs import inspect_view
            result = inspect_view(project, payload)
        else:
            from .project import recover_request
            result = recover_request(project, payload['target_request_id'])
        diagnostics = result.pop('diagnostics', [])
        return _response(request, result=result, diagnostics=diagnostics, ok=not diagnostics)
    if operation != 'check' or 'edit_path' in payload or payload.get('plan_path') is not None:
        return _failure(request, 'OPERATION_UNSUPPORTED', '尚未实现此操作，或没有提供受支持的 payload 形式。', 'operation')
    project = Path(request['project_path']).resolve()
    try:
        path = project_file(project, payload['candidate_path'], f".ai-sow-lite/work")
        parts = path.relative_to(project).parts
        if len(parts) < 5 or parts[3] != request['request_id']:
            raise ValueError('request ownership')
    except (ValueError, OSError, RuntimeError):
        return _failure(request, 'CANDIDATE_INVALID', '候选必须属于本项目、本请求的 work 目录。', 'candidate_path')
    report = check_candidate(project, path, payload['scope'], None)
    content = canonical_json_bytes(report)
    digest = hashlib.sha256(content).hexdigest()
    area = '/'.join(parts[:4])
    destination = project_file(project, f'{area}/checks/{digest}.json', area)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = project_file(project, f'{area}/checks/{digest}.json', area)
    try:
        with destination.open('xb') as stream:
            stream.write(content)
    except FileExistsError:
        if destination.read_bytes() != content:
            return _failure(request, 'IO_FAILED', '已有报告字节不一致，未覆盖文件。')
    result = dict(check_ref=dict(path=destination.relative_to(project).as_posix(), sha256=digest),
                  candidate_ref=report['candidate_ref'], plan_ref=None, review_ref=None,
                  candidate_digest=report['candidate_digest'], valid_for_render=report['valid_for_render'],
                  unknowns_count=report['unknowns_count'])
    return _response(request, ok=not report['diagnostics'], result=result, diagnostics=report['diagnostics'])


def execute(request):
    """Return the CLI response; expected and unexpected failures stay redacted."""
    try:
        return _execute(request)
    except StorageError as error:
        return _response(request, diagnostics=error.diagnostics)
    except OSError:
        return _failure(request, 'IO_FAILED', '本地文件读写失败；保留现有文件。')
    except (ValueError, RuntimeError):
        return _failure(request, 'CANDIDATE_INVALID', '候选路径或内容不符合合同。')
    except Exception:
        return _failure(request, 'INTERNAL_ERROR', '工具发生未预期错误；未应用任何版本。')


def exit_code(response):
    if response['ok']:
        return 0
    codes = {item['code'] for item in response['diagnostics']}
    if 'INTERNAL_ERROR' in codes:
        return 1
    if codes & {'IO_FAILED', 'WRITE_BUSY', 'INPUT_UNAVAILABLE', 'CALCULATION_FAILED', 'WORKBOOK_INVALID'}:
        return 3
    if 'REQUEST_CANCELLED' in codes:
        return 4
    return 2


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid CLI arguments')


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    parser = _Parser(add_help=False)
    parser.add_argument('--request', required=True)
    request = None
    try:
        args = parser.parse_args(argv)
        request = load_json(Path(args.request))
        response = execute(request)
    except OSError:
        response = _failure(request, 'IO_FAILED', '请求文件不可读取。')
    except (ValueError, UnicodeError):
        response = _failure(request, 'PROTOCOL_INVALID', '需要 --request 和严格 UTF-8 JSON 请求文件。')
    print(canonical_json_bytes(response).decode('utf-8'))
    return exit_code(response)
