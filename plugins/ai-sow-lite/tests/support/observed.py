"""Build a registered analysis whose topic carries a real observation.

Platform independent: it writes the immutable state the prototype ingest path
would have produced, without needing POSIX directory-fd reads. That lets the
observation-provenance boundary be exercised on Windows too; macOS additionally
covers the full public registration path in test_prototype_records.
"""
import hashlib
from pathlib import Path
from uuid import uuid4

from ai_sow_lite.contracts import canonical_json_bytes
from ai_sow_lite.project import atomic_bytes, safe_path


def _write(project, relative, value):
    raw = canonical_json_bytes(value)
    atomic_bytes(safe_path(project, relative), raw)
    return dict(path=relative, sha256=hashlib.sha256(raw).hexdigest())


def seed_observed_topic(project, *, observations=1):
    """Register one topic bound to `observations` immutable observation records."""
    input_version = str(uuid4())
    refs, identities = [], []
    for _ in range(observations):
        identity = str(uuid4())
        area = f'.ai-sow-lite/analysis/observations/{identity}'
        record = dict(
            schema_version='1.0', observation_id=identity, input_version_id=input_version,
            entrypoint='generate', preconditions='合成登记状态，不代表真实浏览器观察。',
            actions=['打开合成原型入口'], observed_at='2026-09-14T00:00:00Z',
            result='合成结果记录，仅用于来源一致性边界。', resource_refs=[], attachments=[],
            limitations='不证明真实后端或生产能力。')
        ref = _write(project, area + '/observation.json', record)
        _write(project, area + '/registration-ref.json', ref)
        refs.append(ref)
        identities.append((identity, ref['sha256']))

    evidence = [dict(id=str(uuid4()), kind='observation', text='合成依据，仅测试不可变来源。',
                     source_refs=[dict(input_version_id=input_version,
                                       locator=dict(kind='observation', observation_id=identities[0][0]),
                                       excerpt_hash=identities[0][1])],
                     basis_refs=[], limitations='不证明业务语义。')]
    topic = dict(topic_id=str(uuid4()), topic_version_id=str(uuid4()), title='机械记录',
                 input_version_ids=[input_version], uses=['to-be-scope'],
                 covered_regions=[], uncovered_regions=[],
                 evidence_refs=[evidence[0]['id']], related_object_ids=[],
                 external_responsibilities='', limitations='合成主题。',
                 conclusion='合成结论，仅用于来源一致性边界。', historical_items=[])
    registration = dict(schema_version='1.0', evidence=evidence, topics=[topic], observations=refs)

    raw = canonical_json_bytes(registration)
    digest = hashlib.sha256(raw).hexdigest()
    registration_relative = f'.ai-sow-lite/analysis/registrations/{digest}/analysis.json'
    atomic_bytes(safe_path(project, registration_relative), raw)
    registration_ref = dict(path=registration_relative, sha256=digest)

    directory = f".ai-sow-lite/analysis/topics/{topic['topic_version_id']}"
    _write(project, directory + '/registration-ref.json', registration_ref)
    record_ref = _write(project, directory + '/analysis.json', dict(
        schema_version='1.0', topics=[topic], evidence=evidence, observations=refs))
    _write(project, '.ai-sow-lite/analysis/index.json', dict(schema_version='1.0', items=[record_ref]))
    return dict(topic=topic, record=safe_path(project, directory + '/analysis.json'),
                index=safe_path(project, '.ai-sow-lite/analysis/index.json'),
                registration=registration, observation_refs=refs)
