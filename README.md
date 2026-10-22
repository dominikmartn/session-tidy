# session-tidy

A Claude Code plugin that lets each session clean up the scratch copies it created.

When you run many Claude Code sessions, each one clones repos, adds worktrees and installs dependencies in throwaway folders. Nobody remembers later which folder belongs to which session, so they pile up. A central cleaner can't tell what is still in use. Only the session that made a copy knows whether it still needs it.

## What it does

- **Hook (PostToolUse, Bash):** when a command creates something in the scratch folder (`mkdir`, `git clone`, `git worktree add`, `cp -R`, `rsync`, `mv`, `tar -x`, `unzip`), it records the session as the owner. Bookkeeping only, it never blocks.
- **Hook (SessionEnd):** marks the session's copies as ended. It deletes nothing.
- **Skill `/session-tidy:tidy`** (or say "tidy up"): the session removes its own copies, dev servers and jobs, keeps what is still needed (unpushed work, results the user hasn't seen, open PRs, pinned copies) and reports what it kept and why. It runs only when you ask.
- **Sweep:** frees untracked `build`, `target`, `node_modules`, `DerivedData`, `.build` and `dist` folders in copies whose owner is gone, that are clean git repos and untouched for a few days. Anything git tracks stays, so every deletion can be rebuilt.

Nothing is deleted automatically.

## Requirements

macOS or Linux, `python3` and `git` on the `PATH`. Not tested on Windows.

## Install

In Claude Code:

```
/plugin marketplace add dominikmartn/session-tidy
/plugin install session-tidy@session-tidy
```

Restart Claude Code so the hooks load.

## Setup

Create the scratch folder. It must hold only throwaway copies, never your real projects: the sweep frees build folders of every idle, clean repo in it. As a guard against a mistyped path, the sweep refuses to run in a folder that holds no owner entries yet:

```sh
mkdir -p ~/.claude-scratch
```

Tell Claude to use it, for example in `~/.claude/CLAUDE.md`:

```
Throwaway copies, clones and worktrees go in ~/.claude-scratch/<name>.
```

## Config

Set these where the hooks see them: in the `env` block of `~/.claude/settings.json`, or in your shell before starting `claude`.

| Variable | Default | Meaning |
|---|---|---|
| `SESSION_TIDY_DIR` | `~/.claude-scratch` | scratch folder |
| `SESSION_TIDY_REST_DAYS` | `3` | days a copy must sit untouched before the sweep frees its build folders |

## Helper

```sh
python3 scripts/tidy.py pin NAME [reason]   # protect a copy from any cleanup
python3 scripts/tidy.py unpin NAME
python3 scripts/tidy.py share SESSION_ID NAME   # hand a copy to another session
python3 scripts/tidy.py sweep [--run] [-v]  # dry run unless --run
```

A copy containing `.keep-until-YYYY-MM-DD` is also left alone until that date.

## Limits

- Ownership comes from reading the command text. A command that names another session's copy as its target makes it yours once that session is no longer running, including a crashed session you later resume.
- To tell whether a session is still running, the sweep reads `~/.claude/sessions/`, which Claude Code writes but does not document. If that folder is missing or lists no running session, a copy counts as abandoned once its session ended or it has not been touched for the rest period.
- "In use by a process" means a running command line names the copy's path. A dev server started from inside the copy with a relative command is not seen, which is one reason for the rest period.
- Single machine. Copies on remote hosts are not tracked.

## Test

```sh
bash test/e2e.sh
```

Runs in a throwaway home folder and checks registration and the sweep rules.

---

Made by [@dominikmartn](https://x.com/dominikmartn)
