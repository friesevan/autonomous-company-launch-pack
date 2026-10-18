#!/bin/bash
# The hiring-round check (tools/hiring_check.py): a complete round passes; a
# missing interview, a scorecard-free interview, a brief committed after a
# dossier, a worker with no round, and an untraceable career goal each fail
# with a named reason. Run through tests/run.sh, which builds the throwaway copy.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export HOME="$T/home" PATH="$T/home/.local/bin:$PATH"
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
F="$T/hiring"; rm -rf "$F"; mkdir -p "$F"
G() { git -C "$F" -c user.name=t -c user.email=t@example.com "$@"; }
chk() { python3 tools/hiring_check.py --root "$F" "$@"; }
RID=2026-11-02-ios-engineer
D="$F/story/hiring/$RID"

# A round written in the right order: brief first, then the candidates, interviews, decision.
mkdir -p "$D" "$F/personnel/candidates" "$F/personnel/agents"
G init -q
cat > "$D/brief.md" <<'EOF'
---
title: Role brief, iOS engineer
date: 2026-11-02
time: 09:00
kind: memo
workers: ceo
---
Business reason: the Pitch's build plan has 14 Swift tasks with no owner.

## Scorecard
| Competency | Strong looks like |
| --- | --- |
| Swift | ships SwiftUI without hand-holding |
| Shipping | has taken an app through App Review |
| Collaboration | asks for review early |
EOF
G add -A && G commit -qm "brief"
printf -- '---\ndescription: Noor, candidate.\nround: %s\nstatus: candidate\n---\n# Noor\n' "$RID" > "$F/personnel/candidates/noor.md"
printf -- '---\ndescription: Maya, iOS engineer.\n---\n# Maya\nHired on Day 2.\n' > "$F/personnel/agents/maya.md"
for c in maya noor; do cat > "$D/interview-ceo-$c.md" <<EOF
---
title: Interview, $c
date: 2026-11-02
time: 11:00
kind: interview
workers: ceo, $c
---
CEO: What do you want from this job?
$c: To lead the next product once this one ships.

## Scorecard
| Competency | Score |
| --- | --- |
| Swift | 4 |
| Shipping | 3 |
| Collaboration | 5 |
EOF
done
cat > "$D/decision.md" <<'EOF'
---
title: Decision, iOS engineer
date: 2026-11-02
time: 15:00
kind: meeting
workers: ceo
---
Hired Maya. Noor interviewed better on shipping. Offer: 4,000 credits; goal: lead the next product.
EOF
cat > "$F/personnel/registry.json" <<EOF
[{"name": "Ceo", "role": "CEO", "status": "active", "joined": "2026-11-01"},
 {"name": "Maya", "role": "iOS engineer", "status": "active", "round": "$RID", "career_goal": "Lead the next product", "joined": "2026-11-02"},
 {"name": "Noor", "role": "Candidate, iOS engineer", "status": "candidate", "round": "$RID"}]
EOF
G add -A && G commit -qm "round"

echo "== a complete round"
ok "passes" "chk | grep -q 'OK: 1 hiring round'"
ok "exit 0" "chk >/dev/null"

echo "== each missing piece is named"
cp "$D/interview-ceo-noor.md" "$T/noor.bak"; rm "$D/interview-ceo-noor.md"
ok "missing interview" "chk | grep -q 'Noor: no interview record'"
ok "exit 1" "! chk >/dev/null"
cp "$T/noor.bak" "$D/interview-ceo-noor.md"
sed -i.bak 's/^| Swift | 4 |$//' "$D/interview-ceo-maya.md"
ok "scorecard with too few scores" "chk | grep -q 'interview-ceo-maya.md: no .## Scorecard. table'"
mv "$D/interview-ceo-maya.md.bak" "$D/interview-ceo-maya.md"
mv "$D/decision.md" "$T/decision.bak"
ok "missing decision memo" "chk | grep -q 'no decision.md'"
mv "$T/decision.bak" "$D/decision.md"
python3 - "$F/personnel/registry.json" <<'EOF'
import json,sys; p=sys.argv[1]; r=json.load(open(p)); r[1]["career_goal"]="Buy a sailboat and cross the Atlantic"; json.dump(r,open(p,"w"))
EOF
ok "untraceable career goal" "chk | grep -q 'Maya: career goal is not traceable'"
python3 - "$F/personnel/registry.json" <<'EOF'
import json,sys; p=sys.argv[1]; r=json.load(open(p)); r[1]["career_goal"]="Lead the next product"; r.append({"name": "Pat", "role": "QA", "status": "active"}); json.dump(r,open(p,"w"))
EOF
ok "worker hired without a round" "chk | grep -q 'Pat: active or former worker with no hiring round'"
python3 - "$F/personnel/registry.json" <<'EOF'
import json,sys; p=sys.argv[1]; r=json.load(open(p)); r.pop(); r.pop(); json.dump(r,open(p,"w"))
EOF
ok "a round needs at least two candidates" "chk | grep -q 'only 1 candidate'"
G checkout -q -- personnel/registry.json
ok "restored round passes again" "chk | grep -q 'OK: 1 hiring round'"

echo "== the scorecard must come before the candidates"
# The same round in a fresh repository, with the dossiers committed an hour before the brief.
F2="$T/hiring-late"; rm -rf "$F2"; mkdir -p "$F2"; (cd "$F" && tar --exclude ./.git -cf - .) | (cd "$F2" && tar -xf -)
G2() { git -C "$F2" -c user.name=t -c user.email=t@example.com "$@"; }
G2 init -q
mv "$F2/story/hiring/$RID/brief.md" "$T/brief.late"
GIT_COMMITTER_DATE="2026-11-02T09:00:00-05:00" G2 add -A && GIT_COMMITTER_DATE="2026-11-02T09:00:00-05:00" G2 commit -qm "dossiers first"
mv "$T/brief.late" "$F2/story/hiring/$RID/brief.md"
GIT_COMMITTER_DATE="2026-11-02T10:00:00-05:00" G2 add -A && GIT_COMMITTER_DATE="2026-11-02T10:00:00-05:00" G2 commit -qm "brief an hour later"
ok "brief committed after a dossier fails" "python3 tools/hiring_check.py --root $F2 | grep -q 'was committed before brief.md'"
ok "and the first fixture, in the right order, still passes" "chk | grep -q 'OK: 1 hiring round'"

echo "== uncommitted files: order is noted, not failed"
printf -- '---\ndescription: Sam, candidate.\nround: %s\nstatus: candidate\n---\n# Sam\n' "$RID" > "$F/personnel/candidates/sam.md"
cp "$D/interview-ceo-noor.md" "$D/interview-ceo-sam.md"; sed -i.bak 's/noor/sam/g' "$D/interview-ceo-sam.md"; rm -f "$D/interview-ceo-sam.md.bak"
python3 - "$F/personnel/registry.json" "$RID" <<'EOF'
import json,sys; p=sys.argv[1]; r=json.load(open(p)); r.append({"name": "Sam", "role": "Candidate", "status": "candidate", "round": sys.argv[2]}); json.dump(r,open(p,"w"))
EOF
ok "uncommitted dossier is noted" "chk | grep -q 'note: .*sam.md or the brief is not committed yet'"

echo "== no registry"
ok "no registry: nothing to check, exit 0" "python3 tools/hiring_check.py --root $T/nowhere | grep -q 'nothing to check'"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
