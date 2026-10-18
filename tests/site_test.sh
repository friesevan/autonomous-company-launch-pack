#!/bin/bash
# The site build: pages for reports, cast, story, log, usage, and requests from
# fixture records; scrubbing of private links and secrets; the publish script.
# Run through tests/run.sh, which builds the throwaway copy this works in.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export HOME="$T/home" PATH="$T/home/.local/bin:$PATH"
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
OUT="$T/site"

# Fixtures: a company a few days in.
mkdir -p reports story personnel/portraits log ops site/pages .claude/agent-memory/maya
cat > site.json <<'EOF'
{"name": "Orbit Labs", "tagline": "Thirty days to ship an app.", "company_repo": "test/company", "url": "https://test.github.io/site"}
EOF
cat > personnel/registry.json <<'EOF'
[{"name": "Maya", "role": "iOS engineer", "manager": "Ceo", "status": "active", "salary": "4,000 credits", "career_goal": "Lead the next product", "joined": "2026-11-02", "bio": "Fast, exacting, allergic to meetings."},
 {"name": "Ceo", "role": "CEO", "status": "active", "joined": "2026-11-01"},
 {"name": "Olga", "role": "Designer", "status": "former", "joined": "2026-11-02", "left": "2026-11-09"},
 {"name": "Noor", "role": "Candidate, iOS engineer", "status": "candidate", "round": "2026-11-02-ios-engineer", "bio": "Interviewed on Day 2; not hired."}]
EOF
printf '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>' > personnel/portraits/maya.svg
cat > reports/2026-11-03-1800.md <<'EOF'
---
title: Report 5 — the first build
number: 5
day: 3
date: 2026-11-03
time: 18:00
kind: evening
issue: https://github.com/test/company/issues/7
---
# Report 5

The build compiled. See https://github.com/test/company/commit/abc123 for details.

Token in a pasted log: ghp_abcdefghijklmnopqrstuvwxyz0123456789 and {{ liquid }} braces.
EOF
cat > reports/2026-11-04-0600.md <<'EOF'
---
title: Report 6 — overnight
number: 6
day: 4
date: 2026-11-04
time: 06:00
kind: morning
---
Quiet-ish night.
EOF
cat > story/2026-11-03-maya-diary.md <<'EOF'
---
title: Maya's diary, Day 3
date: 2026-11-03
time: 18:20
kind: diary
workers: maya
---
Dear diary. The build works. https://github.com/test/company/issues/3 was annoying.
EOF
mkdir -p story/hiring/2026-11-02-ios-engineer
cat > story/hiring/2026-11-02-ios-engineer/interview-ceo-noor.md <<'EOF'
---
title: Interview, Noor, for iOS engineer
date: 2026-11-02
time: 11:00
kind: interview
workers: ceo, noor
---
Transcript.

## Scorecard

| Competency | Score |
| --- | --- |
| Swift | 4 |
| Shipping | 3 |
| Collaboration | 4 |
EOF
cat > log/events.jsonl <<'EOF'
{"time": "2026-11-03T10:00:00-05:00", "worker": "maya", "type": "commit", "summary": "First compiling build", "link": "https://github.com/test/company/commit/abc123"}
{"time": "2026-11-03T15:30:00-05:00", "worker": "ceo", "type": "decision", "summary": "Chose SwiftUI over UIKit", "link": ""}
{"time": "2026-11-04T05:10:00-05:00", "worker": "maya", "type": "test", "summary": "Tests green on the Simulator | 12/12", "link": ""}
EOF
mkdir -p story/private; printf -- '---\ntitle: Secret plan\ndate: 2026-11-03\nworkers: maya\n---\nnot for the site\n' > story/private/plan.md
printf '{"revenue_usd": 0, "spent_usd": 99, "day": 4, "days_left": 26, "app_name": "Orbit", "status": "building"}\n' > ops/scoreboard.json
printf '# Memory\n\n- The build command is tools/xc.sh. Secret: github_pat_11AAAAAAA0000000000000000000000.\n' > .claude/agent-memory/maya/MEMORY.md
printf '# Privacy policy\n\nWe collect nothing.\n' > site/pages/privacy.md
python3 tools/governor.py set-day1 2026-11-01 >/dev/null; python3 tools/governor.py set-budget 140 >/dev/null; python3 tools/governor.py set-5h-budget 20 >/dev/null

echo "== build"
ok "builds and reports counts" "python3 tools/site_build.py --out $OUT | grep -q 'reports 2, workers 4, events 3, story 2, requests 2'"
ok "jekyll config, layout, feed" "grep -q 'jekyll-feed' $OUT/_config.yml && grep -q 'feed_meta' $OUT/_layouts/default.html"
ok "reports are posts, newest first by filename" "[ -f $OUT/_posts/2026-11-03-2026-11-03-1800-evening.md ] && [ -f $OUT/_posts/2026-11-04-2026-11-04-0600-morning.md ]"
ok "private copy linked from the report" "grep -q 'issues/7' $OUT/_posts/2026-11-03-*evening.md && grep -q 'Questions for the Investors' $OUT/_posts/2026-11-03-*evening.md"
ok "private repo links scrubbed in reports" "! grep -q 'github.com/test/company/commit' $OUT/_posts/2026-11-03-*evening.md && grep -q '(private)' $OUT/_posts/2026-11-03-*evening.md"
ok "the private copy link itself survives (Investors need it)" "grep -c 'github.com/test/company/issues/7' $OUT/_posts/2026-11-03-*evening.md | grep -q 1"
ok "tokens removed everywhere" "! grep -rq 'ghp_abc\|github_pat_11' $OUT"
ok "liquid braces are wrapped in raw" "grep -q '{% raw %}' $OUT/_posts/2026-11-03-*evening.md"
ok "cast index has active and former" "grep -q 'Working here now' $OUT/cast/index.md && grep -q 'Former workers' $OUT/cast/index.md && grep -q 'cast/olga.html' $OUT/cast/index.md"
ok "cast index has a Considered group between them, with the candidate" "grep -q 'Considered, not hired' $OUT/cast/index.md && grep -q 'cast/noor.html' $OUT/cast/index.md && grep -n 'Working here now\\|Considered\\|Former workers' $OUT/cast/index.md | sed -n 2p | grep -q Considered"
ok "candidate page links the interview; interview page links both" "grep -q 'interview-ceo-noor.html' $OUT/cast/noor.md && grep -q 'cast/noor.html' $OUT/story/hiring/2026-11-02-ios-engineer/interview-ceo-noor.md && grep -q 'cast/ceo.html' $OUT/story/hiring/2026-11-02-ios-engineer/interview-ceo-noor.md"
ok "worker page: profile, activity, diary, memory scrubbed" "grep -q 'Lead the next product' $OUT/cast/maya.md && grep -q 'First compiling build' $OUT/cast/maya.md && grep -q 'story/2026-11-03-maya-diary.html' $OUT/cast/maya.md && grep -q 'What they remember' $OUT/cast/maya.md && grep -q '\[removed\]' $OUT/cast/maya.md"
ok "worker page: portrait only when it exists" "grep -q 'portraits/maya.svg' $OUT/cast/maya.md && ! grep -q 'portraits/ceo.svg' $OUT/cast/ceo.md"
ok "story page links its worker" "grep -q 'cast/maya.html' $OUT/story/2026-11-03-maya-diary.md && grep -q '(private)' $OUT/story/2026-11-03-maya-diary.md"
ok "combined log newest first, pipes escaped, json export" "head -20 $OUT/log/index.md | grep -q 'Tests green' && grep -q '12/12' $OUT/log/index.md && grep -q '\\\\|' $OUT/log/index.md && python3 -c 'import json; d=json.load(open(\"$OUT/log/events.json\")); assert len(d)==3 and d[0][\"type\"]==\"test\"'"
ok "usage page has every window" "grep -q 'Last 5 hours' $OUT/usage.md && grep -q 'This week' $OUT/usage.md && grep -q 'Fable this week' $OUT/usage.md"
ok "usage page lists the hiring category and the 87% floor" "grep -q '| hiring |' $OUT/usage.md && grep -q 'at least 87%' $OUT/usage.md"
ok "requests page lists open issues, urgent first, with message link" "grep -q 'two-factor' $OUT/requests.md && grep -q 'Questions from Report 12' $OUT/requests.md && grep -n 'two-factor\|Report 12' $OUT/requests.md | head -1 | grep -q two-factor && grep -q 'issues/new?labels=directive' $OUT/requests.md"
ok "index has the scoreboard and the message link" "grep -q 'net proceeds' $OUT/index.md && grep -q 'Day 4' $OUT/index.md && grep -q 'issues/new' $OUT/index.md"
ok "pages: written privacy copied, others are placeholders" "grep -q 'We collect nothing' $OUT/privacy.md && grep -q 'published here at launch' $OUT/press.md"
ok "story/private is skipped" "[ ! -e $OUT/story/private ] && ! grep -rq 'Secret plan' $OUT"
ok "disclosure in the layout" "grep -q 'site.disclosure' $OUT/_layouts/default.html && grep -q 'AI-simulated' $OUT/_config.yml"

echo "== rebuild removes stale files; --no-gh skips GitHub"
touch $OUT/stale.md; printf 'x' > $OUT/CNAME
python3 tools/site_build.py --out $OUT --no-gh >/dev/null
ok "stale file removed, CNAME kept" "[ ! -f $OUT/stale.md ] && [ -f $OUT/CNAME ]"
ok "no-gh: requests page explains" "grep -q 'listed here when the site is built' $OUT/requests.md"

echo "== publish script"
SITE="$T/sitepub"; mkdir -p "$SITE" && (cd "$SITE" && git init -q -b main)
ok "no site clone: silent exit 0" "SITE_DIR=$T/nowhere tools/site_publish.sh; [ \$? = 0 ]"
ok "with a clone: builds and commits" "SITE_DIR=$SITE SITE_NO_GH=1 tools/site_publish.sh && (cd $SITE && git log --oneline | grep -q '^[0-9a-f]* site: ')"
ok "nothing changed: no second commit" "SITE_DIR=$SITE SITE_NO_GH=1 tools/site_publish.sh && [ \$(cd $SITE && git rev-list --count HEAD) = 1 ]"
ok "supervisor calls the publish script after a session" "grep -q 'site_publish.sh' tools/supervisor.sh"

echo "== report-usage"
ok "report-usage prints the windows" "python3 tools/governor.py report-usage --now 2026-11-04T10:00:00-05:00 | grep -q 'Last 5 hours' "
ok "5-hour share uses the calibrated budget" "python3 tools/governor.py status --json --now 2026-11-04T10:00:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"five_hour_budget_usd\"]==20.0 and \"window_5h_usd\" in d'"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
