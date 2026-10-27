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

A SEALED lane is never re-run: one seal per lane, ever. Any doubt about a sealed lane is a re-vote
the adjudicator orders (a fresh lane under revote/).

  lane_auth.py issue --prompt FILE
  lane_auth.py seal --verdict FILE --sha256 HEX --agent-id ID
  lane_auth.py manifest --verdict FILE   (run by a lane: the "probes" object for its verdict)
  lane_auth.py reissue (--verdict FILE | --round R --lane LANE) --reason TEXT
  lane_auth.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import argparse, contextlib, fcntl, hashlib, json, os, re, secrets, subprocess, tempfile, threading
from pathlib import Path

COMMIT_LOCK = threading.Lock()

class AuthError(ValueError):
    """A refusal. `code` is its cause code (project.CAUSES), printed as PROBLEM[<code>] by lanecheck."""
    def __init__(self, msg, code='auth-metadata'):
        super().__init__(msg)
        self.code = code


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if r.returncode:
        raise AuthError('git failed: ' + r.stderr.strip())
    return r.stdout.strip()


def locations(verdict):
    """(round dir, verdict path relative to it, token commitment, seal). One seal per lane, ever:
    `.lane-seals/<lane>.json`."""
    verdict = Path(verdict).resolve()
    rd = verdict.parent.parent if verdict.parent.name == 'revote' else verdict.parent
    rel = verdict.relative_to(rd)
    # lane verdicts: <lane>.json, <lane>@<part>.json; re-votes: revote/<lane>--<item slug>.json; a tool patch's
    # reviewer (tool_patch.py, OPERATOR-PATCH): tool-patches/TP<k>/review-<attempt>-<n>.json
    if is_tool_patch(rd):
        if not re.fullmatch(r'review-[1-9]\d*-[1-9]\d*\.json', rel.as_posix()):
            raise AuthError('invalid tool-patch review verdict path')
    elif is_core_review(rd):
        if not re.fullmatch(r'core-review-[1-9]\d*\.json', rel.as_posix()):
            raise AuthError('invalid core-fault review verdict path')
    elif is_ack_review(rd):
        if rel.as_posix() != 'review.json':
            raise AuthError('invalid acknowledgment review verdict path')
    elif not re.fullmatch(r'(?:[a-z-]+(?:@\d+)?|revote/[a-z-]+--[A-Za-z0-9_.-]+)\.json', rel.as_posix()):
        raise AuthError('invalid lane verdict path')
    return rd, rel, rd / '.lane-auth' / rel, rd / '.lane-seals' / rel


def is_tool_patch(rd):
    """Is `rd` a tool patch's directory (<rounds dir>/tool-patches/TP<k>)? Its reviewers are sealed like lanes,
    under the tool-patch subjects (integrity.OWNERS: tool-patches/* is owned by "tool-patch " commits)."""
    return Path(rd).parent.name == 'tool-patches' and bool(re.fullmatch(r'TP[1-9]\d*', Path(rd).name))


def is_core_review(rd):
    """Is `rd` a stop's directory (<rounds dir>/stops/S<n>)? A core-fault close's fresh reviewer (stops.py
    core-fault, C2-FIX 5b) is sealed there like a lane, under the stop's subjects (integrity.OWNERS: stops/* is owned by
    "stop " commits)."""
    return Path(rd).parent.name == 'stops' and bool(re.fullmatch(r'S[1-9]\d*', Path(rd).name))


def is_ack_review(rd):
    """Is `rd` a reviewed acknowledgment's directory (<rounds dir>/acknowledgments/AK<k>; integrity.py --ack-request,
    SWEEP-FIX D2)? Its fresh reviewer is sealed there like a lane, as "acknowledge AK<k> seal review.json"."""
    return Path(rd).parent.name == 'acknowledgments' and bool(re.fullmatch(r'AK[1-9]\d*', Path(rd).name))


def seal_subject(rd, rel):
    if is_ack_review(rd):
        return f'acknowledge {Path(rd).name} seal {rel}'
    if is_core_review(rd):
        return f'stop {Path(rd).name} core-review seal {rel}'
    return (f'tool-patch {Path(rd).name} seal {rel}' if is_tool_patch(rd) else 'seal ' + Path(rd).name + ' ' + rel)


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
    """Commit exactly `paths`, by name (never `add -A`), under `subject`. On a failed add or commit
    the paths are unstaged again, so nothing is left half-recorded in the index."""
    rels = [Path(p).resolve().relative_to(repo).as_posix() for p in paths]
    try:
        git(repo, 'add', '--', *rels)
        git(repo, 'commit', '--only', '-m', subject, '--', *rels)
    except AuthError:
        subprocess.run(['git', '-C', str(repo), 'reset', '-q', '--', *rels], capture_output=True)
        raise
    return git(repo, 'rev-parse', 'HEAD')


def not_ignored(repo, paths):
    """`paths` without those git ignores (a `git add` of an ignored path fails, and a lane's probe
    directory may hold a `__pycache__` or a build output an ignore rule covers)."""
    paths = [Path(p).resolve() for p in paths if '__pycache__' not in Path(p).parts]
    rels = [p.relative_to(repo).as_posix() for p in paths]
    if not rels:
        return []
    r = subprocess.run(['git', '-C', str(repo), 'check-ignore', '--stdin'], input='\n'.join(rels) + '\n',
                       capture_output=True, text=True)
    ignored = set(r.stdout.splitlines())
    return [p for p, rel in zip(paths, rels) if rel not in ignored]


def committed_at(repo, path):
    """The first commit that added `path`, or None."""
    rel = Path(path).resolve().relative_to(repo).as_posix()
    h = git(repo, 'log', '--reverse', '--format=%H', '--diff-filter=A', '--', rel).split()
    return h[0] if h else None


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
    if is_tool_patch(rd) or is_core_review(rd) or is_ack_review(rd):
        raise AuthError('a tool patch\'s, a core fault\'s or an acknowledgment\'s reviewer is issued only by tool_patch.py '
                        'review, stops.py core-fault or integrity.py --ack-request (its prompt is rendered there)')
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
    """[] when the verdict authenticates, else one problem "[<code>] <lane>: <why>". The codes:
    lane-output (no readable verdict: a mechanical failure), unsealed (returned, not yet sealed:
    seal it), and the tampering ones -- auth-metadata, prompt-changed, seal-mismatch."""
    rd, rel, commitment, seal = locations(verdict)
    try:
        meta = original_doc(commitment, reissue_round=rd.name)
        try:
            raw = Path(verdict).read_bytes()
            data = json.loads(raw)
        except (OSError, ValueError) as e:
            raise AuthError('no readable verdict (' + str(e)[:80] + ')', 'lane-output')
        if not isinstance(data, dict) or not isinstance(meta, dict):
            raise AuthError('verdict and commitment must be JSON objects', 'lane-output')
        if sha(Path(meta['prompt']).read_bytes()) != meta['prompt_sha256']:
            raise AuthError('prompt changed since lane token was issued', 'prompt-changed')
        token = data.get('lane_token')
        if meta.get('verdict') != rel.as_posix():
            raise AuthError('commitment belongs to another lane', 'seal-mismatch')
        if not isinstance(token, str) or sha(token.encode()) != meta['token_sha256']:
            raise AuthError('lane token does not match its spawn commitment', 'seal-mismatch')
        # A copied token cannot authenticate changed contents. The owning child's completion
        # digest (not whatever bytes the parent sees later) establishes expected contents.
        if expected is not None and sha(raw) != expected:
            raise AuthError('verdict differs from owner-returned completion digest', 'seal-mismatch')
        if require_seal:
            sp = locations(verdict)[3]
            if not sp.exists() and not committed_at(audit_repo(rd), sp):
                raise AuthError('returned but not sealed yet (seal it from the lane\'s own LANE_COMPLETION line)',
                                'unsealed')
            sealed = original_doc(sp)
            if sealed.get('verdict') != rel.as_posix() or sha(raw) != sealed.get('sha256'):
                raise AuthError('verdict differs from its completion seal', 'seal-mismatch')
            if sealed.get('token_sha256') != meta['token_sha256']:
                raise AuthError('seal belongs to another spawn', 'seal-mismatch')
        return []
    except AuthError as e:
        return ['[' + e.code + '] ' + rel.as_posix() + ': ' + str(e)]
    except (OSError, KeyError, ValueError) as e:
        return ['[auth-metadata] ' + rel.as_posix() + ': ' + str(e)]


def probes_dir(verdict):
    """The lane's probe directory: next to its verdict, named after it."""
    v = Path(verdict).resolve()
    return v.with_name(v.name[:-len('.json')] + '.probes')


def probe_manifest(verdict):
    """{path relative to the probe directory: sha256} of every file the lane left there."""
    d = probes_dir(verdict)
    return {p.relative_to(d).as_posix(): sha(p.read_bytes())
            for p in sorted(d.rglob('*')) if p.is_file() and '__pycache__' not in p.parts} if d.is_dir() else {}


def own_manifest(verdict):
    """The probe manifest the LANE wrote into its own verdict ("probes": {path: sha256}), which its
    owner-returned digest covers -- so nobody can change the probes before the seal either (review
    round 3, P1). None if the verdict has none."""
    try:
        m = json.loads(Path(verdict).read_text()).get('probes')
    except (OSError, ValueError, AttributeError):
        return None
    return m if isinstance(m, dict) else None


def manifest_faults(own, disk):
    """(listed files missing or changed on disk, files on disk the manifest does not list)."""
    if own is None:
        return [], sorted(disk)
    changed = sorted(k for k in own if disk.get(k) != own[k])
    return changed, sorted(k for k in disk if k not in own)


def sealed_doc(verdict):
    """The lane's committed seal document, or None (not sealed)."""
    rd, rel, commitment, _ = locations(verdict)
    try:
        meta = json.loads(commitment.read_text())
        return original_doc(locations(verdict)[3])
    except (OSError, ValueError, AttributeError):
        return None


def seal_faults(verdict):
    """["[lane-fault] ..."]: the lane's own mistakes its seal recorded (RULINGS A2/A3) -- no probe
    manifest in its verdict, a listed probe missing or changed before the seal, files in its probe
    directory its manifest does not list. Each voids the evidence it touches: the adjudicator
    re-votes, never rejects on it."""
    s_ = sealed_doc(verdict)
    if not s_:
        return []
    rel = locations(verdict)[1].as_posix()
    out = []
    if s_.get('probes_unprotected'):
        out.append(f'[lane-fault] {rel}: its verdict has no "probes" manifest, so its probe files were not '
                   f'protected before the seal')
    for k in s_.get('listed_changed') or []:
        out.append(f'[lane-fault] {rel}: probe {probes_dir(verdict).name}/{k} is listed in its manifest but was '
                   f'missing or changed when it was sealed')
    extra = s_.get('unlisted') or []
    if extra:
        out.append(f'[lane-fault] {rel}: {len(extra)} file(s) in its probe directory not listed in its manifest '
                   f'({", ".join(extra[:3])})')
    return out


def after_seal(verdict):
    """["[evidence-after-seal] ..."]: the lane's verdict or a probe file changed, removed or added
    after its seal commit -- tampering with sealed evidence, a stop for the human (only a change
    BEFORE the seal is the lane's own mistake). From git, which holds the files since the seal."""
    rd, rel, _, _ = locations(verdict)
    if not sealed_doc(verdict):
        return []
    repo = audit_repo(rd)
    v = Path(verdict).resolve()
    if not committed_at(repo, v):
        return []          # sealed before ownership 2 (the seal did not commit the files)
    paths = [v.relative_to(repo).as_posix(), probes_dir(v).relative_to(repo).as_posix()]
    st = git(repo, 'status', '--porcelain', '--untracked-files=all', '--', *paths)
    return [f'[evidence-after-seal] {rel.as_posix()}: changed after its seal: {l.strip()}'
            for l in st.splitlines() if l.strip() and '__pycache__' not in l][:5]


def lane_files(verdict):
    """The files a seal commits with the seal itself: the verdict and every file under its probe
    directory (not bytecode caches, not paths git ignores)."""
    v = Path(verdict).resolve()
    d = probes_dir(v)
    files = [v] + ([p for p in sorted(d.rglob('*')) if p.is_file()] if d.is_dir() else [])
    return not_ignored(audit_repo(v.parent), files)


def seal(verdict, owner_digest, agent_id):
    """Seal a returned lane: its seal file, its verdict and its probe files are committed together,
    by name, as "seal <R> <lane>" (so a lane's evidence is in git from the moment it is sealed, and
    a dead round or an unsettled re-vote leaves nothing uncommitted behind). Idempotent: a seal
    killed between writing the seal file and its commit is completed by running it again (the
    uncommitted seal file must equal what this run computes); a lane already sealed with the same
    digest returns its seal commit.

    A probe directory that differs from the manifest the lane wrote into its verdict, or a verdict
    with no manifest, is the LANE's mistake (it re-ran a probe after listing it, left a file
    unlisted, forgot the list): it is sealed, the mismatch is recorded in the seal, and lanecheck
    reports it as a lane fault the adjudicator re-votes (RULINGS A2/A3). Only the token and the
    owner digest -- which protect the verdict itself -- refuse a seal."""
    if not re.fullmatch('[0-9a-f]{64}', owner_digest) or not agent_id.strip():
        raise AuthError('require owner-returned SHA-256 and originating child id')
    probs = validate(verdict, owner_digest, require_seal=False)
    if probs:
        raise AuthError('; '.join(probs))
    rd, rel, commitment, _ = locations(verdict)
    own, disk = own_manifest(verdict), probe_manifest(verdict)
    changed, unlisted = manifest_faults(own, disk)
    meta = original_doc(commitment, reissue_round=rd.name)
    out = locations(verdict)[3]
    doc = {'verdict': rel.as_posix(), 'sha256': owner_digest, 'token_sha256': meta['token_sha256'],
           'agent_id': agent_id, 'probes': disk}
    if own is None:
        doc['probes_unprotected'] = True
    if changed:
        doc['listed_changed'] = changed
    if unlisted and own is not None:
        doc['unlisted'] = unlisted
    return commit_seal(verdict, out, doc, seal_subject(rd, rel.as_posix()))


def commit_seal(verdict, out, doc, subject):
    """Write the seal `out` and commit it with the lane's files (see `seal`)."""
    repo = audit_repo(Path(out).parent if Path(out).parent.exists() else Path(verdict).resolve().parent)
    out.parent.mkdir(parents=True, exist_ok=True)
    with repo_lock(repo):
        first = committed_at(repo, out)
        if first:
            prior = json.loads(git(repo, 'show', first + ':' + out.relative_to(repo).as_posix()))
            if prior.get('sha256') == doc['sha256'] and prior.get('verdict') == doc['verdict']:
                return first          # already sealed (a seal run again after its commit landed)
            raise AuthError('lane already sealed with another digest (seal ' + first[:11] + '): ' + doc['verdict'])
        if out.exists():
            try:
                existing = json.loads(out.read_text())
            except ValueError:
                existing = None       # a seal file cut short by a crash: written again below
            if existing is not None and existing != doc:
                raise AuthError('an uncommitted seal file with other contents exists (' + out.name + '): it was not '
                                'written by this seal; a real stop')
        with out.open('w', encoding='utf-8') as f:
            json.dump(doc, f, sort_keys=True, indent=2); f.write('\n')
        try:
            return commit_paths(repo, [out] + lane_files(verdict), subject)
        except AuthError:
            # an uncommitted seal would make every later attempt compare against it; a failed
            # commit leaves the lane exactly as it was before the seal
            with contextlib.suppress(OSError):
                out.unlink()
            raise


def interrupted_restore(verdict):
    """B13 (U2 §8, restarts). A lane command killed between its writes and its commit leaves them
    uncommitted, and every later check of the lane would read them as tampering. Two cases, each only in the
    exact form that command writes (anything else is left for the checks to report):
    - `issue` killed: a token commitment never committed, with no verdict and no seal ever -> the commitment
      is removed; returns ("issue", its prompt), so the lane is issued afresh (no reissue is spent: no token
      was ever delivered);
    - `reissue` killed: the commitment differs from its newest commit exactly as reissue writes it (the
      next reissue number, `reissued_in` 0, only the token, reason and previous verdict hash changed) -> it is
      checked out again and the evidence moved aside (`.reissued/...{n}`, untracked) moved back; returns
      ("reissue", None), so the same reissue runs again.
    None when nothing was interrupted."""
    rd, rel, commitment, seal_path = locations(verdict)
    if not commitment.exists():
        return None
    repo = audit_repo(rd)
    crel = commitment.relative_to(repo).as_posix()
    v = Path(verdict).resolve()
    if committed_at(repo, commitment) is None:
        ever = seal_path.exists() or git(repo, 'log', '--all', '--format=%H', '--', seal_path.relative_to(repo).as_posix())
        if v.exists() or ever:
            return None
        try:
            doc = json.loads(commitment.read_text())
        except (OSError, ValueError):
            doc = {}
        if not isinstance(doc, dict) or doc.get('verdict') != rel.as_posix() or not doc.get('prompt'):
            return None
        try:
            found = re.findall(r'Write that JSON object, and nothing else, to (\S+\.json)', Path(doc['prompt']).read_text())
        except OSError:
            return None
        if len(found) != 1 or Path(found[0]).resolve() != v:
            return None         # its prompt writes another verdict: not this lane's issue; the checks report it
        commitment.unlink()
        return ('issue', doc['prompt'])
    newest = git(repo, 'log', '-1', '--format=%H', '--', crel)
    committed_text = git(repo, 'show', newest + ':' + crel)
    try:
        c = json.loads(committed_text)
    except ValueError:
        return None
    if not isinstance(c, dict) or 'reissued_in' in c:
        return None         # already reissued once: nothing a reissue could have left half-done
    n = int(c.get('reissue', 0)) + 1
    done = False
    if commitment.read_text().strip() != committed_text:
        try:
            w = json.loads(commitment.read_text())
        except ValueError:
            return None
        free = ('token_sha256', 'reason', 'previous_verdict_sha256', 'reissue', 'reissued_in')
        if not (isinstance(w, dict) and w.get('reissue') == n and w.get('reissued_in') == 0
                and {k: x for k, x in w.items() if k not in free} == {k: x for k, x in c.items() if k not in free}):
            return None
        git(repo, 'checkout', 'HEAD', '--', crel)
        done = True
    # the evidence a killed reissue moved aside (before or after writing the commitment), never committed
    tracked = lambda p: bool(git(repo, 'ls-files', '--', p.relative_to(repo).as_posix()))
    ev = rd / '.reissued' / (rel.as_posix().replace('/', '__') + f'.{n}.json')
    if ev.exists() and not v.exists() and not tracked(ev):
        os.replace(ev, v); done = True
    evp = rd / '.reissued' / (rel.as_posix().replace('/', '__')[:-len('.json')] + f'.probes.{n}')
    if evp.is_dir() and not probes_dir(v).exists() and not tracked(evp):
        os.replace(evp, probes_dir(v)); done = True
    with contextlib.suppress(OSError):
        (rd / '.reissued').rmdir()
    return ('reissue', None) if done else None


def reissue(verdict, reason):
    """A new token for a lane whose spawn line was lost before the lane was sealed (the
    conversation that held it ended). Refused once the lane has a seal. A verdict the lane may
    already have written is moved to `.reissued/` as evidence, never used. Returns the new spawn
    line; the commit is "scope <R> (reissue <lane>: <reason>)"."""
    if is_tool_patch(locations(verdict)[0]):
        raise AuthError('a tool patch\'s review is never reissued: withdraw the tool patch and begin a new one')
    if is_core_review(locations(verdict)[0]):
        raise AuthError('a core fault\'s review is never reissued: request a new one (stops.py core-fault)')
    if is_ack_review(locations(verdict)[0]):
        raise AuthError('an acknowledgment\'s review is never reissued: request a new one (integrity.py --ack-request)')
    reason = ' '.join(str(reason or '').split())
    if not reason:
        raise AuthError('a reissue needs a --reason (it is recorded in the commit message)')
    fin = interrupted_restore(verdict)
    if fin and fin[0] == 'issue':
        # the issue was killed before its commit: the lane is issued afresh (its prompt writes this verdict)
        return issue(verdict, fin[1])
    rd, rel, commitment, seal_path = locations(verdict)
    repo0 = audit_repo(rd)
    meta = original_doc(commitment, reissue_round=rd.name)
    ever_sealed = seal_path.exists() or git(repo0, 'log', '--all', '--format=%H', '--',
                                            seal_path.relative_to(repo0).as_posix())
    if ever_sealed:
        raise AuthError('lane already sealed (now or earlier in history); a sealed lane is never reissued: '
                        + rel.as_posix())
    try:
        written = json.loads(Path(verdict).read_text()).get('lane_token')
    except (OSError, ValueError, AttributeError):
        written = None
    if isinstance(written, str) and sha(written.encode()) == meta.get('token_sha256'):
        raise AuthError('the lane returned: its verdict carries the current token, so this is not a lost spawn '
                        'line. Seal it from its own LANE_COMPLETION line; a lane with a verdict under its token is '
                        're-voted by the adjudicator (or its round set aside), never reissued: ' + rel.as_posix())
    # `reissued_in` is 0 in every commitment a reissue writes (it named a generation, which are gone;
    # committed files keep the key, so it is still the marker read here)
    if meta.get('reissued_in') == 0:
        raise AuthError('this lane was already reissued once; a lane is reissued at most once, so a lost spawn '
                        'line cannot become a way to re-roll it: ' + rel.as_posix())
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
        old_commitment = commitment.read_bytes()
        moved = []          # (from, to): undone if the commit fails (ROUND3 M5)
        try:
            if v.exists():
                ev = rd / '.reissued' / (rel.as_posix().replace('/', '__') + f'.{n}.json')
                ev.parent.mkdir(parents=True, exist_ok=True)
                os.replace(v, ev); moved.append((v, ev))
                paths.append(ev)
            pd = probes_dir(v)
            if pd.is_dir():
                # the earlier verdict's probes go with it
                evp = rd / '.reissued' / (rel.as_posix().replace('/', '__')[:-len('.json')] + f'.probes.{n}')
                evp.parent.mkdir(parents=True, exist_ok=True)
                os.replace(pd, evp); moved.append((pd, evp))
                paths += [p for p in evp.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
            with commitment.open('w', encoding='utf-8') as f:
                json.dump(dict(meta, token_sha256=sha(token.encode()), reissue=n, reason=reason,
                               previous_verdict_sha256=prev, reissued_in=0),
                          f, sort_keys=True, indent=2); f.write('\n')
            commit_paths(repo, paths, f'scope {rd.name} (reissue {rel.as_posix()}: {reason[:120]})')
        except (AuthError, OSError):
            # a failed commit (e.g. a stale index.lock) leaves the lane exactly as it was: the
            # verdict and probes back in place, the commitment unchanged, nothing staged; after
            # `stops.py repair-lock` the same reissue runs again
            commitment.write_bytes(old_commitment)
            for src, dst in reversed(moved):
                with contextlib.suppress(OSError):
                    os.replace(dst, src)
            with contextlib.suppress(OSError):
                (rd / '.reissued').rmdir()          # only if this reissue created it and left it empty
            with contextlib.suppress(AuthError):
                git(repo, 'reset', '-q', '--', *[Path(p).resolve().relative_to(repo).as_posix() for p in paths])
            raise
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
    # a re-vote lane set aside (stops.py set-aside --lane) is no longer expected
    abandoned = lambda p: (rd / '.abandoned' / (p.relative_to(rd).as_posix()[:-len('.json')].replace('/', '__') + '.json')).exists()
    issued = {rd / p.relative_to(rd / '.lane-auth') for p in (rd / '.lane-auth').rglob('*.json')}
    expected = {p for p in issued if not abandoned(p)}
    for prompt in (rd / 'prompts').glob('*.txt'):
        for path in re.findall(r'Write that JSON object, and nothing else, to (\S+\.json)', prompt.read_text()):
            candidate = Path(path).resolve()
            if (candidate.parent == rd or candidate.parent == rd / 'revote') and not abandoned(candidate):
                expected.add(candidate)
    actual = {Path(p).resolve() for p in verdicts if not abandoned(Path(p).resolve())}
    if not expected:
        return [] if issued else ['round has no lane token commitments; unauthenticated round']
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
        a.write_text(json.dumps({'probes':{},'lane_token':ta,'summary':'owner'}));good=a.read_bytes();digest=sha(good)
        b.write_text(json.dumps({'probes':{},'lane_token':tb,'summary':'sibling'}));seal(b,sha(b.read_bytes()),'child-b')
        say('missing seal rejects a pending file, coded [unsealed] (seal it), not as tampering',
            len(validate(a))==1 and validate(a)[0].startswith('[unsealed] '))
        prompt.write_text('tampered')
        say('prompt edits violate the spawn commitment',any('prompt changed' in x for x in validate(a)))
        prompt.write_text('fixture')
        a.write_text('[]')
        say('non-object verdict rejected',bool(validate(a)))
        a.write_bytes(good)
        a.write_text(json.dumps({'probes':{},'lane_token':tb,'summary':'overwrite'}))
        say('wrong lane token rejected',any('token' in x for x in validate(a,digest,False)))
        a.write_text(json.dumps({'probes':{},'lane_token':ta,'summary':'copied token; overwrite before completion'}))
        try:seal(a,digest,'child-a');caught=False
        except AuthError:caught=True
        say('copied token before completion cannot be sealed',caught)
        if not caught:
            print('selftest: FAILED'); return 1
        a.write_bytes(good);seal(a,digest,'child-a')
        say('clean parallel-issued round passes',check_round(rd,[a,b])==[])
        a.write_text(json.dumps({'probes':{},'lane_token':ta,'summary':'overwrite after completion'}))
        say('copied token after completion violates seal',any('seal' in x for x in validate(a)))
        a.write_bytes(good)
        sealpath=locations(a)[3];saved=sealpath.read_bytes();obj=json.loads(saved);obj['sha256']='0'*64;sealpath.write_text(json.dumps(obj))
        say('seal metadata edits rejected',any('metadata changed' in x for x in validate(a)))
        sealpath.write_bytes(saved)
        try:issue(a,prompt);silent=False
        except AuthError:silent=True
        say('silent reissue refused',silent)
        def interrupted_checks():
            # B13 (U2 §8, restarts): a reissue / issue killed between its writes and its commit
            g=globals();real=g['commit_paths']
            def killed(*a_,**k_):raise KeyboardInterrupt('killed before the commit')
            e=rd/'correspondence@7.json';te=token(issue(e,prompt))
            e.write_text(json.dumps({'probes':{},'lane_token':'1'*64,'summary':'partial, no token'}));old_e=e.read_bytes()
            g['commit_paths']=killed
            try:reissue(e,'conversation ended');died=False
            except KeyboardInterrupt:died=True
            finally:g['commit_paths']=real
            half=bool(validate(e))   # the commitment changed and uncommitted: every check reads tampering
            msg_e=reissue(e,'conversation ended');te2=token(msg_e)
            ev=rd/'.reissued'/'correspondence@7.json.1.json'
            say('B13 kill point (reissue): resumed, the same reissue runs once: new token, the old verdict committed as '
                'evidence (not lost), commitment committed, nothing left uncommitted',
                died and half and te2!=te and not e.exists() and ev.exists() and ev.read_bytes()==old_e
                and git(d,'log','-1','--format=%s')=='scope '+rd.name+' (reissue correspondence@7.json: conversation ended)'
                and git(d,'status','--porcelain','--',str(locations(e)[2].relative_to(d)),str((rd/'.reissued').relative_to(d)),
                        str(e.relative_to(d)))==''
                and json.loads(locations(e)[2].read_text()).get('reissue')==1)
            e.write_text(json.dumps({'probes':{},'lane_token':te2,'summary':'the reissued lane'}))
            say('B13 kill point (reissue): the reissued lane authenticates (unsealed until sealed)',
                [x[:10] for x in validate(e)]==['[unsealed]'])
            f=rd/'correspondence@8.json';pf=rd/'prompts';pf.mkdir(exist_ok=True);pp=pf/'prior-art.txt'
            pp.write_text(f'Write that JSON object, and nothing else, to {f}\n')
            g['commit_paths']=killed
            try:issue(f,pp);died=False
            except KeyboardInterrupt:died=True
            finally:g['commit_paths']=real
            stuck=False
            try:issue(f,pp)
            except AuthError:stuck=True
            msg_f=reissue(f,'issue killed');tf=token(msg_f)
            f.write_text(json.dumps({'probes':{},'lane_token':tf,'summary':'fresh'}))
            say('B13 kill point (issue): a token commitment never committed, no verdict, no seal: reissue issues the lane '
                'afresh (no reissue spent) and its token authenticates',
                died and stuck and git(d,'log','-1','--format=%s')=='scope '+rd.name+' (lane token correspondence@8.json)'
                and [x[:10] for x in validate(f)]==['[unsealed]'] and 'reissue' not in json.loads(locations(f)[2].read_text()))
            hand=rd/'correspondence@9.json';cm=locations(hand)[2];cm.parent.mkdir(parents=True,exist_ok=True)
            cm.write_text(json.dumps({'verdict':'correspondence@9.json','prompt':str(pp)}))
            try:reissue(hand,'x');forged=False
            except AuthError:forged=True
            cm.unlink()
            say('B13: an uncommitted commitment whose prompt writes another verdict is never issued from',forged)
        def later_checks():
            # re-vote verdict paths (revote/<lane>--<item>.json) are lane paths too
            rv=rd/'revote'/'correspondence--P.thm_1_2.json';rv.parent.mkdir()
            msg_r=issue(rv,prompt);rv.write_text(json.dumps({'probes':{},'lane_token':token(msg_r)}))
            try:seal(rv,sha(rv.read_bytes()),'child-r');rv_ok=validate(rv)==[]
            except AuthError:rv_ok=False
            say('a re-vote lane can be issued and sealed',rv_ok)
            # reissue: a lane whose spawn line was lost before it was sealed
            c=rd/'non-vacuity.json';msg_c=issue(c,prompt);tc=token(msg_c)
            c.write_text(json.dumps({'probes':{},'lane_token':tc,'summary':'returned, but its seal failed'}))
            try:reissue(c,'lost');returned_ok=False
            except AuthError as e_r:returned_ok='lane returned' in str(e_r)
            say('review 4 P3: a lane whose verdict carries the current token returned: never reissued',returned_ok)
            c.write_text(json.dumps({'probes':{},'lane_token':'0'*64,'summary':'a partial file without the token'}))
            os.makedirs(rd/'non-vacuity.probes',exist_ok=True);(rd/'non-vacuity.probes'/'p.lean').write_text('x')
            try:reissue(c,'');noreason=False
            except AuthError:noreason=True
            say('a reissue needs a reason',noreason)
            msg_c2=reissue(c,'conversation ended before sealing');tc2=token(msg_c2)
            moved=list((rd/'.reissued').glob('non-vacuity.json.1.json'))
            subj=git(d,'log','-1','--format=%s')
            say('reissue: new token, old verdict AND its probes moved to evidence, logged commit',
                tc2!=tc and not c.exists() and len(moved)==1 and not (rd/'non-vacuity.probes').exists()
                and (rd/'.reissued'/'non-vacuity.probes.1'/'p.lean').exists()
                and subj=='scope '+rd.name+' (reissue non-vacuity.json: conversation ended before sealing)')
            c.write_text(json.dumps({'probes':{},'lane_token':tc,'summary':'old token'}))
            say('after a reissue the old token is refused (only the newest commitment counts)',
                any('token' in x for x in validate(c,None,False)))
            c.write_text(json.dumps({'probes':{},'lane_token':tc2,'summary':'new spawn'}));seal(c,sha(c.read_bytes()),'child-c2')
            say('the reissued lane seals and validates',validate(c)==[])
            try:reissue(c,'again');resealed=False
            except AuthError:resealed=True
            say('a sealed lane is never reissued',resealed)
            u_=rd/'unsealed.json';m_u=issue(u_,prompt);u_.write_text(json.dumps({'probes':{},'lane_token':token(m_u)}))
            seal(u_,sha(u_.read_bytes()),'child-u')
            (rd/'ADOPTED.md').write_text('| lane | item |\n');git(d,'add','--',(rd/'ADOPTED.md').relative_to(d).as_posix());git(d,'commit','-qm','adjudicate '+rd.name)
            git(d,'rm','-q',(rd/'ADOPTED.md').relative_to(d).as_posix());git(d,'commit','-qm','adjudicate '+rd.name+' (fixture: removed for the next checks)')
            # A3: a probe directory that differs from the lane's own manifest, or no manifest at all, is the
            # lane's mistake: sealed, recorded in the seal, reported as a lane fault (never a refusal)
            pl=rd/'probed.json';m_p=issue(pl,prompt);pd_=rd/'probed.probes';pd_.mkdir()
            (pd_/'witness.lean').write_text('-- evidence');(pd_/'other.lean').write_text('x')
            pl.write_text(json.dumps({'probes':{'witness.lean':sha(b'-- evidence')},'lane_token':token(m_p)}))
            seal(pl,sha(pl.read_bytes()),'child-p')
            say('A3: files on disk the manifest does not list are sealed, recorded, and a lane fault',
                json.loads(locations(pl)[3].read_text()).get('unlisted')==['other.lean']
                and any(x.startswith('[lane-fault]') and 'other.lean' in x for x in seal_faults(pl)))
            ch=rd/'rerun-probe.json';m_ch=issue(ch,prompt);pdc=rd/'rerun-probe.probes';pdc.mkdir()
            (pdc/'w.out').write_text('second run');ch.write_text(json.dumps({'probes':{'w.out':sha(b'first run')},'lane_token':token(m_ch)}))
            seal(ch,sha(ch.read_bytes()),'child-ch')
            say('A2/A3: a listed probe changed before the seal (the lane re-ran it) is sealed and is a lane fault, not a stop',
                any('[lane-fault]' in x and 'w.out' in x and 'missing or changed' in x for x in seal_faults(ch)))
            nm=rd/'no-manifest.json';m_nm=issue(nm,prompt);nm.write_text(json.dumps({'lane_token':token(m_nm)}))
            seal(nm,sha(nm.read_bytes()),'child-nm')
            say('A3: a verdict without its own probe manifest is sealed as probes_unprotected, a lane fault',
                json.loads(locations(nm)[3].read_text()).get('probes_unprotected') is True
                and any('no "probes" manifest' in x for x in seal_faults(nm)))
            ok_=rd/'listed.json';m_ok=issue(ok_,prompt);pdo=rd/'listed.probes';pdo.mkdir();(pdo/'witness.lean').write_text('-- evidence')
            ok_.write_text(json.dumps({'probes':probe_manifest(ok_),'lane_token':token(m_ok)}));seal(ok_,sha(ok_.read_bytes()),'child-ok')
            say('a lane whose manifest matches its probes has no lane fault and nothing changed after its seal',
                seal_faults(ok_)==[] and after_seal(ok_)==[])
            (pdo/'witness.lean').unlink();ep1=after_seal(ok_);git(d,'checkout','--',(pdo/'witness.lean').relative_to(d).as_posix())
            (pdo/'witness.lean').write_text('-- forged');ep2=after_seal(ok_);git(d,'checkout','--',(pdo/'witness.lean').relative_to(d).as_posix())
            (pdo/'late.lean').write_text('x');ep3=after_seal(ok_);(pdo/'late.lean').unlink()
            ok_.write_text(ok_.read_text()+' ');ep4=after_seal(ok_);git(d,'checkout','--',ok_.relative_to(d).as_posix())
            say('A3: a probe removed, changed or added, or the verdict changed, AFTER the seal commit is tampering '
                '(evidence-after-seal), from git',
                all(any(x.startswith('[evidence-after-seal]') and n in x for x in e) for e,n in
                    ((ep1,'witness.lean'),(ep2,'witness.lean'),(ep3,'late.lean'),(ep4,'listed.json'))) and after_seal(ok_)==[])
            r2_=rd/'twice.json';m_t2=issue(r2_,prompt);reissue(r2_,'lost once')
            try:reissue(r2_,'lost twice');twice=False
            except AuthError:twice=True
            say('a lane is reissued at most once (a lost spawn line is no re-roll)',twice)
            t_=rd/'tamper.json';m_t=issue(t_,prompt);t_.write_text(json.dumps({'probes':{},'lane_token':token(m_t)}))
            cm=locations(t_)[2];doc=json.loads(cm.read_text());doc['token_sha256']=sha(b'x')
            cm.write_text(json.dumps(doc));git(d,'add','-A');git(d,'commit','-qm','scope '+rd.name+' tidy')
            say('a commitment changed by any commit other than a reissue is refused',
                any('not a reissue' in x for x in validate(t_,None,False)))
            # a failed seal commit leaves no seal file behind (the lane stays sealable)
            e=rd/'substantiveness.json';msg_e=issue(e,prompt);e.write_text(json.dumps({'probes':{},'lane_token':token(msg_e)}))
            hook=d/'.git'/'hooks'/'pre-commit';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o755)
            try:seal(e,sha(e.read_bytes()),'child-e');failed=False
            except AuthError:failed=True
            say('a failed seal commit removes the seal file',failed and not locations(e)[3].exists())
            hook.unlink()
            try:seal(e,sha(e.read_bytes()),'child-e');again=True
            except AuthError:again=False
            say('... so the lane can be sealed afterwards',again and validate(e)==[])
            # A4: the seal commits the lane's verdict and probes with the seal, by name
            k4=rd/'commit-at-seal.json';m4=issue(k4,prompt);pd4=rd/'commit-at-seal.probes';(pd4/'sub').mkdir(parents=True)
            (pd4/'w.lean').write_text('-- w');(pd4/'sub'/'run.out').write_text('o')
            (pd4/'__pycache__').mkdir();(pd4/'__pycache__'/'w.cpython-312.pyc').write_bytes(b'x')
            (d/'.gitignore').write_text('*.olean\n');git(d,'add','--','.gitignore');git(d,'commit','-qm','ignore')
            (pd4/'built.olean').write_text('ignored build output')
            k4.write_text(json.dumps({'probes':probe_manifest(k4),'lane_token':token(m4)}))
            h4=seal(k4,sha(k4.read_bytes()),'child-k4')
            names4=set(git(d,'show','--name-only','--format=',h4).splitlines())
            rel4=lambda p_:p_.relative_to(d).as_posix()
            say('A4: the seal commit holds the seal, the verdict and every probe file (not __pycache__, not an ignored path)',
                names4=={rel4(locations(k4)[3]),rel4(k4),rel4(pd4/'w.lean'),rel4(pd4/'sub'/'run.out')}
                and git(d,'log','-1','--format=%s')=='seal '+rd.name+' commit-at-seal.json')
            say('A4: after the seal nothing of the lane is uncommitted',
                [l for l in git(d,'status','--porcelain','--untracked-files=all','--',rel4(k4),rel4(pd4)).splitlines()
                 if '__pycache__' not in l]==[])
            say('A4: a seal run again after its commit landed returns the same commit (idempotent)',
                seal(k4,sha(k4.read_bytes()),'child-k4')==h4)
            try:seal(k4,sha(b'other'),'child-k4');other_ok=False
            except AuthError:other_ok=True
            say('A4: a second seal with another digest is refused',other_ok)
            # a seal killed after writing its file and before its commit is completed by a re-run
            k5=rd/'crashed.json';m5=issue(k5,prompt);k5.write_text(json.dumps({'probes':{},'lane_token':token(m5)}))
            meta5=original_doc(locations(k5)[2],reissue_round=rd.name);sp5=locations(k5)[3];sp5.parent.mkdir(exist_ok=True)
            sp5.write_text(json.dumps({'verdict':'crashed.json','sha256':sha(k5.read_bytes()),'token_sha256':meta5['token_sha256'],
                                       'agent_id':'child-k5','probes':{}},sort_keys=True,indent=2)+'\n')
            try:h5=seal(k5,sha(k5.read_bytes()),'child-k5');crash_ok=validate(k5)==[] and bool(h5)
            except AuthError:crash_ok=False
            say('A4: a seal file left uncommitted by a crash is committed by running the seal again',crash_ok)
            k6=rd/'forged.json';m6=issue(k6,prompt);k6.write_text(json.dumps({'probes':{},'lane_token':token(m6)}))
            sp6=locations(k6)[3];sp6.write_text(json.dumps({'verdict':'forged.json','sha256':'0'*64}))
            try:seal(k6,sha(k6.read_bytes()),'child-k6');forged_ok=False
            except AuthError as e6:forged_ok='other contents' in str(e6)
            say('A4: an uncommitted seal file with other contents is never overwritten',forged_ok)
            sp6.unlink();seal(k6,sha(k6.read_bytes()),'child-k6')
            # parallel seal commands (separate processes) do not race on the index
            lanes=[rd/f'lane-{chr(97+i)}.json' for i in range(10)]
            for L in lanes:
                m_=issue(L,prompt);L.write_text(json.dumps({'probes':{},'lane_token':token(m_)}))
            ds=rd/'deleted-seal.json';m_d=issue(ds,prompt);ds.write_text(json.dumps({'probes':{},'lane_token':token(m_d)}))
            seal(ds,sha(ds.read_bytes()),'child-d');sp=locations(ds)[3];sp.unlink()
            git(d,'add','-A');git(d,'commit','-qm','seal '+rd.name+' tidy')
            ds.unlink()   # not the lane-returned case: only the seal's history can refuse this reissue
            try:reissue(ds,'seal file gone');hist=False
            except AuthError:hist=True
            say('a lane whose seal was deleted is still never reissued (the seal is in git history)',hist)
            git(d,'checkout','HEAD~1','--',sp.relative_to(d).as_posix());git(d,'commit','-qm','seal '+rd.name+' restore')
            rs=[x for x in reissues(rd) if x[1]=='non-vacuity.json']
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
            interrupted_checks()
        except Exception as e_:  # a crash in these checks is a FAIL, not a crash of the suite
            say(f'reissue/seal checks ran to the end ({type(e_).__name__}: {str(e_)[:80]})', False)
        b.unlink();say('missing expected verdict rejected',bool(check_round(rd,[a])))
        say('missing commitments fail closed',bool(check_round(d/'empty',[])))
    print('selftest: '+('ok' if all(checks) else 'FAILED'))
    return 0 if all(checks) else 1


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--selftest',action='store_true')
    ap.add_argument('command',nargs='?',choices=['issue','seal','reissue','manifest']);ap.add_argument('--prompt');ap.add_argument('--verdict');ap.add_argument('--sha256');ap.add_argument('--agent-id')
    ap.add_argument('--round');ap.add_argument('--lane',help='reissue: the lane file name without .json, e.g. correspondence@2');ap.add_argument('--reason')
    a=ap.parse_args()
    if a.selftest:return selftest()
    try:
        if a.command=='reissue' and not a.verdict and a.round and a.lane:
            sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
            import project
            cfg=project.select()[0]
            a.verdict=os.path.join(project.REPO,cfg['rounds_dir'],a.round,a.lane+'.json')
        if a.command=='manifest' and a.verdict:print(json.dumps(probe_manifest(a.verdict),sort_keys=True))
        elif a.command=='issue' and a.prompt:print(issue_prompt(a.prompt))
        elif a.command=='seal' and a.verdict and a.sha256 and a.agent_id:
            h=seal(a.verdict,a.sha256,a.agent_id);print('sealed '+a.verdict+' in commit '+h+' (log this hash in RUN_LOG.md)')
        elif a.command=='reissue' and a.verdict:
            line=reissue(a.verdict,a.reason)
            print('reissued '+a.verdict+'; spawn ONE fresh lane (subagent_type auditor; Codex: agent_type formalize_auditor, fork_turns none) with exactly: '+line)
        else:ap.error('issue needs --prompt; seal needs --verdict --sha256 --agent-id; reissue needs (--verdict | --round --lane) --reason')
        return 0
    except (OSError,ValueError) as e:print('STOP: '+str(e),file=sys.stderr);return 1

if __name__=='__main__':
    import project
    raise SystemExit(project.run_main(main))
