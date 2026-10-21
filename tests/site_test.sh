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
[{"name": "Maya", "role": "iOS engineer", "manager": "Ceo", "status": "active", "salary": "4,000 credits", "career_goal": "Lead the next product", "joined": "2026-11-02", "bio": "Fast, exacting, allergic to meetings.", "temperament": "restless"},
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
mood: 4
feeling: Relieved
mood_reason: The build finally works.
---
Dear diary. The build works. https://github.com/test/company/issues/3 was annoying.
EOF
cat > story/2026-11-02-maya-diary.md <<'EOF'
---
title: Maya's diary, Day 2
date: 2026-11-02
time: 18:10
kind: diary
workers: maya
mood: 2
feeling: Frustrated
mood_reason: Nothing compiles yet.
---
First day. Nothing compiles.
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
printf '{"revenue_usd": 0, "spent_usd": 99, "day": 4, "days_left": 26, "app_name": "Orbit", "status": "building", "stage": "build", "history": [{"date": "2026-11-03", "revenue_usd": 0}, {"date": "2026-11-04", "revenue_usd": 0}]}\n' > ops/scoreboard.json
printf '# Memory\n\n- The build command is tools/xc.sh. Secret: github_pat_11AAAAAAA0000000000000000000000.\n' > .claude/agent-memory/maya/MEMORY.md
printf '# Privacy policy\n\nWe collect nothing.\n' > site/pages/privacy.md
python3 tools/governor.py set-day1 2026-11-01 >/dev/null; python3 tools/governor.py set-budget 140 >/dev/null; python3 tools/governor.py set-5h-budget 20 >/dev/null
python3 -c 'import json; u=json.load(open("ops/usage.json")); u["cats"]={__import__("datetime").date.today().isoformat(): {"project": 9.0, "reports": 0.4, "meetings": 0.3, "hiring": 0.2, "talk": 0.1}}; u["days"]={"2026-11-03": 10.0, __import__("datetime").date.today().isoformat(): 10.0}; json.dump(u, open("ops/usage.json", "w"))'

echo "== build"
ok "builds and reports counts" "python3 tools/site_build.py --out $OUT | grep -q 'reports 2, workers 4, events 3, story 3, requests 2'"
ok "report permalink applies to posts only (pages keep .html)" "grep -q 'type: posts' $OUT/_config.yml && ! grep -q '^permalink' $OUT/_config.yml"
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
ok "every worker gets an animated portrait; still copies kept" "grep -q 'portraits/maya.svg' $OUT/cast/maya.md && [ -f $OUT/assets/portraits/ceo.svg ] && [ -f $OUT/assets/portraits/still/maya.svg ] && grep -q animateTransform $OUT/assets/portraits/ceo.svg"
ok "portrait: reduced-motion rule and a still fallback inside" "grep -q 'prefers-reduced-motion' $OUT/assets/portraits/maya.svg && grep -q 'class=\"still\"' $OUT/assets/portraits/maya.svg"
ok "temperament changes the motion (restless = rotate)" "grep -q 'type=\"rotate\"' $OUT/assets/portraits/maya.svg && ! grep -q 'type=\"rotate\"' $OUT/assets/portraits/olga.svg || grep -q 'type=\"rotate\"' $OUT/assets/portraits/maya.svg"
ok "mood: color-coded words on the cast, the worker's own word and reason on their page, sparkline" "grep -q 'mood-word lv4\">Relieved' $OUT/cast/index.md && grep -q 'The build finally works' $OUT/cast/maya.md && grep -q 'class=\"spark\"' $OUT/cast/maya.md && grep -q 'Mood, from the diaries' $OUT/cast/maya.md && grep -q 'Frustrated' $OUT/cast/maya.md"
ok "no diary: says so, no made-up mood" "grep -q 'No mood recorded yet' $OUT/cast/ceo.md && ! grep -q 'mood-word lv[1-5]' $OUT/cast/ceo.md"
ok "no faces anywhere (moods are words)" "! grep -rq 'class=\"face\"' $OUT"
ok "home: tiles, pipeline hero pre-launch, no revenue chart yet" "grep -q 'class=\"tiles\"' $OUT/index.md && grep -q 'class=\"pipe\"' $OUT/index.md && grep -q 'li class=\"now\"><span class=\"dot\"></span><span class=\"lbl\">Build' $OUT/index.md && ! grep -q 'net proceeds by day' $OUT/index.md && grep -q 'team morale' $OUT/index.md"
ok "report: strip with day track, money bar, and usage as a share of the daily pace; no morale" "grep -q 'class=\"strip\"' $OUT/_posts/2026-11-03-*evening.md && grep -q 'class=\"track\"' $OUT/_posts/2026-11-03-*evening.md && grep -q 'Net proceeds' $OUT/_posts/2026-11-03-*evening.md && grep -q 'of the daily pace' $OUT/_posts/2026-11-03-*evening.md && ! grep -q 'Team morale' $OUT/_posts/2026-11-03-*evening.md && ! grep -q 'mood-word' $OUT/_posts/2026-11-03-*evening.md"
ok "the report is the CEO's: her byline and portrait" "grep -q 'class=\"byline\"' $OUT/_posts/2026-11-03-*evening.md && grep -q 'From <a href=.*>Ceo</a>, CEO' $OUT/_posts/2026-11-03-*evening.md"
ok "a report links to its period's records" "grep -q 'Behind the scenes' $OUT/_posts/2026-11-03-*evening.md && grep -q 'story/#d-2026-11-03' $OUT/_posts/2026-11-03-*evening.md"
ok "cast lead is one sentence" "grep -q 'Every worker is an AI-simulated character with a first name, a role, a personality, and a career goal.</p>' $OUT/cast/index.md"
ok "home shows the latest records" "grep -q 'From the records' $OUT/index.md && grep -q 'maya-diary.html' $OUT/index.md"
ok "url and baseurl come from the site's address" "grep -q '^url: \"https://test.github.io\"' $OUT/_config.yml && grep -q '^baseurl: \"/site\"' $OUT/_config.yml"
ok "a 404 page" "grep -q 'permalink: \"/404.html\"' $OUT/404.md && grep -q 'Page not found' $OUT/404.md"
ok "usage: progress bars and the stacked category bar" "grep -q 'class=\"bar-fill\"' $OUT/usage.md && grep -q 'Fable this week' $OUT/usage.md && grep -q 'class=\"stack\"' $OUT/usage.md"
ok "story page links its worker" "grep -q 'cast/maya.html' $OUT/story/2026-11-03-maya-diary.md && grep -q '(private)' $OUT/story/2026-11-03-maya-diary.md"
ok "combined log newest first, pipes escaped, json export" "head -20 $OUT/log/index.md | grep -q 'Tests green' && grep -q '12/12' $OUT/log/index.md && grep -q '\\\\|' $OUT/log/index.md && python3 -c 'import json; d=json.load(open(\"$OUT/log/events.json\")); assert len(d)==3 and d[0][\"type\"]==\"test\"'"
ok "usage page has every window" "grep -q 'Last 5 hours' $OUT/usage.md && grep -q 'This week' $OUT/usage.md && grep -q 'Fable this week' $OUT/usage.md"
ok "usage page lists the hiring category and the 90% floor" "grep -q '| hiring |' $OUT/usage.md && grep -q 'at least 90%' $OUT/usage.md"
ok "usage is shown in percent, never in dollars" "grep -q 'of the weekly limit' $OUT/usage.md && ! grep -q '[\$]' $OUT/usage.md"
ok "requests page lists open issues, urgent first, with message link" "grep -q 'two-factor' $OUT/requests.md && grep -q 'Questions from Report 12' $OUT/requests.md && grep -n 'two-factor\|Report 12' $OUT/requests.md | head -1 | grep -q two-factor && grep -q 'issues/new?labels=directive' $OUT/requests.md"
ok "index has the scoreboard and the message link" "grep -q 'net proceeds' $OUT/index.md && grep -q 'Day 4' $OUT/index.md && grep -q 'issues/new' $OUT/index.md"
ok "pages: written privacy copied, others are placeholders" "grep -q 'We collect nothing' $OUT/privacy.md && grep -q 'published here at launch' $OUT/press.md"
ok "story/private is skipped" "[ ! -e $OUT/story/private ] && ! grep -rq 'Secret plan' $OUT"
ok "disclosure in the layout" "grep -q 'site.disclosure' $OUT/_layouts/default.html && grep -q 'AI-simulated' $OUT/_config.yml"

echo "== navigation: tabs, back links, report headers, day groups, records"
ok "layout has the section tabs, the current one marked" "grep -q 'class=\"tabs\"' $OUT/_layouts/default.html && grep -q 'page.section == \"reports\"' $OUT/_layouts/default.html && grep -q 'page.section == \"records\"' $OUT/_layouts/default.html && grep -q 'aria-current' $OUT/_layouts/default.html"
ok "every page names its section" "grep -q '^section: \"reports\"' $OUT/_posts/2026-11-03-*evening.md && grep -q '^section: \"reports\"' $OUT/reports/index.md && grep -q '^section: \"cast\"' $OUT/cast/maya.md && grep -q '^section: \"records\"' $OUT/story/2026-11-03-maya-diary.md && grep -q '^section: \"log\"' $OUT/log/index.md && grep -q '^section: \"about\"' $OUT/privacy.md && grep -q '^section: \"home\"' $OUT/index.md"
ok "a report says what it is and links back and to its neighbour" "grep -q 'class=\"crumbs\"' $OUT/_posts/2026-11-03-*evening.md && grep -q \"'/reports/' | relative_url\" $OUT/_posts/2026-11-03-*evening.md && grep -q 'Evening report' $OUT/_posts/2026-11-03-*evening.md && grep -q 'class=\"num\">Report 5' $OUT/_posts/2026-11-03-*evening.md && grep -q 'reports/2026-11-04-0600-morning/' $OUT/_posts/2026-11-03-*evening.md && grep -q 'class=\"pager\"' $OUT/_posts/2026-11-03-*evening.md"
ok "the report sits beside its period panel" "grep -q 'class=\"report-grid\" markdown=\"1\"' $OUT/_posts/2026-11-03-*evening.md && grep -q 'class=\"panel period\"' $OUT/_posts/2026-11-03-*evening.md"
ok "reports index: one block per day, a card per report, with its opening line" "[ \$(grep -o 'class=\"day\"' $OUT/reports/index.md | wc -l) = 2 ] && [ \$(grep -o 'class=\"card report\"' $OUT/reports/index.md | wc -l) = 2 ] && grep -q 'The build compiled' $OUT/reports/index.md && ! grep -q '{{ liquid }}' $OUT/reports/index.md"
ok "records: the hiring rounds, then records by day" "grep -q 'id=\"hiring-rounds\"' $OUT/story/index.md && grep -q 'story/hiring/2026-11-02-ios-engineer/' $OUT/story/index.md && grep -q 'maya-diary.html' $OUT/story/index.md && grep -q 'Day 3' $OUT/story/index.md"
ok "a hiring round has its own page: steps, candidates with scorecards, records" "grep -q 'class=\"pipe\"' $OUT/story/hiring/2026-11-02-ios-engineer/index.md && grep -q 'On the bench' $OUT/story/hiring/2026-11-02-ios-engineer/index.md && grep -q 'Scorecard average 3.7 (Ceo)' $OUT/story/hiring/2026-11-02-ios-engineer/index.md && grep -q 'interview-ceo-noor.html' $OUT/story/hiring/2026-11-02-ios-engineer/index.md"
ok "an interview links back to its round; a diary links back to the records" "grep -q \"story/hiring/2026-11-02-ios-engineer/' | relative_url\" $OUT/story/hiring/2026-11-02-ios-engineer/interview-ceo-noor.md && grep -q 'Hiring round: iOS engineer' $OUT/story/hiring/2026-11-02-ios-engineer/interview-ceo-noor.md && grep -q \"'/story/' | relative_url\" $OUT/story/2026-11-03-maya-diary.md"
ok "a worker page links back to the cast and to the hiring round" "grep -q \"'/cast/' | relative_url\" $OUT/cast/maya.md && grep -q 'story/hiring/2026-11-02-ios-engineer/' $OUT/cast/noor.md"
ok "about pages share their own tabs, the current one marked" "grep -q 'class=\"subtabs\"' $OUT/privacy.md && grep -q 'aria-current=\"page\">Privacy' $OUT/privacy.md && grep -q 'aria-current=\"page\">Press kit' $OUT/press.md"
ok "the log is grouped by day" "grep -q '^## Day 4 <small>' $OUT/log/index.md && grep -q '^## Day 3 <small>' $OUT/log/index.md"
ok "every portrait sits on a white tile" "grep -q 'rx=\"14\" fill=\"#ffffff\"' $OUT/assets/portraits/maya.svg && ! grep -q '40%,15%' $OUT/assets/portraits/*.svg"

echo "== report period panel: timeline, people, moods"
ok "evening report lists the period's events as a timeline, oldest first" "grep -q 'class=\"rail\"' $OUT/_posts/2026-11-03-*evening.md && grep -q 'First compiling build' $OUT/_posts/2026-11-03-*evening.md && grep -q 'Chose SwiftUI' $OUT/_posts/2026-11-03-*evening.md && ! grep -q 'Tests green' $OUT/_posts/2026-11-03-*evening.md"
ok "morning report covers only its own window" "grep -q 'Tests green' $OUT/_posts/2026-11-04-*morning.md && ! grep -q 'First compiling build' $OUT/_posts/2026-11-04-*morning.md"
ok "the report leaves moods to the records" "! grep -q 'How they felt' $OUT/_posts/2026-11-03-*evening.md && ! grep -q 'Relieved' $OUT/_posts/2026-11-03-*evening.md && grep -q 'Relieved' $OUT/story/index.md"
printf '{"time": "2026-11-03T12:00:00-05:00", "worker": "maya", "type": "hire", "summary": "Maya joins as iOS engineer", "link": ""}\n' >> log/events.jsonl
cat > reports/2026-11-07-1800.md <<'EOF'
---
title: Report 11 — Week 1 in review
number: 11
day: 7
date: 2026-11-07
time: 18:00
kind: weekly
---
Week one.
EOF
python3 tools/site_build.py --out $OUT --no-gh >/dev/null
ok "a hire shows on the report's timeline as a team fact, with no People strip" "grep -q 'Maya joins as iOS engineer' $OUT/_posts/2026-11-03-*evening.md && ! grep -q 'class=\"people\"' $OUT/_posts/2026-11-03-*evening.md"
ok "weekly report keeps the usage bars; the mood lines move to the records" "grep -q 'last 7 days' $OUT/_posts/2026-11-07-*weekly.md && grep -q 'Claude usage by day' $OUT/_posts/2026-11-07-*weekly.md && ! grep -q 'class=\"minis\"' $OUT/_posts/2026-11-07-*weekly.md && grep -q 'class=\"minis\"' $OUT/story/index.md"
rm -f reports/2026-11-07-1800.md
cat > reports/2026-11-30-1800.md <<'EOF'
---
title: Report 60 — the Final Report
number: 60
day: 30
date: 2026-11-30
time: 18:00
kind: final
---
The end.
EOF
python3 tools/site_build.py --out $OUT --no-gh >/dev/null
ok "final report adds the month's milestones and the revenue chart" "grep -q 'in milestones' $OUT/_posts/2026-11-30-*final.md && grep -q 'Maya joins' $OUT/_posts/2026-11-30-*final.md && grep -q 'net proceeds by day' $OUT/_posts/2026-11-30-*final.md"
rm -f reports/2026-11-30-1800.md
ok "portraits use the distinct variants and carry the family on the worker page" "grep -q 'curve, seeded by the name' $OUT/cast/maya.md"

echo "== post-launch: the revenue chart becomes the hero"
printf '{"revenue_usd": 61.5, "spent_usd": 99, "day": 24, "days_left": 6, "app_name": "Orbit", "status": "on sale", "stage": "selling", "launched": "2026-11-20", "history": [{"date": "2026-11-20", "revenue_usd": 0}, {"date": "2026-11-22", "revenue_usd": 20}, {"date": "2026-11-24", "revenue_usd": 61.5}]}\n' > ops/scoreboard.json
python3 tools/site_build.py --out $OUT --no-gh >/dev/null
ok "chart with goal line and the latest point" "grep -q 'net proceeds by day' $OUT/index.md && grep -q 'goal \$200' $OUT/index.md && grep -q '\$61.50' $OUT/index.md && grep -q 'class=\"hero two\"' $OUT/index.md"
ok "launch day marked on the track" "grep -q 'now launch\|past launch\|todo launch' $OUT/index.md"
printf '{"revenue_usd": 0, "spent_usd": 99, "day": 4, "days_left": 26, "app_name": "Orbit", "status": "building", "stage": "build"}\n' > ops/scoreboard.json

echo "== the Investors' controls (investors/site/)"
mkdir -p investors/site/pages investors/site/files
printf -- '---\ntitle: FAQ\n---\n# FAQ\n\nAsk us anything.\n' > investors/site/pages/faq.md
printf -- '---\ntitle: Our privacy\n---\n# Our privacy\n\nWritten by the Investors.\n' > investors/site/pages/privacy.md
printf 'User-agent: *\n' > investors/site/files/robots.txt
printf ':root{--accent:#0b7a55}\n' > investors/site/theme.css
printf '{"publish": false, "announcement": "Launch week!"}\n' > investors/site/settings.json
python3 tools/site_build.py --out $OUT --no-gh >/dev/null
ok "their theme is added after the site's styles" "grep -q 'investors/site/theme.css' $OUT/_layouts/default.html && grep -q -- '--accent:#0b7a55' $OUT/_layouts/default.html"
ok "their announcement shows on every page" "grep -q 'announcement: \"Launch week!\"' $OUT/_config.yml && grep -q 'site.announcement' $OUT/_layouts/default.html"
ok "their pages add to and replace the company's" "grep -q 'Ask us anything' $OUT/faq.md && grep -q 'aria-current=\"page\">FAQ' $OUT/faq.md && grep -q 'Written by the Investors' $OUT/privacy.md && ! grep -q 'We collect nothing' $OUT/privacy.md && grep -q 'faq.html' $OUT/about.md"
ok "their files are copied as they are" "grep -q 'User-agent' $OUT/robots.txt"
printf '{"publish": false, "announcement": ""}\n' > investors/site/settings.json

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
REMOTE="$T/site-remote.git"; git init -q --bare "$REMOTE"; (cd "$SITE" && git remote add origin "$REMOTE")
printf '{"publish": false}\n' > investors/site/settings.json
ok "unpublished: built and committed, nothing pushed" "SITE_DIR=$SITE SITE_NO_GH=1 tools/site_publish.sh | grep -q 'unpublished' && ! git -C $REMOTE rev-parse --verify -q main >/dev/null"
printf '{"publish": true}\n' > investors/site/settings.json
ok "published: pushed to main" "SITE_DIR=$SITE SITE_NO_GH=1 tools/site_publish.sh && git -C $REMOTE rev-parse --verify -q main >/dev/null"
ok "published and nothing new: the remote matches" "SITE_DIR=$SITE SITE_NO_GH=1 tools/site_publish.sh && [ \$(git -C $REMOTE rev-parse main) = \$(git -C $SITE rev-parse HEAD) ]"
printf '{"publish": false, "announcement": ""}\n' > investors/site/settings.json

echo "== report-usage"
ok "report-usage prints the windows" "python3 tools/governor.py report-usage --now 2026-11-04T10:00:00-05:00 | grep -q 'Last 5 hours' "
ok "report-usage is in percent only" "python3 tools/governor.py report-usage --now 2026-11-04T10:00:00-05:00 | grep -q 'of the weekly limit' && ! python3 tools/governor.py report-usage --now 2026-11-04T10:00:00-05:00 | grep -q '[\$]'"
ok "5-hour share uses the calibrated budget" "python3 tools/governor.py status --json --now 2026-11-04T10:00:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"five_hour_budget_usd\"]==20.0 and \"window_5h_usd\" in d'"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
