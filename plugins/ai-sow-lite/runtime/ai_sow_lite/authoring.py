"""Small Python client for caller-selected operations; no workflow or semantic decisions."""
from copy import deepcopy
from pathlib import Path

from .cli import execute
from .contracts import load_json
from .project import StorageError, ensure_request, file_ref, request_area, safe_path, write_json


def source_ref(region_result):
    """Map an actual region result, preserving the XLSX read identity when present."""
    coverage = region_result['coverage']
    selector = coverage['selector']
    locator = coverage['locator'] if selector['locator']['kind'] == 'xlsx_range' else selector['locator']
    return deepcopy(dict(input_version_id=selector['input_version_id'], locator=locator,
                         excerpt_hash=coverage['excerpt_hash']))


class OperationError(RuntimeError):
    """Stop the caller's batch and retain the complete original diagnostic response."""

    def __init__(self, response):
        self.response = response
        super().__init__('; '.join(item['code'] + ': ' + item['message']
                                  for item in response['diagnostics']))


class Client:
    def __init__(self, project, request_id, entrypoint, *, observation_context=None):
        self.project = Path(project).resolve()
        self.request_id = request_id
        self.entrypoint = entrypoint
        self.area = request_area(request_id, entrypoint)
        self.observation_context = deepcopy(observation_context)

    def call(self, operation, payload):
        """Execute exactly one existing operation, returning its result or raising."""
        if 'entrypoint' in payload and payload['entrypoint'] != self.entrypoint:
            raise StorageError('REQUEST_ID_CONFLICT', '同一客户端不能改变请求入口。')
        request = dict(protocol_version='1.0', request_id=self.request_id,
                       project_path=str(self.project), operation=operation, payload=payload)
        if self.observation_context is not None:
            request['observation_context'] = deepcopy(self.observation_context)
        response = execute(request)
        if not response['ok']:
            raise OperationError(response)
        return response['result']

    def save(self, name, value):
        """Save caller-authored JSON without overwriting core state or an earlier draft."""
        if not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\\' in name:
            raise StorageError('PATH_UNSAFE', '草稿只接受一个文件名，不能包含目录。')
        if not safe_path(self.project, self.area + '/request.json').is_file():
            raise StorageError('CHECKPOINT_UNKNOWN', '先完成输入登记，再保存本请求草稿。')
        ensure_request(self.project, self.request_id, self.entrypoint)
        return write_json(self.project, self.area + '/authoring/' + name, value, immutable=True)

    def mark(self, name, phase):
        """Observe a real boundary, using current labels; never infer or advance business state."""
        from .telemetry import record_mark
        context = self.observation_context if isinstance(self.observation_context, dict) else {}
        return record_mark(self.project, dict(schema_version='1.0', request_id=self.request_id,
            execution_id=context.get('execution_id'), name=name, phase=phase,
            activity_ids=[] if name == 'request' else context.get('activity_ids', []),
            slice_ids=[] if name == 'request' else context.get('slice_ids', [])))

    def bind_confirmation(self, check_ref, answer_ref):
        """Attach the caller-recognized real answer; the existing check still validates it.

        This does not infer consent, ingest an answer, validate business intent, or apply.
        """
        if self.entrypoint != 'clarify' or answer_ref['locator']['kind'] != 'text_lines':
            raise StorageError('CONFIRMATION_INVALID', '确认需使用本次 Clarify 实际执行答复的文本区域。')

        def verified(ref):
            path = safe_path(self.project, ref['path'], self.area)
            if file_ref(self.project, path) != ref:
                raise StorageError('EVIDENCE_CHANGED', '展示工件已变化；不能绑定旧确认。', ref['path'])
            return path, load_json(path)

        _, report = verified(check_ref)
        if not report.get('valid_for_render') or not report.get('plan_ref'):
            raise StorageError('CONFIRMATION_INVALID', '需要成功检查的具体方案。')
        shown_ref = report['plan_ref']
        shown_path, plan = verified(shown_ref)
        if plan['confirmation'] is not None:
            raise StorageError('CONFIRMATION_INVALID', '使用原展示计划；不能替换已有确认。')
        plan['confirmation'] = dict(digest=report['plan_digest'], input_ref=deepcopy(answer_ref),
            shown_plan_ref=plan.get('subset_of', shown_ref), selected_changes=deepcopy(plan['changes']))
        relative = shown_path.with_name('confirmed-plan.json').relative_to(self.project).as_posix()
        return write_json(self.project, relative, plan, immutable=True)
