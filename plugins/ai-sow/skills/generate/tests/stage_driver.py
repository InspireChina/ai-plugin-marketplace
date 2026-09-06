"""Pure narrow IR fixture driver; never starts a run or invokes Office/browser."""
from collections import defaultdict
from copy import deepcopy


def stage_result(kind,packet):
    contexts=[ref['canonicalContent'] for ref in packet['contextRefs']]
    dependencies=[body['normalizedResult'] for body in contexts if body.get('kind')=='DEPENDENCY_RESULT']
    if kind=='SOURCE_SCAN':
        return [{'coverageRootId':row['payload']['coverageRootId'],'disposition':'FACT','facts':[{
            'localKey':'fact','factKind':'REQUIREMENT','statement':row['payload']['sourceBlock']['content'],
            'evidenceIds':[row['payload']['coverageRootId']],'qualifiers':[]}]} for row in packet['workItems']]
    if kind=='SOURCE_AUDIT':
        return {'checks':[{'coverageRootId':row['coverageRootId'],'category':category,'decision':'COVERED',
            'relatedFactKeys':[fact['localKey'] for fact in row['facts']],'evidenceIds':[row['coverageRootId']]}
            for scan in dependencies for row in scan for category in ('THRESHOLD','NEGATION','EXCLUSION','EXCEPTION','ROLE','TIME')]}
    if kind in {'SCOPE_SYNTHESIS','SCOPE_PROPOSAL'}:
        scans=[row for dependency in dependencies if isinstance(dependency,list) for row in dependency]
        roots=[row['coverageRootId'] for row in scans]
        facts=[row['coverageRootId']+':'+fact['localKey'] for row in scans for fact in row['facts']]
        def decision(key,kind,facts,relations,name,classification='BUSINESS'):
            return {'localKey':key,'decisionKind':kind,'factIds':facts,'priorEntityIds':[],
                'boundaryEvidence':{'name':name,'classification':classification,'evidenceIds':roots,'facetFacts':[],'observationKeys':[]},
                'relations':relations}
        def relation(kind,keys): return {'kind':kind,'targetLocalKeys':keys,'evidenceIds':roots}
        rows=[decision('epic','EPIC',[],[],'订单管理'),decision('feature','FEATURE',facts,[relation('PARENT',['epic'])],'订单查询')]
        for policy in ('policy-sit-automation','policy-uat-automation','policy-go-live'):
            rows.append(decision(policy,'POLICY_INSTANCE',[],[relation('APPLIES_TO',['feature'])],policy,policy))
        return {'decisions':rows}
    if kind=='STORY_AC':
        groups=defaultdict(list)
        for row in packet['workItems']:
            obligation=row['payload']['obligation']
            groups[(obligation['featureId'],obligation['storyBoundaryKey'])].append(row['payload'])
        result=[]
        for number,rows in enumerate(groups.values()):
            facts=sorted({key for row in rows for key in row['obligation']['sourceFactIds']})
            outcome={'policy-sit-automation':'自动集成验证','policy-uat-automation':'自动验收验证',
                'policy-go-live':'部署与回退'}.get(rows[0]['obligation'].get('policyId'),'订单查询')
            assert len(facts)>=2,'fixture needs distinct source anchors for two independently identified AC'
            result.append({'localKey':'story-'+str(number),'scopeDecisionKeys':[row['scopeDecisionKey'] for row in rows],
                'actorKey':facts[0],'deliverableOutcome':'用户可验收'+outcome,'sourceFactIds':facts,
                'acceptanceCriteria':[{'localKey':'success','condition':outcome+'成功条件','observableResult':'返回成功结果','sourceFactIds':facts[:1]},
                    {'localKey':'empty','condition':outcome+'失败条件','observableResult':'显示失败原因','sourceFactIds':facts[1:]}]})
        return {'stories':result}
    if kind=='TASK':
        targets=[body for body in contexts if body.get('kind')=='TASK_TARGET']
        stories=defaultdict(list)
        for row in packet['workItems']: stories[row['payload']['storyLocalKey']].append(row['payload'])
        result=[]
        for number,(key,criteria) in enumerate(stories.items()):
            applicable=[target for target in targets if key in target['storyKeys']]
            policies=[target for target in applicable if target['targetKind']=='POLICY_INSTANCE']
            selected=policies or [target for target in applicable if target['targetKind']=='USER_INTERFACE'][:1]
            for target in selected:
                result.append({'localKey':'task-'+str(number)+'-'+str(len(result)),'storyLocalKey':key,
                    'acceptanceCriterionKeys':[item['acceptanceCriterionKey'] for item in criteria],
                    'technicalTarget':target['targetKey'],'workTypeId':'ENG-PIPELINE' if policies else 'FE-VIEW',
                    'deliverableBoundary':'一套可独立移交和验证的工程化产物' if policies else '一张可查询订单的页面',
                    'workModeDecision':'新建','complexityDecision':'M','evidenceIds':target['evidenceIds']})
        return {'tasks':result}
    if kind in {'SOURCE_SCOPE','STORY_DESIGN','TASK_ESTIMATION'}: return {'decision':'PASS','findings':[]}
    if kind=='ARTIFACT_VISUAL_REVIEW':
        return {'sheets':[{'sheetKey':key,'checks':{name:'PASS' for name in ('clipping','readability','unexpectedBlank','styleLoss')},'decision':'PASS','findings':[]} for key in packet['workItems'][0]['payload']['visibleSheets']], 'overallDecision':'PASS'}
    raise AssertionError('Unsupported fixture action '+kind)
