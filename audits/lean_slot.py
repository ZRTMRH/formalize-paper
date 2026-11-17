#!/usr/bin/env python3
"""A machine-wide limit on the Lean probes reviewers and helpers compile (next batch D5, CR-9: 26 lanes ran 12-15
`lean` processes at once and the machine ran out of memory).

  python3 audits/lean_slot.py run [--timeout S] [--no-slot] -- <command ...>
  python3 audits/lean_slot.py --show
  python3 audits/lean_slot.py --selftest

`run` waits for one of the machine's Lean slots (a non-blocking `flock` on /tmp/formalize-paper-lean-slots/slot<k>,
k < the run's `lean_slots`) and for `lean_free_mb` of free memory, polling every 2 s, then runs the command and
returns its exit code. It ONLY DELAYS: it never refuses and never changes a result (MAINTAINING P1, A4):
  - after `lean_max_wait` seconds (default 300) it runs anyway and prints
    `NOTE[lean-slot] ran without a slot after waiting <s> s (...)`, so a 300 s wait plus a 240 s probe stays under a
    harness's 600 s tool-call cap;
  - when the memory floor cannot be met and no other slot is held, it runs at once (nothing else to wait for);
  - a lock directory or slot file it cannot use is one NOTE, and the command runs (fail open).
`--timeout S` (default and maximum 240 s, counted from the command's start, not from the wait; a larger value is cut
to 240 with a NOTE, never refused) runs the command in its own process group and kills the group at S: exit 124
with `NOTE[lean-slot] timed out after S s` -- the probe's own result, never a protocol FAIL line. `--no-slot` skips
the queue (a probe script that is not Lean) and keeps the timeout.

Settings: the project config's `lean_slots`, `lean_free_mb`, `lean_max_wait`, `lean_ram_mb`, `lean_reserve_mb`. Absent
keys are derived from the machine's memory (DESIGN-RAM §3: `sizing`): T = min(RAM, cgroup memory.max, lean_ram_mb),
reserve R = max(4096, T/4) MB, slots S = clamp((T-R-P)/P, 1, 4) and floor F = min(R+P, T-P/2), with P = 5000 MB per
probe; an explicit `lean_slots: 0` still means no limit. Runs with different `lean_slots` share the slot files, so the machine's total
is the largest setting among them. The flock is the kernel's: it is dropped when this process exits (no stale lock),
and Python descriptors are not inherited (PEP 446), so the probe's own children do not keep it. Slot files are
created 0o666 and locked through a read-only descriptor, so another account's run can lock them; a slot file a tmp
cleaner deleted while it was held is caught by an inode re-check. Holder information is in per-pid side files
holder-<pid>.json (read by --show; a stale one, whose pid is gone, is ignored).

Not in the proof-validity core: no core file and no tool-internal Lean call imports or runs this script (Phase 0,
the axiom sweep and `project.run_lean` are not slotted, a trade-off in TRADEOFFS.md). Agents run it by instruction
(AUDIT_PROTOCOL.md common rules 7, 9, 10).

THE MEMORY GUARD (DESIGN-RAM; the protection, which relies on no agent):
  python3 audits/lean_slot.py guard --ensure
starts, unless it runs, one guard per account (a try-lock on LOCKDIR/guard-<uid>.lock, held for the guard's life;
log LOCKDIR/guard-<uid>.log). Started by code: Claude Code's SessionStart hook (claude_settings.py), and
`start_guard()` from prompt.py, lanecheck.py, `run` and `--show`. Every second it reads free memory A
(MemAvailable and the cgroup's limit; macOS vm_stat) and memory pressure (PSI `some` of the binding cgroup, else
of the machine; none on macOS), and when A < R, or A minus what the young probes (started or resumed less than
60 s ago) are presumed still to need (P_g = min(P, (T - R)/2) each, less what they hold) is < R, or the pressure over
the last 2 s is >= 5 % it pauses (SIGSTOP) the probe `lean` processes of every formalize-paper project of this
account: all but the oldest in one tick, or all of them while a tool check runs (a `lean` whose nearest
`python3 audits/<x>.py` ancestor -- the script path resolved against that process's cwd, or `-m audits.<x>` -- is
not the wrapper or codex_spawn.py, the launcher of Codex reviewers); tool checks, `lean --server`/`--worker` and
leans outside a formalize-paper project or of another account are never paused. It resumes (SIGCONT) the oldest
paused probe when A minus the young probes' need is >= R + 1 GB and the pressure stayed below 1 % for 5 s (one per
5 s; a probe so resumed is not paused again by the presumption alone for 60 s), or when nothing else runs; a pause
reaching 10 min is resumed regardless (re-paused only after 30 s of running); a probe paused 15 min in all is kept
running as the one probe while a tool check runs; a paused probe with a terminating signal pending (Linux) or whose
parent is pid 1 is resumed. A probe the wrapper cut at its time limit after a pause is reported as inconclusive
("paused M s by the memory guard; the time limit includes the pause"), never as too large. It ONLY DELAYS: it never kills, refuses or
changes a result; it raises a probe's oom_score_adj to 1000 so the kernel's OOM killer, if it ever fires, takes a
probe. Each pause is recorded (paused-<pid>.json, fsync) BEFORE the stop; on SIGTERM/SIGINT/SIGHUP or exit the guard
resumes everything; when the guard is dead (the try-lock succeeds) `--ensure` first resumes every recorded pause
(re-check R1: never while a live guard owns them). Fail open: no guard, the run behaves as before.
"""
import argparse, fcntl, glob, json, os, re, signal, subprocess, sys, tempfile, time
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LOCKDIR = "/tmp/formalize-paper-lean-slots"
MAX_TIMEOUT = 240
DEFAULT_MAX_WAIT = 300
POLL = 2.0
NOTE = "NOTE[lean-slot]"
PROBE_MB = 5000             # one probe's footprint P (DESIGN-RAM §3; replace by V2's measured marginal anon/PSS)
NO_GUARD = "FORMALIZE_PAPER_NO_GUARD"           # set: no guard is started (a selftest and its children)
TEST_KNOBS = "FORMALIZE_PAPER_GUARD_TEST"       # selftests only: JSON {lock_dir, only_under, fake_mem, tick, ...}
_TEST_AFTER_OPEN = None     # selftest hook: called (path) after a slot file is opened, before it is locked


def parse_meminfo(text):
    """MB available from Linux /proc/meminfo text (MemAvailable), or None."""
    for ln in text.splitlines():
        if ln.startswith("MemAvailable:"):
            try:
                return int(ln.split()[1]) // 1024
            except (IndexError, ValueError):
                return None
    return None


def parse_vm_stat(text):
    """MB available from macOS `vm_stat` text (free + inactive + speculative pages x page size), or None."""
    import re
    m = re.search(r"page size of (\d+) bytes", text)
    if not m:
        return None
    size, pages = int(m.group(1)), 0
    for key in ("Pages free", "Pages inactive", "Pages speculative"):
        k = re.search(rf"^{key}:\s+(\d+)", text, re.M)
        if k:
            pages += int(k.group(1))
    return pages * size // (1024 * 1024)


def cgroup_mb(root="/sys/fs/cgroup", own=None):
    """(limit, free) in MB of the tightest cgroup-v2 memory.max among this process's cgroup and its ancestors (free =
    max - current + inactive_file: page cache the kernel drops first is not counted as used), or (None, None)."""
    try:
        if own is None:
            own = next(ln[3:].strip() for ln in open("/proc/self/cgroup", encoding="utf-8") if ln.startswith("0::"))
    except (OSError, StopIteration):
        return None, None
    lim = free = None
    p = "/" + own.strip("/")
    while True:
        d = os.path.join(root, p.lstrip("/"))
        try:
            mx = open(os.path.join(d, "memory.max"), encoding="utf-8").read().strip()
            if mx != "max":
                mx, cur = int(mx) >> 20, int(open(os.path.join(d, "memory.current"), encoding="utf-8").read()) >> 20
                try:
                    cache = int(re.search(r"^inactive_file (\d+)", open(os.path.join(d, "memory.stat"),
                                          encoding="utf-8").read(), re.M).group(1)) >> 20
                except (OSError, AttributeError, ValueError):
                    cache = 0
                lim = mx if lim is None else min(lim, mx)
                free = mx - cur + cache if free is None else min(free, mx - cur + cache)
        except (OSError, ValueError):
            pass
        if p == "/":
            return lim, free
        p = os.path.dirname(p)


def psi_path(root="/sys/fs/cgroup", own=None):
    """The memory-pressure (PSI) file of the cgroup whose memory.max binds this process (its tightest limit), else the
    machine's /proc/pressure/memory, else None (no PSI: macOS, an old kernel)."""
    best, lim = None, None
    try:
        if own is None:
            own = next(ln[3:].strip() for ln in open("/proc/self/cgroup", encoding="utf-8") if ln.startswith("0::"))
        p = "/" + own.strip("/")
        while True:
            d = os.path.join(root, p.lstrip("/"))
            try:
                mx = open(os.path.join(d, "memory.max"), encoding="utf-8").read().strip()
                if mx != "max" and (lim is None or int(mx) < lim) and os.path.exists(os.path.join(d, "memory.pressure")):
                    best, lim = os.path.join(d, "memory.pressure"), int(mx)
            except (OSError, ValueError):
                pass
            if p == "/":
                break
            p = os.path.dirname(p)
    except (OSError, StopIteration):
        pass
    return best or ("/proc/pressure/memory" if os.path.exists("/proc/pressure/memory") else None)


def psi_total(path):
    """The cumulative `some` stall time (microseconds) in a PSI file, or None."""
    try:
        m = re.search(r"^some .*\btotal=(\d+)", open(path, encoding="utf-8").read(), re.M)
        return int(m.group(1)) if m else None
    except (OSError, TypeError):
        return None


def total_mb(cg=None):
    """The machine's memory T in MB (Linux MemTotal and the cgroup limit; macOS hw.memsize), or None."""
    t = None
    try:
        m = re.search(r"^MemTotal:\s+(\d+)", open("/proc/meminfo", encoding="utf-8").read(), re.M)
        t = int(m.group(1)) // 1024 if m else None
    except OSError:
        try:
            t = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                   timeout=10).stdout.strip()) >> 20
        except (OSError, ValueError, subprocess.SubprocessError):
            t = None
    lim = (cg or cgroup_mb)()[0]
    return min(x for x in (t, lim) if x is not None) if (t or lim) else None


def avail_mb(cg=None):
    """Free memory in MB (Linux MemAvailable, with a cgroup's own limit when it is tighter; macOS vm_stat), or None
    when unreadable (the floor is then ignored). Under WSL this is the VM's memory, not Windows' (TRADEOFFS)."""
    a = None
    try:
        a = parse_meminfo(open("/proc/meminfo", encoding="utf-8").read())
    except OSError:
        try:
            a = parse_vm_stat(subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10).stdout)
        except (OSError, subprocess.SubprocessError):
            a = None
    free = (cg or cgroup_mb)()[1]
    return min(x for x in (a, free) if x is not None) if (a is not None or free is not None) else None


def _pos(v):
    try:
        v = int(v)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def sizing(total, cfg=None):
    """DESIGN-RAM §3: {T, R, P, S, F} in MB from the machine's memory and the config's `lean_ram_mb` and
    `lean_reserve_mb`, or None when the memory is unknown. F = min(R + P, T - P/2): a floor that can be met on 8 GB."""
    cfg = cfg or {}
    ts = [t for t in (_pos(total), _pos(cfg.get("lean_ram_mb"))) if t]
    if not ts:
        return None
    t = min(ts)
    r = _pos(cfg.get("lean_reserve_mb")) or max(4096, t // 4)
    p = PROBE_MB
    return dict(T=t, R=r, P=p, S=max(1, min(4, (t - r - p) // p)), F=min(r + p, t - p // 2))


def settings(cfg, total=None):
    """(slots or 0, free_mb, max_wait) from a project config. An absent `lean_slots` or `lean_free_mb` is derived from
    the machine's memory (`sizing`; unknown memory: no limit, no floor); an explicit 0 means none; wait 300 s."""
    def num(k, d):
        try:
            v = int((cfg or {}).get(k, d))
            return v if v >= 0 else d
        except (TypeError, ValueError):
            return d
    sz = sizing(total_mb() if total is None else total, cfg)
    # fix round 1 (compat 1): the wait is capped at 300 s, so a wait plus a 240 s probe stays under a 600 s call
    return (num("lean_slots", sz["S"] if sz else 0), num("lean_free_mb", sz["F"] if sz else 0),
            min(num("lean_max_wait", DEFAULT_MAX_WAIT), DEFAULT_MAX_WAIT))


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True     # another account's process
    except OSError:
        return False


def holders(lockdir):
    """[holder record] of the live holders (holder-<pid>.json whose pid is alive)."""
    out = []
    for p in sorted(glob.glob(os.path.join(lockdir, "holder-*.json"))):
        try:
            h = json.load(open(p, encoding="utf-8"))
            if isinstance(h, dict) and _alive(int(h.get("pid", -1))):
                out.append(h)
        except (OSError, ValueError, TypeError):
            continue
    return out


def _slot_held(path):
    """Is slot file `path` locked by someone (a probe: lock and release at once)?"""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def _open_slot(path):
    fd = os.open(path, os.O_CREAT | os.O_RDONLY, 0o666)
    try:
        os.fchmod(fd, 0o666)
    except OSError:
        pass        # another account's file: still lockable through a read-only descriptor
    return fd


def acquire(slots, free_mb, max_wait, lockdir=LOCKDIR, poll=POLL, mem=avail_mb, info=None):
    """(slot descriptor or None, [note]). None with no note: no limit configured. None with a note: ran without a
    slot (waited max_wait, or the lock directory / a slot file was unusable). Never raises for a lock problem."""
    if not slots:
        return None, []
    try:
        if not os.path.isdir(lockdir):
            os.makedirs(lockdir, exist_ok=True)
            os.chmod(lockdir, 0o1777)
        if not os.access(lockdir, os.W_OK | os.X_OK):
            raise PermissionError(f"{lockdir} is not writable")
    except OSError as e:
        return None, [f"{NOTE} the lock directory cannot be used ({type(e).__name__}: {e}): ran without a slot"]
    start = time.monotonic()
    while True:
        for k in range(slots):
            path = os.path.join(lockdir, f"slot{k}")
            try:
                fd = _open_slot(path)
            except OSError as e:
                return None, [f"{NOTE} slot file {path} cannot be opened ({type(e).__name__}: {e}): ran without a slot"]
            if _TEST_AFTER_OPEN:
                _TEST_AFTER_OPEN(path)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            except OSError as e:
                os.close(fd)
                return None, [f"{NOTE} slot file {path} cannot be locked ({type(e).__name__}: {e}): ran without a slot"]
            try:
                same = os.fstat(fd).st_ino == os.stat(path).st_ino
            except OSError:
                same = False
            if not same:        # deleted (a tmp cleaner) after we opened it: another caller may hold its successor
                os.close(fd)
                continue
            m = mem() if free_mb else None
            if free_mb and m is not None and m < free_mb:
                others = any(_slot_held(os.path.join(lockdir, f"slot{j}")) for j in range(max(slots, 8)) if j != k)
                if others:
                    os.close(fd)        # below the floor while others run: wait for one to finish
                    break
            _write_holder(lockdir, k, info)
            return fd, []
        waited = time.monotonic() - start
        if waited >= max_wait:
            hs = holders(lockdir)
            return None, [f"{NOTE} ran without a slot after waiting {int(waited)} s ({len(hs)} held by: "
                          f"{', '.join(str(h.get('pid')) for h in hs) or 'unknown'})"]
        time.sleep(min(poll, max(0.05, max_wait - waited)))


def _holder_path(lockdir):
    return os.path.join(lockdir, f"holder-{os.getpid()}.json")


def _write_holder(lockdir, k, info):
    try:
        p = _holder_path(lockdir)
        fd = os.open(p, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w") as f:
            json.dump(dict(info or {}, pid=os.getpid(), slot=k), f)
    except OSError:
        pass        # holder information is for --show only


def release(fd, lockdir=LOCKDIR):
    if fd is None:
        return
    try:
        os.remove(_holder_path(lockdir))
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def run_cmd(cmd, timeout, paused=lambda: 0):
    """(exit code, [note]): `cmd` in its own process group; at `timeout` s the group is killed: 124. `paused()`, read
    BEFORE the kill (the guard resumes a killed probe and logs it afterwards), is the seconds the memory guard paused
    the probe: a cut probe that was paused is inconclusive, never "too large" (fix round RAMK, F1)."""
    try:
        p = subprocess.Popen(cmd, start_new_session=True)
    except OSError as e:
        print(f"lean_slot: cannot run {cmd[:1]}: {e}", file=sys.stderr)
        return 127, []

    def _killed(sig, _frame):
        # fix round 1 (compat 1): a wrapper killed by the harness (a Bash timeout, a stopped background task, a
        # subagent that returned) takes its probe with it: no unslotted, untimed Lean is left running
        for s_ in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, s_)
            except OSError:
                pass
            try:
                p.wait(timeout=3)
                break
            except subprocess.TimeoutExpired:
                continue
        raise SystemExit(128 + sig)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        try:
            signal.signal(sig, _killed)
        except (OSError, ValueError):
            pass
    try:
        return p.wait(timeout=timeout), []
    except subprocess.TimeoutExpired:
        try:
            m = int(paused() or 0)
        except Exception:       # noqa: BLE001 -- the note is advice only
            m = 0
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                pass
            try:
                p.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        # fix round RAMK F1': only a pause that took a real share of the limit (>= a quarter) makes the cut
        # inconclusive; a short pause leaves the size advice (so a probe that is really too large cannot be told to
        # "re-run" forever)
        if m > 0 and m * 4 >= timeout:
            return 124, [f"{NOTE} timed out after {timeout} s, paused {m} s by the memory guard; the time limit "
                         f"includes the pause \u2014 re-run, this is not a too-large probe (inconclusive: cite nothing "
                         f"from it)"]
        extra = f" (it was paused {m} s by the memory guard, under a quarter of the limit)" if m > 0 else ""
        return 124, [f"{NOTE} timed out after {timeout} s: the probe is too large{extra}; split it into smaller probes, or "
                     f"mark the item NotDoneYet and say why"]


# ---------------------------------------------------------------------------------------------------------------
# The memory guard (DESIGN-RAM §2; module docstring). Times in seconds, memory in MB.
TICK, PAUSE_CAP, REPAUSE_AFTER, RESUME_GAP, HYST_MB, IDLE_EXIT = 1.0, 600, 30, 5, 1024, 6 * 3600
# V2 round 1: 12 probes mapping Mathlib's .olean files thrashed the page cache (PSI full avg10 40 %) while free memory
# looked ample. Memory pressure (PSI `some`, the share of time a task waited for memory) over the last PSI_WINDOW s
# also pauses; a memory resume also needs the pressure below PSI_RESUME over the last 5 s.
PSI_PAUSE, PSI_RESUME, PSI_WINDOW = 0.05, 0.01, 2.0
YOUNG = 60          # a probe's start-up, and the time after a resume, during which it is presumed to grow to P
# fix round RAMK (F2): the presumed need is sized to the machine, P_g = min(P, (T - R) / 2) (2 GB on 8 GB), a memory
# resume needs free - need >= R + 1 GB, and a probe so resumed is not re-paused by the projection alone for YOUNG s
# (low free memory or pressure still pause it): a second probe can run on 8 GB, or on 16 GB with 8 GB available. A
# probe paused TOTAL_PAUSE s in all is kept running as the one probe while a tool check runs (never killed).
TOTAL_PAUSE = 900
TERM_MASK = sum(1 << (s_ - 1) for s_ in (1, 2, 9, 15))     # SIGHUP, SIGINT, SIGKILL, SIGTERM pending
TOOL_RE = re.compile(r"(?:^|/)audits/([A-Za-z0-9_]+)\.py$")
LOCK_TOOLS = ("phase0", "axiom_sweep", "signoff", "fingerprint", "dependencies", "scope", "selftest_all")
RESUME_RE = re.compile(r"\bt=(\d+) resume pid=(\d+) after=(\d+)s anc=([\d,]*)")


def _knobs():
    try:
        k = json.loads(os.environ.get(TEST_KNOBS) or "{}")
        return k if isinstance(k, dict) else {}
    except ValueError:
        return {}


def _guard_paths(lockdir):
    uid = os.getuid()
    return os.path.join(lockdir, f"guard-{uid}.lock"), os.path.join(lockdir, f"guard-{uid}.log")


AGENT_SCRIPTS = ("lean_slot", "codex_spawn")   # the probe wrapper, and the launcher of Codex reviewers (agents)


MOD_RE = re.compile(r"(?:audits\.)?([A-Za-z0-9_]+)$")


def _audits_script(argv, cwd=lambda: None):
    """The <name> of a `python3 … audits/<name>.py` command line, else None. Fix round RAMK (F3): a relative script
    path is resolved against the process's cwd (`cwd()`, read only when needed): `cd audits && python3 phase0.py`,
    `python3 ./audits//phase0.py` and `python3 -m audits.phase0` (or `-m phase0` inside audits/) are tool checks too."""
    if not argv or not os.path.basename(argv[0]).startswith("python"):
        return None
    args, here = argv[1:], []

    def wd():
        if not here:
            try:
                here.append(cwd())
            except Exception:       # noqa: BLE001 -- an unreadable cwd: the path as written
                here.append(None)
        return here[0]
    for i, a in enumerate(args):
        if a.startswith("-m") and not a.startswith("--"):
            mod = a[2:] or (args[i + 1] if i + 1 < len(args) else "")
            m = MOD_RE.fullmatch(mod)
            if m and (mod.startswith("audits.") or ((w := wd()) and os.path.basename(os.path.normpath(w)) == "audits")):
                return m.group(1)
            return None
        if not a.endswith(".py"):
            continue
        if (m := TOOL_RE.search(os.path.normpath(a))):
            return m.group(1)
        if not os.path.isabs(a) and (w := wd()) and (m := TOOL_RE.search(os.path.normpath(os.path.join(w, a)))):
            return m.group(1)
    return None


class LinuxProcs:
    """The process table from /proc (Linux, WSL)."""
    cwd_depth = 64      # how many processes (the lean, then its ancestors) are asked for a cwd while looking for a root

    def table(self):
        out = {}
        for e in os.listdir("/proc"):
            if not e.isdigit():
                continue
            try:
                st = open(f"/proc/{e}/stat", encoding="utf-8", errors="replace").read()
                uid = os.stat(f"/proc/{e}").st_uid
                i = st.rfind(")")
                f = st[i + 2:].split()
                out[int(e)] = dict(comm=st[st.find("(") + 1:i], state=f[0], ppid=int(f[1]), start=int(f[19]), uid=uid)
            except (OSError, ValueError, IndexError):
                continue
        return out

    def argv(self, pid):
        try:
            return open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", "replace").split("\0")[:-1]
        except OSError:
            return []

    def cwd(self, pid):
        try:
            return os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            return None

    def _status(self, pid, key):
        try:
            m = re.search(rf"^{key}:\s+(\S+)", open(f"/proc/{pid}/status", encoding="utf-8").read(), re.M)
            return m.group(1) if m else None
        except OSError:
            return None

    def pending_term(self, pid):
        return any(int(self._status(pid, k) or "0", 16) & TERM_MASK for k in ("ShdPnd", "SigPnd"))

    def anon_mb(self, pid):
        return int(self._status(pid, "RssAnon") or 0) // 1024

    def oom(self, pid):
        try:
            with open(f"/proc/{pid}/oom_score_adj", "w") as f:
                f.write("1000")
        except OSError:
            pass

    kill = staticmethod(os.kill)


def parse_ps(text):
    """{pid: row} from `ps -axww -o pid=,ppid=,uid=,state=,lstart=,rss=,args=` (macOS); start = lstart as epoch. `ps`
    runs with LC_ALL=C; a row whose lstart still does not parse (another locale) is skipped: the guard does not see
    that process (fails open: it is never paused)."""
    out = {}
    for ln in text.splitlines():
        f = ln.split(None, 10)
        if len(f) < 11:
            continue
        try:
            start = int(time.mktime(time.strptime(" ".join(f[4:9]), "%a %b %d %H:%M:%S %Y")))
            out[int(f[0])] = dict(comm=os.path.basename(f[10].split()[0]), state=f[3][:1], ppid=int(f[1]),
                                  start=start, uid=int(f[2]), rss=int(f[9]) // 1024, args=f[10].split())
        except (ValueError, IndexError):
            continue
    return out


class PsProcs:
    """The process table from `ps` and `lsof` (macOS): no pending-signal test (the 10 min cap covers it), no
    oom_score_adj. Fix round RAMK (F6): one `lsof` per pid per tick (cached), at most 8 processes per root search."""
    cwd_depth = 8

    def __init__(self):
        self.t, self.cw = {}, {}

    def table(self):
        self.cw = {}
        try:
            self.t = parse_ps(subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,uid=,state=,lstart=,rss=,args="],
                                             capture_output=True, text=True, timeout=10,
                                             env=dict(os.environ, LC_ALL="C")).stdout)
        except (OSError, subprocess.SubprocessError):
            self.t = {}
        return self.t

    def argv(self, pid):
        return self.t.get(pid, {}).get("args", [])

    def cwd(self, pid):
        if pid in self.cw:
            return self.cw[pid]
        try:
            r = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True,
                               timeout=10)
            self.cw[pid] = next((ln[1:] for ln in r.stdout.splitlines() if ln.startswith("n")), None)
        except (OSError, subprocess.SubprocessError):
            self.cw[pid] = None
        return self.cw[pid]

    def pending_term(self, pid):
        return False

    def anon_mb(self, pid):
        return self.t.get(pid, {}).get("rss", 0)

    def oom(self, pid):
        pass

    kill = staticmethod(os.kill)


def recover(lockdir):
    """Resume every pause recorded in `lockdir` by this account whose process still runs with the recorded start
    time, and remove the records: run only by the holder of the guard lock (a dead guard's pauses; re-check R1)."""
    n, table = 0, None
    for p in glob.glob(os.path.join(lockdir, "paused-*.json")):
        try:
            if os.stat(p).st_uid != os.getuid():
                continue
            r = json.load(open(p, encoding="utf-8"))
            if table is None:
                table = (LinuxProcs() if os.path.isdir("/proc/self") else PsProcs()).table()
            if table.get(int(r["pid"]), {}).get("start") == r.get("start"):
                os.kill(int(r["pid"]), signal.SIGCONT)
                n += 1
        except (OSError, ValueError, KeyError, TypeError):
            pass
        try:
            os.remove(p)
        except OSError:
            pass
    return n


def _mkdir(lockdir):
    if not os.path.isdir(lockdir):
        os.makedirs(lockdir, exist_ok=True)
        os.chmod(lockdir, 0o1777)


def _log(path, msg):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} t={int(time.time())} {msg}\n")
    except OSError:
        pass


def ensure(lockdir=None):
    """Start the guard unless one runs for this account. Never raises, never waits (a try-lock); 'running' (a live
    guard owns its pauses: nothing is touched, re-check R1), 'started' (the guard was dead: its recorded pauses are
    resumed first), 'off' ($FORMALIZE_PAPER_NO_GUARD) or 'error' (one log line)."""
    if os.environ.get(NO_GUARD):
        return "off"
    k = _knobs()
    lockdir = lockdir or k.get("lock_dir") or LOCKDIR
    fd = None
    lock, log = _guard_paths(lockdir)
    try:
        _mkdir(lockdir)
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "running"
        n = recover(lockdir)
        if n:
            _log(log, f"ensure: resumed {n} process(es) a dead guard had paused")
        args = [a for o in ("only_under", "fake_mem", "tick", "gap", "cap", "repause")
                if k.get(o) is not None for a in (f"--{o.replace('_', '-')}", str(k[o]))]
        with open(log, "a") as lf:
            subprocess.Popen([sys.executable, "-B", os.path.abspath(__file__), "guard", "--lock-dir", lockdir,
                              "--lock-fd", str(fd), *args], stdin=subprocess.DEVNULL, stdout=lf, stderr=lf,
                             pass_fds=(fd,), start_new_session=True, cwd="/")
        return "started"
    except Exception as e:      # noqa: BLE001 -- fail open: one log line and nothing else
        _log(log, f"ensure: could not start the guard ({type(e).__name__}: {e})")
        return "error"
    finally:
        if fd is not None:
            os.close(fd)


def start_guard():
    """The pinned scripts' starter (prompt.py, lanecheck.py, `run`, `--show`): ensure the guard; never raises, never
    waits, prints nothing. A selftest process starts none, and neither do its children."""
    try:
        if os.environ.get(NO_GUARD):
            return "off"
        import project
        if project._in_selftest():
            os.environ[NO_GUARD] = "1"
            return "off"
        return ensure()
    except Exception:       # noqa: BLE001
        return "error"


class Guard:
    """One tick a second (DESIGN-RAM §2.3). `procs` is LinuxProcs/PsProcs (or a test's fake), `mem()` -> (A, T)."""
    def __init__(self, lockdir, procs, mem, only_under=None, clock=time.monotonic, gap=RESUME_GAP, cap=PAUSE_CAP,
                 repause=REPAUSE_AFTER, psi=lambda: None):
        self.ld, self.os, self.mem, self.clock, self.psi = lockdir, procs, mem, clock, psi
        self.psi_hist = []          # [(clock, cumulative `some` stall microseconds)]
        self.only = os.path.realpath(only_under) if only_under else None
        self.gap, self.cap, self.repause = gap, cap, repause
        self.uid = os.getuid()
        self.log_path = _guard_paths(lockdir)[1]
        self.paused = {}            # pid -> [start, clock time paused, ancestors]
        self.hold = {}              # pid -> clock time before which it is not paused (cap, signal, orphan resumes)
        self.admit = {}             # pid -> clock time before which the projection alone does not pause it (F2)
        self.info = {}              # (pid, start) -> [class, root, peak anon MB] or None (no lean of a formalize-paper project of this account)
        self.roots, self.roots_t, self.cfgs = {}, clock(), {}
        self.last_resume, self.last_lean, self.last_note, self.last_stall = -1e18, clock(), -1e18, None

    def log(self, msg):
        _log(self.log_path, msg)

    def _root(self, d):
        """The nearest directory at or above `d` holding a formalize-paper config (audits/projects/*.json), or None."""
        seen, r = [], None
        while d and d not in self.roots:
            seen.append(d)
            if glob.glob(os.path.join(d, "audits", "projects", "*.json")):
                r = d
                break
            up = os.path.dirname(d)
            d = up if up != d else None
        else:
            r = self.roots.get(d)
        for x in seen:
            self.roots[x] = r
        return r

    def classify(self, pid, tab):
        """[class, root, peak, young since, anon, paused s] of a `lean` of any formalize-paper project of this account
        (class tool or probe; "this run's" in the comments), else None; cached per (pid, start)."""
        p = tab[pid]
        key = (pid, p["start"])
        if key in self.info:
            return self.info[key]
        res = None
        if p["comm"] == "lean" and p["uid"] == self.uid:
            argv = self.os.argv(pid)
            if not any(a.startswith(("--server", "--worker")) for a in argv[1:]):
                # class: the NEAREST `python3 audits/<x>.py` ancestor decides (tool, unless it is the wrapper or the
                # launcher of Codex reviewers, whose leans are agents' probes)
                root, cls, q, n = None, None, pid, 0
                depth = getattr(self.os, "cwd_depth", 64)
                while q in tab and q > 1 and n < 64:
                    if root is None and n < depth:
                        c = self.os.cwd(q)
                        root = self._root(os.path.realpath(c)) if c else None
                    if q != pid and cls is None and (name := _audits_script(self.os.argv(q),
                                                                            lambda q_=q: self.os.cwd(q_))):
                        cls = "probe" if name in AGENT_SCRIPTS else "tool"
                    q, n = tab[q]["ppid"], n + 1
                cls = cls or "probe"
                if root and (not self.only or (root + "/").startswith(self.only + "/")):
                    res = [cls, root, 0, None, 0, 0]   # class, root, peak anon, young since, anon now, paused s
        self.info[key] = res
        return res

    def _cfg(self, roots):
        """The tightest `lean_ram_mb` and the largest `lean_reserve_mb` of the configs under these roots (read again
        once a minute)."""
        key = frozenset(roots)
        if key in self.cfgs and self.clock() - self.cfgs[key][0] < 60:
            return self.cfgs[key][1]
        ram, res = [], []
        for r in roots:
            for f in glob.glob(os.path.join(r, "audits", "projects", "*.json")):
                try:
                    c = json.load(open(f, encoding="utf-8"))
                    ram.append(_pos(c.get("lean_ram_mb")))
                    res.append(_pos(c.get("lean_reserve_mb")))
                except (OSError, ValueError, AttributeError):
                    continue
        ram, res = [x for x in ram if x], [x for x in res if x]
        self.cfgs[key] = (self.clock(), dict(lean_ram_mb=min(ram) if ram else None,
                                             lean_reserve_mb=max(res) if res else None))
        return self.cfgs[key][1]

    def _record(self, pid, tab, anc):
        try:
            fd = os.open(os.path.join(self.ld, f"paused-{pid}.json"), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
            with os.fdopen(fd, "w") as f:
                json.dump(dict(pid=pid, start=tab[pid]["start"], t=int(time.time()), anc=anc), f)
                f.flush()
                os.fsync(f.fileno())
            return True
        except OSError as e:
            self.log(f"cannot record a pause of pid={pid} ({e}): not paused")
            return False

    def _unrecord(self, pid):
        try:
            os.remove(os.path.join(self.ld, f"paused-{pid}.json"))
        except OSError:
            pass

    def _pause(self, pid, tab, now, a, r):
        anc, q = [], tab[pid]["ppid"]
        while q in tab and q > 1 and len(anc) < 64:
            anc.append(q)
            q = tab[q]["ppid"]
        if not self._record(pid, tab, anc):
            return
        try:
            self.os.kill(pid, signal.SIGSTOP)
        except OSError:
            self._unrecord(pid)
            return
        self.paused[pid] = [tab[pid]["start"], now, anc]
        self.log(f"pause pid={pid} free={a}MB reserve={r}MB pressure={self.last_stall}")

    def _resume(self, pid, why, now):
        st = self.paused.pop(pid, None)
        if st and (pid, st[0]) in self.info and self.info[(pid, st[0])]:
            self.info[(pid, st[0])][3] = now      # resumed: young again (it may grow to P from here)
            self.info[(pid, st[0])][5] += now - st[1]
        if why == "memory":
            self.admit[pid] = now + YOUNG
        if why != "gone":
            try:
                self.os.kill(pid, signal.SIGCONT)
            except OSError:
                pass
        self._unrecord(pid)
        if why in ("memory", "idle"):
            self.last_resume = now
        if st:
            self.log(f"resume pid={pid} after={int(now - st[1])}s anc={','.join(map(str, st[2]))} why={why}")

    def resume_all(self, why="guard-exit"):
        for pid in list(self.paused):
            self._resume(pid, why, self.clock())

    def tick(self):
        """One tick; True when the guard should exit (no run lean for 6 h)."""
        now = self.clock()
        if now - self.roots_t > 60:
            self.roots, self.roots_t = {}, now
        tab = self.os.table()
        # a zombie (exited, not yet reaped by its parent) holds no memory and runs nothing: not a lean that runs
        leans = {pid: c for pid in tab if tab[pid]["state"] not in ("Z", "X") and (c := self.classify(pid, tab))}
        for key in [k_ for k_ in self.info if k_[0] not in tab or tab[k_[0]]["start"] != k_[1]]:
            c = self.info.pop(key)
            if c and c[2] >= 1024:
                self.log(f"peak pid={key[0]} class={c[0]} anon={c[2]}MB")
        for pid, c in leans.items():
            if c[2] == 0 and c[0] == "probe":
                self.os.oom(pid)
            c[4] = self.os.anon_mb(pid) or 0
            c[2] = max(c[2], c[4], 1)
            if c[3] is None:
                c[3] = now
        a, t = self.mem()
        sz = sizing(t, self._cfg({c[1] for c in leans.values()}))
        r = sz["R"] if sz else None
        for pid in list(self.paused):
            st = self.paused[pid]
            if pid not in tab or tab[pid]["start"] != st[0] or tab[pid]["state"] in ("Z", "X"):
                self._resume(pid, "gone", now)
                continue
            why = ("signal" if self.os.pending_term(pid) else "orphan" if tab[pid]["ppid"] == 1
                   else "cap" if now - st[1] >= self.cap else None)
            if why:
                self._resume(pid, why, now)
                self.hold[pid] = now + (self.repause if why == "cap" else 1e18)
        tools = [p for p, c in leans.items() if c[0] == "tool"]
        running = sorted((p for p, c in leans.items() if c[0] == "probe" and p not in self.paused),
                         key=lambda p: (tab[p]["start"], p))
        tot = self.psi()
        if tot is not None:
            self.psi_hist = [x for x in self.psi_hist if now - x[0] <= 6] + [(now, tot)]

        def stall(secs):
            """The share of the last ~`secs` seconds some task waited for memory, or None (no PSI history)."""
            old = [x for x in self.psi_hist if 0.9 <= now - x[0] <= secs + 1.5]
            if tot is None or not old:
                return None
            t0, v0 = old[0]
            return (tot - v0) / ((now - t0) * 1e6)
        sp = stall(PSI_WINDOW)
        self.last_stall = None if sp is None else f"{100 * sp:.0f}%"
        pressed = sp is not None and sp >= PSI_PAUSE
        # V2 round 2: a probe in its first YOUNG s is presumed to still need P minus what it holds (fast allocation is
        # what stalls: 3 probes starting together already reach PSI 5 %), so a burst is paused before it allocates
        p_ = min(sz["P"], max(HYST_MB, (sz["T"] - sz["R"]) // 2)) if sz else PROBE_MB
        need = sum(max(0, p_ - c[4]) for p, c in leans.items()
                   if c[0] == "probe" and p not in self.paused and now - (c[3] or now) < YOUNG)
        proj = None if a is None else a - need
        low = (proj is not None and r is not None and proj < r) or pressed
        real = pressed or (a is not None and r is not None and a < r)     # not the projection alone
        if low:
            # F2: while a tool check runs, a probe already paused TOTAL_PAUSE s in all is kept as the one probe
            keep = set(running[:1]) if not tools else set([p for p in running if leans[p][5] >= TOTAL_PAUSE][:1])
            for p in running:
                if (p not in keep and tab[p]["ppid"] != 1 and self.hold.get(p, 0) <= now
                        and (real or self.admit.get(p, 0) <= now)):
                    self._pause(p, tab, now, a, r)
        oldest = sorted(self.paused, key=lambda p: (self.paused[p][0], p))
        if oldest and not tools and all(p in self.paused for p, c in leans.items() if c[0] == "probe"):
            self._resume(oldest[0], "idle", now)
        elif (oldest and not low and now - self.last_resume >= self.gap
              and (proj is None or r is None or proj >= r + HYST_MB)
              and ((s5 := stall(5)) is None or s5 < PSI_RESUME)):
            self._resume(oldest[0], "memory", now)
        if self.paused and not tools and now - self.last_note >= 60:
            busy = [p for p, x in tab.items() if x["uid"] == self.uid and x["comm"].startswith("python")
                    and _audits_script(self.os.argv(p), lambda p_=p: self.os.cwd(p_)) in LOCK_TOOLS
                    and (c_ := self.os.cwd(p)) and (r_ := self._root(os.path.realpath(c_)))
                    and (not self.only or (r_ + "/").startswith(self.only + "/"))]
            if busy:
                self.last_note = now
                self.log(f"note: tool script pid={busy[0]} runs with no lean while {len(self.paused)} probe(s) are "
                         f"paused (it may wait on a Lake lock a paused probe holds: bounded by the 10 min cap)")
        for d_ in (self.hold, self.admit):
            for p in [p for p in d_ if p not in tab]:
                del d_[p]
        if leans:
            self.last_lean = now
        return now - self.last_lean >= IDLE_EXIT


def _wsl():
    try:
        return "microsoft" in open("/proc/version", encoding="utf-8").read().lower()
    except OSError:
        return False


def _windows_free(lockdir, log):
    """WSL only, every 60 s: Windows' free memory (setup-e2e.sh's PowerShell call, 15 s timeout) into
    LOCKDIR/winfree-<uid> for the wrapper's NOTE. A flag: it never pauses and never waits."""
    ps = "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"
    while True:
        try:
            out = subprocess.run([ps, "-NoProfile", "-Command",
                                  "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            if out.isdigit():
                with open(os.path.join(lockdir, f"winfree-{os.getuid()}"), "w") as f:
                    f.write(f"{out} {int(time.time())}\n")
                if int(out) < 2048:
                    _log(log, f"windows free memory {out}MB (below 2 GB; the guard sees only the WSL VM)")
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        time.sleep(60)


def guard_main(a):
    lockdir = a.lock_dir
    lock, log = _guard_paths(lockdir)
    if a.lock_fd is None:       # started by hand: take the lock (held: a guard runs, nothing to do), recover first
        try:
            _mkdir(lockdir)
            fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        recover(lockdir)
    try:
        if os.path.getsize(log) > 20 << 20:
            os.replace(log, log + ".1")
    except OSError:
        pass
    if a.fake_mem:
        def mem():
            try:
                x = open(a.fake_mem, encoding="utf-8").read().split()
                return int(x[0]), int(x[1])
            except (OSError, ValueError, IndexError):
                return None, None

        def psi():      # an optional third number: cumulative stall microseconds
            try:
                return int(open(a.fake_mem, encoding="utf-8").read().split()[2])
            except (OSError, ValueError, IndexError):
                return None
    else:
        def mem():
            return avail_mb(), total_mb()
        pf = psi_path()

        def psi():
            return psi_total(pf)
    g = Guard(lockdir, LinuxProcs() if os.path.isdir("/proc/self") else PsProcs(), mem, a.only_under,
              gap=a.gap, cap=a.cap, repause=a.repause, psi=psi)

    def stop(sig, _frame):
        raise SystemExit(0)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    g.log(f"guard started pid={os.getpid()}")
    if _wsl() and not a.fake_mem:
        import threading
        threading.Thread(target=_windows_free, args=(lockdir, log), daemon=True).start()
    errs = 0
    try:
        while True:
            try:
                if g.tick():
                    g.log("guard exits: no run lean for 6 h")
                    return 0
            except Exception as e:      # noqa: BLE001 -- one bad tick is logged, the guard goes on
                errs += 1
                if errs <= 20:
                    g.log(f"tick error ({type(e).__name__}: {e})")
            time.sleep(a.tick)
    finally:
        g.resume_all()
        g.log(f"guard stopped pid={os.getpid()}")


def pause_secs(lockdir, since, me=None):
    """Seconds the guard paused a process under this wrapper (pid `me`) since `since`: the ended pauses of its log and
    (F1) the pauses still in progress (paused-<pid>.json records naming `me` among the ancestors). Records are read
    first; a pid whose resume the log already shows is counted once."""
    me = str(me or os.getpid())
    cur = {}
    for f in glob.glob(os.path.join(lockdir, "paused-*.json")):
        try:
            r = json.load(open(f, encoding="utf-8"))
            if me in [str(x) for x in r.get("anc") or []]:
                cur[str(r["pid"])] = max(0, int(time.time()) - int(r["t"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    try:
        with open(_guard_paths(lockdir)[1], "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - (256 << 10)))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    s = 0
    for m in RESUME_RE.finditer(text):
        if int(m.group(1)) >= since and me in m.group(4).split(","):
            s += int(m.group(3))
            cur.pop(m.group(2), None)
    return s + sum(cur.values())


def pause_note(lockdir, since, me=None, pause_line=True):
    """The wrapper's NOTE: seconds the guard paused a process under this wrapper (pid `me`) since `since`, or ''."""
    me = str(me or os.getpid())
    try:
        with open(_guard_paths(lockdir)[1], "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - (256 << 10)))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    s = sum(int(m.group(3)) for m in RESUME_RE.finditer(text) if int(m.group(1)) >= since and me in m.group(4).split(","))
    out = f"{NOTE} paused {s} s by the memory guard (machine memory low)" if s and pause_line else ""
    try:
        w, t = open(os.path.join(lockdir, f"winfree-{os.getuid()}"), encoding="utf-8").read().split()
        if int(w) < 2048 and time.time() - int(t) < 180:
            out += ("\n" if out else "") + (f"{NOTE} Windows reports {w} MB free: the guard sees only the WSL VM's "
                                            f"memory (INSTALL.md, WSL)")
    except (OSError, ValueError):
        pass
    return out


def _cfg():
    try:
        import project
        return project.select()[0]
    except Exception:       # noqa: BLE001 -- no config: no limit (today's behaviour)
        return {}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(prog="lean_slot.py")
    ap.add_argument("--show", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--timeout", type=float, default=MAX_TIMEOUT)
    r.add_argument("--no-slot", action="store_true")
    # test and operator overrides of the config's settings
    for o in ("--slots", "--free-mb", "--max-wait"):
        r.add_argument(o, type=float, default=None, help=argparse.SUPPRESS)
    r.add_argument("--lock-dir", default=LOCKDIR, help=argparse.SUPPRESS)
    r.add_argument("--poll", type=float, default=POLL, help=argparse.SUPPRESS)
    r.add_argument("command", nargs=argparse.REMAINDER)
    g = sub.add_parser("guard")
    g.add_argument("--ensure", action="store_true")
    g.add_argument("--lock-dir", default=_knobs().get("lock_dir") or LOCKDIR, help=argparse.SUPPRESS)
    g.add_argument("--lock-fd", type=int, default=None, help=argparse.SUPPRESS)
    g.add_argument("--only-under", default=None, help=argparse.SUPPRESS)
    g.add_argument("--fake-mem", default=None, help=argparse.SUPPRESS)
    for o, d in (("--tick", TICK), ("--gap", RESUME_GAP), ("--cap", PAUSE_CAP), ("--repause", REPAUSE_AFTER)):
        g.add_argument(o, type=float, default=d, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.cmd == "guard":
        if a.ensure:
            ensure(a.lock_dir)
            return 0        # always 0: the SessionStart hook and the scripts never see a failure
        return guard_main(a)
    if a.show:
        state = start_guard()
        cfg = _cfg()
        sl, fm, mw = settings(cfg)
        print(f"lean slots: {sl or 'no limit'} (lean_slots), memory floor {fm} MB (lean_free_mb), wait at most {mw} s "
              f"(lean_max_wait); free memory now: {avail_mb()} MB; lock directory {LOCKDIR}")
        for k in range(max(sl, 1)):
            print(f"  slot{k}: {'held' if _slot_held(os.path.join(LOCKDIR, f'slot{k}')) else 'free'}")
        for h in holders(LOCKDIR):
            print(f"  held by pid {h.get('pid')} (slot{h.get('slot')}, project {h.get('project', '?')}): "
                  f"{str(h.get('command', ''))[:120]}")
        print(show_guard(cfg, state, _knobs().get("lock_dir") or LOCKDIR))
        return 0
    if a.cmd != "run":
        ap.print_help()
        return 2
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        print("lean_slot.py run: no command (python3 audits/lean_slot.py run --timeout 240 -- lake env lean <file>)")
        return 2
    start_guard()
    t_start = int(time.time())
    notes, timeout = [], a.timeout
    if timeout > MAX_TIMEOUT or timeout <= 0:
        notes.append(f"{NOTE} --timeout {a.timeout:g} cut to {MAX_TIMEOUT} s (the maximum: a wait plus a probe must "
                     f"stay under a 600 s tool call)")
        timeout = MAX_TIMEOUT
    fd = None
    if not a.no_slot:
        cfg = _cfg() if None in (a.slots, a.free_mb, a.max_wait) else {}
        sl, fm, mw = settings(cfg)
        sl = int(a.slots) if a.slots is not None else sl
        fm = int(a.free_mb) if a.free_mb is not None else fm
        mw = a.max_wait if a.max_wait is not None else mw
        if mw > DEFAULT_MAX_WAIT:     # fix round 2: the command line is capped like the config value
            notes.append(f"{NOTE} --max-wait {mw:g} cut to {DEFAULT_MAX_WAIT} s (the maximum: a wait plus a probe must "
                         f"stay under a 600 s tool call)")
            mw = DEFAULT_MAX_WAIT
        fd, n_ = acquire(sl, fm, mw, a.lock_dir, a.poll,
                         info={"project": (cfg or {}).get("name", "?"), "command": " ".join(cmd)[:300]})
        notes += n_
    for n_ in notes:
        print(n_, flush=True)
    gld = _knobs().get("lock_dir") or LOCKDIR
    try:
        rc, n2 = run_cmd(cmd, timeout, paused=lambda: pause_secs(gld, t_start))
    finally:
        release(fd, a.lock_dir)
    # a timeout NOTE that names the guard's pause already gives the seconds
    pn = pause_note(gld, t_start, pause_line=not any("by the memory guard" in x for x in n2))
    for n_ in n2 + ([pn] if pn else []):
        print(n_, flush=True)
    return rc


def show_guard(cfg, state, lockdir):
    """`--show`'s memory lines (Checkpoint A, Stage 1): the guard, the reserve, the slots, and the heavy-Lean NOTE
    when the guard's log saw one `lean` above T/2 (DESIGN-RAM §3). Never a stop or a question."""
    sz = sizing(total_mb(), cfg)
    if not sz:
        return "Memory guard: the machine's memory cannot be read: no reserve (the run behaves as before)"
    on = {"running": "on", "started": "on", "off": "off (FORMALIZE_PAPER_NO_GUARD)"}.get(state, "not running "
                                                                                          "(fail open)")
    out = [f"Memory guard: {on} (reserve {sz['R'] / 1024:.1f} GB of {sz['T'] / 1024:.1f} GB); probe slots {sz['S']}; "
           f"log {_guard_paths(lockdir)[1]}"]
    try:
        text = open(_guard_paths(lockdir)[1], encoding="utf-8", errors="replace").read()[-(1 << 20):]
    except OSError:
        text = ""
    peaks = [int(x) for x in re.findall(r" peak pid=\d+ class=\w+ anon=(\d+)MB", text)]
    pauses = re.findall(r" resume pid=\d+ after=(\d+)s", text)
    if pauses:
        out.append(f"  memory guard pauses in the log: {len(pauses)}, longest {max(map(int, pauses))} s "
                   f"({_guard_paths(lockdir)[1]})")
    if peaks and max(peaks) > sz["T"] // 2:
        out.append(f"NOTE[lean-slot] one Lean file may need about {max(peaks) / 1024:.0f} GB; on "
                   f"{sz['T'] / 1024:.0f} GB the run will be slow (probes pause), and below 12 GB it may need swap")
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------------------
class _FakeProcs:
    """A process table for the guard's unit tests: kill() only records and sets the state."""
    def __init__(self, ld):
        self.t, self.av, self.cw, self.pend, self.oomed, self.sent, self.rec_first, self.ld = {}, {}, {}, set(), set(), [], [], ld

    def add(self, pid, ppid, comm="lean", cwd=None, argv=None, uid=None):
        self.t[pid] = dict(comm=comm, state="S", ppid=ppid, start=pid, uid=os.getuid() if uid is None else uid)
        self.av[pid], self.cw[pid] = argv or [comm], cwd

    def table(self):
        return {p: dict(x) for p, x in self.t.items()}

    def argv(self, pid):
        return self.av.get(pid, [])

    def cwd(self, pid):
        return self.cw.get(pid)

    def pending_term(self, pid):
        return pid in self.pend

    def anon_mb(self, pid):
        return 2000

    def oom(self, pid):
        self.oomed.add(pid)

    def kill(self, pid, sig):
        if sig == signal.SIGSTOP:
            self.rec_first.append(os.path.exists(os.path.join(self.ld, f"paused-{pid}.json")))
        self.sent.append((pid, sig))
        if pid in self.t:
            self.t[pid]["state"] = "T" if sig == signal.SIGSTOP else "S"

    def stopped(self):
        return {p for p, x in self.t.items() if x["state"] == "T"}


def _state(pid):
    try:
        st = open(f"/proc/{pid}/stat").read()
        return st[st.rfind(")") + 2]
    except OSError:
        return None


def _until(cond, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def selftest_guard(say, d):
    """DESIGN-RAM: sizing, cgroup, membership, the policy (fake process table, injected clock), and on Linux the
    real lifetime: ensure, the hook, records, recovery only for a dead guard (R1), SIGTERM, a pending SIGTERM."""
    me = os.path.abspath(__file__)
    # sizing (§3) and the wrapper's derived defaults
    s8, s16, s32 = sizing(8192), sizing(16384), sizing(32768)
    say("(m) sizing at 8/16/32 GB: reserve 4/4/8 GB, slots 1/1/3, floor F = min(R+P, T-P/2) (5.6/8.9/12.9 GB), "
        "F <= T - P/2; lean_ram_mb lowers T; absent keys are derived, an explicit lean_slots 0 is no limit",
        (s8["R"], s8["S"], s8["F"]) == (4096, 1, 5692) and (s16["R"], s16["S"], s16["F"]) == (4096, 1, 9096)
        and (s32["R"], s32["S"], s32["F"]) == (8192, 3, 13192)
        and all(x["F"] <= x["T"] - x["P"] // 2 for x in (s8, s16, s32))
        and sizing(32768, {"lean_ram_mb": 8192})["T"] == 8192 and sizing(None) is None
        and settings({}, total=16384) == (1, 9096, DEFAULT_MAX_WAIT)
        and settings({"lean_slots": 0}, total=16384)[0] == 0 and settings({}, total=0) == (0, 0, DEFAULT_MAX_WAIT))
    ld = os.path.join(d, "f-locks")
    os.makedirs(ld, exist_ok=True)
    hold = _open_slot(os.path.join(ld, "slot0"))
    fcntl.flock(hold, fcntl.LOCK_EX | fcntl.LOCK_NB)
    t0 = time.monotonic()
    fd, n_ = acquire(2, settings({}, total=8192)[1], 2, ld, 0.1, mem=lambda: 6000)
    say("(m2) 8 GB, another slot held, 6000 MB free (between T-P/2 and R+P): the floor is met, the second slot is "
        "taken at once (a floor of R+P would wait the full wait)", fd is not None and time.monotonic() - t0 < 1)
    release(fd, ld)
    os.close(hold)
    # cgroup-aware free memory
    cg = os.path.join(d, "cg")
    for sub_, mx, cur in (("", "max", None), ("a", str(16 << 30), str(10 << 30)), ("a/b", "max", None)):
        os.makedirs(os.path.join(cg, sub_), exist_ok=True)
        open(os.path.join(cg, sub_, "memory.max"), "w").write(mx + "\n")
        if cur:
            open(os.path.join(cg, sub_, "memory.current"), "w").write(cur + "\n")
            open(os.path.join(cg, sub_, "memory.stat"), "w").write(f"anon 1\ninactive_file {2 << 30}\n")
    say("(n) cgroup v2: the tightest memory.max among the ancestors, free = max - current + inactive_file; the "
        "wrapper's and the guard's free memory take the smaller of MemAvailable and the cgroup's",
        cgroup_mb(cg, "/a/b") == (16384, 8192) and cgroup_mb(cg, "/") == (None, None)
        and avail_mb(cg=lambda: (16384, 700)) <= 700 and total_mb(cg=lambda: (1000, 1)) <= 1000)
    # membership and classes (fake table)
    proj, out_ = os.path.join(d, "proj"), os.path.join(d, "elsewhere")
    os.makedirs(os.path.join(proj, "audits", "projects"), exist_ok=True)
    os.makedirs(out_, exist_ok=True)
    open(os.path.join(proj, "audits", "projects", "x.json"), "w").write('{"name": "x"}')
    fp = _FakeProcs(ld)
    fp.add(10, 1, "node", proj)
    for i in range(6):
        fp.add(100 + i, 10, cwd=os.path.join(proj, "scratch") if i == 5 else proj)
    fp.add(50, 10, "python3", proj, ["python3", "-B", "audits/phase0.py"])
    fp.add(51, 50, "lake", proj)
    fp.add(52, 51, cwd=proj)
    fp.add(60, 10, "python3", proj, ["python3", "audits/lean_slot.py", "run", "--", "lake", "env", "lean", "f"])
    fp.add(61, 60, cwd=proj)
    fp.add(62, 10, "python3", proj, ["python3", "audits/codex_spawn.py", "--kind", "auditor", "x"])
    fp.add(63, 62, "codex", proj, ["codex", "exec"])
    fp.add(64, 63, cwd=proj)
    fp.add(65, 50, "python3", proj, ["python3", "audits/lean_slot.py", "run", "--", "lean", "f"])
    fp.add(66, 65, cwd=proj)
    fp.add(70, 1, cwd=proj, argv=["lean", "--server"])
    fp.add(71, 70, cwd=proj, argv=["lean", "--worker", "file:///x.lean"])
    fp.add(80, 1, cwd=out_)
    fp.add(90, 10, cwd=proj, uid=os.getuid() + 1)
    clk = [1000.0]
    mem = [100000, 16384]
    g = Guard(ld, fp, lambda: tuple(mem), clock=lambda: clk[0])
    tab = fp.table()
    cls = {p: (g.classify(p, tab) or [None])[0] for p in tab}
    say("(o) membership: this run's leans are probes (also in a subdirectory, under the wrapper, under a Codex "
        "reviewer that codex_spawn.py launched), a lean under `python3 audits/phase0.py` is a tool; `lean --server`/`--worker`, a lean outside a formalize-paper project "
        "and another account's lean are not counted; --only-under narrows it",
        [cls[p] for p in (100, 105, 61, 64, 66, 52, 70, 71, 80, 90, 10)] == ["probe"] * 5 + ["tool"] + [None] * 5
        and Guard(ld, fp, lambda: tuple(mem), only_under=out_).classify(100, tab) is None)
    # the policy
    del fp.t[50], fp.t[51], fp.t[52]
    for p in (60, 61, 62, 63, 64, 65, 66):
        del fp.t[p]
    g = Guard(ld, fp, lambda: tuple(mem), clock=lambda: clk[0])
    g.tick()
    say("(v) oom_score_adj is raised on every probe when first seen, never on a tool or a foreign lean",
        fp.oomed == {100, 101, 102, 103, 104, 105})
    mem[0] = 3000
    g.tick()
    say("(p) burst: below the reserve every probe but the oldest is paused in ONE tick",
        fp.stopped() == {101, 102, 103, 104, 105})
    say("(r) each pause is recorded (paused-<pid>.json) before its SIGSTOP",
        fp.rec_first and all(fp.rec_first) and len(glob.glob(os.path.join(ld, "paused-*.json"))) == 5)
    fp.add(50, 10, "python3", proj, ["python3", "-B", "audits/axiom_sweep.py"])
    fp.add(52, 50, cwd=proj)
    clk[0] += 1
    g.tick()
    say("(q) while a tool check runs every probe pauses, the oldest too; the tool check is never stopped",
        fp.stopped() == {100, 101, 102, 103, 104, 105} and not any(p == 52 for p, _s in fp.sent))
    del fp.t[50], fp.t[52]
    clk[0] += 1
    g.tick()
    w1 = fp.stopped() == {101, 102, 103, 104, 105}
    fp.t[100]["state"] = "Z"
    clk[0] += 1
    g.tick()
    w2 = fp.stopped() == {102, 103, 104, 105}
    fp.t[100]["state"] = "S"        # (its parent reaps it; a new probe of the same pid starts)
    say("(w) nothing running (the tool ended, or the running probe is a zombie its parent has not reaped) while memory "
        "is low: the oldest paused probe resumes at once", w1 and w2)
    for _ in range(2):
        clk[0] += 1
        g.tick()
    mem[0] = 20000      # room for 3 more young probes (each presumed to grow to P = 5000 from its 2000 MB)
    res = []
    for dt in (1, 1, 3, 1, 4):
        clk[0] += dt
        g.tick()
        res.append(len(fp.stopped()))
    say("(s) memory back: the oldest paused probe resumes, one per 5 s, while free memory minus what the young probes "
        "still need stays >= R + 1 GB", res == [5, 5, 4, 4, 3])
    mem[0] = 3000
    clk[0] += 1
    g.tick()
    nstop = len(fp.stopped())
    clk[0] += PAUSE_CAP
    g.tick()
    after_cap = fp.stopped()
    clk[0] += REPAUSE_AFTER - 2
    g.tick()
    still = fp.stopped()
    clk[0] += 3
    g.tick()
    say("(t) the 10 min cap: a pause reaching 600 s is resumed regardless; it is paused again only after 30 s of "
        "running", nstop == 5 and after_cap == set() and still == set() and fp.stopped() == {101, 102, 103, 104, 105})
    fp.pend.add(101)
    clk[0] += 1
    g.tick()
    clk[0] += REPAUSE_AFTER + 1
    g.tick()
    say("(u) a paused probe with a terminating signal pending gets SIGCONT so it can die, and is not paused again",
        101 not in fp.stopped() and (101, signal.SIGCONT) in fp.sent)
    g.resume_all()
    say("(y) on exit every paused probe is resumed and its record removed",
        fp.stopped() == set() and not glob.glob(os.path.join(ld, "paused-*.json")))
    # V2 round 1: memory pressure (PSI) pauses too, and holds a memory resume back
    open(os.path.join(cg, "a", "memory.pressure"), "w").write("some avg10=1.00 avg60=0 avg300=0 total=1234\n"
                                                             "full avg10=0 avg60=0 avg300=0 total=5\n")
    fp2 = _FakeProcs(ld)
    fp2.add(10, 1, "node", proj)
    for i in range(4):
        fp2.add(200 + i, 10, cwd=proj)
    stall_us, clk2 = [0], [5000.0]
    mem2 = [100000, 16384]
    g2 = Guard(ld, fp2, lambda: tuple(mem2), clock=lambda: clk2[0], psi=lambda: stall_us[0])
    g2.tick()
    calm = fp2.stopped() == set()
    clk2[0] += 1
    stall_us[0] += 500000       # half of the last second some task waited for memory
    g2.tick()
    pressed = fp2.stopped() == {201, 202, 203}
    held = []
    for _ in range(5):
        clk2[0] += 1
        g2.tick()
        held.append(len(fp2.stopped()))
    clk2[0] += 1
    g2.tick()
    say("(ps) memory pressure (PSI some >= 5 % over the last 2 s) pauses all probes but the oldest even with ample free "
        "memory; a memory resume waits until the pressure stays below 1 % for 5 s; the PSI file is the binding cgroup's",
        calm and pressed and held == [3] * 5 and len(fp2.stopped()) == 2
        and psi_path(cg, "/a/b") == os.path.join(cg, "a", "memory.pressure")
        and psi_total(os.path.join(cg, "a", "memory.pressure")) == 1234)
    g2.resume_all()
    # V2 round 2: the young-probe projection (a burst is paused before it allocates)
    fp3 = _FakeProcs(ld)
    fp3.add(10, 1, "node", proj)
    for i in range(4):
        fp3.add(300 + i, 10, cwd=proj)
    clk3, mem3 = [9000.0], [15000, 16384]
    g3 = Guard(ld, fp3, lambda: tuple(mem3), clock=lambda: clk3[0])
    g3.tick()
    first = fp3.stopped() == {301, 302, 303}
    seq = []
    for _ in range(12):
        clk3[0] += 1
        g3.tick()
        seq.append(len(fp3.stopped()))
    clk3[0] += YOUNG
    g3.tick()
    g3.resume_all()
    say("(pj) 4 probes start together with 15 GB free on 16 GB: each young probe is presumed to grow to P, so 3 pause "
        "at once (before they allocate); they resume one per 5 s while free minus the young probes' need leaves R + 1 GB "
        "(15000 - 3 x 3000 = 6000 still does, 3000 does not)",
        first and seq == [2] * 5 + [1] * 5 + [0] * 2)
    # fix round RAMK (F2): the presumption sized to the machine, memory resumes on 8 GB and on 16 GB with 8 GB
    # available, no flapping after a resume, and a bound on the total pause while a tool check runs
    def sim(memf, T, secs, tool=False, n=2):
        fp_ = _FakeProcs(ld)
        fp_.add(10, 1, "node", proj)
        for i in range(n):
            fp_.add(400 + i, 10, cwd=proj)
        if tool:
            fp_.add(450, 10, "python3", proj, ["python3", "-B", "audits/axiom_sweep.py"])
            fp_.add(451, 450, cwd=proj)
        ck = [20000.0]
        g_ = Guard(ld, fp_, lambda: (memf(ck[0] - 20000), T), clock=lambda: ck[0])
        ran, longest, cur = {p: 0 for p in range(400, 400 + n)}, {p: 0 for p in range(400, 400 + n)}, {}
        for _ in range(secs):
            g_.tick()
            st_ = fp_.stopped()
            for p in ran:
                if p in st_:
                    cur[p] = cur.get(p, 0) + 1
                    longest[p] = max(longest[p], cur[p])
                else:
                    ran[p], cur[p] = ran[p] + 1, 0
            ck[0] += 1
        stops = sum(1 for p_, s_ in fp_.sent if s_ == signal.SIGSTOP and p_ == 401)
        g_.resume_all()
        return ran, longest, stops
    s8_ = sizing(8192)
    p8 = min(s8_["P"], max(HYST_MB, (s8_["T"] - s8_["R"]) // 2))
    ran8, _l8, st8 = sim(lambda t: 6000, 8192, 300)
    ran16, _l16, st16 = sim(lambda t: 8000, 16384, 300)
    say("(f2) the young-probe need is sized to the machine (2 GB on 8 GB: with 6 GB free two probes run); with 8 GB "
        "free on 16 GB the second probe resumes for memory once the first is past its start-up, and the projection "
        "alone does not pause it again (one pause, no flapping)",
        p8 == 2048 and ran8[401] == 300 and st8 == 0 and ran16[401] >= 200 and st16 == 1)
    ran7, _l7, st7 = sim(lambda t: 7000, 8192, 5)
    say("(f2b) on 8 GB with 7 GB free two new probes both run (each presumed to need 2 GB, not 5 GB)",
        ran7[401] == 5 and st7 == 0)
    ranr, _lr, str_ = sim(lambda t: 8000 if t < 70 else 3000, 16384, 120)
    say("(f2c) after a memory resume, free memory really below the reserve still pauses that probe",
        st16 == 1 and str_ == 2)
    rant, lt, _st = sim(lambda t: 3000, 16384, 3600, tool=True, n=1)
    say("(f2d) while a tool check runs and memory stays low, a probe paused 15 min in all is kept running as the one "
        "probe: its longest stop is at most the 10 min cap, and it runs most of the hour (never killed)",
        lt[400] <= PAUSE_CAP + 1 and rant[400] >= 3600 - TOTAL_PAUSE - PAUSE_CAP - 60)
    # fix round RAMK (F3): tool scripts started by a relative path resolve against the process's cwd
    fp4 = _FakeProcs(ld)
    fp4.add(10, 1, "node", proj)
    au = os.path.join(proj, "audits")
    forms = ((au, ["python3", "phase0.py"]), (proj, ["python3", "./audits//phase0.py"]),
             (proj, ["python3", "-B", "-m", "audits.phase0"]), (au, ["python3", "-m", "phase0"]),
             (os.path.join(proj, "scratch"), ["python3", "../audits/axiom_sweep.py"]))
    for i, (cw_, av_) in enumerate(forms):
        fp4.add(500 + 2 * i, 10, "python3", cw_, av_)
        fp4.add(501 + 2 * i, 500 + 2 * i, cwd=proj)
    fp4.add(520, 10, "python3", proj, ["python3", "probe.py"])
    fp4.add(521, 520, cwd=proj)
    fp4.add(522, 10, "python3", au, ["python3", "-m", "json.tool"])
    fp4.add(523, 522, cwd=proj)
    g4, tab4 = Guard(ld, fp4, lambda: tuple(mem), clock=lambda: clk[0]), fp4.table()
    cls4 = [(g4.classify(501 + 2 * i, tab4) or [None])[0] for i in range(len(forms))]
    say("(f3) a tool check started as `cd audits && python3 phase0.py`, `python3 ./audits//phase0.py`, `python3 -m "
        "audits.phase0`, `python3 -m phase0` inside audits/ or `python3 ../audits/x.py` is a tool (never paused); "
        "`python3 probe.py` and `python3 -m json.tool` are not",
        cls4 == ["tool"] * len(forms) and g4.classify(521, tab4)[0] == "probe" and g4.classify(523, tab4)[0] == "probe")
    say("(x) the guard only ever sends SIGSTOP and SIGCONT (it never kills)",
        {s_ for _p, s_ in fp.sent} == {signal.SIGSTOP, signal.SIGCONT})
    open(_guard_paths(ld)[1], "a").write(f"x t={int(time.time())} resume pid=5 after=42s anc=7,{os.getpid()},1 "
                                         f"why=memory\nx t=1 resume pid=6 after=99s anc={os.getpid()} why=memory\n")
    say("(z0) the wrapper's NOTE sums this wrapper's pauses since it started",
        pause_note(ld, int(time.time()) - 5) == f"{NOTE} paused 42 s by the memory guard (machine memory low)"
        and pause_note(ld, int(time.time()) - 5, me=12345) == "")
    # fix round RAMK (F1): a pause in progress counts, a pid the log already shows resumed counts once, and a probe cut
    # at its time limit after a guard pause is inconclusive, never "too large"
    json.dump(dict(pid=77, start=1, t=int(time.time()) - 30, anc=[os.getpid(), 1]),
              open(os.path.join(ld, "paused-77.json"), "w"))
    json.dump(dict(pid=5, start=1, t=int(time.time()) - 50, anc=[os.getpid()]), open(os.path.join(ld, "paused-5.json"), "w"))
    ps_now = pause_secs(ld, int(time.time()) - 5)
    for f_ in ("paused-77.json", "paused-5.json"):
        os.remove(os.path.join(ld, f_))
    rc1, n1 = run_cmd([sys.executable, "-c", "import time; time.sleep(30)"], 1, paused=lambda: 7)
    rc2, n2_ = run_cmd([sys.executable, "-c", "import time; time.sleep(30)"], 1)
    say("(z0b) a timeout after a guard pause: 'paused 7 s by the memory guard ... re-run, this is not a too-large probe' "
        "in place of the size advice; with no pause the size advice stays; pauses in progress are counted, once",
        72 <= ps_now <= 75 and rc1 == rc2 == 124 and "paused 7 s by the memory guard" in n1[0]
        and "not a too-large probe" in n1[0] and "too large;" not in n1[0] and "the probe is too large" in n2_[0])
    rc3, n3 = run_cmd([sys.executable, "-c", "import time; time.sleep(30)"], 8, paused=lambda: 1)
    say("(z0c) a short pause (1 s of an 8 s limit, under a quarter) keeps the size advice and names the pause; "
        "it is not called inconclusive (fix round RAMK F1')",
        rc3 == 124 and "the probe is too large (it was paused 1 s" in n3[0] and "not a too-large probe" not in n3[0])
    if not os.path.isdir("/proc/self"):
        say("(z) the real-process guard tests run on Linux only (skipped here)", True)
        return
    # the real guard: started by ensure, fake memory, only this test's directory
    rl = os.path.join(d, "r-locks")
    fm = os.path.join(d, "mem")
    open(fm, "w").write("100000 16384")
    knobs = dict(lock_dir=rl, only_under=d, fake_mem=fm, tick=0.1, gap=0.2)
    env = {k: v for k, v in os.environ.items() if k != NO_GUARD}
    env[TEST_KNOBS] = json.dumps(knobs)
    old_env = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    binl = os.path.join(d, "bin")
    os.makedirs(binl, exist_ok=True)
    os.symlink(sys.executable, os.path.join(binl, "lean"))
    leans = []
    # the stand-ins are detached from this test's own ancestry: under `python3 audits/selftest_all.py` a lean below
    # it is (rightly) a tool check, which the guard never pauses
    holder = ("import os, subprocess, sys\nif os.fork():\n    os._exit(0)\nos.setsid()\n"
              "p = subprocess.Popen(sys.argv[3:], cwd=sys.argv[2], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
              "stderr=subprocess.DEVNULL)\nopen(sys.argv[1] + '.t', 'w').write(str(p.pid))\n"
              "os.replace(sys.argv[1] + '.t', sys.argv[1])\np.wait()\n")

    class _Detached:
        def __init__(self, pid):
            self.pid = pid

        def poll(self):
            return None if _state(self.pid) not in (None, "Z") else 0

        def kill(self):
            os.kill(self.pid, signal.SIGKILL)

        def wait(self, timeout=None):
            _until(lambda: self.poll() is not None, timeout or 5)

    def lean(code="import time; time.sleep(60)", *extra):
        pf = os.path.join(d, f"lean-{len(leans)}.pid")
        subprocess.run([sys.executable, "-c", holder, pf, proj, os.path.join(binl, "lean"), "-c", code, *extra],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        _until(lambda: os.path.exists(pf), 10)
        p = _Detached(int(open(pf).read()))
        leans.append(p)
        return p

    def guard_pid():
        for e in os.listdir("/proc"):
            if e.isdigit():
                try:
                    a = open(f"/proc/{e}/cmdline", "rb").read().split(b"\0")
                except OSError:
                    continue
                if b"guard" in a and rl.encode() in a:
                    return int(e)
        return None
    try:
        hp = os.path.join(d, "hookproj")
        os.makedirs(os.path.join(hp, "audits"))
        os.symlink(me, os.path.join(hp, "audits", "lean_slot.py"))
        import claude_settings
        t0 = time.monotonic()
        r = subprocess.run(["bash", "-c", claude_settings.HOOK_CMD], env=dict(env, CLAUDE_PROJECT_DIR=hp),
                           capture_output=True, text=True, timeout=20)
        el = time.monotonic() - t0
        g1 = _until(guard_pid, 10) and guard_pid()
        say("(z1) the SessionStart hook command returns in < 1 s with exit 0 and no output, leaving the guard running "
            "(N1); outside a project it is a silent exit 0",
            r.returncode == 0 and r.stdout == r.stderr == "" and el < 1 and bool(g1)
            and subprocess.run(["bash", "-c", claude_settings.HOOK_CMD], env=dict(env, CLAUDE_PROJECT_DIR=out_),
                               capture_output=True, text=True, timeout=20).returncode == 0)
        t0 = time.monotonic()
        st2 = ensure()
        say("(z2) ensure is non-blocking and idempotent: a second ensure returns at once, one guard runs",
            st2 == "running" and time.monotonic() - t0 < 0.5 and guard_pid() == g1)
        ps_ = [lean() for _ in range(3)]
        time.sleep(0.5)
        open(fm, "w").write("1000 16384")
        stopped = lambda: [p.pid for p in ps_ if _state(p.pid) == "T"]
        _until(lambda: len(stopped()) == 2, 20)
        paused_before = sorted(stopped())
        st3 = ensure()
        time.sleep(0.8)
        say("(z3) R1: an ensure while the guard is alive leaves its paused probes paused and their records in place",
            st3 == "running" and len(paused_before) == 2 and sorted(stopped()) == paused_before
            and len(glob.glob(os.path.join(rl, "paused-*.json"))) == 2)
        os.kill(g1, signal.SIGKILL)
        _until(lambda: _state(g1) in (None, "Z"), 10)
        time.sleep(0.3)
        left = sorted(stopped())
        open(fm, "w").write("100000 16384")
        st4 = ensure()
        ok_ = _until(lambda: not stopped(), 10)
        say("(z4) S3: the guard SIGKILLed while 2 probes are paused leaves them stopped; the next ensure (the lock "
            "free) resumes every recorded pause and starts a new guard",
            left == paused_before and st4 == "started" and ok_ and not glob.glob(os.path.join(rl, "paused-*.json")))
        g2 = _until(lambda: guard_pid() not in (None, g1), 10) and guard_pid()
        open(fm, "w").write("1000 16384")
        _until(lambda: len(stopped()) == 2, 20)
        n2 = len(stopped())
        os.kill(g2, signal.SIGTERM)
        say("(z5) SIGTERM to the guard: everything it paused is resumed at once",
            n2 == 2 and _until(lambda: not stopped(), 5) and not glob.glob(os.path.join(rl, "paused-*.json")))
        st5 = ensure()
        _until(lambda: len(stopped()) == 2, 20)
        victim = (stopped() or [ps_[1].pid])[0]
        os.kill(victim, signal.SIGTERM)
        vp = next(p for p in ps_ if p.pid == victim)
        say("(z6) S4: SIGTERM to a paused probe: the guard continues it and it dies within seconds",
            st5 == "started" and _until(lambda: vp.poll() is not None, 5))
        say("(z7) a probe's oom_score_adj is 1000 (the OOM killer's first choice)",
            open(f"/proc/{ps_[0].pid}/oom_score_adj").read().strip() == "1000")
    except Exception as e:      # noqa: BLE001
        say(f"the real-process guard tests ran ({type(e).__name__}: {e})", False)
    finally:
        for p in leans:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:       # noqa: BLE001
                pass
        gp = guard_pid()
        if gp:
            os.kill(gp, signal.SIGTERM)
        os.environ.clear()
        os.environ.update(old_env)


def selftest():
    ok = True

    def say(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)
    me = os.path.abspath(__file__)
    os.environ[NO_GUARD] = "1"      # no real guard from this test's wrappers (the guard tests start their own)
    d = tempfile.mkdtemp(prefix="lean-slot-")
    ld = os.path.join(d, "locks")

    def wrap(*args, env=None):
        t0 = time.monotonic()
        try:
            r = subprocess.run([sys.executable, "-B", me, "run", "--lock-dir", ld, "--poll", "0.1", *args],
                               capture_output=True, text=True, env=env, timeout=60)
        except subprocess.TimeoutExpired:
            return None, "the wrapper did not return within 60 s", time.monotonic() - t0
        return r.returncode, r.stdout + r.stderr, time.monotonic() - t0

    def holder(seconds, slots=1):
        return subprocess.Popen([sys.executable, "-B", me, "run", "--lock-dir", ld, "--poll", "0.1", "--slots",
                                 str(slots), "--max-wait", "30", "--", "sleep", str(seconds)])
    global _TEST_AFTER_OPEN
    real_acquire = globals()["acquire"]

    def _alarm(*_a):
        raise TimeoutError("an in-process wait did not end (an unbounded queue)")

    def acquire(*a, **k):       # noqa: F811 -- the selftest's own bound on every in-process wait
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(30)
        try:
            return real_acquire(*a, **k)
        except TimeoutError as e:
            return None, [f"TIMEOUT {e}"]
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    try:
        # (a) slots=1: B waits for A and runs when A releases, without a NOTE
        a_ = holder(3)
        time.sleep(0.8)
        rc, out, el = wrap("--slots", "1", "--max-wait", "30", "--", "true")
        a_.wait()
        say("(a) slots=1: a second caller waits for the holder and runs when it releases (no NOTE)",
            rc == 0 and el >= 1.5 and NOTE not in out)
        # (b) bounded wait: a holder longer than max_wait; the caller runs after max_wait with the NOTE
        a_ = holder(15)
        time.sleep(0.8)
        rc, out, el = wrap("--slots", "1", "--max-wait", "2", "--", "true")
        a_.kill(); a_.wait()
        say("(b) bounded wait: with a holder longer than max_wait the caller returns within max_wait + ε and says so",
            rc == 0 and 1.8 <= el < 8 and "ran without a slot after waiting" in out)
        # (c) the floor cannot be met and no other slot is held: run at once
        fd, n_ = acquire(1, 10 ** 9, 30, ld, 0.1, mem=lambda: 100)
        say("(c) floor unreachable and no other slot held: the slot is taken at once", fd is not None and n_ == [])
        release(fd, ld)
        # memory-gated: another slot held and the floor unmet -> wait (then run without a slot)
        hold = _open_slot(os.path.join(ld, "slot0")); fcntl.flock(hold, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if a slot leaked
        t0 = time.monotonic()
        fd, n_ = acquire(2, 10 ** 9, 1, ld, 0.1, mem=lambda: 100)
        el = time.monotonic() - t0
        say("(c2) below the floor while another slot is held: the caller waits (here up to max_wait) instead of "
            "taking the free slot", fd is None and el >= 0.9 and any("ran without a slot" in x for x in n_))
        fd2, n2 = acquire(2, 0, 1, ld, 0.1, mem=lambda: 100)
        say("(c3) control: with no floor the free second slot is taken at once", fd2 is not None and n2 == [])
        release(fd2, ld); os.close(hold)
        # (d) lock directory unusable -> NOTE and run
        open(os.path.join(d, "afile"), "w").write("x")
        fd, n_ = acquire(1, 0, 5, os.path.join(d, "afile", "locks"), 0.1)
        rc, out, _el = (lambda r: (r.returncode, r.stdout, 0))(subprocess.run(
            [sys.executable, "-B", me, "run", "--lock-dir", os.path.join(d, "afile", "locks"), "--slots", "1", "--",
             "true"], capture_output=True, text=True, timeout=60))
        say("(d) an unusable lock directory: one NOTE, the command runs (fail open)",
            fd is None and len(n_) == 1 and "cannot be used" in n_[0] and rc == 0 and NOTE in out)
        # (e) a slot file created 0o666; a read-only (0o444) pre-existing one is still lockable read-only
        fd, n_ = acquire(1, 0, 5, ld, 0.1)
        mode0 = os.stat(os.path.join(ld, "slot0")).st_mode & 0o777
        release(fd, ld)
        os.chmod(os.path.join(ld, "slot0"), 0o444)
        fd, n_ = acquire(1, 0, 5, ld, 0.1)
        say("(e) slot files are 0o666 and locked through a read-only descriptor (a 0o444 file of another account "
            "is still lockable)", mode0 == 0o666 and fd is not None and n_ == [])
        release(fd, ld)
        # (f) inode re-check: the file is replaced (and the new one held) between open and lock -> no slot
        holdf = []

        def swap(path):
            global _TEST_AFTER_OPEN
            _TEST_AFTER_OPEN = None
            os.remove(path)
            h = _open_slot(path); fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB); holdf.append(h)
        _TEST_AFTER_OPEN = swap
        fd, n_ = acquire(1, 0, 1, ld, 0.1)
        _TEST_AFTER_OPEN = None
        say("(f) a slot file deleted and re-created (and held) after the caller opened it: the caller does not count "
            "the old file's lock as a slot", fd is None and any("ran without a slot" in x for x in n_))
        for h in holdf:
            os.close(h)
        # (g) two configurations on one lock directory: slots 1 and 2 -> at most 2 holders
        fa, _ = acquire(1, 0, 1, ld, 0.1)
        fb, _ = acquire(2, 0, 1, ld, 0.1)
        fc, nc = acquire(2, 0, 1, ld, 0.1)
        say("(g) runs with slots 1 and 2 share the files: at most 2 hold at once (the largest setting)",
            fa is not None and fb is not None and fc is None and any("ran without a slot" in x for x in nc))
        for f_ in (fa, fb):
            release(f_, ld)
        # (h) --timeout kills the process group, exit 124 with the NOTE
        rc, out, el = wrap("--no-slot", "--timeout", "2", "--", "bash", "-c", "sleep 30 & sleep 30; wait")
        say("(h) --timeout kills the command's process group: exit 124, NOTE, within seconds",
            rc == 124 and "timed out after 2" in out and el < 15)
        # (h2) a --timeout above 240 is cut to 240 with a NOTE, never refused (re-check LOW (a))
        rc, out, _el = wrap("--no-slot", "--timeout", "900", "--", "true")
        say("(h2) --timeout 900 is cut to 240 with a NOTE and the command runs (exit 0)",
            rc == 0 and "--timeout 900 cut to 240 s" in out)
        # (h3) fix round 1 (compat 1): a wrapper killed by SIGTERM kills its probe's process group
        pf = os.path.join(d, "child.pid")
        w = subprocess.Popen([sys.executable, "-B", me, "run", "--no-slot", "--timeout", "60", "--", "bash", "-c",
                              f"echo $$ > {pf}; sleep 47"])
        for _ in range(50):
            if os.path.exists(pf) and open(pf).read().strip():
                break
            time.sleep(0.1)
        cpid = int(open(pf).read().strip())
        w.send_signal(signal.SIGTERM)
        w.wait(timeout=20)
        time.sleep(0.5)
        say("(h3) a wrapper killed by SIGTERM kills its probe (no orphaned Lean); lean_max_wait is capped at 300 s",
            not _alive(cpid) and settings({"lean_slots": 1, "lean_max_wait": 900})[2] == DEFAULT_MAX_WAIT)
        # (h4) fix round 2: a --max-wait above 300 on the command line is cut to 300 with a NOTE, never rejected
        rc, out, _el = wrap("--slots", "1", "--max-wait", "900", "--", "true")
        say("(h4) --max-wait 900 is cut to 300 with a NOTE and the command runs (exit 0)",
            rc == 0 and "--max-wait 900 cut to 300 s" in out)
        # (i) the child's environment is unchanged
        env = dict(os.environ, LEAN_SLOT_TEST_VAR="QZ1")
        rc, out, _el = wrap("--slots", "1", "--max-wait", "5", "--", sys.executable, "-c",
                            "import os, json; print(json.dumps(dict(os.environ), sort_keys=True))", env=env)
        try:
            got = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            got = {}
        say("(i) the command sees exactly the caller's environment", rc == 0 and got == env)
        # (j) memory parsers
        say("(j) Linux MemAvailable and macOS vm_stat parse to MB; unreadable -> None",
            parse_meminfo("MemTotal: 100 kB\nMemAvailable:    2097152 kB\n") == 2048
            and parse_vm_stat("Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 1000.\n"
                              "Pages active: 5.\nPages inactive: 2000.\nPages speculative: 1000.\n") == 62
            and parse_meminfo("nothing") is None and parse_vm_stat("nothing") is None)
        # no limit configured: run at once, no lock taken
        say("(k) lean_slots 0 (or unknown memory): no wait, no lock, no NOTE; explicit settings override the derived "
            "ones",
            acquire(0, 0, 5, ld)[0] is None and acquire(0, 0, 5, ld)[1] == []
            and settings({}, total=0) == (0, 0, DEFAULT_MAX_WAIT)
            and settings({"lean_slots": 2, "lean_free_mb": 2048, "lean_max_wait": 120}) == (2, 2048, 120))
        say("(l) the holder side file is written while held and removed on release",
            (lambda f_: (os.path.exists(_holder_path(ld)), release(f_, ld), os.path.exists(_holder_path(ld))))(
                acquire(1, 0, 5, ld, 0.1, info={"project": "T"})[0]) == (True, None, False))
        selftest_guard(say, d)
    except Exception as e:      # noqa: BLE001 -- a failing control (a leaked slot blocks a lock), not a crash
        say(f"the selftest's controls ran ({type(e).__name__}: {e})", False)
    finally:
        _TEST_AFTER_OPEN = None
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))
