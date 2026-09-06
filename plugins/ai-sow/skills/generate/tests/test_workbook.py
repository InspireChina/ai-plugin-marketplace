"""Task12 projection and integrity boundaries; no full host setup."""
import json
import sys
from pathlib import Path
import openpyxl
import pytest

TEST_LAYER = 'unit'
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import workbook
from contracts import canonical_json_bytes, sha256_bytes


def render_model():
    from ir_samples import task_story_model
    from task_standard_catalog import catalog
    model = task_story_model()
    source = catalog(ROOT / 'assets/sow-template.xlsx')
    model['project']['templateSha256'] = source.template_sha256
    model['tasks'] = [{'taskId':'task-query','storyId':'story-query','name':'订单查询页面',
        'workTypeId':'FE-VIEW','rowSemanticSha256':source.by_work_type_id['FE-VIEW']['rowSemanticSha256'],
        'workMode':'新建','complexity':'M','actualMeasurementScope':'一张订单查询页面',
        'sourceRefs':model['stories'][0]['sourceRefs'],'integrationIds':[]}]
    return model


@pytest.mark.parametrize('prefix', ['=', '+', '-', '@'])
def test_template_projection_preserves_authority_and_safe_text(tmp_path, prefix):
    model = render_model(); model['tasks'][0]['name'] = prefix+'plain text'
    path = tmp_path/'sow.xlsx'; template = ROOT/'assets/sow-template.xlsx'
    workbook.write_workbook(template, model, path)
    source = openpyxl.load_workbook(template); result = openpyxl.load_workbook(path)
    try:
        workbook.verify_static_authority(result, source)
        workbook.verify_worksheet_authority(result, source)
        assert result['02-任务清单']['B5'].data_type == 's'
        assert result['02-任务清单']['B5'].value == "'"+prefix+'plain text'
        for name in workbook.TABLES:
            sheet, table = workbook.table_index(result)[name]
            assert table.autoFilter.ref == table.ref
        assert any('TaskTable[' in workbook.formula_text(c.value) for s in result for row in s for c in row if c.data_type == 'f')
    finally:
        source.close(); result.close()


@pytest.mark.parametrize('error', ['#REF!','#DIV/0!','#VALUE!','#NAME?','#N/A','#NUM!','#NULL!',"='missing sheet'!A1",'ZIP'])
def test_workbook_integrity_errors_block_verification(tmp_path, error):
    path = tmp_path/'bad.xlsx'; book = openpyxl.Workbook()
    book.active['A1'] = error
    book.save(path); book.close()
    if error == 'ZIP': path.write_bytes(b'PK corrupted')
    assert callable(getattr(workbook, 'scan_workbook_integrity', None)), 'complete ZIP/formula scanner missing'
    with pytest.raises(ValueError): workbook.scan_workbook_integrity(path)


@pytest.mark.integration
def test_template_projection_prior_adapter_round_trip(tmp_path):
    from prior_state import inventory_prior_workbook, materialize_prior_snapshot
    from test_prior_state import revision_for
    model = render_model(); path = tmp_path/'transferred.xlsx'
    workbook.write_workbook(ROOT/'assets/sow-template.xlsx', model, path)
    before = path.read_bytes(); inventory = inventory_prior_workbook(path)
    ids = {'epic-orders','feature-query','story-query','ac-success','ac-empty','task-query','input-a','input-b'}
    entities = []
    for entity_id in sorted(ids):
        evidence = [e for e in inventory['evidence'] if any(c['value'] == entity_id for c in e['canonicalCellValues'])]
        assert evidence, 'visible whole-cell identity missing: '+entity_id
        entities.append({'localKey':entity_id,'sourceId':'prior','entityKind':'CONTRACT_ENTITY',
            'semanticSummary':entity_id,'deliveryStatus':'CURRENT_BY_CONTRACT','visiblePriorId':entity_id,
            'evidenceIds':[e['priorEvidenceId'] for e in evidence]})
    decision = {'entities':entities,'sourceRelations':[],'entitySupersessions':[],'unsupportedRegions':[]}
    snapshot = materialize_prior_snapshot([inventory], decision, input_revision_bytes=revision_for([inventory],['prior']))
    assert {e['entityId'] for e in snapshot['entities']} == ids
    values = [c['value'] for e in inventory['evidence'] for c in e['canonicalCellValues']]
    assert canonical_json_bytes(model['inputItems'][0]['sourceRefs'][0]).decode().strip() in values
    assert path.read_bytes() == before


def shared_asset_render_model():
    import copy
    model=render_model()
    other=copy.deepcopy(model['stories'][0]);other.update(storyId='story-acceptance',name='用户验收订单查询')
    model['stories'].append(other)
    model['acceptanceCriteria'][1]['storyId']=other['storyId']
    model['tasks'][0]['acceptanceCriterionIds']=['ac-success','ac-empty']
    return model


def test_shared_asset_projection_lists_coverage_but_keeps_one_charge_and_template_financial_formulas(tmp_path):
    model=shared_asset_render_model();template=ROOT/'assets/sow-template.xlsx';path=tmp_path/'shared.xlsx'
    workbook.write_workbook(template,model,path)
    b=openpyxl.load_workbook(path);source=openpyxl.load_workbook(template)
    try:
        tasks=workbook.table_records(b,'TaskTable');stories=workbook.table_records(b,'SOWStoryTable')
        assert len(tasks)==1 and len(stories)==2
        assert '共享' in stories[1]['备注'] and model['stories'][0]['name'] in stories[1]['备注']
        assert 'COUNTIFS(TaskTable[所属故事],' in stories[1]['校验结果']
        assert '订单查询页面' in workbook.formula_text(stories[1]['任务列表'])
        from openpyxl.formula.translate import Translator
        assert stories[1]['故事人天']==Translator(source['01-需求故事']['H5'].value,origin='H5').translate_formula('H6')
        for header in workbook.FORMULA_HEADERS['TaskTable']:
            col=workbook.TABLE_HEADERS['TaskTable'].index(header)+1
            assert workbook.comparable_formula(b['02-任务清单'].cell(5,col).value)==workbook.comparable_formula(source['02-任务清单'].cell(5,col).value)
        workbook.verify_static_authority(b,source)
    finally:b.close();source.close()


def test_distinct_work_types_qualify_shared_context_names_without_hiding_same_type_duplicates(tmp_path):
    import copy
    from task_standard_catalog import catalog
    model=render_model();original=copy.deepcopy(model)
    second=copy.deepcopy(model['tasks'][0]);second.update(taskId='task-query-api',workTypeId='FE-QUERY-API',
        actualMeasurementScope='一个查询 API')
    standard=catalog(ROOT/'assets/sow-template.xlsx')
    second['rowSemanticSha256']=standard.by_work_type_id[second['workTypeId']]['rowSemanticSha256']
    model['tasks'].append(second);before=copy.deepcopy(model)
    path=tmp_path/'different-assets.xlsx';workbook.write_workbook(ROOT/'assets/sow-template.xlsx',model,path)
    book=openpyxl.load_workbook(path)
    try:
        rows=workbook.table_records(book,'TaskTable')
        assert len(rows)==2 and len({row['任务名称'] for row in rows})==2
        for row,task in zip(rows,model['tasks'],strict=True):
            assert row['任务名称']==task['name']+'：'+standard.by_work_type_id[task['workTypeId']]['工作类型名称']
        assert model==before
    finally: book.close()
    model['tasks'][1]=copy.deepcopy(original['tasks'][0]);model['tasks'][1]['taskId']='another-same-type'
    with pytest.raises(ValueError,match='duplicated'): workbook.build_rows(model,standard)


@pytest.mark.e2e
def test_shared_asset_real_office_reread_keeps_all_stories_and_one_task(tmp_path):
    from office_engine import recalculate_workbook,require_office_engine
    model=shared_asset_render_model();template=ROOT/'assets/sow-template.xlsx'
    projected=tmp_path/'projected.xlsx';final=tmp_path/'final.xlsx';reference=tmp_path/'reference.xlsx'
    workbook.write_workbook(template,model,projected)
    engine=require_office_engine();recalculate_workbook(projected,final,engine);recalculate_workbook(projected,reference,engine)
    assert workbook.dual_reopen(final,projected)['cachedValueCount']>0
    audit=workbook.audit_calculated_workbook(final,template,model,engine,expected_layout_path=projected,reference_path=reference)
    assert audit.task_count==1 and audit.story_count==2
    b=openpyxl.load_workbook(final,data_only=True)
    try:
        rows=workbook.table_records(b,'SOWStoryTable')
        assert [row['校验结果'] for row in rows]==['通过','通过']
        assert all('订单查询页面' in row['任务列表'] for row in rows)
        assert rows[1]['故事人天']==0 and rows[0]['故事人天']>0
    finally:b.close()
