#!/usr/bin/env python3
"""Generate/check Codex custom roles from the canonical Claude reviewer and protocol sources."""
import sys
sys.dont_write_bytecode=True
import argparse, hashlib, json, re, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROLES={'formalize_auditor':'reviewer lane', 'formalize_adjudicator':'independent adjudicator',
       'formalize_informalizer':'blind informalizer', 'formalize_reader':'fresh document reader',
       'formalize_writer':'sign-off writer', 'formalize_escalation':'escalation check',
       'formalize_renderer':'PDF renderer, verifier and checker (render_record.py)',
       'formalize_tool_patch_reviewer':'fresh reviewer of a tool patch (tool_patch.py; release mode)',
       'formalize_status_check':'advisory status check of the summary against the report and records (delivery)',
       'formalize_citations':'citation notes, agent 1 (draft) and agent 2 (review)',
       'formalize_helper':'author-side helper (statements or proofs; never a reviewer)'}
DEFAULT_MODEL='gpt-6.1-sol'
# CODEX-PORT test (a citation child asked the person to approve a download): Codex children run in the parent's
# sandbox, where the network is off and only the project is writable. Appended to every role (Codex only; the
# Claude prompts are unchanged).
SANDBOX_RULE=('Codex sandbox: you run inside the session\'s sandbox (no network; only the project and the temporary '
              'directory are writable). Never request an approval or escalation to run a command outside it or with '
              'the network, whatever your task file allows: a command the sandbox blocks is a failure you record in '
              'your output (for a source you could not read: "not reachable"), never a question to the person.')


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
        body=(auditor if name=='formalize_auditor' else common)+'\n\n'+SANDBOX_RULE
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


# CODEX-PORT: every agent kind the protocol spawns maps to a generated role. A spawn instruction in a script
# ("spawn ... with: <line>") names its Codex role (or prints one through prompt.spawn_kind); every role named in a
# script or an instruction file is one this module generates; and every generated role is spawned somewhere.
SPAWN_RE=re.compile(r'\bspawn\b(?:(?!\bspawn\b)[^\n]){0,160}?\bwith(?: exactly)?:\s',re.I)
ROLE_NAME_RE=re.compile(r'\bformalize_[a-z_]+\b')


def spawn_coverage(audits=HERE,spawn_roles=None):
    """Problems (strings) with the spawn-to-role map of the scripts and instruction files under `audits`."""
    audits=Path(audits);probs=[];named=set(spawn_roles or ())
    consts={}
    for f in sorted(audits.glob('*.py')):
        if f.name in ('codex_spawn.py','codex_agents.py'):continue
        src=f.read_text(errors='replace')
        for m in re.finditer(r'(?m)^([A-Z_]+)\s*=\s*["\'](formalize_[a-z_]+)["\']',src):consts[m.group(1)]=m.group(2)
        joined=re.sub(r'''["']\s*\n\s*[fr]?["']''','',src)   # implicitly concatenated literals as one
        joined=joined.replace('\\n','\n')    # a literal's "\n" ends a printed line (e.g. "...:\nSpawn ... with exactly:\n")
        for m in SPAWN_RE.finditer(joined):
            w=m.group(0)
            r=re.search(r'Codex: agent_type \{?([A-Za-z_]+)\}?',w)
            if r:
                role=consts.get(r.group(1),r.group(1));named.add(role)
                if role not in ROLES:probs.append(f'{f.name}: a spawn line names {role}, which is not a generated role')
            elif 'spawn_kind(' not in w:
                probs.append(f'{f.name}: a spawn line names no Codex role: {w[:100]!r}')
    for f in sorted(list(audits.glob('*.py'))+list(audits.rglob('*.md'))):
        if f.name=='codex_agents.py' or 'tests' in f.relative_to(audits).parts:continue
        for role in set(ROLE_NAME_RE.findall(f.read_text(errors='replace'))):
            if role not in ROLES:probs.append(f'{f.relative_to(audits)}: names {role}, which is not a generated role')
    for role in sorted(set(ROLES)-named):
        probs.append(f'the generated role {role} is never spawned (no spawn line names it)')
    return probs


def prompt_spawn_roles():
    """The roles prompt.py's spawn_kind prints for its generated subagent prompts."""
    import prompt
    return {prompt.spawn_kind(k).split('agent_type ')[1].split(',')[0] for k in prompt.EXTRA_PROMPTS
            if 'agent_type ' in prompt.spawn_kind(k)}


def selftest():
    good=[]
    def say(n,ok):good.append(ok);print(('  ok    ' if ok else '  FAIL  ')+n)
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);s=d/'source';(s/'agents').mkdir(parents=True)
        (s/'agents/auditor.md').write_text('---\nname: auditor\n---\nReviewer canonical instructions.\n')
        (s/'AUDIT_PROTOCOL.md').write_text('### Common rules for every other subagent\n\n```\nCOMMON RULES\n<NETWORK-RULE>\n```\n')
        roles=d/'roles';first=install(roles,s)
        say('exactly eleven named roles: the escalation check, the PDF renderer, the tool-patch reviewer, the status check, the citation agents and the helper among them (C18; PDF-AGENTS; OPERATOR-PATCH; DOC-FIX; CODEX-U2; no stall resolver)',
            len(first['sha256'])==11 and all(r+'.toml' in first['sha256'] for r in
            ('formalize_escalation','formalize_renderer','formalize_tool_patch_reviewer','formalize_status_check',
             'formalize_citations','formalize_helper'))
            and 'formalize_resolver.toml' not in first['sha256'])
        say('no role turns on the network or changes the sandbox (intake 1c: the task file carries the network rule)',
            all(not re.search(r'(?m)^(web_search|sandbox_mode|sandbox_workspace_write|approval_policy|tools)\b', p.read_text())
                for p in roles.glob('*.toml')))
        text=(roles/'formalize_auditor.toml').read_text()
        say('every role tells its child never to ask for an approval to leave the sandbox (CODEX-PORT test: a citation child asked to download)',
            all(json.dumps(SANDBOX_RULE)[1:-1] in p.read_text() for p in roles.glob('*.toml')))
        say('canonical body without Claude front matter', 'Reviewer canonical instructions.' in text and 'name: auditor' not in text)
        say('all roles use medium reasoning',all('model_reasoning_effort = "medium"' in p.read_text() for p in roles.glob('*.toml')))
        say('chosen model is pinned',first['model']==DEFAULT_MODEL)
        target=roles/'formalize_reader.toml';old=target.read_text();target.write_text(old+'# changed\n')
        try:state(roles,s);caught=False
        except ValueError:caught=True
        say('role edit is caught',caught);target.write_text(old)
        inst=Path(__file__).resolve().parent.parent/'codex'/'install-codex.sh'
        if inst.exists():   # the clone (an installed project has no codex/): the install message counts the roles it installed
            ln=[l for l in inst.read_text().splitlines() if 'generated project roles installed' in l]
            say('install-codex.sh states the role count from the installed files, never a typed number (safety review LOW 5)',
                len(ln)==1 and 'formalize_*.toml' in ln[0] and 'wc -l' in ln[0])
        (s/'agents/auditor.md').write_text('Different canonical reviewer.')
        try:state(roles,s);caught=False
        except ValueError:caught=True
        say('source drift is caught',caught)
        if (HERE/'prompt.py').exists():
            probs=spawn_coverage(HERE,prompt_spawn_roles())
            for p_ in probs:print('        '+p_)
            say('every agent kind the protocol spawns names a generated Codex role, and every role is spawned (CODEX-PORT)',not probs)
        a2=d/'audits';a2.mkdir()
        (a2/'x.py').write_text('print(f"  spawn (general-purpose) with: {line}")\nprint("spawn one (Codex: agent_type formalize_nobody, fork_turns none) with: "+l)\n')
        (a2/'y.md').write_text('Spawn it as `formalize_ghost`.\n')
        bad=spawn_coverage(a2,set(ROLES))
        say('control: a spawn line with no role, an unknown role and an unknown role in the text are each caught',
            sum('names no Codex role' in b for b in bad)==1 and any('formalize_nobody, which is not' in b for b in bad)
            and any(b.startswith('y.md: names formalize_ghost') for b in bad))
        bad2=spawn_coverage(a2,set(ROLES)-{'formalize_helper'})
        say('control: a generated role nobody spawns is caught',any('formalize_helper is never spawned' in b for b in bad2))
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

if __name__=='__main__':
    import project
    raise SystemExit(project.run_main(main))
