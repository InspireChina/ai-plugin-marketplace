"""Reusable native-QA fixtures. Executes genuine ingest/check/render; never mocks Office."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import uuid4

if __package__ in (None,''):
    sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'runtime'),str(Path(__file__).resolve().parents[2])]
    from tests.support.fixtures import build_ingested_case,read_json,write_json
    from tests.support.cli import run_request
else:
    from .fixtures import build_ingested_case,read_json,write_json
    from .cli import run_request


def medium_list_model(model):
    """Review I-2: short inputs and three medium names with no other row-height demand."""
    model=deepcopy(model)
    story=model['stories'][0];story.update(title='故事',notes='')
    story['acs']=story['acs'][:1];story['acs'][0]['text']='通过。'
    feature=next(f for f in model['features'] if f['id']==story['feature_id'])
    epic=next(e for e in model['epics'] if e['id']==feature['epic_id'])
    epic['title']='需求';feature['title']='功能'
    prototype=model['tasks'][0]
    model.update(epics=[epic],features=[feature],stories=[story],dependencies=[],lineage=[],tasks=[
        dict(deepcopy(prototype),id=str(uuid4()),story_id=story['id'],
             name=f'测试任务长名称用于检验故事任务列表可读性{i}',notes='') for i in range(3)])
    return model


def prepare_case(project, variant='representative', *, render=True):
    project=Path(project).resolve()
    case=build_ingested_case(project)
    if variant=='expanded':
        model=read_json(case.file('model.json'))
        prototype=deepcopy(model['stories'][0]); task=deepcopy(model['tasks'][0])
        while len(model['stories'])<61:
            story=deepcopy(prototype); story['id']=str(uuid4()); story['title']=f'扩展故事 {len(model["stories"])+1}'
            for ac in story['acs']: ac['id']=str(uuid4())
            model['stories'].append(story)
        names=['查询~*?订单','CASE','case','é','e\u0301','=SUM(A1:A9)','😀'*61]
        for story,name in zip(model['stories'],names): story['title']=name
        model['stories'][0]['acs'][0]['text']='完整验收条件😀\n'*6000
        for story in model['stories']:
            if not any(t['story_id']==story['id'] for t in model['tasks']):
                model['tasks'].append(dict(deepcopy(task),id=str(uuid4()),story_id=story['id'],name=f'扩展任务 {len(model["tasks"])+1}'))
        while len(model['tasks'])<201:
            model['tasks'].append(dict(deepcopy(task),id=str(uuid4()),story_id=model['stories'][0]['id'],name=f'任务清单长文本 {len(model["tasks"])+1}'))
        model['tasks'][0]['name']='=SUM(A1:A9)'
        model['tasks'][0]['notes']='=SUM(A1:A9)'
        model['tasks'][1]['notes']='保留完整备注\n'*6000
        write_json(case.file('model.json'),model)
    elif variant=='medium-list':
        model=medium_list_model(read_json(case.file('model.json')))
        write_json(case.file('model.json'),model)
        for name in ['pending-items.json','decisions.json']:
            write_json(case.file(name),dict(schema_version='1.0',items=[]))
        # Register a new test analysis for this smaller scope; never mutate the
        # already registered topics or leave their removed-object references.
        analysis=read_json(case.file('analysis.json'))
        identities={o['id'] for key in ['epics','features','stories','tasks'] for o in model[key]}
        identities.update(ac['id'] for story in model['stories'] for ac in story['acs'])
        for topic in analysis['topics']:
            topic.update(topic_id=str(uuid4()),topic_version_id=str(uuid4()),
                         related_object_ids=[i for i in topic['related_object_ids'] if i in identities])
        write_json(case.file('medium-analysis.json'),analysis)
        registered=run_request(project,case.request_id,'ingest',dict(kind='analysis',entrypoint='generate',
            analysis_path=case.file('medium-analysis.json').relative_to(project).as_posix()))
        assert registered['ok'],registered
        candidate=read_json(case.candidate_path)
        candidate['topic_version_ids']=[t['topic_version_id'] for t in analysis['topics']]
        write_json(case.candidate_path,candidate)
    elif variant!='representative':
        raise ValueError('Unknown fixture variant')
    relative=case.candidate_path.relative_to(project).as_posix()
    checked=run_request(project,case.request_id,'check',dict(candidate_path=relative,scope='full',plan_path=None))
    assert checked['ok'],checked
    payload=dict(candidate_path=relative,check_path=checked['result']['check_ref']['path'],expected_current=None)
    write_json(case.file('render-request.json'),dict(protocol_version='1.0',request_id=case.request_id,
        project_path=str(project),operation='render',payload=payload))
    result=run_request(project,case.request_id,'render',payload) if render else None
    return case,payload,result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True)
    parser.add_argument('--variant',choices=['representative','expanded','medium-list'],default='representative')
    args=parser.parse_args()
    case,payload,result=prepare_case(args.project,args.variant)
    print(json.dumps(dict(project=str(case.project),request_id=case.request_id,result=result),ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['ok'] else 1)
