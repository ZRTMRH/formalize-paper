#!/usr/bin/env python3
"""Install the required Codex shell environment without replacing unrelated settings."""
import sys
sys.dont_write_bytecode = True
import argparse
import copy
import fnmatch
import json
from pathlib import Path
import re
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # Python 3.10: install tomli, or use Python 3.11+.
    except ImportError:
        raise SystemExit('Codex environment configuration needs Python 3.11+ or the tomli package')

KEY = 'PYTHONDONTWRITEBYTECODE'


def _check_includes(policy, where):
    # Codex 0.163.0 applies its include allowlist AFTER explicit set values.
    includes = list(policy.get('include_only', []))
    filters = policy.get('filters', {})
    includes += [k for k, v in filters.items() if v == 'include']
    if includes and not any(fnmatch.fnmatchcase(KEY.lower(), p.lower()) for p in includes):
        raise ValueError(where+' include filters must retain '+KEY)


def configured(text):
    old = tomllib.loads(text)
    policy = old.get('shell_environment_policy', {})
    _check_includes(policy, 'shell_environment_policy')
    # a profile's own policy replaces the top-level one when that profile is selected
    for name, prof in (old.get('profiles') or {}).items():
        if isinstance(prof, dict) and isinstance(prof.get('shell_environment_policy'), dict):
            _check_includes(prof['shell_environment_policy'], 'profiles.'+name+'.shell_environment_policy')
    values = policy.get('set', {})
    if values.get(KEY) == '1':
        return text
    expected = copy.deepcopy(old)
    expected.setdefault('shell_environment_policy', {}).setdefault('set', {})[KEY] = '1'
    value_line = KEY+' = "1"\n'
    if not values and 'set' not in policy:
        changed = text.rstrip()+'\n\n[shell_environment_policy.set]\n'+value_line
    else:
        # Preserve comments, order, and every unrelated key. Support a normal set table
        # and a single-line inline set map; unusual layouts fail without writing.
        table = re.search(r'(?m)^\[shell_environment_policy\.set\][ \t]*(?:#.*)?$', text)
        if table:
            start = table.end()
            end = re.search(r'(?m)^\s*\[', text[start:])
            end = start+end.start() if end else len(text)
            section = text[start:end]
            key = re.compile(r'(?m)^[ \t]*(?:'+KEY+'|"'+KEY+'"|\''+KEY+r"')[ \t]*=[ \t]*(?:\"[^\"\n]*\"|'[^'\n]*'|[^#\n]*?)([ \t]*#.*)?$")
            # keep a line comment that followed the old value
            section = (key.sub(lambda m: value_line.rstrip()+(m.group(1) or ''), section) if KEY in values
                       else section.rstrip()+'\n'+value_line)
            changed = text[:start]+section.rstrip()+'\n\n'+text[end:]
        else:
            updated = dict(values, **{KEY: '1'})
            inline = '{ '+', '.join(json.dumps(k)+' = '+json.dumps(v) for k, v in updated.items())+' }'
            candidates = list(re.finditer(r'(?m)^(\s*(?:shell_environment_policy\.)?set\s*=\s*)\{[^\n]*\}', text))
            changed = None
            for match in candidates:
                candidate = text[:match.start()]+match.group(1)+inline+text[match.end():]
                try:
                    if tomllib.loads(candidate) == expected:
                        changed = candidate
                        break
                except tomllib.TOMLDecodeError:
                    pass
            if changed is None:
                raise ValueError('unsupported shell_environment_policy.set layout; set '+KEY+' = "1" manually')
    if tomllib.loads(changed) != expected:
        raise ValueError('configuration edit would change unrelated settings; configure '+KEY+' manually')
    return changed


def selftest():
    for text in ['', '# preserved\nmodel = "example"\n',
                 '[shell_environment_policy]\ninherit = "core"\n',
                 '[shell_environment_policy.set]\nOTHER = "keep"\n',
                 '[shell_environment_policy.set]\nPYTHONDONTWRITEBYTECODE = "0"\nOTHER = "keep"\n',
                 '[shell_environment_policy]\nset = { OTHER = "keep" } # preserved\n',
                 'shell_environment_policy.set = { PYTHONDONTWRITEBYTECODE = "0", OTHER = "keep" }\n']:
        result = configured(text)
        assert configured(result) == result
        assert tomllib.loads(result)['shell_environment_policy']['set'][KEY] == '1'
        if 'OTHER' in text:
            assert tomllib.loads(result)['shell_environment_policy']['set']['OTHER'] == 'keep'
        if '# preserved' in text:
            assert '# preserved' in result
    for text in ['[shell_environment_policy]\ninclude_only = ["PATH"]\n',
                 '[shell_environment_policy.set]\n'+KEY+' = """0\n0"""\n']:
        try:
            configured(text)
        except (ValueError, tomllib.TOMLDecodeError):
            pass
        else:
            raise AssertionError('unsafe configuration accepted')
    assert configured('[shell_environment_policy]\ninclude_only = ["PATH", "PYTHON*"]\n')
    kept = configured('[shell_environment_policy.set]\n'+KEY+' = "0"  # why it was off\n')
    assert '# why it was off' in kept and tomllib.loads(kept)['shell_environment_policy']['set'][KEY] == '1', kept
    try:
        configured('[profiles.p.shell_environment_policy]\ninclude_only = ["PATH"]\n')
    except ValueError:
        pass
    else:
        raise AssertionError("a profile's include_only that drops the variable was accepted")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td)/'c'/'config.toml'
        assert write(cfg, '', configured(''), dry_run=True) and not cfg.exists(), 'dry run wrote'
        write(cfg, '', configured(''))
        assert cfg.exists() and not list(cfg.parent.glob('.config.*.tmp')), 'not written atomically'
        old = cfg.read_text(); new = configured(old.replace('"1"', '"0"'))
        cfg.write_text(old.replace('"1"', '"0"')); write(cfg, cfg.read_text(), new)
        assert (cfg.parent/'config.toml.before-formalize-paper').read_text() == old.replace('"1"', '"0"')
    print('configure-environment: selftest OK')


def write(config, text, result, dry_run=False):
    """Write `result` atomically (temporary file + rename), backing up an existing file once.
    With dry_run, only check that it could be written. Returns True."""
    import os, tempfile
    config = Path(os.path.realpath(config))
    d = config.parent
    probe = d
    while not probe.exists():
        probe = probe.parent
    if (config.exists() and not os.access(config, os.W_OK)) or not os.access(probe, os.W_OK | os.X_OK):
        raise ValueError(str(config)+' is not writable')
    if dry_run or result == text:
        return True
    d.mkdir(parents=True, exist_ok=True)
    if config.exists():
        backup = config.with_name(config.name+'.before-formalize-paper')
        if not os.path.lexists(backup):
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(text)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.config.', suffix='.tmp')
    with os.fdopen(fd, 'w') as f:
        f.write(result)
    if config.exists():
        os.chmod(tmp, config.stat().st_mode & 0o7777)
    os.replace(tmp, config)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path, nargs='?')
    parser.add_argument('--dry-run', action='store_true', help='check only; write nothing')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.config is None:
        parser.error('config path required')
    try:
        text = args.config.read_text() if args.config.exists() else ''
        result = configured(text)
        write(args.config, text, result, dry_run=args.dry_run)
    except (ValueError, OSError, UnicodeDecodeError) as error:
        parser.exit(1, 'Codex environment: '+str(error)+'; original config unchanged\n')
    if not args.dry_run:
        print('  Codex: '+str(args.config)+' requires '+KEY+'=1 for spawned commands')


if __name__ == '__main__':
    main()
