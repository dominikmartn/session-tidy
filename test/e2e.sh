#!/bin/bash
# End-to-end check in a throwaway HOME: hooks register owners, sweep frees only what it may.
# Leaves its sandbox at $SANDBOX for inspection when a check fails.
set -u
TIDY="$(cd "$(dirname "$0")/.." && pwd)/scripts/tidy.py"
SANDBOX=$(mktemp -d)
export HOME="$SANDBOX" CLAUDE_TIDY_DIR="$SANDBOX/.claude-scratch"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
S="$CLAUDE_TIDY_DIR"; fail=0
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
hook() { printf '{"session_id":"%s","tool_input":{"command":%s}}' "$1" "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$2")" | python3 "$TIDY" hook-register; }
end() { printf '{"session_id":"%s","reason":"other"}' "$1" | python3 "$TIDY" hook-session-end; }
owner() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["session"])' "$S/.owners/$1.json" 2>/dev/null; }
old() { find "$1" -exec touch -h -t 202001010000 {} +; }
repo() { mkdir -p "$S/$1/node_modules/x" && git -C "$S/$1" init -q && echo x > "$S/$1/a" && echo node_modules > "$S/$1/.gitignore" && git -C "$S/$1" add -A && git -C "$S/$1" commit -qm i; }

# Registration
mkdir -p "$S"
hook S1 'mkdir -p ~/.claude-scratch/alpha && cd ~/.claude-scratch/alpha'
check "mkdir registers owner" '[ "$(owner alpha)" = S1 ]'
hook S2 'cp -R ~/.claude-scratch/alpha $HOME/.claude-scratch/beta'
check "copy target goes to the copying session" '[ "$(owner beta)" = S2 ]'
check "copy source keeps its owner" '[ "$(owner alpha)" = S1 ]'
hook S2 "git clone https://example.invalid/r.git $S/gamma"
check "absolute path registers" '[ "$(owner gamma)" = S2 ]'
hook S2 'cp -rf src $CLAUDE_TIDY_DIR/delta; gh repo clone o/r ${CLAUDE_TIDY_DIR}/eps; tar xzf a.tgz -C ~/.claude-scratch/zeta'
check "cp -rf with \$CLAUDE_TIDY_DIR registers" '[ "$(owner delta)" = S2 ]'
check "gh repo clone registers" '[ "$(owner eps)" = S2 ]'
check "tar xzf registers" '[ "$(owner zeta)" = S2 ]'
hook S3 'ls ~/.claude-scratch/alpha'
check "read-only mention does not take ownership" '[ "$(owner alpha)" = S1 ]'
hook S3 'cp -R x ~/.claude-scratch/alpha'
check "copying into a running owner's copy does not steal it" '[ "$(owner alpha)" = S1 ]'
check "mine skips copies without a folder" '[ -z "$(python3 "$TIDY" mine S1)" ]'
mkdir -p "$S/alpha"
check "mine finds an existing copy" '[ "$(python3 "$TIDY" mine S1)" = "$S/alpha" ]'
end S1
check "session end marks ended" 'grep -q ended "$S/.owners/alpha.json"'
hook S4 'mkdir ~/.claude-scratch/alpha'
check "a reused name goes to the new session once the old one ended" '[ "$(owner alpha)" = S4 ]'
printf 'not json' | python3 "$TIDY" hook-register; rc=$?
check "hook survives bad input" '[ $rc = 0 ]'
check "pin rejects a path outside the scratch folder" '! python3 "$TIDY" pin ../../x 2>/dev/null'

# Sweep refuses a folder the hook never wrote to
mkdir -p "$SANDBOX/projects/p/node_modules"
CLAUDE_TIDY_DIR="$SANDBOX/projects" python3 "$TIDY" sweep --run >/dev/null 2>&1; rc=$?
check "sweep refuses a folder without .owners" '[ $rc != 0 ] && [ -d "$SANDBOX/projects/p/node_modules" ]'

# Sweep rules. A fake ~/.claude/sessions file marks session LIVE as running.
rm -rf "$S"/* "$S/.owners"
for c in free dirty pinned recent nogit live shared kept used tracked link; do
  if [ $c = nogit ]; then mkdir -p "$S/$c/node_modules"; else repo $c; fi
  hook GONE "mkdir $S/$c"
done
echo y >> "$S/dirty/a"
python3 "$TIDY" pin pinned "release" >/dev/null
touch "$S/kept/.keep-until-2999-01-01"
mkdir -p "$S/tracked/build" && echo w > "$S/tracked/build/webpack.js" && git -C "$S/tracked" add -A && git -C "$S/tracked" commit -qm b
mkdir -p "$SANDBOX/outside/keep" && rm -rf "$S/link/node_modules" && ln -s "$SANDBOX/outside" "$S/link/node_modules"
end GONE
mkdir -p "$HOME/.claude/sessions"; sleep 300 & LIVEPID=$!
printf '{"pid":%s,"sessionId":"LIVE"}' $LIVEPID > "$HOME/.claude/sessions/$LIVEPID.json"
rm "$S/.owners/live.json"; hook LIVE "mkdir $S/live"
python3 "$TIDY" share LIVE shared >/dev/null
(exec -a "tool $S/used/server" sleep 300) & USEDPID=$!
for c in free dirty pinned nogit live shared kept used tracked link; do old "$S/$c"; done
hook GONE "mkdir $S/ghost"  # owner entry without a folder

python3 "$TIDY" sweep -v > "$SANDBOX/dry.txt"
check "dry run deletes nothing" '[ -d "$S/free/node_modules" ]'
python3 "$TIDY" sweep --run -v > "$SANDBOX/run.txt"
check "abandoned clean copy loses node_modules" '[ ! -d "$S/free/node_modules" ] && [ -f "$S/free/a" ]'
for c in dirty pinned recent nogit live shared kept used; do check "$c keeps node_modules" "[ -d \"$S/$c/node_modules\" ]"; done
check "git-tracked build folder stays" '[ -f "$S/tracked/build/webpack.js" ] && [ -z "$(git -C "$S/tracked" status --porcelain)" ]'
check "symlinked folder: target survives, failure is reported" '[ -d "$SANDBOX/outside/keep" ] && grep -q "could not remove node_modules: symlink" "$SANDBOX/run.txt"'
check "owner entries of vanished copies are dropped" '[ ! -e "$S/.owners/ghost.json" ] && [ -e "$S/.owners/free.json" ]'
kill $LIVEPID $USEDPID 2>/dev/null; wait $LIVEPID $USEDPID 2>/dev/null

if [ $fail = 0 ]; then rm -rf "$SANDBOX"; echo "all passed"; else echo "sandbox kept: $SANDBOX"; cat "$SANDBOX/run.txt"; exit 1; fi
