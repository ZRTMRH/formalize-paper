#!/usr/bin/env python3
"""Spawn-only lane tokens and owner-returned completion seals, shared by Claude and Codex.

issue prints the token ONLY in the generated spawn message, never in the prompt/commitment file.
The token is NOT a secret from sibling lanes: the spawn message sits in the parent's transcript,
which a sandboxed sibling can read, and the verdict publishes it. What binds a verdict to its lane
is the owning agent's in-memory digest, returned in its own completion message, and the seal
committed from it. Never seal by trusting a digest freshly read from disk after the owner has
finished. Seals are committed alone, one at a time (a lock on the audit repository), and compared
with their FIRST committed bytes on every check. A commitment may change only through `reissue`
(a lane whose spawn line was lost before it was sealed), committed as
"scope <R> (reissue <lane>: <reason>)"; only the newest commitment counts.
This detects persistent verdict replacement, not a transient write subsequently restored, and not
a rewrite of the audit repository's history (see KNOWN_LIMITATIONS.md).

  lane_auth.py issue --prompt FILE
  lane_auth.py seal --verdict FILE --sha256 HEX --agent-id ID
  lane_auth.py reissue (--verdict FILE | --round R --lane LANE) --reason TEXT
  lane_auth.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import argparse, contextlib, fcntl, hashlib, json, os, re, secrets, subprocess, tempfile, threading
from pathlib import Path

COMMIT_LOCK = threading.Lock()

class AuthError(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if r.returncode:
        raise AuthError('git failed: ' + r.stderr.strip())
    return r.stdout.strip()


def locations(verdict):
    verdict = Path(verdict).resolve()
    rd = verdict.parent.parent if verdict.parent.name == 'revote' else verdict.parent
    rel = verdict.relative_to(rd)
    # lane verdicts: <lane>.json, <lane>@<part>.json; re-votes: revote/<lane>--<item slug>.json
    if not re.fullmatch(r'(?:[a-z-]+(?:@\d+)?|revote/[a-z-]+--[A-Za-z0-9_.-]+)\.json', rel.as_posix()):
        raise AuthError('invalid lane verdict path')
    return rd, rel, rd / '.lane-auth' / rel, rd / '.lane-seals' / rel


def audit_repo(rd):
    return Path(git(rd, 'rev-parse', '--show-toplevel'))


@contextlib.contextmanager
def repo_lock(repo):
    """One metadata commit at a time across processes: parallel seal commands used to race on
    git's index.lock, leaving a seal file written but uncommitted (and the lane unsealable)."""
    gd = Path(git(repo, 'rev-parse', '--absolute-git-dir'))
    with COMMIT_LOCK, open(gd / 'formalize-paper-lane-auth.lock', 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def commit_paths(repo, paths, subject):
    rels = [Path(p).resolve().relative_to(repo).as_posix() for p in paths]
    git(repo, 'add', '--', *rels)
    git(repo, 'commit', '--only', '-m', subject, '--', *rels)
    return git(repo, 'rev-parse', 'HEAD')


def save_once(path, doc, subject):
    path.parent.mkdir(parents=True, exist_ok=True)
    repo = audit_repo(path.parent)
    with repo_lock(repo):
        # Exclusive creation: a completed seal/commitment cannot silently be replaced.
        with path.open('x', encoding='utf-8') as f:
            json.dump(doc, f, sort_keys=True, indent=2); f.write('\n')
        try:
            return commit_paths(repo, [path], subject)
        except AuthError:
            # an uncommitted seal would block every later attempt to seal this lane
            with contextlib.suppress(OSError):
                git(repo, 'reset', '-q', '--', path.relative_to(repo).as_posix())
            path.unlink()
            raise


def original_doc(path, reissue_round=None):
    """The committed metadata document. A seal must equal its FIRST commit. A commitment may
    also have been replaced by `reissue` commits (and nothing else); then its newest commit
    counts, and the file must equal it."""
    repo = audit_repo(path.parent)
    rel = path.relative_to(repo).as_posix()
    commits = git(repo, 'log', '--reverse', '--format=%H', '--diff-filter=A', '--', rel).splitlines()
    if not commits:
        raise AuthError('uncommitted attribution metadata: ' + rel)
    use = commits[0]
    if reissue_round:
        later = git(repo, 'log', '--reverse', '--format=%H %s', commits[0] + '..HEAD', '--', rel).splitlines()
        for line in later:
            h, subj = line.split(' ', 1)
            if not subj.startswith('scope ' + reissue_round + ' (reissue '):
                raise AuthError('attribution metadata changed by a commit that is not a reissue: ' + rel)
            use = h
    original = git(repo, 'show', use + ':' + rel)
    if path.read_text().strip() != original:
        raise AuthError('attribution metadata changed since its ' + ('newest reissue' if use != commits[0] else 'first commit') + ': ' + rel)
    return json.loads(original)


def issue(verdict, prompt):
    rd, rel, commitment, seal = locations(verdict)
    if Path(verdict).exists() or commitment.exists() or seal.exists():
        raise AuthError('lane already issued or has output; do not silently rerun/rekey it: ' + str(rel))
    token = secrets.token_hex(32)
    prompt = Path(prompt).resolve()
    save_once(commitment, {'verdict': rel.as_posix(), 'token_sha256': sha(token.encode()),
                           'prompt': str(prompt), 'prompt_sha256': sha(prompt.read_bytes())}, 'scope ' + rd.name + ' (lane token ' + rel.as_posix() + ')')
    return spawn_line(prompt, token)


def issue_prompt(prompt):
    text = Path(prompt).read_text()
    matches = re.findall(r'Write that JSON object, and nothing else, to (\S+\.json)', text)
    if len(matches) != 1:
        raise AuthError('cannot find exactly one generated verdict path in prompt')
    return issue(matches[0], prompt)


def validate(verdict, expected=None, require_seal=True):
    rd, rel, commitment, seal = locations(verdict)
    try:
        meta = original_doc(commitment, reissue_round=rd.name)
        raw = Path(verdict).read_bytes()
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(meta, dict):
            raise AuthError('verdict and commitment must be JSON objects')
        if sha(Path(meta['prompt']).read_bytes()) != meta['prompt_sha256']:
            raise AuthError('prompt changed since lane token was issued')
        token = data.get('lane_token')
        if meta.get('verdict') != rel.as_posix():
            raise AuthError('commitment belongs to another lane')
        if not isinstance(token, str) or sha(token.encode()) != meta['token_sha256']:
            raise AuthError('lane token does not match its spawn commitment')
        # A copied token cannot authenticate changed contents. The owning child's completion
        # digest (not whatever bytes the parent sees later) establishes expected contents.
        if expected is not None and sha(raw) != expected:
            raise AuthError('verdict differs from owner-returned completion digest')
        if require_seal:
            sealed = original_doc(seal)
            if sealed.get('verdict') != rel.as_posix() or sha(raw) != sealed.get('sha256'):
                raise AuthError('verdict differs from its completion seal')
            if sealed.get('token_sha256') != meta['token_sha256']:
                raise AuthError('seal belongs to another spawn')
        return []
    except (OSError, KeyError, ValueError) as e:
        return [rel.as_posix() + ': ' + str(e)]


def seal(verdict, owner_digest, agent_id):
    if not re.fullmatch('[0-9a-f]{64}', owner_digest) or not agent_id.strip():
        raise AuthError('require owner-returned SHA-256 and originating child id')
    probs = validate(verdict, owner_digest, require_seal=False)
    if probs:
        raise AuthError('; '.join(probs))
    rd, rel, commitment, out = locations(verdict)
    meta = original_doc(commitment, reissue_round=rd.name)
    return save_once(out, {'verdict': rel.as_posix(), 'sha256': owner_digest,
                           'token_sha256': meta['token_sha256'], 'agent_id': agent_id},
                     'seal ' + rd.name + ' ' + rel.as_posix())


def reissue(verdict, reason):
    """A new token for a lane whose spawn line was lost before the lane was sealed (the
    conversation that held it ended). Refused once the lane has a seal. A verdict the lane may
    already have written is moved to `.reissued/` as evidence, never used. Returns the new spawn
    line; the commit is "scope <R> (reissue <lane>: <reason>)"."""
    reason = ' '.join(str(reason or '').split())
    if not reason:
        raise AuthError('a reissue needs a --reason (it is recorded in the commit message)')
    rd, rel, commitment, seal_path = locations(verdict)
    repo0 = audit_repo(rd)
    ever_sealed = seal_path.exists() or git(repo0, 'log', '--all', '--format=%H', '--',
                                            seal_path.relative_to(repo0).as_posix())
    if ever_sealed:
        raise AuthError('lane already sealed (now or earlier in history); a sealed lane is never reissued: '
                        + rel.as_posix())
    meta = original_doc(commitment, reissue_round=rd.name)
    prompt = Path(meta['prompt'])
    if sha(prompt.read_bytes()) != meta['prompt_sha256']:
        raise AuthError('prompt changed since the lane token was issued; not reissued')
    repo = audit_repo(rd)
    token = secrets.token_hex(32)
    n = int(meta.get('reissue', 0)) + 1
    with repo_lock(repo):
        paths = [commitment]
        v = Path(verdict).resolve()
        prev = sha(v.read_bytes()) if v.exists() else 'none (no verdict file existed at the reissue)'
        if v.exists():
            ev = rd / '.reissued' / (rel.as_posix().replace('/', '__') + f'.{n}.json')
            ev.parent.mkdir(parents=True, exist_ok=True)
            os.replace(v, ev)
            paths.append(ev)
        with commitment.open('w', encoding='utf-8') as f:
            json.dump(dict(meta, token_sha256=sha(token.encode()), reissue=n, reason=reason,
                           previous_verdict_sha256=prev),
                      f, sort_keys=True, indent=2); f.write('\n')
        commit_paths(repo, paths, f'scope {rd.name} (reissue {rel.as_posix()}: {reason[:120]})')
    return spawn_line(prompt, token)


def spawn_line(prompt, token):
    return (f'Read the file {prompt} and carry out the task it describes, exactly. '
            f'That file is your complete task; this message adds only lane authentication. '
            f'Your lane_token is {token}. Include it in your verdict. Follow the reviewer '
            f'completion-digest rule; return LANE_COMPLETION with verdict path and sha256.')


def reissues(rd):
    """[(commit, lane, reason, evidence files)] for every reissue in this round, oldest first:
    shown by lanecheck, the adjudicator's block and the report, because a reissue is the one way a
    lane's first answer can be replaced (RUN.md, "Resuming a half-finished round")."""
    rd = Path(rd)
    try:
        repo = audit_repo(rd)
    except AuthError:
        return []
    pre = 'scope ' + rd.name + ' (reissue '
    out = []
    for line in git(repo, 'log', '--reverse', '--format=%H%x09%s', '--', (rd / '.lane-auth').relative_to(repo).as_posix()).splitlines():
        h, _, subj = line.partition('\t')
        if subj.startswith(pre):
            lane, _, reason = subj[len(pre):].rstrip(')').partition(': ')
            files = [f for f in git(repo, 'show', '--name-only', '--format=', h).splitlines() if '/.reissued/' in f]
            out.append((h, lane, reason, files))
    return out


def check_round(rd, verdicts):
    rd = Path(rd)
    probs = []
    expected = {rd / p.relative_to(rd / '.lane-auth') for p in (rd / '.lane-auth').rglob('*.json')}
    for prompt in (rd / 'prompts').glob('*.txt'):
        for path in re.findall(r'Write that JSON object, and nothing else, to (\S+\.json)', prompt.read_text()):
            candidate = Path(path).resolve()
            if candidate.parent == rd or candidate.parent == rd / 'revote':
                expected.add(candidate)
    actual = {Path(p).resolve() for p in verdicts}
    if not expected:
        return ['round has no lane token commitments; unauthenticated round']
    for p in sorted(expected | actual):
        probs.extend(validate(p))
    return probs


def selftest():
    checks = []
    def say(n, ok):
        checks.append(ok); print(('  ok    ' if ok else '  FAIL  ') + n)
    with tempfile.TemporaryDirectory(prefix='lane-auth-') as td:
        d=Path(td); subprocess.run(['git','init','-q',str(d)],check=True)
        git(d,'config','user.name','t');git(d,'config','user.email','t@t')
        (d/'initial').write_text('x');git(d,'add','.');git(d,'commit','-qm','initial')
        rd=d/'2026-10-18-abcdef0';rd.mkdir();prompt=rd/'prompt.txt';prompt.write_text('fixture')
        a=rd/'correspondence.json';b=rd/'paper-faithfulness.json'
        msg_a=issue(a,prompt);msg_b=issue(b,prompt)
        token=lambda msg:re.search(r'lane_token is ([a-f0-9]{64})',msg).group(1)
        ta,tb=token(msg_a),token(msg_b)
        say('separate unpredictable lane tokens',ta!=tb and len(ta)==64)
        say('tokens absent from public metadata and prompt',all(ta not in p.read_text() and tb not in p.read_text() for p in rd.rglob('*') if p.is_file()))
        a.write_text(json.dumps({'lane_token':ta,'summary':'owner'}));good=a.read_bytes();digest=sha(good)
        b.write_text(json.dumps({'lane_token':tb,'summary':'sibling'}));seal(b,sha(b.read_bytes()),'child-b')
        say('missing seal rejects a pending file',bool(validate(a)))
        prompt.write_text('tampered')
        say('prompt edits violate the spawn commitment',any('prompt changed' in x for x in validate(a)))
        prompt.write_text('fixture')
        a.write_text('[]')
        say('non-object verdict rejected',bool(validate(a)))
        a.write_bytes(good)
        a.write_text(json.dumps({'lane_token':tb,'summary':'overwrite'}))
        say('wrong lane token rejected',any('token' in x for x in validate(a,digest,False)))
        a.write_text(json.dumps({'lane_token':ta,'summary':'copied token; overwrite before completion'}))
        try:seal(a,digest,'child-a');caught=False
        except AuthError:caught=True
        say('copied token before completion cannot be sealed',caught)
        if not caught:
            print('selftest: FAILED'); return 1
        a.write_bytes(good);seal(a,digest,'child-a')
        say('clean parallel-issued round passes',check_round(rd,[a,b])==[])
        a.write_text(json.dumps({'lane_token':ta,'summary':'overwrite after completion'}))
        say('copied token after completion violates seal',any('seal' in x for x in validate(a)))
        a.write_bytes(good)
        sealpath=locations(a)[3];saved=sealpath.read_bytes();obj=json.loads(saved);obj['sha256']='0'*64;sealpath.write_text(json.dumps(obj))
        say('seal metadata edits rejected',any('metadata changed' in x for x in validate(a)))
        sealpath.write_bytes(saved)
        try:issue(a,prompt);silent=False
        except AuthError:silent=True
        say('silent reissue refused',silent)
        def later_checks():
            # re-vote verdict paths (revote/<lane>--<item>.json) are lane paths too
            rv=rd/'revote'/'correspondence--P.thm_1_2.json';rv.parent.mkdir()
            msg_r=issue(rv,prompt);rv.write_text(json.dumps({'lane_token':token(msg_r)}))
            try:seal(rv,sha(rv.read_bytes()),'child-r');rv_ok=validate(rv)==[]
            except AuthError:rv_ok=False
            say('a re-vote lane can be issued and sealed',rv_ok)
            # reissue: a lane whose spawn line was lost before it was sealed
            c=rd/'non-vacuity.json';msg_c=issue(c,prompt);tc=token(msg_c)
            c.write_text(json.dumps({'lane_token':tc,'summary':'written before the conversation died'}))
            try:reissue(c,'');noreason=False
            except AuthError:noreason=True
            say('a reissue needs a reason',noreason)
            msg_c2=reissue(c,'conversation ended before sealing');tc2=token(msg_c2)
            moved=list((rd/'.reissued').glob('non-vacuity.json.1.json'))
            subj=git(d,'log','-1','--format=%s')
            say('reissue: new token, old verdict moved to evidence, logged commit',
                tc2!=tc and not c.exists() and len(moved)==1
                and subj=='scope '+rd.name+' (reissue non-vacuity.json: conversation ended before sealing)')
            c.write_text(json.dumps({'lane_token':tc,'summary':'old token'}))
            say('after a reissue the old token is refused (only the newest commitment counts)',
                any('token' in x for x in validate(c,None,False)))
            c.write_text(json.dumps({'lane_token':tc2,'summary':'new spawn'}));seal(c,sha(c.read_bytes()),'child-c2')
            say('the reissued lane seals and validates',validate(c)==[])
            try:reissue(c,'again');resealed=False
            except AuthError:resealed=True
            say('a sealed lane is never reissued',resealed)
            t_=rd/'tamper.json';m_t=issue(t_,prompt);t_.write_text(json.dumps({'lane_token':token(m_t)}))
            cm=locations(t_)[2];doc=json.loads(cm.read_text());doc['token_sha256']=sha(b'x')
            cm.write_text(json.dumps(doc));git(d,'add','-A');git(d,'commit','-qm','scope '+rd.name+' tidy')
            say('a commitment changed by any commit other than a reissue is refused',
                any('not a reissue' in x for x in validate(t_,None,False)))
            # a failed seal commit leaves no seal file behind (the lane stays sealable)
            e=rd/'substantiveness.json';msg_e=issue(e,prompt);e.write_text(json.dumps({'lane_token':token(msg_e)}))
            hook=d/'.git'/'hooks'/'pre-commit';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o755)
            try:seal(e,sha(e.read_bytes()),'child-e');failed=False
            except AuthError:failed=True
            say('a failed seal commit removes the seal file',failed and not locations(e)[3].exists())
            hook.unlink()
            try:seal(e,sha(e.read_bytes()),'child-e');again=True
            except AuthError:again=False
            say('... so the lane can be sealed afterwards',again and validate(e)==[])
            # parallel seal commands (separate processes) do not race on the index
            lanes=[rd/f'lane-{chr(97+i)}.json' for i in range(10)]
            for L in lanes:
                m_=issue(L,prompt);L.write_text(json.dumps({'lane_token':token(m_)}))
            ds=rd/'deleted-seal.json';m_d=issue(ds,prompt);ds.write_text(json.dumps({'lane_token':token(m_d)}))
            seal(ds,sha(ds.read_bytes()),'child-d');sp=locations(ds)[3];sp.unlink()
            git(d,'add','-A');git(d,'commit','-qm','seal '+rd.name+' tidy')
            try:reissue(ds,'seal file gone');hist=False
            except AuthError:hist=True
            say('a lane whose seal was deleted is still never reissued (the seal is in git history)',hist)
            git(d,'checkout','HEAD~1','--',sp.relative_to(d).as_posix());git(d,'commit','-qm','seal '+rd.name+' restore')
            rs=reissues(rd)
            say('reissues are listed with commit, lane, reason and evidence file',
                len(rs)==1 and rs[0][1]=='non-vacuity.json' and rs[0][2]=='conversation ended before sealing'
                and any('.reissued/' in f for f in rs[0][3]))
            say('a reissue records the hash of the verdict it set aside',
                re.fullmatch('[0-9a-f]{64}',json.loads(locations(c)[2].read_text()).get('previous_verdict_sha256','')) is not None)
            procs=[subprocess.Popen([sys.executable,os.path.abspath(__file__),'seal','--verdict',str(L),
                                     '--sha256',sha(L.read_bytes()),'--agent-id','p'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for L in lanes]
            rcs=[p_.wait() for p_ in procs]
            say('parallel seal commands all commit (repository lock)',rcs==[0]*len(lanes) and all(validate(L)==[] for L in lanes))
        try:
            later_checks()
        except Exception as e_:  # a crash in these checks is a FAIL, not a crash of the suite
            say(f'reissue/seal checks ran to the end ({type(e_).__name__}: {str(e_)[:80]})', False)
        b.unlink();say('missing expected verdict rejected',bool(check_round(rd,[a])))
        say('missing commitments fail closed',bool(check_round(d/'empty',[])))
    print('selftest: '+('ok' if all(checks) else 'FAILED'))
    return 0 if all(checks) else 1


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--selftest',action='store_true')
    ap.add_argument('command',nargs='?',choices=['issue','seal','reissue']);ap.add_argument('--prompt');ap.add_argument('--verdict');ap.add_argument('--sha256');ap.add_argument('--agent-id')
    ap.add_argument('--round');ap.add_argument('--lane',help='reissue: the lane file name without .json, e.g. correspondence@2');ap.add_argument('--reason')
    a=ap.parse_args()
    if a.selftest:return selftest()
    try:
        if a.command=='reissue' and not a.verdict and a.round and a.lane:
            sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
            import project
            cfg=project.select()[0]
            a.verdict=os.path.join(project.REPO,cfg['rounds_dir'],a.round,a.lane+'.json')
        if a.command=='issue' and a.prompt:print(issue_prompt(a.prompt))
        elif a.command=='seal' and a.verdict and a.sha256 and a.agent_id:
            h=seal(a.verdict,a.sha256,a.agent_id);print('sealed '+a.verdict+' in commit '+h+' (log this hash in RUN_LOG.md)')
        elif a.command=='reissue' and a.verdict:
            line=reissue(a.verdict,a.reason)
            print('reissued '+a.verdict+'; spawn ONE fresh lane with exactly: '+line)
        else:ap.error('issue needs --prompt; seal needs --verdict --sha256 --agent-id; reissue needs (--verdict | --round --lane) --reason')
        return 0
    except (OSError,ValueError) as e:print('STOP: '+str(e),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
