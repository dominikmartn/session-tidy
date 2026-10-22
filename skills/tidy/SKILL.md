---
name: tidy
description: The session cleans up after itself. It removes the scratch copies, dev servers and background jobs it created, keeps what is still needed and says why, then frees build folders of abandoned copies. Use only when the user runs /claude-tidy:tidy or says "tidy up", "clean up after yourself" or similar. Never start it on your own, not even when the disk is low.
---

# Tidy

Only the session knows what it still needs. So each session cleans up its own things and nobody else's. A central cleaner that guesses from the outside frees little and risks deleting live work.

The scratch folder is `$CLAUDE_TIDY_DIR` (default `~/.claude-scratch`). The helper is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tidy.py"`, called `tidy.py` below.

## 1. Collect your own things

- Copies you created or used in this session: every path under the scratch folder that appears in your conversation, including folders without git, logs and scripts.
- Cross-check with the owner registry: `tidy.py mine ${CLAUDE_SESSION_ID}`. If the ID is not filled in, match the names from your conversation against the files in `<scratch>/.owners/`.
- Dev servers and background jobs you started (port and PID from the conversation).
- `.keep-until-YYYY-MM-DD` files you set yourself.

Never touch copies that belong to other sessions, however big or old. Step 3 handles their build folders.

## 2. Decide per copy

Keep it if any of these is true:
- Unpushed commits or uncommitted changes worth keeping. Never commit or push without being asked; mention it in the report.
- The user has not seen the result yet, or you gave them a URL served from it that they still need.
- An open PR, a running release or a handover to another session depends on it (`.tidy-pin`, or `co_owners` in the registry entry).
- The work continues in this session right away.

Otherwise remove it:
- Git worktree: `git -C <main-repo> worktree remove <path>` (never plain `rm`, it leaves the worktree registered). If git refuses because of local changes, check them again against the list above; add `--force` only once you are sure they can go.
- Anything else: `rm -rf <path>`.
- If you keep a copy but no longer need its build output (`node_modules`, `target`, `build`, `DerivedData`, `dist`), delete only that.
- Stop your own dev servers and jobs by PID, never by `pkill` pattern.
- Remove your own `.keep-until-*` once the reason is gone.

Never without the user's go-ahead: anything outside the scratch folder, copies with `.tidy-pin`.

## 3. Build folders of abandoned copies

Run `tidy.py sweep` first, it is a dry run. Then `tidy.py sweep --run`. It deletes only untracked `build`, `target`, `node_modules`, `DerivedData`, `.build` and `dist` folders, and only in copies whose owner session is no longer running, that are clean git repos of their own, untouched for `CLAUDE_TIDY_REST_DAYS` days (default 3), not pinned and not named in any running command line. Anything git tracks stays. It refuses to run in a folder without an `.owners` registry.

## 4. Report (short)

- Free disk space before and after (`df -h` on the volume holding the scratch folder). State only the measured difference, no estimate.
- Removed: names.
- Kept: name and the reason in half a sentence.
- Build folder sweep: one line with the freed GB, plus any folder it could not remove.
- No list of other sessions' copies for the user to decide on. That costs their attention and is not this session's business.
