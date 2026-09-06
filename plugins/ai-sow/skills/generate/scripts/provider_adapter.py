from __future__ import annotations

import json
from types import MappingProxyType

from models import canonical_json_bytes


MODEL_PROFILE_ESTIMATORS = MappingProxyType({
    "host-canonical-messages-v1": frozenset({"utf8-bytes-v1"}),
})


def validate_model_estimator(model_profile_id: str, estimator_version: str) -> None:
    if estimator_version not in MODEL_PROFILE_ESTIMATORS.get(model_profile_id, ()):
        raise ValueError("modelProfileId 未注册或 estimatorVersion 不属于该 profile。")


def pack_lossless_tables(packet: bytes) -> dict:
    """Factor repeated object keys, preserving every value and original JSON path."""
    import hashlib
    value=json.loads(packet)
    original=canonical_json_bytes(value)
    tables=[]

    def visit(node,path):
        if isinstance(node,dict):
            return {key:visit(child,[*path,key]) for key,child in node.items()}
        if not isinstance(node,list): return node
        children=[visit(child,[*path,index]) for index,child in enumerate(node)]
        if len(children)<3 or not all(isinstance(child,dict) for child in children): return children
        columns=sorted(children[0])
        if len(columns)<2 or any(sorted(child)!=columns for child in children): return children
        rows=[[child[key] for key in columns] for child in children]
        table={'path':path,'columns':columns}
        if len(canonical_json_bytes(rows))+len(canonical_json_bytes(table))>=len(canonical_json_bytes(children)): return children
        tables.append(table)
        return rows

    compact=visit(value,[])
    result={'transportEncoding':'ai-sow-lossless-tables-v1','packetSha256':hashlib.sha256(original).hexdigest(),
        'packet':compact,'tables':sorted(tables,key=lambda item:canonical_json_bytes(item['path']))}
    if unpack_lossless_tables(result)!=original: raise ValueError('无损表格传输无法还原原 packet。')
    return result


def unpack_lossless_tables(value: dict) -> bytes:
    import hashlib
    from copy import deepcopy
    if (not isinstance(value,dict) or set(value)!={'transportEncoding','packetSha256','packet','tables'}
            or value['transportEncoding']!='ai-sow-lossless-tables-v1' or not isinstance(value['tables'],list)):
        raise ValueError('无损表格传输格式无效。')
    result=deepcopy(value['packet']);seen=set()
    for table in sorted(value['tables'],key=lambda item:len(item['path'])):
        if set(table)!={'path','columns'} or not isinstance(table['path'],list) or not isinstance(table['columns'],list):
            raise ValueError('表格索引无效。')
        path,columns=table['path'],table['columns']
        key=canonical_json_bytes(path)
        if key in seen or not columns or any(not isinstance(name,str) for name in columns) or len(set(columns))!=len(columns):
            raise ValueError('表格路径或列重复。')
        seen.add(key)
        parent=None;rows=result
        try:
            for part in path:
                if type(part) not in (str,int): raise ValueError('表格路径类型无效。')
                parent=rows;rows=rows[part]
        except (KeyError,IndexError,TypeError) as error: raise ValueError('表格路径无效。') from error
        if not isinstance(rows,list) or any(not isinstance(row,list) or len(row)!=len(columns) for row in rows):
            raise ValueError('表格行列不完整。')
        decoded=[dict(zip(columns,row,strict=True)) for row in rows]
        if path: parent[path[-1]]=decoded
        else: result=decoded
    raw=canonical_json_bytes(result)
    if hashlib.sha256(raw).hexdigest()!=value['packetSha256']: raise ValueError('还原 packet hash 不一致。')
    return raw

def canonical_provider_request(
    model_profile_id: str, instruction: str, packet: bytes, max_output_tokens: int,
    hydration_responses=(), *, lossless_tables=False,
) -> bytes:
    if model_profile_id not in MODEL_PROFILE_ESTIMATORS:
        raise ValueError("modelProfileId 未注册。")
    if not isinstance(instruction, str) or type(max_output_tokens) is not int or max_output_tokens < 0:
        raise ValueError("请求 instruction 或 maxOutputTokens 无效。")
    body=canonical_json_bytes(json.loads(packet)).decode('utf-8')
    if lossless_tables:
        packed=pack_lossless_tables(packet)
        compact=canonical_json_bytes(packed).decode('utf-8')
        if len(compact.encode())<len(body.encode()):
            body=compact
            instruction+='\n输入使用 ai-sow-lossless-tables-v1 无损表示。tables 中 path 指原 JSON 路径，columns 与 packet 中对应二维数组逐行 zip 后还原对象；先还原父路径，再还原子路径。所有值、旧结果和证据均保留，packetSha256 绑定完整还原结果。按还原后的原字段含义判断，输出仍用原结果 schema。'
    return canonical_json_bytes({
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": body},
            *[{"role": "user", "content": canonical_json_bytes(response).decode("utf-8")}
              for response in hydration_responses],
        ],
        "maxOutputTokens": max_output_tokens,
    })


def estimate_provider_request(
    model_profile_id: str, estimator_version: str, request: bytes
) -> int:
    value = json.loads(request)
    if not isinstance(value, dict) or set(value) != {"messages", "maxOutputTokens"}:
        raise ValueError("estimator 只接受完整 provider request。")
    return estimate_canonical_transport(model_profile_id, estimator_version, request)


def estimate_canonical_transport(
    model_profile_id: str, estimator_version: str, payload: bytes
) -> int:
    validate_model_estimator(model_profile_id, estimator_version)
    if canonical_json_bytes(json.loads(payload)) != payload:
        raise ValueError("estimator 只接受 canonical transport bytes。")
    return len(payload)
