"""One process, one canonical request; synthetic IR, never real provider evidence."""
import hashlib
import json
import os
from pathlib import Path
import sys

PLUGIN = Path(__file__).resolve().parents[2]
SKILL = PLUGIN / 'skills/generate'
for path in (PLUGIN, SKILL / 'scripts', SKILL / 'tests'):
    sys.path.insert(0, str(path))
from contracts import canonical_json_bytes
from stage_driver import stage_result
from test_scope_compiler import scope_owner_result


def main():
    invocation = json.loads(sys.stdin.buffer.read())
    if set(invocation) != {'request', 'kind'}:
        raise ValueError('one request and action kind only; no history accepted')
    request = invocation['request']
    if set(request) != {'messages', 'maxOutputTokens'}:
        raise ValueError('invalid canonical request')
    if [message['role'] for message in request['messages']] != ['system', 'user']:
        raise ValueError('fixture host must receive a fresh request')
    if type(request['maxOutputTokens']) is not int or request['maxOutputTokens'] <= 0:
        raise ValueError('missing output limit')
    kind = invocation['kind']
    packet = json.loads(request['messages'][1]['content'])
    result = scope_owner_result(kind, packet) if kind.startswith('PRIOR_') else stage_result(kind, packet)
    sys.stdout.buffer.write(canonical_json_bytes({
        'result': result,
        'invocation': {'pid': os.getpid(), 'contextMode': 'FRESH_NO_HISTORY',
                       'requestSha256': hashlib.sha256(canonical_json_bytes(request)).hexdigest(),
                       'maxOutputTokens': request['maxOutputTokens'],
                       'actualProviderVerified': False},
    }))


if __name__ == '__main__':
    main()
