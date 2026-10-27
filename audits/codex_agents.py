#!/usr/bin/env python3
"""Generate/check Codex custom roles from the canonical Claude reviewer and protocol sources."""
import sys
sys.dont_write_bytecode=True
import argparse, hashlib, json, re, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROLES={'formalize_auditor':'reviewer lane', 'formalize_adjudicator':'independent adjudicator',
       'formalize_informalizer':'blind informalizer', 'formalize_reader':'fresh document reader',
       'formalize_writer':'sign-off writer'}
DEFAULT_MODEL='gpt-6.1-sol'


def generated(source=HERE,model=DEFAULT_MODEL):
    source=Path(source)
    auditor=(source/'agents/auditor.md').read_text()
    auditor=re.sub(r'\A---\n.*?\n---\n','',auditor,count=1,flags=re.S).strip()
    protocol=(source/'AUDIT_PROTOCOL.md').read_text()
    start=protocol.index('### Common rules for every other subagent')
    start=protocol.index('```\n',start)+4;end=protocol.index('\n```',start)
    common=protocol[start:end].replace('<NETWORK-RULE>','Follow the network rule in your generated task file.')
    result={}
    for name,desc in ROLES.items():
        body=auditor if name=='formalize_auditor' else common
        result[name+'.toml']=('name = '+json.dumps(name)+'\ndescription = '+json.dumps(desc)+
                             '\nmodel = '+json.dumps(model)+'\nmodel_reasoning_effort = "medium"\n'+
                             'developer_instructions = '+json.dumps(body)+'\n')
    return result


def state(directory,source=HERE):
    """Validate deterministic derivation, then return exactly the installed bytes' hashes."""
    directory=Path(directory)
    if not directory.exists():return None
    first=directory/'formalize_auditor.toml'
    if not first.exists():raise ValueError('Codex roles incomplete: missing '+str(first))
    match=re.search(r'^model = (".*")$',first.read_text(),re.M)
    if not match:raise ValueError('Codex auditor model is missing')
    model=json.loads(match.group(1));expected=generated(source,model)
    for name,body in expected.items():
        path=directory/name
        if not path.exists() or path.read_text()!=body:
            raise ValueError('Codex role differs from canonical source: '+str(path))
    return {'model':model,'sha256':{name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in expected}}


def install(directory,source=HERE,model=DEFAULT_MODEL):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    for name,body in generated(source,model).items():
        path=directory/name
        if path.exists() and path.read_text()!=body:
            raise ValueError('refusing to overwrite existing different role: '+str(path))
        path.write_text(body)
    return state(directory,source)


def selftest():
    good=[]
    def say(n,ok):good.append(ok);print(('  ok    ' if ok else '  FAIL  ')+n)
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);s=d/'source';(s/'agents').mkdir(parents=True)
        (s/'agents/auditor.md').write_text('---\nname: auditor\n---\nReviewer canonical instructions.\n')
        (s/'AUDIT_PROTOCOL.md').write_text('### Common rules for every other subagent\n\n```\nCOMMON RULES\n<NETWORK-RULE>\n```\n')
        roles=d/'roles';first=install(roles,s)
        say('exactly five named roles',len(first['sha256'])==5)
        text=(roles/'formalize_auditor.toml').read_text()
        say('canonical body without Claude front matter', 'Reviewer canonical instructions.' in text and 'name: auditor' not in text)
        say('all roles use medium reasoning',all('model_reasoning_effort = "medium"' in p.read_text() for p in roles.glob('*.toml')))
        say('chosen model is pinned',first['model']==DEFAULT_MODEL)
        target=roles/'formalize_reader.toml';old=target.read_text();target.write_text(old+'# changed\n')
        try:state(roles,s);caught=False
        except ValueError:caught=True
        say('role edit is caught',caught);target.write_text(old)
        (s/'agents/auditor.md').write_text('Different canonical reviewer.')
        try:state(roles,s);caught=False
        except ValueError:caught=True
        say('source drift is caught',caught)
    print('selftest: '+('ok' if all(good) else 'FAILED'));return 0 if all(good) else 1


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--install');ap.add_argument('--check');ap.add_argument('--model',default=DEFAULT_MODEL);ap.add_argument('--selftest',action='store_true');a=ap.parse_args()
    if a.selftest:return selftest()
    try:
        if a.install:doc=install(a.install,model=a.model)
        elif a.check:doc=state(a.check)
        else:ap.error('give --install or --check')
        print(json.dumps(doc,indent=2));return 0
    except (OSError,ValueError) as e:print('STOP: '+str(e),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
