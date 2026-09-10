"""A recipient can read the deliverable after taking only the XLSX file."""
from copy import deepcopy
import re

import openpyxl
import pytest

from ai_sow_lite.contracts import schema_validator
from ai_sow_lite.project import StorageError
from ai_sow_lite.workbook import audit_workbook, project_workbook
from .support.fixtures import PLUGIN
from .test_workbook import bundle, project


def assert_internal_delivery(book):
    assert book.sheetnames == ['01-需求故事', '02-任务清单', '03-工作量汇总',
                               '90-估算标准', '04-待确认事项', '05-完整说明']
    for sheet in book:
        assert sheet.sheet_state == 'visible'
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    assert not re.search(r'(?:details|pending-items)\.md(?:#|\b)', cell.value)
                if cell.hyperlink:
                    assert cell.hyperlink.target is None
                    location = cell.hyperlink.location
                    match = re.fullmatch(r"'([^']+)'!([A-Z]+[0-9]+)", location)
                    assert match, location
                    assert book[match[1]][match[2]].value is not None
    for name in ['04-待确认事项', '05-完整说明']:
        for row in book[name].iter_rows(min_row=5):
            assert (book[name].row_dimensions[row[0].row].height or 15) <= 409
            for cell in row:
                if cell.value is not None:
                    assert cell.data_type == 's'
                    assert len(cell.value.encode('utf-16-le')) // 2 <= 32767


def test_xlsx_alone_preserves_long_ac_notes_and_pending(tmp_path):
    model, pending, decisions = bundle()
    raw = '验收原文😀\r\n' * 6000 + '最终验收条件。'
    model['stories'][0]['acs'][0]['text'] = raw
    model['tasks'][0]['notes'] = '=不是公式\n' + '备注全文。' * 500
    pending['items'][0]['question'] = '需要决定的真实问题。' * 300
    pending['items'][0]['current_handling'] = '采用M但记录数量仍未知。' * 300
    project(tmp_path, model, pending, decisions)
    # All companion files are deliberately unavailable to the recipient.
    for path in tmp_path.glob('*.md'):
        path.unlink()
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    assert_internal_delivery(book)
    full = ''.join(row[0] or '' for row in book['05-完整说明'].iter_rows(min_row=5, min_col=4, max_col=4, values_only=True))
    assert raw.replace('\r\n', '\n') in full
    assert model['stories'][0]['acs'][1]['text'] in full
    assert model['tasks'][0]['notes'] in full
    issues = ''.join(row[0] or '' for row in book['04-待确认事项'].iter_rows(min_row=5, min_col=4, max_col=4, values_only=True))
    assert pending['items'][0]['question'] in issues
    assert pending['items'][0]['current_handling'] in issues
    assert pending['items'][0]['id'] not in (book['02-任务清单']['G10'].value or '')
    assert book['01-需求故事']['D5'].hyperlink.location.startswith("'05-完整说明'!")


def test_all_target_kinds_and_closed_questions_are_readable_in_workbook(tmp_path):
    model, pending, decisions = bundle()
    item = pending['items'][0]
    item['targets'] = [dict(object_id=model['epics'][0]['id'], field='title'),
                       dict(object_id=model['stories'][0]['acs'][0]['id'], field='text')]
    item['question'] = '确认需求和验收之间的边界。'
    old = deepcopy(item)
    old.update(id='00000000-0000-4000-8000-000000009999', status='superseded',
               question='已替换问题保留历史。', resolution=dict(
                   replacement_item_ids=[item['id']], lineage_refs=[],
                   request_id='00000000-0000-4000-8000-000000009998',
                   reason='按拆清后的目标重新确认。'))
    pending['items'].append(old)
    schema_validator('pending-items').validate(pending)
    project(tmp_path, model, pending, decisions)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    assert_internal_delivery(book)
    text = '\n'.join(str(c.value) for row in book['04-待确认事项'] for c in row if c.value)
    assert item['question'] in text and old['question'] in text
    assert '已替代' in text and '待确认' in text
    assert '01-需求故事' in text
    assert old['resolution']['reason'] in text and '后续事项' in text
    answers = [row[3] for row in book['04-待确认事项'].iter_rows(values_only=True)
               if row[1] == '已采用答复']
    assert answers == ['尚无已采用答复', '尚无已采用答复']


@pytest.mark.parametrize('entry', [1, 2])
def test_pending_target_identifies_the_specific_ac(tmp_path, entry):
    model, pending, decisions = bundle()
    story = model['stories'][0]
    item = pending['items'][0]
    item.update(question='请确认该验收条件。', current_handling='保留待确认。',
                targets=[dict(object_id=story['acs'][entry - 1]['id'], field='text')])
    project(tmp_path, model, pending, decisions)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    try:
        targets = ''.join(row[3] or '' for row in book['04-待确认事项'].iter_rows(values_only=True)
                          if row[1] == '关联位置')
        assert story['title'] in targets
        assert f'第 {entry} 条 AC' in targets
        assert f'第 {3 - entry} 条 AC' not in targets
        assert 'text' in targets and '01-需求故事!D5' in targets
        assert_internal_delivery(book)
    finally:
        book.close()


@pytest.mark.parametrize('collection', ['epics', 'features'])
def test_unrendered_parent_target_retains_its_name(tmp_path, collection):
    model, pending, decisions = bundle()
    parent = deepcopy(model[collection][0])
    parent.update(id='00000000-0000-4000-8000-000000009997', title='跨区库存同步边界')
    model[collection].append(parent)
    gap = deepcopy(pending['items'][0])
    gap.update(id='00000000-0000-4000-8000-000000009996', question='请确认该范围。',
               current_handling='确认后再拆明工作。', unestimated_work=True,
               targets=[dict(object_id=parent['id'], field=None)])
    pending['items'].append(gap)
    schema_validator('pending-items').validate(pending)
    project(tmp_path, model, pending, decisions)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    try:
        targets = ''.join(row[3] or '' for row in book['04-待确认事项'].iter_rows(values_only=True)
                          if row[1] == '关联位置')
        assert parent['title'] in targets
        assert '整个对象' in targets and '无对应数据行' in targets
        assert_internal_delivery(book)
    finally:
        book.close()


def test_zero_questions_and_short_text_need_no_external_file(tmp_path):
    model, pending, decisions = bundle()
    pending['items'] = []
    project(tmp_path, model, pending, decisions)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    assert_internal_delivery(book)
    assert '无待确认事项' in '\n'.join(str(c.value) for row in book['04-待确认事项'] for c in row)
    assert book['01-需求故事']['D5'].value == '1. ' + model['stories'][0]['acs'][0]['text'] + '\n2. ' + model['stories'][0]['acs'][1]['text']


def test_actual_adopted_answer_is_readable_without_machine_json(tmp_path):
    model, pending, decisions = bundle()
    item = pending['items'][0]
    decision = decisions['items'][0]
    decision['text'] = '采用M作为本次估算口径，不代表记录总量已经查明。\n' * 100
    decision['applies_to'] = deepcopy(item['targets'])
    item.update(status='resolved', resolution=dict(decision_id=decision['id'],
        request_id='00000000-0000-4000-8000-000000009998', summary='用户明确采用当前档位。'))
    schema_validator('pending-items').validate(pending)
    schema_validator('decisions').validate(decisions)
    question_source = 'hld.md；第 10—12 行；原问题依据'
    answer_source = 'answers.md；第 3—3 行；决定答复依据'
    evidence = {item['evidence_refs'][0]: question_source,
                decision['evidence_refs'][0]: answer_source}
    project_workbook(PLUGIN / 'assets/sow-template.xlsx', model, pending, decisions,
                     '00000000-0000-4000-8000-000000009995', tmp_path, evidence=evidence)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    assert_internal_delivery(book)
    text = ''.join(row[0] or '' for row in book['04-待确认事项'].iter_rows(
        min_row=5, min_col=4, max_col=4, values_only=True))
    assert '已解决' in text and item['resolution']['summary'] in text
    assert decision['text'] in text
    assert decision['id'] not in text and 'decision_id' not in text
    assert question_source in text and answer_source in text


@pytest.mark.parametrize('long_text', [False, True])
def test_literal_history_address_cannot_become_the_full_text_link(tmp_path, long_text):
    model, pending, decisions = bundle()
    raw = "历史定位 '05-完整说明'!D99999，仅作原文保留。"
    if long_text:
        raw += '\n' + '此次说明全文。' * 150
    model['tasks'][0]['notes'] = raw
    project(tmp_path, model, pending, decisions)
    path = tmp_path / 'projected.xlsx'
    book = openpyxl.load_workbook(path)
    try:
        cell = book['02-任务清单']['G5']
        if long_text:
            assert cell.hyperlink is not None
            assert cell.hyperlink.location != "'05-完整说明'!D99999"
            full = ''.join(row[0] or '' for row in book['05-完整说明'].iter_rows(
                min_row=5, min_col=4, max_col=4, values_only=True))
            assert raw in full
        else:
            assert cell.value == raw and cell.hyperlink is None
        assert_internal_delivery(book)
        audit_workbook(path, path, caches=False)
    finally:
        book.close()


def test_one_primary_jump_keeps_other_generated_addresses_readable(tmp_path):
    model, pending, decisions = bundle()
    story = model['stories'][0]
    story['notes'] = '保留原备注。' * 150
    item = pending['items'][0]
    item.update(targets=[dict(object_id=story['id'], field='notes')],
                current_handling='先保留第一项范围。')
    second = deepcopy(item)
    second.update(id='00000000-0000-4000-8000-000000009994',
                  question='另一个独立范围问题。', current_handling='先保留第二项范围。')
    pending['items'].append(second)
    project(tmp_path, model, pending, decisions)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    try:
        note = book['01-需求故事']['E5']
        assert note.hyperlink.location in note.value
        full = ''.join(row[0] or '' for row in book['05-完整说明'].iter_rows(
            min_row=5, min_col=4, max_col=4, values_only=True))
        assert story['notes'] in full
        targets = [f"'04-待确认事项'!D{row[3].row}" for row in book['04-待确认事项']
                   if row[1].value == '状态']
        assert len(targets) == 2
        assert all(target in note.value + full for target in targets)
        assert_internal_delivery(book)
    finally:
        book.close()


@pytest.mark.parametrize('prefix', ['\n' * 8, ' ' * 800])
def test_leading_blank_lines_remain_valid_full_text_destinations(tmp_path, prefix):
    model, pending, decisions = bundle()
    raw = prefix + '保留正文与前导空行。' * 150
    model['tasks'][0]['notes'] = raw
    project(tmp_path, model, pending, decisions)
    path = tmp_path / 'projected.xlsx'
    book = openpyxl.load_workbook(path)
    try:
        full = ''.join(row[0] or '' for row in book['05-完整说明'].iter_rows(
            min_row=5, min_col=4, max_col=4, values_only=True))
        assert raw in full
        assert_internal_delivery(book)
        audit_workbook(path, path, caches=False)
    finally:
        book.close()


def test_nested_name_reference_uses_the_visible_section_as_primary_jump(tmp_path):
    model, pending, decisions = bundle()
    model['stories'][0].update(title='完整故事名称' * 150, notes='')
    project(tmp_path, model, pending, decisions)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    try:
        note = book['01-需求故事']['E5']
        assert note.hyperlink.location in note.value
        assert_internal_delivery(book)
    finally:
        book.close()


@pytest.mark.parametrize('location', ["'05-完整说明'!D99999", "'05-完整说明'!D3",
                                      "'不存在的说明表'!D5"])
def test_audit_rejects_empty_internal_target_even_when_expected_matches(tmp_path, location):
    project(tmp_path)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    try:
        link = next(c for row in book['01-需求故事'] for c in row if c.hyperlink)
        link.hyperlink.location = location
        damaged = tmp_path / 'damaged.xlsx'
        book.save(damaged)
        # Equality with expected bytes cannot establish destination validity.
        with pytest.raises(StorageError, match='WORKBOOK_INVALID'):
            audit_workbook(damaged, damaged, caches=False)
    finally:
        book.close()


@pytest.mark.office
def test_real_office_preserves_internal_content_and_rejects_broken_jump(tmp_path):
    from .support.excel import prepare_case
    from ai_sow_lite.workbook import audit_workbook
    from ai_sow_lite.project import StorageError
    case, _, response = prepare_case(tmp_path / 'project')
    assert response['ok'], response
    path = case.project / response['result']['workbook_ref']['path']
    book = openpyxl.load_workbook(path)
    assert_internal_delivery(book)
    link = next(c for row in book['01-需求故事'] for c in row if c.hyperlink)
    link.hyperlink.location = "'05-完整说明'!D99999"
    damaged = tmp_path / 'damaged.xlsx'
    book.save(damaged)
    with pytest.raises(StorageError, match='WORKBOOK_INVALID'):
        audit_workbook(damaged, path.with_name('projected.xlsx'), caches=False)
