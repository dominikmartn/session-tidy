#!/usr/bin/env python3
"""session-tidy: keep track of which Claude Code session created which scratch copy,
so each session can clean up after itself, and free build folders of abandoned copies.

  tidy.py hook-register        PostToolUse(Bash) hook, reads the hook JSON on stdin
  tidy.py hook-session-end     SessionEnd hook, marks the session's copies as ended
  tidy.py mine SESSION_ID      list copies owned by a session
  tidy.py pin NAME [reason]    protect a copy from any cleanup
  tidy.py unpin NAME
  tidy.py share SESSION_ID NAME   hand a copy over: SESSION_ID becomes co-owner
  tidy.py sweep [--run] [-v]   delete build folders of abandoned copies (dry run by default)

Config (environment):
  SESSION_TIDY_DIR        scratch folder, default ~/.claude-scratch
  SESSION_TIDY_REST_DAYS  days a copy must sit untouched before its build folders go, default 3
"""
import json, os, re, shutil, subprocess, sys, time

HOME = os.path.expanduser("~")
TMP = os.path.abspath(os.path.expanduser(os.environ.get("SESSION_TIDY_DIR", "~/.claude-scratch")))
REG = os.path.join(TMP, ".owners")
try:
    REST_DAYS = max(1, int(os.environ.get("SESSION_TIDY_REST_DAYS", "3")))
except ValueError:
    REST_DAYS = 3
BUILD = {"build", "target", "node_modules", "DerivedData", ".build", "dist"}
VERB = re.compile(r"\b(git\s+(?:-C\s+\S+\s+)?worktree\s+add|(?:git|gh\s+repo)\s+clone|cp\s+-\w*[rRa]\w*|rsync|ditto|mkdir|mv|tar\s+(?:-?\w*x\w*|--extract)|unzip)\b")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
NAME_CHARS = r"/([A-Za-z0-9][A-Za-z0-9._-]*)"


def name_pattern():
    """The scratch folder as it may appear in a command: absolute, ~/..., $HOME/...,
    $SESSION_TIDY_DIR/..."""
    forms = [TMP, "$SESSION_TIDY_DIR", "${SESSION_TIDY_DIR}"]
    if TMP.startswith(HOME + "/"):
        rel = TMP[len(HOME) + 1:]
        forms += ["~/" + rel, "$HOME/" + rel, "${HOME}/" + rel]
    return re.compile("(?:" + "|".join(re.escape(f) for f in forms) + ")" + NAME_CHARS)


def entry_path(name):
    return os.path.join(REG, name + ".json")


def load(name):
    try:
        with open(entry_path(name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(name, entry):
    os.makedirs(REG, exist_ok=True)
    tmp = entry_path(name) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entry, f)
    os.replace(tmp, entry_path(name))


def owners(entry):
    return [entry.get("session")] + entry.get("co_owners", [])


def hook_register():
    """Record the session that creates a copy. Bookkeeping only, never blocks.
    Known limit: plain text heuristic on the command line; a command that names someone
    else's copy as its target makes it yours. Upgrade path: create copies through a
    command that registers itself."""
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    sid = data.get("session_id") or ""
    cmd = (data.get("tool_input") or {}).get("command") or ""
    pat = name_pattern()
    if not sid or not pat.search(cmd):
        return
    now = int(time.time())
    created, mentioned = set(), set(pat.findall(cmd))
    for seg in re.split(r"&&|\|\||;|\n|\|", cmd):
        names = pat.findall(seg)
        if names and VERB.search(seg):
            created.add(names[-1])  # the last path is the target, not the source
    for name in created | mentioned:
        entry = load(name)
        if name in created and (entry is None or stale(entry, sid)):
            save(name, {"session": sid, "created": now, "seen": now})
        elif entry and sid in owners(entry):
            entry["seen"] = now
            entry.pop("ended", None)
            save(name, entry)


def stale(entry, sid):
    """An entry another session may take over: its owners are gone. A running owner
    keeps ownership, so a command that merely copies into its folder steals nothing."""
    if sid in owners(entry):
        return False
    return not owner_alive(entry, live_sessions())


def hook_session_end():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    sid = data.get("session_id") or ""
    # On /clear and resume the user keeps working on the same task, so the copies are not
    # marked ended; the seen timestamp still ages them out.
    if not sid or data.get("reason") in ("clear", "resume") or not os.path.isdir(REG):
        return
    for f in os.listdir(REG):
        name = f[:-5] if f.endswith(".json") else None
        entry = name and load(name)
        if entry and entry.get("session") == sid:
            entry["ended"] = int(time.time())
            save(name, entry)


def live_sessions():
    """Session IDs of running Claude Code processes, or None if this can't be told.
    Known limit: reads ~/.claude/sessions/*.json, which Claude Code writes but does not
    document. Without it, sweep falls back to the ended marker and the seen timestamp."""
    d = os.path.join(HOME, ".claude", "sessions")
    if not os.path.isdir(d):
        return None
    ids = set()
    for f in os.listdir(d):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, f)) as fh:
                s = json.load(fh)
            try:
                os.kill(int(s["pid"]), 0)
            except PermissionError:
                pass  # another user's process: it exists, so it counts as running
            ids.add(s["sessionId"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return ids or None


def owner_alive(entry, live):
    if entry is None:
        return False  # copies without an owner count as abandoned
    if live is not None:
        return any(s in live for s in owners(entry))
    if entry.get("ended") and not entry.get("co_owners"):
        return False
    return time.time() - entry.get("seen", 0) < REST_DAYS * 86400


def build_dirs(copy):
    found = []
    for root, dirs, _ in os.walk(copy):
        if root[len(copy):].count(os.sep) >= 3:
            dirs[:] = []
            continue
        for d in list(dirs):
            if d in BUILD and not tracked(copy, os.path.join(root, d)):
                found.append(os.path.join(root, d))
                dirs.remove(d)
            elif d == ".git":
                dirs.remove(d)
    return found


def tracked(copy, path):
    """A folder named like build output that git tracks is source, not output."""
    r = subprocess.run(["git", "-C", copy, "ls-files", "--", path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def recently_touched(copy, days):
    cutoff = time.time() - days * 86400
    for root, dirs, files in os.walk(copy):
        dirs[:] = [d for d in dirs if d not in BUILD and d != ".git"]
        for f in files + dirs:
            try:
                if os.lstat(os.path.join(root, f)).st_mtime > cutoff:
                    return True
            except OSError:
                pass
    return False


def is_own_repo(copy):
    """True only if the copy is itself a git work tree, not a folder inside a bigger repo."""
    r = subprocess.run(["git", "-C", copy, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.returncode == 0 and os.path.realpath(r.stdout.strip()) == os.path.realpath(copy)


def keep_until(copy):
    today = time.strftime("%Y-%m-%d")
    dates = sorted(f[len(".keep-until-"):] for f in os.listdir(copy)
                   if re.fullmatch(r"\.keep-until-\d{4}-\d{2}-\d{2}", f))
    return dates[-1] if dates and dates[-1] >= today else None


def du_kb(paths):
    r = subprocess.run(["du", "-sk"] + paths, capture_output=True, text=True)
    return sum(int(l.split()[0]) for l in r.stdout.splitlines() if l.split())


def sweep(run, verbose):
    if not os.path.isdir(TMP):
        print(f"{TMP} does not exist, nothing to do")
        return
    if TMP in ("/", HOME) or not os.path.isdir(REG):
        # Guard against a mistyped SESSION_TIDY_DIR pointing at real projects: only a
        # folder the hook has already written owner entries into counts as scratch.
        sys.exit(f"tidy: {TMP} has no .owners folder, so it is not a scratch folder; refusing to sweep")
    live = live_sessions()
    procs = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
    total = 0
    for name in sorted(os.listdir(TMP)):
        copy = os.path.join(TMP, name)
        if name.startswith(".") or not os.path.isdir(copy) or os.path.islink(copy):
            continue
        bau = build_dirs(copy)
        if not bau:
            continue
        if os.path.exists(os.path.join(copy, ".tidy-pin")):
            status = "pinned"
        elif until := keep_until(copy):
            status = "keep-until " + until
        elif owner_alive(load(name), live):
            status = "owner still running"
        elif not is_own_repo(copy):
            status = "not a git repo"
        elif subprocess.run(["git", "-C", copy, "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
            status = "uncommitted changes"
        elif recently_touched(copy, REST_DAYS):
            status = f"touched within {REST_DAYS} days"
        elif re.search(re.escape(copy) + r"(?:/|\s|$)", procs, re.M):
            status = "a running command line names it"
        else:
            if run:
                kb, failed = 0, []
                for b in bau:
                    if os.path.islink(b):
                        failed.append(f"{os.path.relpath(b, copy)}: symlink, left alone")
                        continue
                    size = du_kb([b])
                    try:
                        shutil.rmtree(b)
                        kb += size
                    except OSError as e:
                        failed.append(f"{os.path.relpath(b, copy)}: {e.strerror or e}")
                if len(failed) < len(bau):
                    print(f"removed build folders in {name} ({kb / 1048576:.1f} GB)")
                for f in failed:
                    print(f"  could not remove {f}")
            else:
                kb = du_kb(bau)
                print(f"would remove build folders in {name} ({kb / 1048576:.1f} GB)")
            total += kb
            continue
        if verbose:
            print(f"kept {name}: {status}")
    if run:  # forget owners of copies that no longer exist, so their names are free again
        for f in os.listdir(REG):
            if f.endswith(".json") and not os.path.isdir(os.path.join(TMP, f[:-5])):
                os.remove(os.path.join(REG, f))
    print(f"{'Freed' if run else 'Dry run, would free'}: {total / 1048576:.1f} GB (per du)")


def valid(name):
    if not NAME_RE.match(name):
        sys.exit(f"tidy: {name!r} is not a copy name (letters, digits, . _ -)")
    return name


def pin(name, reason):
    copy = os.path.join(TMP, name)
    if not os.path.isdir(copy):
        sys.exit(f"tidy: {copy} does not exist")
    with open(os.path.join(copy, ".tidy-pin"), "w") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {reason}\n")
    print(f"pinned {name}")


def unpin(name):
    try:
        os.remove(os.path.join(TMP, name, ".tidy-pin"))
    except FileNotFoundError:
        pass
    print(f"unpinned {name}")


def share(sid, name):
    entry = load(name)
    if entry is None:
        sys.exit(f"tidy: no owner entry for {name}")
    co = entry.setdefault("co_owners", [])
    if sid != entry.get("session") and sid not in co:
        co.append(sid)
    save(name, entry)
    print(f"shared {name} with {sid}")


def mine(sid):
    if not os.path.isdir(REG):
        return
    for f in sorted(os.listdir(REG)):
        entry = load(f[:-5]) if f.endswith(".json") else None
        if entry and sid in owners(entry) and os.path.isdir(os.path.join(TMP, f[:-5])):
            print(os.path.join(TMP, f[:-5]))


def main(argv):
    cmd, args = (argv[0] if argv else ""), argv[1:]
    if cmd == "hook-register":
        try:
            hook_register()
        except Exception:
            pass  # a bookkeeping hook must never break the user's tool call
    elif cmd == "hook-session-end":
        try:
            hook_session_end()
        except Exception:
            pass
    elif cmd == "sweep":
        sweep("--run" in args, "-v" in args)
    elif cmd == "pin" and args:
        pin(valid(args[0]), " ".join(args[1:]) or "pinned")
    elif cmd == "unpin" and args:
        unpin(valid(args[0]))
    elif cmd == "share" and len(args) == 2:
        share(args[0], valid(args[1]))
    elif cmd == "mine" and args:
        mine(args[0])
    else:
        print(__doc__.strip())
        sys.exit(0 if cmd in ("", "-h", "--help") else 2)


if __name__ == "__main__":
    main(sys.argv[1:])
