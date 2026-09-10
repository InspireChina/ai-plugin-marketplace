"""The original tables alone carry acceptance and unresolved user decisions."""
from copy import deepcopy
from uuid import uuid4

import openpyxl
import pytest

from ai_sow_lite.project import StorageError
from .test_workbook import bundle, project


def test_original_four_sheets_complete_acs_and_normally_empty_notes(tmp_path):
    m,p,d=bundle()
    for obj in [*m['stories'],*m['tasks']]: obj['notes']=''
    for task in m['tasks']: task.update(work_mode='新建', complexity='M')
    p['items']=[]
    result=project(tmp_path,m,p,d)
    w=openpyxl.load_workbook(tmp_path/'projected.xlsx')
    assert w.sheetnames==['01-需求故事','02-任务清单','03-工作量汇总','90-估算标准']
    assert w['01-需求故事']['D5'].value=='\n'.join(f'{i}. {ac["text"]}' for i,ac in enumerate(m['stories'][0]['acs'],1))
    assert all(w['01-需求故事'][f'E{r}'].value is None for r in range(5,9))
    assert all(w['02-任务清单'][f'G{r}'].value is None for r in range(5,12))
    assert not any(c.hyperlink for s in list(w)[:2] for row in s.iter_rows(min_row=5) for c in row)
    assert result['details']==[] and not (tmp_path/'details.md').exists()


def test_pending_question_and_current_handling_are_inline_without_ids_or_paths(tmp_path):
    m,p,d=bundle()
    m['tasks'][-2]['notes']=''
    project(tmp_path,m,p,d)
    w=openpyxl.load_workbook(tmp_path/'projected.xlsx')
    text=w['02-任务清单']['G10'].value
    item=p['items'][0]
    assert text.startswith('待确认：')
    assert item['question'] in text and item['current_handling'] in text
    assert item['id'] not in text and '.md' not in text and '见 ' not in text
    assert w['02-任务清单']['L10'].data_type=='f'


@pytest.mark.parametrize('target_kind',['epic','feature','story','ac','task'])
def test_pending_is_on_its_own_rows_and_not_unrelated_rows(tmp_path,target_kind):
    m,p,d=bundle()
    for o in [*m['stories'],*m['tasks']]:o['notes']=''
    s=m['stories'][0]
    obj={'epic':m['epics'][0],'feature':m['features'][0],'story':s,'ac':s['acs'][1],'task':m['tasks'][0]}[target_kind]
    p['items'][0].update(question='该边界是否包含？',current_handling='等待答复。',targets=[dict(object_id=obj['id'],field=None)])
    project(tmp_path,m,p,d)
    w=openpyxl.load_workbook(tmp_path/'projected.xlsx')
    sheet,col=('02-任务清单','G') if target_kind=='task' else ('01-需求故事','E')
    note=w[sheet][f'{col}5'].value
    assert note.startswith('待确认：') and '该边界是否包含？' in note
    if target_kind=='ac':assert '第 2 条 AC' in note
    assert w['01-需求故事']['E8'].value is None
    assert w['02-任务清单']['G10'].value is None


@pytest.mark.parametrize('collection',['epics','features'])
def test_undivided_scope_has_an_original_table_row_without_inventing_a_story(tmp_path,collection):
    m,p,d=bundle(); original=deepcopy(m)
    parent=dict(deepcopy(m[collection][0]),id=str(uuid4()),title='尚待明确的数据移交范围')
    m[collection].append(parent)
    p['items'][0].update(question='哪些数据需要移交？',current_handling='未拆明，未估算。',unestimated_work=True,
                          targets=[dict(object_id=parent['id'],field=None)])
    result=project(tmp_path,m,p,d)
    record=next(o for o in result['objects'] if o['object_id']==parent['id'])
    assert len(record['rows'])==1
    w=openpyxl.load_workbook(tmp_path/'projected.xlsx');row=record['rows'][0]
    assert w['01-需求故事'][f'C{row}'].value is None
    assert w['01-需求故事'][f'E{row}'].value.startswith('待确认：')
    assert '哪些数据需要移交？' in w['01-需求故事'][f'E{row}'].value
    assert m['stories']==original['stories'] and m['tasks']==original['tasks']
    assert result['pending_items'][0]['targets'][0]['cells']


def test_closed_questions_do_not_keep_rows_pending_and_history_stays_in_project(tmp_path):
    m,p,d=bundle()
    for obj in [*m['stories'],*m['tasks']]:obj['notes']=''
    p['items'][0].update(status='resolved',resolution=dict(decision_id=d['items'][0]['id'],request_id=str(uuid4()),summary='确认沿用M。'))
    project(tmp_path,m,p,d)
    w=openpyxl.load_workbook(tmp_path/'projected.xlsx')
    assert w['02-任务清单']['G10'].value is None
    assert p['items'][0]['question'] in (tmp_path/'pending-items.md').read_text()
    assert '已采用答复' in (tmp_path/'pending-items.md').read_text()


def test_no_ac_count_gate_and_no_truncation_or_sidecar_for_long_cell(tmp_path):
    m,p,d=bundle()
    raw='源文中的验收界限😀。'*500
    m['stories'][0]['acs']=[dict(id=str(uuid4()),text=f'{n}项验收。',evidence_refs=m['stories'][0]['evidence_refs']) for n in range(20)]
    m['stories'][0]['acs'][0]['text']=raw
    project(tmp_path,m,p,d)
    w=openpyxl.load_workbook(tmp_path/'projected.xlsx')
    assert w['01-需求故事']['D5'].value=='\n'.join(f'{i}. {ac["text"]}' for i,ac in enumerate(m['stories'][0]['acs'],1))
    assert w['01-需求故事'].row_dimensions[5].height<=409
    assert not (tmp_path/'details.md').exists()


def test_text_beyond_excel_capacity_returns_specific_target_without_partial_xlsx(tmp_path):
    m,p,d=bundle(); m['stories'][0]['acs'][0]['text']='😀'*17000
    with pytest.raises(StorageError) as caught:project(tmp_path,m,p,d)
    assert caught.value.diagnostics[0]['code']=='WORKBOOK_INVALID'
    assert caught.value.diagnostics[0]['target']['object_id']==m['stories'][0]['id']
    assert caught.value.diagnostics[0]['target']['field']=='acs'
    assert not (tmp_path/'projected.xlsx').exists()


@pytest.mark.parametrize('filename', ['sow-template-before-inline.xlsx', 'sow-template-before-task-reasons.xlsx'])
def test_old_project_template_is_unchanged_but_gets_current_inline_status_formulas(tmp_path, filename):
    import hashlib
    from .support.fixtures import FIXTURES,PLUGIN
    from ai_sow_lite.workbook import project_workbook,formula_text
    old=FIXTURES/'workbook'/filename;original=old.read_bytes()
    m,p,d=bundle()
    result=project_workbook(old,m,p,d,str(uuid4()),tmp_path)
    w=openpyxl.load_workbook(tmp_path/'projected.xlsx')
    before=openpyxl.load_workbook(old);current=openpyxl.load_workbook(PLUGIN/'assets/sow-template.xlsx')
    assert result['template_hash']==hashlib.sha256(original).hexdigest()
    for sn,col in [('01-需求故事','J'),('02-任务清单','L')]:
        assert w[sn][f'{col}5'].value==current[sn][f'{col}5'].value
        assert w[sn]['A2'].value==current[sn]['A2'].value
        assert next(c for c in w[sn].tables.values()).tableColumns[-1].calculatedColumnFormula.text==w[sn][f'{col}5'].value[1:]
    for sheet in before:
        for row in sheet:
            for cell in row:
                if cell.data_type=='f' and not ((sheet.title,cell.column_letter) in [('01-需求故事','J'),('02-任务清单','L')]):
                    assert formula_text(w[sheet.title][cell.coordinate].value)==formula_text(cell.value)
    assert old.read_bytes()==original


def test_crlf_capacity_is_checked_after_display_newline_normalization(tmp_path):
    m,p,d=bundle();raw='字\r\n'*11000
    m['tasks'][0]['notes']=raw
    project(tmp_path,m,p,d)
    w=openpyxl.load_workbook(tmp_path/'projected.xlsx')
    assert w['02-任务清单']['G5'].value==raw.replace('\r\n','\n')


@pytest.mark.parametrize('field',['question','current_handling'])
def test_oversize_scope_note_points_to_an_existing_pending_field(tmp_path,field):
    m,p,d=bundle();orphan=dict(deepcopy(m['epics'][0]),id=str(uuid4()),title='未拆明范围')
    m['epics'].append(orphan)
    item=p['items'][0];item.update(targets=[dict(object_id=orphan['id'],field=None)],unestimated_work=True)
    item[field]='字段正文。'*6600
    with pytest.raises(StorageError) as caught:project(tmp_path,m,p,d)
    target=caught.value.diagnostics[0]['target']
    assert target['object_id']==item['id'] and target['field']==field
    assert not (tmp_path/'projected.xlsx').exists()


@pytest.mark.parametrize('collection,field',[('stories','title'),('tasks','name')])
def test_oversize_alias_original_points_to_the_authored_name(tmp_path,collection,field):
    m,p,d=bundle();obj=m[collection][0];obj[field]='长名称'*11000
    with pytest.raises(StorageError) as caught:project(tmp_path,m,p,d)
    assert caught.value.diagnostics[0]['target']['object_id']==obj['id']
    assert caught.value.diagnostics[0]['target']['field']==field
