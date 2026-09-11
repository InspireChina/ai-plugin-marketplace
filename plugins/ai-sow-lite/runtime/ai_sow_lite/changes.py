"""Finite, stable-address edits over one immutable base; no professional inference."""
from copy import deepcopy
import json
from pathlib import Path

from .contracts import canonical_json_bytes, load_json, schema_validator, semantic_digest
from .project import (StorageError, atomic_bytes, checked_json, ensure_request, file_ref,
                      read_current, request_area, safe_path, save_checkpoint, write_json)

COLLECTIONS = ('epics', 'features', 'stories', 'acs', 'tasks', 'dependencies', 'lineage',
               'pending_items', 'decisions', 'input_refs', 'topic_refs', 'evidence_refs')
REFS = dict(input_refs='input_version_ids', topic_refs='topic_version_ids', evidence_refs='evidence_ids')
FILES = {'model.json': 'model_path', 'pending-items.json': 'pending_items_path', 'decisions.json': 'decisions_path'}
PLAN_CONTENT = ('plan_id', 'revision', 'base_version_id', 'changes', 'read_set', 'write_set',
                'read_boundary', 'conditions', 'unresolved_items', 'change_summary')


def plan_digest(plan):
    content = {key: plan[key] for key in PLAN_CONTENT}
    if 'subset_of' in plan:
        content['subset_of'] = plan['subset_of']
    return semantic_digest(content)


def _identity(collection, item):
    if collection in REFS:
        return item
    if collection == 'lineage':
        return canonical_json_bytes([item['from_version_id'], item['from_ids']]).decode('utf-8')
    return item['id']


def _members(bundle, collection):
    if collection == 'acs':
        return [ac for story in bundle.get('stories', []) for ac in story['acs']]
    return bundle.get(collection, [])


def diff_bundle(before, after):
    """Actual values in display order; addresses never depend on Excel positions."""
    changes = []
    for collection in COLLECTIONS:
        old = {_identity(collection, item): item for item in _members(before, collection)}
        new = {_identity(collection, item): item for item in _members(after, collection)}
        for identity in dict.fromkeys([*old, *new]):
            a, b = old.get(identity), new.get(identity)
            if collection == 'acs' and a is not None and b is not None:
                parents = [next(s['id'] for s in bundle['stories'] if any(ac['id'] == identity for ac in s['acs']))
                           for bundle in (before, after)]
                if parents[0] != parents[1]:
                    changes.extend([dict(op='remove', collection='acs', object_id=identity, field=None, before=a, after=None),
                                    dict(op='add', collection='acs', object_id=identity, field=None, before=None, after=b)])
                    continue
            if a == b:
                continue
            if a is None or b is None:
                changes.append(dict(op='add' if a is None else 'remove', collection=collection,
                                    object_id=identity, field=None, before=a, after=b))
            else:
                for field in dict.fromkeys([*a, *b]):
                    if field not in a or field not in b or a[field] != b[field]:
                        op = 'add' if field not in a else 'remove' if field not in b else 'replace'
                        changes.append(dict(op=op, collection=collection, object_id=identity,
                                            field=field, before=a.get(field), after=b.get(field)))
    return changes


def _bundle(model, pending, decisions, refs):
    return dict(model, pending_items=pending['items'], decisions=decisions['items'],
                **{collection: refs[key] for collection, key in REFS.items()})


def _documents(bundle):
    return [dict((key, value) for key, value in bundle.items() if key not in (*REFS, 'pending_items', 'decisions')),
            dict(schema_version='1.0', items=bundle['pending_items']),
            dict(schema_version='1.0', items=bundle['decisions'])]


def _base(project, version):
    current, manifest = read_current(project)
    if current is None or current['version_id'] != version:
        raise StorageError('BASE_STALE', '当前完整版本已不同于方案基线；保留草案。')
    files = {Path(ref['path']).name: ref for ref in manifest['files']}
    raw = {name: safe_path(project, files[name]['path']).read_bytes() for name in FILES}
    from .contracts import strict_json_loads
    values = [strict_json_loads(raw[name]) for name in FILES]
    return current, manifest, raw, _bundle(*values, manifest)


def _read_set(project, selectors):
    from .inputs import inspect_view
    result = []
    for selector in selectors:
        observed = inspect_view(project, dict(selector, limit=100, cursor=None))
        result.append(dict(selector=selector, observed_version=observed['selected_version']))
    return result


def _write_set(changes):
    result = []
    for item in changes:
        address = dict(collection=item['collection'], object_id=item['object_id'], field=item['field'])
        if address not in result:
            result.append(address)
        if item['collection'] == 'stories' and item['field'] is None:
            result.append(dict(address, field='acs'))
    return result


def _selectors(draft, changes):
    selectors = deepcopy(draft['read_selectors'])
    # These are structural containers of embedded ACs, not inferred business dependencies.
    for change in changes:
        if change['collection'] == 'stories' and change['field'] in ('acs', None):
            selected = dict(view='objects', selector=dict(collection='stories', object_ids=[change['object_id']]))
            if selected not in selectors:
                selectors.append(selected)
    return selectors


def _apply_edits(before, edits):
    from .validation import diagnostic
    after = deepcopy(before)
    errors, seen = [], set()
    for edit in edits:
        collection, identity, field = (edit[key] for key in ('collection', 'object_id', 'field'))
        address = (collection, identity, field)
        def fail(message):
            from uuid import UUID
            try:
                object_id = identity if UUID(identity).version == 4 else None
            except ValueError:
                object_id = None
            errors.append(diagnostic('SCOPE_EXCEEDED', object_id=object_id, field=field, message=message))
        if collection == 'acs' or collection in REFS:
            fail('AC 通过父 Story.acs 编辑；新增采用引用只通过 additional_refs。')
            continue
        if address in seen or (collection, identity, None) in seen or (field is None and any(a[:2] == address[:2] for a in seen)):
            fail('同一地址重复编辑，或完整对象与字段编辑交叠。')
            continue
        seen.add(address)
        item = next((obj for obj in _members(after, collection) if _identity(collection, obj) == identity), None)
        op, value = edit['op'], deepcopy(edit.get('value'))
        if field is None:
            if op == 'replace' or (op == 'add') == (item is not None):
                fail('完整对象只允许明确新增或删除，身份必须与操作相符。')
                continue
            if op == 'remove':
                after[collection].remove(item)
            else:
                try:
                    if not isinstance(value, dict) or _identity(collection, value) != identity:
                        raise ValueError('identity')
                except (KeyError, ValueError):
                    fail('新增对象必须提供完整内容和相同稳定身份。')
                    continue
                parent = {'features': 'epic_id', 'stories': 'feature_id', 'tasks': 'story_id'}.get(collection)
                siblings = [n for n, obj in enumerate(after[collection]) if parent and obj.get(parent) == value.get(parent)]
                after[collection].insert(siblings[-1] + 1 if siblings else len(after[collection]), value)
        elif item is None or field == 'id' or (op == 'add' and field in item) or (op != 'add' and field not in item):
            fail('编辑必须指向明确的已有对象，字段存在性须与操作相符。')
        elif op == 'remove':
            del item[field]
        else:
            item[field] = value
    if not errors:
        for name, document in zip(('model', 'pending-items', 'decisions'), _documents(after)):
            for error in schema_validator(name).iter_errors(document):
                field = next((part for part in reversed(error.absolute_path) if isinstance(part, str)), None)
                errors.append(diagnostic('CANDIDATE_INVALID', field=field, message='明确编辑后的字段类型或结构不符合业务合同。'))
    if errors:
        error = StorageError('SCOPE_EXCEEDED', '有限编辑存在结构错误或越界。')
        error.diagnostics = errors[:64]
        raise error
    # Reject reordering of surviving siblings, including embedded ACs.
    pairs = [(before.get(c, []), after.get(c, []), c) for c in COLLECTIONS if c != 'acs']
    new_stories = {s['id']: s for s in after.get('stories', [])}
    pairs += [(s['acs'], new_stories[s['id']]['acs'], 'acs') for s in before.get('stories', []) if s['id'] in new_stories]
    for old, new, collection in pairs:
        try:
            a = [_identity(collection, v) for v in old]
            b = [_identity(collection, v) for v in new]
        except (KeyError, TypeError):
            continue  # Full schemas diagnose malformed explicit values.
        if [i for i in a if i in b] != [i for i in b if i in a]:
            errors.append(diagnostic('SCOPE_EXCEEDED', field=collection, message='不能重排既有对象或 AC 的相对顺序。'))
    if errors:
        error = StorageError('SCOPE_EXCEEDED', '有限编辑存在越界。')
        error.diagnostics = errors[:64]
        raise error
    return after


def _encoded(value, original):
    """Rewrite changed JSON values while retaining untouched token spans and layout.

    Internal document encoding only: callers still supply finite domain edits,
    never paths, indices or arbitrary JSON patches.
    """
    from .contracts import strict_json_loads
    before = strict_json_loads(original)
    if before == value:
        return original
    text, decoder = original.decode('utf-8'), json.JSONDecoder()
    def skip(pos):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        return pos
    def encode(old, new, start, end):
        if old == new:
            return text[start:end]
        if not isinstance(old, (dict, list)) or type(old) is not type(new):
            return canonical_json_bytes(new).decode('utf-8')
        members, pos = [], skip(start + 1)
        for key, child in (old.items() if isinstance(old, dict) else enumerate(old)):
            begin = pos
            if isinstance(old, dict):
                _, pos = decoder.raw_decode(text, pos)
                pos = skip(skip(pos) + 1)  # colon
            child_start = pos
            _, child_end = decoder.raw_decode(text, pos)
            members.append((key, child, begin, child_start, child_end))
            pos = skip(child_end)
            if text[pos:pos + 1] == ',':
                pos = skip(pos + 1)
        prefix = text[start + 1:members[0][2]] if members else ''
        suffix = text[members[-1][4]:end - 1] if members else ''
        separator = text[members[0][4]:members[1][2]] if len(members) > 1 else ','
        by_key = {m[0]: m for m in members}
        by_id = {m[1]['id']: m for m in members if isinstance(m[1], dict) and 'id' in m[1]}
        output = []
        for key, child in (new.items() if isinstance(new, dict) else enumerate(new)):
            member = by_key.get(key) if isinstance(new, dict) else (
                by_id.get(child['id']) if isinstance(child, dict) and 'id' in child else by_key.get(key))
            if member is None:
                rendered = canonical_json_bytes(child).decode('utf-8')
                output.append((json.dumps(key, ensure_ascii=False) + ':' if isinstance(new, dict) else '') + rendered)
            else:
                _, prior, begin, child_start, child_end = member
                output.append(text[begin:child_start] + encode(prior, child, child_start, child_end))
        return text[start] + prefix + separator.join(output) + suffix + text[end - 1]
    start = skip(0)
    _, end = decoder.raw_decode(text, start)
    return (text[:start] + encode(before, value, start, end) + text[end:]).encode('utf-8')


def _review(plan, bundle):
    objects = {item['id']: item for collection in ('epics', 'features', 'stories', 'acs', 'tasks', 'pending_items')
               for item in _members(bundle, collection)}

    def label(identity):
        item = objects.get(identity, {})
        text = next((item[key] for key in ('title', 'name', 'question', 'text') if key in item), None)
        return f'{text}（{identity}）' if text else identity

    def bullets(items):
        return '\n'.join('- ' + item.replace('\n', '\n  ') for item in items) if items else '无。'

    boundary = plan['read_boundary']
    depth = {'current': '当前交付', 'topic': '分析主题', 'source': '原始资料'}[boundary['depth']]
    changes = '\n'.join(
        f"- {c['collection']} / {c['object_id']} / {c['field']}："
        f"{json.dumps(c['before'], ensure_ascii=False)} → {json.dumps(c['after'], ensure_ascii=False)}"
        for c in plan['changes']) or '无。'
    return '\n\n'.join([
        '# 具体修改方案', plan['change_summary'], '## 具体变化', changes,
        '## 执行条件', bullets(plan['conditions']),
        '## 仍未解决的事项', bullets([label(identity) for identity in plan['unresolved_items']]),
        '## 回查边界', f"最深回查：{depth}（{boundary['depth']}）。",
        '输入：' + ('、'.join(boundary['input_version_ids']) or '无。'),
        '主题：' + ('、'.join(boundary['topic_version_ids']) or '无。'),
        '对象：\n' + bullets([label(identity) for identity in boundary['object_ids']]),
    ]) + '\n'


def _save_attempt(project, area, draft, checkpoint):
    """Fixed physical branches, independent of the two professional revisions."""
    from .project import _verify_refs
    previous_ref = checkpoint.get('clarify_draft_ref')
    if previous_ref is None and checkpoint['candidate_path']:
        # Existing r1/r2 captures retain their original identity and digest.
        previous_ref = file_ref(project, safe_path(project,
            Path(checkpoint['candidate_path']).with_name('edit-draft.json').as_posix(), area))
    previous = None
    if previous_ref:
        _verify_refs(project, [previous_ref])
        previous = load_json(safe_path(project, previous_ref['path'], area))
        if draft == previous:
            return Path(previous_ref['path']).parent.as_posix(), previous_ref
        if draft['plan_id'] != previous['plan_id']:
            raise StorageError('SCOPE_EXCEEDED', '同一请求不能换方案身份刷新额度。')
    elif safe_path(project, area + '/plans').exists():
        raise StorageError('CHECKPOINT_UNKNOWN', '已有保存尝试但位置未知；保留工件，不重置次数。')

    directory = f"{area}/plans/{draft['plan_id']}/r{draft['revision']}"
    repair = draft.get('repair')
    if repair:
        if (previous is None or repair['draft_ref'] != previous_ref or previous.get('repair')
                or draft['revision'] != previous['revision']
                or draft.get('subset_of') != previous.get('subset_of')):
            raise StorageError('LOOP_LIMIT_REACHED', '机械返修必须沿上一候选，且同一候选只能返修一次。')
        retries = checkpoint.get('operation_retries', {})
        if checkpoint['repair_batches'] >= 2 or retries.get(repair['operation'], 0):
            raise StorageError('LOOP_LIMIT_REACHED', '请求返修或同操作/根因重试已到限。')
        directory = (Path(previous_ref['path']).parent / 'repair').as_posix()
    elif 'subset_of' in draft:
        if (previous is None or previous.get('subset_of')
                or draft['revision'] != previous['revision']):
            raise StorageError('LOOP_LIMIT_REACHED', '每份专业方案只机械提取一次明确子集，不嵌套或重开。')
        shown = file_ref(project, safe_path(project, Path(previous_ref['path']).with_name('plan.json').as_posix(), area))
        if draft['subset_of'] != shown:
            raise StorageError('SCOPE_EXCEEDED', '子集必须引用上一份具体展示计划。')
        directory = (Path(previous_ref['path']).parent / 'subset').as_posix()
    elif draft['revision'] != (previous['revision'] + 1 if previous else 1):
        raise StorageError('SCOPE_EXCEEDED', '专业方案从 1 开始，变化须沿原身份递增；机械返修须明确来源。')

    path = directory + '/edit-draft.json'
    if safe_path(project, path, area).exists():
        raise StorageError('CHECKPOINT_UNKNOWN', '保存槽已有工件但不是最近记录；保留并查询恢复，不覆盖或重新扣次数。')
    ref = write_json(project, path, draft, immutable=True)
    if repair:
        checkpoint['repair_batches'] += 1
        checkpoint.setdefault('operation_retries', {})[repair['operation']] = 1
        checkpoint['last_repair'] = repair['reason']
    checkpoint['clarify_draft_ref'] = ref
    save_checkpoint(project, checkpoint)
    return directory, ref


def _subset_source(project, ref, area):
    """Resolve the original constructed plan, including its bound reading snapshot."""
    from .project import _verify_refs
    path = safe_path(project, ref['path'], area)
    _verify_refs(project, [ref])
    shown = load_json(path)
    if list(schema_validator('change-plan').iter_errors(shown)) or 'subset_of' in shown:
        raise StorageError('SCOPE_EXCEEDED', '子集来源须为原具体方案，不能嵌套子集。')
    construction = checked_json(project, path.with_name('construction.json').relative_to(project).as_posix(),
                                'edit_construction', area)
    if construction['plan_ref'] != ref:
        raise StorageError('SCOPE_EXCEEDED', '子集来源不是构造时的具体展示计划。')
    return shown, construction


def _verify_subset(project, plan, area):
    """Check exact selected values and retained premises; never infer independence."""
    from .validation import check_candidate
    ref = plan['subset_of']
    shown, construction = _subset_source(project, ref, area)
    path = safe_path(project, ref['path'], area)
    report = check_candidate(project, safe_path(project, construction['candidate_ref']['path'], area), 'full', path)
    if not report['valid_for_render']:
        raise StorageError('SCOPE_EXCEEDED', '子集来源未通过当前机械复核；不能沿用旧展示。')
    if (any(plan[key] != shown[key] for key in ('plan_id', 'revision', 'base_version_id',
                                              'read_set', 'read_boundary', 'conditions'))
            or not plan['changes'] or len(plan['changes']) >= len(shown['changes'])
            or any(change not in shown['changes'] for change in plan['changes'])):
        raise StorageError('SCOPE_EXCEEDED', '纯子集必须保留读取/条件，实际变化严格取自已展示前后值；新值须专业修订。')
    return report['dependencies'] + [ref]


def prepare_edit(project, request_id, edit_path):
    project = Path(project).resolve()
    area = request_area(request_id, 'clarify')
    path = safe_path(project, edit_path, area)
    draft = load_json(path)
    if list(schema_validator('change-plan', 'edit_draft').iter_errors(draft)):
        raise StorageError('CANDIDATE_INVALID', '有限编辑稿字段或版本不符合合同。')
    current, manifest, raw, before = _base(project, draft['base_version_id'])
    checkpoint = ensure_request(project, request_id, 'clarify')
    directory, draft_ref = _save_attempt(project, area, draft, checkpoint)
    after = _apply_edits(before, draft['edits'])
    for collection, key in REFS.items():
        after[collection] = list(dict.fromkeys([*before[collection], *draft['additional_refs'][key]]))
    values = _documents(after)
    candidate = dict(schema_version='1.0', entrypoint='clarify', base_version_id=current['version_id'],
                     template_hash=manifest['template_hash'], **{key: after[collection] for collection, key in REFS.items()})
    for (name, key), value in zip(FILES.items(), values):
        candidate[key] = directory + '/' + name
        atomic_bytes(safe_path(project, candidate[key], area), _encoded(value, raw[name]), immutable=True)
    candidate_ref = write_json(project, directory + '/candidate.json', candidate, immutable=True)
    changes = diff_bundle(before, after)
    selectors = _selectors(draft, changes)
    snapshot = None
    if 'subset_of' in draft:
        shown, source_construction = _subset_source(project, draft['subset_of'], area)
        if (selectors != [r['selector'] for r in shown['read_set']]
                or any(draft[key] != shown[key] for key in ('read_boundary', 'conditions'))):
            raise StorageError('SCOPE_EXCEEDED', '子集只能继承原选择器、读取边界和条件，不能改写读取前提。')
        reads = deepcopy(shown['read_set'])
        snapshot = source_construction['input_index_snapshot_ref']
    else:
        reads = _read_set(project, selectors)
    plan = {key: draft[key] for key in ('schema_version', 'plan_id', 'revision', 'base_version_id',
                                      'read_boundary', 'conditions', 'unresolved_items', 'change_summary')}
    plan.update(changes=changes, read_set=reads,
                write_set=_write_set(changes), confirmation=None)
    if 'subset_of' in draft:
        plan['subset_of'] = draft['subset_of']
    plan_ref = write_json(project, directory + '/plan.json', plan, immutable=True)
    review = _review(plan, after)
    review_path = safe_path(project, directory + '/review.md', area)
    atomic_bytes(review_path, review.encode('utf-8'), immutable=True)
    if snapshot is None:
        snapshot = write_json(project, directory + '/input-index.json',
                              checked_json(project, '.ai-sow-lite/inputs/index.json', 'input_index'), immutable=True)
    write_json(project, directory + '/construction.json', dict(expected_current=current, draft_ref=draft_ref,
        candidate_ref=candidate_ref, plan_ref=plan_ref, input_index_snapshot_ref=snapshot,
        business_refs=[file_ref(project, safe_path(project, candidate[key])) for key in FILES.values()]), immutable=True)
    checkpoint['candidate_path'] = candidate_ref['path']
    save_checkpoint(project, checkpoint)
    return dict(candidate_ref=candidate_ref, plan_ref=plan_ref, review_ref=file_ref(project, review_path),
                no_change=not changes, current_version=current['version_id'])


def check_plan(ctx, candidate, candidate_path, model, pending, decisions, plan_path):
    """Reuse already-loaded candidate collections; one baseline load per check."""
    plan = ctx.json(plan_path, '/'.join(candidate_path.relative_to(ctx.project).parts[:4]), 'change-plan')
    if plan is None:
        return None
    current, manifest, _, before = _base(ctx.project, candidate['base_version_id'])
    construction_path = candidate_path.parent / 'construction.json'
    construction = ctx.json(construction_path, '/'.join(candidate_path.relative_to(ctx.project).parts[:4]),
                            'artifacts', 'edit_construction')
    if construction is None:
        return plan
    area = '/'.join(candidate_path.relative_to(ctx.project).parts[:4])
    preview = ctx.json(construction['plan_ref']['path'], area, 'change-plan')
    snapshot_ref = construction['input_index_snapshot_ref']
    snapshot = ctx.json(snapshot_ref['path'], area, 'artifacts', 'input_index')
    ctx.plan_binding = dict(plan_ref=ctx.dependencies[ctx.relative(safe_path(ctx.project, plan_path, area))],
                            plan_digest=plan_digest(plan), input_index_snapshot_ref=snapshot_ref)
    if snapshot is None or preview is None:
        return plan
    if ctx.dependencies[snapshot_ref['path']] != snapshot_ref:
        ctx.add('input_index_snapshot_ref', '输入登记快照字节变化。', code='EVIDENCE_MISSING')
    if plan_digest(plan) != plan_digest(preview):
        ctx.add('changes', '确认版的具体内容不同于已展示方案。', code='SCOPE_EXCEEDED')
    if 'subset_of' in plan:
        try:
            for ref in _verify_subset(ctx.project, plan, area):
                ctx.dependencies[ref['path']] = ref
        except StorageError as error:
            ctx.diagnostics.extend(error.diagnostics)
    try:
        _index_extension(ctx.project, snapshot_ref)
    except StorageError as error:
        ctx.diagnostics.extend(error.diagnostics)
    if construction['expected_current'] != current:
        ctx.add('base_version_id', '基线完整指针与构造时不同。', code='BASE_STALE')
    for ref in [construction['candidate_ref'], construction['plan_ref'], construction['draft_ref'], *construction['business_refs']]:
        if file_ref(ctx.project, safe_path(ctx.project, ref['path'])) != ref:
            ctx.add('candidate_ref', '构造后文件字节已变化，不能替换已展示方案。', code='SCOPE_EXCEEDED')
    for ref in [dict(path=f".ai-sow-lite/versions/{current['version_id']}/manifest.json", sha256=current['manifest_hash']),
                *manifest['files'], *manifest['dependencies']]:
        ctx.dependencies[ref['path']] = ref
    _registered_topics(ctx, [v for v in candidate['topic_version_ids'] if v not in manifest['topic_version_ids']])
    if plan['base_version_id'] != candidate['base_version_id']:
        ctx.add('base_version_id', '方案与候选基线不同。', code='BASE_STALE')
    if model is not None and pending is not None and decisions is not None:
        after = _bundle(model, pending, decisions, candidate)
        draft = load_json(safe_path(ctx.project, construction['draft_ref']['path']))
        expected = _apply_edits(before, draft['edits'])
        for collection, key in REFS.items():
            expected[collection] = list(dict.fromkeys([*before[collection], *draft['additional_refs'][key]]))
        if expected != after:
            ctx.add('changes', '候选内容或顺序不等于明确编辑的结果。', code='SCOPE_EXCEEDED')
        actual = diff_bundle(before, after)
        if actual != plan['changes'] or _write_set(actual) != plan['write_set']:
            ctx.add('changes', '候选实际前后值或写集合超出具体方案。', code='SCOPE_EXCEEDED')
        old_pending = {item['id']: item for item in before['pending_items']}
        open_questions = {item['id'] for item in pending['items'] if item['status'] == 'open'}
        for identity in plan['unresolved_items']:
            if identity not in open_questions:
                ctx.add('unresolved_items', '方案未决问题必须指向候选中仍开放的问题。', object_id=identity)
        live = {item['id'] for collection in ('epics', 'features', 'stories', 'acs', 'tasks') for item in _members(after, collection)}
        retained = {item['id'] for item in pending['items']}
        for old in before['pending_items']:
            if old['status'] == 'open' and old['unestimated_work'] and old['id'] not in retained and any(t['object_id'] in live for t in old['targets']):
                ctx.add('unestimated_work', '范围仍在时须明确解决或替代未拆明工作问题，不能仅删除该问题。', object_id=old['id'])
        for item in pending['items']:
            old = old_pending.get(item['id'])
            if old and any(old[field] != item[field] for field in ('question', 'targets', 'unestimated_work')) and item['revision'] <= old['revision']:
                ctx.add('revision', '问题内容、目标或未拆明工作标记变化必须提升修订号。', object_id=item['id'])
    if not _reads_match(ctx.project, plan['read_set'], snapshot):
        ctx.add('read_set', '所选读取版本已变化。', code='SCOPE_EXCEEDED')
    if plan['confirmation'] is not None:
        try:
            proof = confirmation_details(ctx.project, plan_path, candidate_path)
            for ref in proof['dependencies']:
                ctx.dependencies[ref['path']] = ref
        except StorageError as error:
            ctx.diagnostics.extend(error.diagnostics)
    return plan


def _index_extension(project, snapshot_ref):
    """One named mutable registry: only unchanged-prefix registration appends pass."""
    from .project import _verify_refs
    from .inputs import input_index
    _verify_refs(project, [snapshot_ref])
    snapshot = checked_json(project, snapshot_ref['path'], 'input_index', '.ai-sow-lite/work')
    current = input_index(project)
    if current['items'][:len(snapshot['items'])] != snapshot['items']:
        raise StorageError('EVIDENCE_MISSING', '既有输入登记项被修改、删除或重排；不能复用已展示方案。')
    return snapshot, current


def _registered_topics(ctx, versions):
    # Use the same split-topic provenance check as normal evidence validation.
    # Original registration may name work observations; stored topics use their
    # immutable observation refs, so reconstructing observations=[] is invalid.
    from ._prototype import topic_dependencies
    for version in versions:
        area = f'.ai-sow-lite/analysis/topics/{version}'
        stored = ctx.json(area + '/analysis.json', area, 'artifacts', 'analysis')
        if stored is None:
            continue
        try:
            for ref in topic_dependencies(ctx.project, version, stored):
                ctx.dependencies[ref['path']] = ref
        except StorageError as error:
            ctx.diagnostics.extend(error.diagnostics)


def _reads_match(project, reads, snapshot):
    from .inputs import input_index
    fresh = _read_set(project, [r['selector'] for r in reads])
    for old, new in zip(reads, fresh):
        if old == new:
            continue
        selected = old['selector']
        if selected['view'] != 'inputs' or not selected['selector']:
            return False
        selector = selected['selector']
        field = 'input_version_id' if 'input_version_ids' in selector else 'input_id'
        identities = selector[field + 's']
        prior = [e for e in snapshot['items'] if e[field] in identities]
        actual = [e for e in input_index(project)['items'] if e[field] in identities]
        if old['observed_version'] != semantic_digest(snapshot) or prior != actual:
            return False
    return True


def checks_match(project, saved, fresh):
    """Never waive arbitrary dependencies. Admit only the verified index append."""
    if saved == fresh:
        return True
    snapshot = saved.get('input_index_snapshot_ref')
    if not snapshot or snapshot != fresh.get('input_index_snapshot_ref') or not fresh['valid_for_render']:
        return False
    _index_extension(project, snapshot)
    old_refs = {r['path']: r for r in saved['dependencies']}
    adjusted = deepcopy(fresh)
    index = '.ai-sow-lite/inputs/index.json'
    if index not in old_refs:
        return False
    adjusted['dependencies'] = [old_refs[index] if r['path'] == index else r for r in fresh['dependencies']]
    return adjusted == saved


def confirmation_details(project, plan_path, candidate_path):
    """Verify content/source bindings, not human identity or the meaning of assent."""
    import hashlib
    from .inputs import input_index, source_excerpt
    from .project import _verify_refs
    candidate_path = safe_path(project, candidate_path, '.ai-sow-lite/work/clarify')
    area = '/'.join(candidate_path.relative_to(Path(project).resolve()).parts[:4])
    path = safe_path(project, plan_path, area)
    plan = load_json(path)
    if list(schema_validator('change-plan').iter_errors(plan)) or plan.get('confirmation') is None:
        raise StorageError('SCOPE_EXCEEDED', '应用需要已展示具体内容与实际执行输入的确认绑定。')
    construction = checked_json(project, (candidate_path.parent / 'construction.json').relative_to(project).as_posix(),
                                'edit_construction', area)
    confirmation = plan['confirmation']
    preview_ref = construction['plan_ref']
    _verify_refs(project, [preview_ref, construction['candidate_ref'], *construction['business_refs']])
    preview = load_json(safe_path(project, preview_ref['path'], area))
    shown_ref = plan.get('subset_of', preview_ref)
    subset_dependencies = _verify_subset(project, plan, area) if 'subset_of' in plan else []
    if (confirmation['digest'] != plan_digest(plan) or plan_digest(plan) != plan_digest(preview)
            or confirmation['shown_plan_ref'] != shown_ref or confirmation['selected_changes'] != plan['changes']):
        raise StorageError('SCOPE_EXCEEDED', '执行输入、展示方案或所选具体变化不能绑定同一内容。')
    binding_path = area + '/confirmations/' + plan_digest(plan).split(':')[1] + '.json'
    if safe_path(project, binding_path).exists():
        sealed = checked_json(project, binding_path, 'file_ref', area)
        if sealed != file_ref(project, path):
            raise StorageError('SCOPE_EXCEEDED', '已检查的确认文件字节或路径已变化。')
    source = confirmation['input_ref']
    entry = next((e for e in input_index(project)['items'] if e['input_version_id'] == source['input_version_id']), None)
    if entry is None or 'answer' not in entry['material_types']:
        raise StorageError('EVIDENCE_MISSING', '确认须引用已登记的实际答复输入。')
    excerpt, dependencies = source_excerpt(project, entry, source['locator'])
    if not excerpt.strip() or hashlib.sha256(excerpt).hexdigest() != source['excerpt_hash']:
        raise StorageError('EVIDENCE_MISSING', '实际确认原话字节与绑定摘录不同。')
    # apply persists this list. Full live checks above remain in the check report;
    # the exact shown plan is verified separately and archived by confirmation_files.
    permanent_dependencies = [ref for ref in dependencies + subset_dependencies
                              if not ref['path'].startswith('.ai-sow-lite/work/')
                              and ref['path'] not in ('.ai-sow-lite/inputs/index.json', '.ai-sow-lite/current.json')]
    return dict(plan=plan, plan_ref=file_ref(project, path), shown_plan_ref=shown_ref,
                input_record=entry, dependencies=permanent_dependencies,
                digest=plan_digest(plan), binding_path=binding_path)


def seal_confirmation(project, plan_path, candidate_path):
    """First checked/consumed confirmation binds exact bytes; no extra user gate."""
    details = confirmation_details(project, plan_path, candidate_path)
    write_json(project, details['binding_path'], details['plan_ref'], immutable=True)
    return details


def confirmation_files(project, details, candidate_path, prepared_path, version):
    """Archive the exact executed/shown bytes with reachable immutable references."""
    import hashlib
    contents = {
        'plan.json': safe_path(project, details['plan_ref']['path']).read_bytes(),
        'shown-plan.json': safe_path(project, details['shown_plan_ref']['path']).read_bytes(),
        'candidate.json': safe_path(project, candidate_path).read_bytes(),
        'prepared.json': safe_path(project, prepared_path).read_bytes(),
    }
    def ref(name):
        return dict(path=f'.ai-sow-lite/versions/{version}/{name}', sha256=hashlib.sha256(contents[name]).hexdigest())
    proof = dict(schema_version='1.0', digest=details['digest'],
        plan_ref=ref('plan.json'), shown_plan_ref=ref('shown-plan.json'), input_record=details['input_record'],
        source_ref=details['plan']['confirmation']['input_ref'], selected_changes=details['plan']['changes'])
    if next(schema_validator('artifacts', 'clarify_confirmation').iter_errors(proof), None):
        raise StorageError('CANDIDATE_INVALID', '具体确认归档不符合合同。')
    contents['confirmation.json'] = canonical_json_bytes(proof)
    return contents
