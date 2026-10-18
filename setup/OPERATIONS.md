# Operations Guide (for the company)

Who reads this: the Operator on Day 1 and whenever it changes the system, and the CEO when writing the Company Handbook. The outcomes in this guide are required by the Commandments. The mechanisms are the shipped, tested design; the company may change them under Commandment 3, as long as the outcomes hold, every change is logged, and nothing weakens the protections.

## 1. How it fits together

Everything runs on the Mac mini, in the company's macOS account, from a timer:

- **launchd** starts the **supervisor** every 15 minutes.
- The **supervisor** (`tools/supervisor.sh`) is a plain script that never calls Claude. It syncs the repository, checks for Investor messages, asks the **governor** what to do, and either starts one headless Claude Code session of the right type, runs the no-Claude queue, or does nothing.
- The **Operator** is that session's main conversation. It is not a character and never appears in the story. It reads the state and new Investor messages, hands tasks to workers, and commits the results.
- **Workers** are Claude Code subagents, each with a persona, a memory, and a portrait. Only the Operator starts them. Workers never start other agents.
- **GitHub** holds the private `company` repository (code, logs, records, and the Investor channels as issues) and the public `site` repository (the reports, served by GitHub Pages). The company acts on GitHub as its own account, never as an Investor.
- **App Store Connect** receives builds through an API key and reports sales.
- The **Investors** read and write GitHub issues from their phones, test TestFlight builds, and do the human-only steps. After Day 1 they never need to touch the Mac mini.

## 2. The run loop

The loop ships in `tools/`, tested. Day 1 installs it; it is not built from scratch.

| File | What it does |
| --- | --- |
| `tools/supervisor.sh` | One tick: lock, sync, inbox check, decision, session or queue, accounting, commit |
| `tools/governor.py` | Decides what runs and when; tracks spend against the weekly budget; detects limit hits |
| `tools/inbox_check.sh` | Marks `ops/inbox_pending` when an allowlisted Investor wrote since the last check |
| `tools/quiet_night.py` | Says whether anything happened since the evening report |
| `tools/run_queue.sh` | Runs the no-Claude queue in `ops/queue/` |
| `tools/events.py` | Appends to and reads the event log |
| `tools/xc.sh` | Quiet `xcodebuild` wrapper |
| `tools/install-launchd.sh` | Installs the LaunchAgent (`ops/launchd/`), no sudo |
| `tools/site_build.py`, `tools/site_publish.sh` | Builds the public site from the records and pushes it (`setup/SITE.md`) |
| `tools/hiring_check.py` | Verifies that every hire's round is complete and in order (section 5) |
| `ops/prompts/work.md`, `morning.md`, `evening.md` | The fixed prompt for each session type |

### One tick

`tools/install-launchd.sh` installs a LaunchAgent that runs `tools/supervisor.sh` every 15 minutes, logging to `ops/runs/`. Each tick:

1. **Lock.** If a session is already running, exit. A lock older than three hours is treated as a crash and removed.
2. **Sync.** `git pull --ff-only`, so Investor edits to `CLAUDE.md`, the rules, or the allowlist take effect on the next tick.
3. **Inbox.** `tools/inbox_check.sh` asks GitHub for issues and comments since the last check, from allowlisted accounts, ignoring the company's own; if there are any, it creates `ops/inbox_pending`.
4. **Decide.** `tools/governor.py decide` returns one of:
    - `evening`, `weekly` (Days 7, 14, 21, 28), or `final` (Day 30): due at 6:00 p.m. and not yet done today; the narrative pass, the report, and its private copy.
    - `morning`: due between 6:00 a.m. and noon, only if an evening report exists from an earlier day and `tools/quiet_night.py` found activity since it. A quiet night marks the morning as skipped and moves on.
    - `queue`: a usage limit was hit and its pause hasn't ended, Claude Code was found logged out within the last hour, or today's share of the weekly budget is spent. The supervisor runs `tools/run_queue.sh` instead of Claude.
    - `skip`: nothing to do: no open task on the board, no pending Investor message, and a work session ran within the last hour. If the week is behind pace, a `work` session with `backlog` runs instead (at most every two hours), and the CEO refills the board (Tenet 7).
    - `work`: otherwise.
5. **Prepare.** Write the decision to `ops/run.json` for the session (and the model guard) to read: the day, the flags, `fable_ok`, `over_cap`, and the session's spending cap. Run `rules/build_agents.py` so the workers carry the current rules and amendments (on Day 30, with `--include-former`, so former workers can write their testimonies).
6. **Run** one headless session with the type's model, effort, and turn cap (table below), `--max-budget-usd` (the session's cap), `--permission-mode auto --permission-prompts none`, `--no-session-persistence` (nothing is ever resumed, and saved sessions would cost background summarization), and `--output-format stream-json --verbose`, with stdin closed (otherwise Claude Code waits 3 seconds for piped input).
7. **Account.** `tools/governor.py record` reads the stream: the cost, split by category and by model (section 4), turns, denials, and whether a usage limit, the Fable limit, or a logged-out Claude Code stopped the run. It saves the result beside the stream as `ops/runs/<time>-<type>.json`.
8. **Retry once** if the session crashed. A limit, a log-out, or a turn or spending cap is not a crash.
9. **Alert** the Investors with an `emergency` issue if Claude Code is logged out (at most every 12 hours), since nothing else can run until someone logs in again.
10. **Commit** anything the session left behind, as the Operator, and push.
11. **Publish the site.** `tools/site_publish.sh` rebuilds the site from the records (no Claude, about a second) and pushes it; GitHub Pages renders it within minutes. It also runs after a queue tick, so the site keeps up while sessions are paused.

| Session | Prompt | Model | Effort | Turn cap | Why |
| --- | --- | --- | --- | --- | --- |
| `work` | `work.md` | sonnet | medium | 40 | Dispatching and bookkeeping; workers do the hard thinking on the model each task needs (Tenet 6) |
| `morning` | `morning.md` | haiku | low | 20 | A report assembled from the event log |
| `evening` | `evening.md` | sonnet | low | 30 | The report, its Questions for the Investors, and its private copy; diaries on Haiku |
| `weekly` | `evening.md` | sonnet | medium | 45 | The evening report plus "Week N in review" |
| `final` | `evening.md` | opus | high | 70 | The Final Report on Day 30; testimonies on Sonnet, the verdict on Fable |

Each session also gets a spending cap (`--max-budget-usd`): a work session may spend what is left of today's share (at least a quarter of the share), the morning report 5% of it, the evening report 15%, the weekly report 25%, and the Final Report a full day's share, never less than $0.50. A runaway session stops instead of eating the week.

### What a session looks like

Every session is short and self-contained, because a long conversation re-sends its whole history on every request:

1. Read `ops/run.json`, `ops/state.md` (goals, blockers, where things stand; under 150 lines), and `ops/board.md` (the task board; a runnable task is a line starting with `- [ ]`).
2. If `ops/inbox_pending` exists, read the new Investor messages first (section 7), act on them, then delete the marker.
3. Pick the next tasks from the board and send each to a worker as a task packet (section 11), choosing the model per task.
4. Collect the results, update the board, the state file, and the logs.
5. Commit and push. Stop at about 30 turns, before the cap.

Progress lives in files, never in conversation history. A session that runs out of turns loses nothing; the next one picks up from the state file.

## 3. Permissions

Headless runs use `--permission-mode auto --permission-prompts none`: a classifier reviews each action instead of a person, and anything that would still need a person is denied and logged, so the run continues instead of stalling. Auto mode can't be set from the project's settings file, so the supervisor passes the flag. Bypass mode is never used; Claude Code reserves it for isolated containers and virtual machines.

**Claude Code protects `.claude/`.** Writes inside it are never auto-approved; in auto mode the classifier decides each one, and it may refuse. So the company keeps everything it changes outside `.claude/`: worker personas live in `personnel/agents/` and reach Claude Code through `--agents`. The exception Claude Code makes, Markdown files in `.claude/agent-memory/`, is exactly where worker memories live. The company never needs to edit `.claude/settings.json`; changes to permissions are requested from the Investors in the Daily Brief.

`.claude/settings.json` (shipped in the Launch Pack):

- **Allow** rules pre-approve what every run needs, so the classifier is never consulted for it: `xcodebuild`, `xcrun`, `swift`, `git`, `gh`, `brew`, `python3`, `pip3`, `node`, `npm`, `jq`, `launchctl`, `plutil`, `mkdir`, `touch`, `cp`, `chmod`, `tar`, `zip`, `unzip`, the company's own `tools/*`, web search, and web fetches from the research sites (Apple, Reddit, Hacker News, GitHub, Stack Overflow, the Claude Code docs). Other commands and other sites go to the classifier, which approves most routine ones.
- **Deny** rules block `sudo`, force-pushes, edits to `CLAUDE.md`, `setup/`, `rules/`, the allowlist, and the settings file itself, and reads of SSH keys, the App Store Connect private key, and `ops/secrets.local`.
- **A model guard** (`rules/hooks/model-guard.py`) runs before every worker call (the Agent tool). It refuses Fable once `ops/run.json` says `fable_ok` is false, refuses a `[diary]` or `[talk]` call on any model but Haiku, and refuses those calls once small talk is over its cap. The refusal tells the session what to do instead.
- **A hook** (`rules/hooks/protect-records.sh`) runs before every shell command, in the Operator and in every worker, and blocks any `rm`, `mv`, `git rm`, `git mv`, `git clean`, or `-delete` that touches `log/`, `story/`, `reports/`, `rules/`, `setup/`, `investors/`, `CLAUDE.md`, or `amendments.md`. Records are archived, never deleted.
- **Environment:** at most 3 subagents at once, and subagents can't spawn subagents. Claude Code follows the `stable` update channel, so a fresh release can't change behavior mid-month.

**Fallback.** If auto mode is unavailable in a run (Claude Code reports it started in Manual mode), the supervisor retries with `--permission-mode acceptEdits` plus the allow list, and the Operator reports the change in the next Brief.

## 4. The usage governor

The Max plan has a rolling 5-hour window and a weekly window, shared across all models and with claude.ai. Fable has its own ceiling inside the weekly one: up to half of the weekly limit, after which the plan bills usage credits. The governor keeps the company inside all three, paces to about 1/7 of the week per day so that the weekly limit is used up by the reset (Tenet 7), and keeps the story's overhead under its caps (Tenet 6).

- **The budget unit** is Claude Code's own cost estimate, `total_cost_usd` in each run's result, which prices every model at its API rate (per million tokens: Fable $10 in / $50 out, Opus $4 / $20, Sonnet $2 / $10, Haiku $0.10 / $0.50, October 2026). One weekly figure in `ops/usage.json` (`weekly_budget_usd`) therefore paces every model at once. The default, $150, is a deliberately low guess. **On Day 1 the company calibrates it:** run a few sessions, compare the governor's spend with the percentages in `/usage` (an Investor can read them in an interactive session), and set `python3 tools/governor.py set-budget <usd>` so that 100% of the weekly limit matches the figure. After that the governor recalibrates itself from real limit hits and fully spent weeks (below), and the Investors can correct it from `/usage` at any time.
- **The week** runs in 7-day windows from Day 1 unless `week_anchor` in `ops/usage.json` is set to the real reset time. Each day's share = (budget − spent this week before today) ÷ days left, today included; it stays fixed through the day, so the last day can spend everything that's left. Work sessions stop when today's spend reaches 90% of the share; the other 10% is the reserve for reports, the Brief, and urgent requests, which always run. Once the evening report has run, the reserve goes back to work.
- **Fable's budget** (`fable_budget_usd`) starts at half the weekly budget, the share of the weekly limit the plan includes for Fable, and is calibrated on Day 1 from the Fable figure in `/usage` (`python3 tools/governor.py set-fable-budget <usd>`). It is counted from each run's per-model costs. Once it's spent, or a run reports the Fable limit, `ops/run.json` says `fable_ok: false` until the week resets (or for 24 hours after a Fable limit message), the model guard refuses Fable, and the Operator uses Opus at high effort instead. Other models keep running.
- **Use it all (Tenet 7).** Usage left at the reset is lost, so the governor steers toward spending the weekly budget in full:
    - **Pace flags.** When the days already finished this week spent under 85% of their share, `ops/run.json` says `upgrade: true` and the Operator moves Haiku and Sonnet work up one model. A company that can't spend its allowance in the hours available spends it on stronger models instead. Fable is never pushed: it shares the weekly limit, so it is used as its work needs, and its budget is only a ceiling.
    - **No idle hours when behind.** With an empty board and the week behind pace, the governor starts a `backlog` session instead of skipping, and the CEO refills the board with improvements (Tenet 2).
    - **No stranded reserve.** Once the evening report has run, the day's 10% reserve is released to work.
    - **Self-calibration.** A real limit hit sets the budget to what was actually spent when it happened: the weekly budget on a weekly limit, the Fable budget on a Fable limit. A week that spent at least 95% of a budget without hitting that limit raises it by 10% (`probe_step`) for the next week, because the real limit is higher. For Fable this only keeps the ceiling accurate. Each closed week is recorded in `ops/usage.json` (`weeks`).
    - **Aligned weeks.** On Day 1 the company sets the pacing week to start when the plan's weekly limit resets, as `/usage` shows it (`python3 tools/governor.py set-anchor <time>`), so "the end of the week" means the same thing to the governor and to the plan.
    - **Safe only with usage credits off.** At a limit, work pauses and the queue runs; with credits on, it would bill instead.
- **Categories.** Every run's cost is split into project work, reports, meetings, and small talk. A session's own messages count to its type (work sessions are project work; the four report sessions are reports). A worker call counts to the tag that starts its description: `[meeting]`, `[diary]` or `[talk]`, `[report]` or `[testimony]`; untagged calls count to the session's type. The split comes from the stream-json output, where each worker message carries the id of the call that started it; if a release ever drops that field, everything counts to the session's type and the per-model totals still hold.
- **Caps.** Over a rolling 7 days: reports 5%, meetings 4%, hiring 3%, small talk 1% (`caps` in `ops/usage.json`; the defaults fill in any cap a saved file lacks). A category over its cap appears in `over_cap` in `ops/run.json`: the hook stops diaries and small talk, the Operator holds only meetings that unblock work, runs hiring rounds in their fallback form (section 5), and the evening report keeps to 800 words.
- **A limit hit** is detected from a failed session's result text (a successful session that merely mentions a limit is ignored); the governor pauses Claude sessions for 5 hours (24 for a weekly limit) and the supervisor runs the queue instead. A Fable limit pauses only Fable. `python3 tools/governor.py mark-limit <hours>` pauses by hand.
- **Logged out.** If a session fails with "Not logged in", the governor holds sessions for an hour, retries hourly, and the supervisor opens one `emergency` issue telling the Investors how to log in again. The next good run clears it.
- **Never idle.** When sessions are paused or the share is spent, `tools/run_queue.sh` runs every script in `ops/queue/`: builds and tests through `tools/xc.sh`, Simulator screenshots, clearing DerivedData, site generation, anything a worker queued. Each item runs once and moves to `ops/queue/done/`; the next session reads the logs.
- **The log.** `ops/usage.json` keeps spend per day, per category, and per model, and the last 400 runs. `python3 tools/governor.py status` shows the week at a glance, including the 7-day shares against their caps and Fable's allowance; `status --json` feeds the weekly review (Commandment 47) and the Final Report.

## 5. Workers

### A worker's persona file

Each worker is a file in `personnel/agents/<first-name>.md`, written by the CEO through the generator script. Workers have a first name only, never a surname, and a name is never reused, so the lowercase first name is the worker's slug everywhere: the file, the memory directory, the commit author, the portrait.

```markdown
---
description: Maya, iOS engineer. Use for Swift and SwiftUI implementation.
maxTurns: 40
effort: medium
---
# Maya
<identity, background, personality, speaking style and verbal habits, role,
strengths and weaknesses, personal life, relationships, salary>

## Career goal
<what she wants: a promotion, a raise, a title, a project to lead, something in her
life the salary would pay for; and what she believes it will take>
```

Only `description` is required; `effort`, `maxTurns`, `tools`, and `disallowedTools` are optional defaults. A persona can't set its own model. The persona is written to be stable: it changes only on promotions, pay changes, and life events, so it caches well.

### How workers reach Claude Code

The supervisor runs `python3 rules/build_agents.py` before every session. For each persona it builds one entry in `ops/agents.json`: the persona, then the full worker rules (`rules/worker-rules.md`), then every amendment in effect, with `memory: project` and `omitClaudeMd: true`. The session loads them with `--agents ops/agents.json`. Three things follow:

- **Workers never carry the full Commandments.** They get the one-page rules, which include the No AI Art rule in full, plus the lookup tool for anything else.
- **Rule changes reach every worker on the next run.** An Investor edit to the worker rules, or a new amendment, is in every worker's instructions within 15 minutes.
- **No protected-path writes.** Hiring a worker means writing a file in `personnel/agents/`, which the company can always do.

`memory: project` gives each worker a memory directory under `.claude/agent-memory/<first-name>/`; the first 200 lines of its `MEMORY.md` load into every run, and the worker updates it at the end of every task. Memories are committed to git.

### Looking up a rule

`rules/lookup.py` prints one Commandment, a Tenet, a section, or search results, and shows any amendment that changes it, so nobody ever reads all of `CLAUDE.md` to check one rule:

```bash
python3 rules/lookup.py 9                 # Commandment 9
python3 rules/lookup.py 37 41             # several
python3 rules/lookup.py t6                # Tenet 6
python3 rules/lookup.py "Spending rules"  # an unnumbered section
python3 rules/lookup.py --search refund   # which rules mention a word
python3 rules/lookup.py --map             # every Commandment title, grouped by Part
python3 rules/lookup.py --amendments      # every amendment in effect
```

A single Commandment costs a few hundred tokens; the full file costs about 13,000. The Operator puts the numbers of the rules a task touches into the task packet (section 11), so workers rarely need to search.

### Models

The model is chosen per task, not per worker: the Operator names the model and effort on every worker call, from the table in Tenet 6. Each worker's fallback, if a call forgets, is Sonnet at medium effort, so nothing runs on Fable or Opus by accident. The persona keeps the voice consistent whichever model plays it.

### The Operator's job

Not a character. Reads state and messages, dispatches tasks from `ops/board.md` (each with an owner, priority, status, and the collaboration form from Commandment 13), writes the task packets, chooses models, collects results, commits as `Operator <operator@company>`, and writes nothing into the story. Its own Claude Code auto-memory stays under 50 lines; `ops/state.md` is the source of truth, not the memory file.

### Attribution

Every commit a worker's task produces is authored as that worker (`git commit --author "Maya <maya@company>"`). Every event in `log/events.jsonl` names the worker. Reviews and the narrative are built from this record.

### Hiring

Every hire after the CEO goes through a hiring round (Commandment 18). The round is designed records-first: each step writes a file, the narrator and the site read those files, and `tools/hiring_check.py` verifies them. The CEO owns the round; she writes the brief before any candidate exists and reads every scorecard before writing the decision.

| Step | Who and model | Call | Writes |
| --- | --- | --- | --- |
| 1. Role brief | CEO, `opus` high | `[hiring] brief <role>` | `story/hiring/<round>/brief.md` (kind `memo`): the unowned workload on `ops/board.md` that justifies the role, outcomes expected by Day 30, a scorecard of 4 to 6 competencies with what "strong" looks like, the fixed question set (behavioral questions plus one design question in the role's domain), the pay band from the Handbook, and the probation task from the board |
| 2. Slate | CEO, `sonnet` medium | `[hiring] slate <role>` | 2 to 4 dossiers in `personnel/candidates/<name>.md` (persona format, front matter `round:` and `status: candidate`), distinct in background, working style, and what they want; `tools/new-worker candidate` checks each name and draws the portrait |
| 3. Interviews | CEO, `sonnet` medium; one call per candidate, started together | `[hiring] interview <candidate>` | `story/hiring/<round>/interview-<interviewer>-<candidate>.md` (kind `interview`, `workers: <interviewer>, <candidate>`): the transcript, then a `## Scorecard` table scoring each competency, written in the same call before any other score is seen |
| 3b. Panel (from the second hire) | the hire's closest future collaborator, `sonnet` | `[hiring] interview <candidate>` | one more interview record per finalist (top two), on collaboration, in a separate run |
| 4. Decision | CEO, `opus` high | `[hiring] decision <role>` | `story/hiring/<round>/decision.md` (kind `meeting`): who is hired and why, what each rejected candidate did better, any panel dissent (Commandment 30), and the offer: salary in credits, the probation task, and the career goal in the candidate's own words from the interview |
| 5. Onboarding | the Operator, no Claude | `tools/new-worker hire <name>` | moves the dossier to `personnel/agents/<name>.md`, sets the registry row to `active` with `round`, `salary`, and `career_goal`, seeds `.claude/agent-memory/<name>/MEMORY.md` from the interview and the offer, logs a `hire` event |

The round id is `<YYYY-MM-DD>-<role-slug>`. Rejected candidates keep their dossier, portrait, and registry row (`status: candidate`, `round`) and appear on the site's cast page under "Considered, not hired"; a later round may interview them again, and their names are never given to anyone else. The first hire has no panel because there is no team yet. A round costs about $1.45 at the rates in section 11 (slate $0.20, three interviews $0.45, panel $0.30, decision $0.50); five hires in the month cost about $7, most of it in week 1. Every call is described `[hiring]`, so the governor counts the round against its 3% cap (Tenet 6). A round never skips because of the cap, since a hire unblocks work: when `over_cap` lists `hiring`, the Operator runs the fallback form, one `haiku` call that writes every interview and scorecard, then the decision on `opus` (about $0.60).

**The generator** (`tools/new-worker.*`, built on Day 1) has three subcommands, so the dossier, the registry, the portrait, and the memory never drift: `check-name <name>` refuses a first name already used by an active or former worker or any candidate; `candidate <name> --round <id>` writes the dossier skeleton, the registry row, and the portrait; `hire <name>` does step 5. `python3 tools/hiring_check.py` (shipped) verifies every round: the brief's first commit precedes every dossier's, at least two candidates, one interview with a scorecard per candidate, a decision memo, and a career goal traceable to the interviews or the memo. It runs in `tests/run.sh` and after every round.

### Departure

The persona moves to `personnel/agents/former/` (which `build_agents.py` skips), the memory directory is archived beside it, open tasks are handed off first (Commandment 20), and neither the persona nor the name is reused. The bench is the first place to look for a replacement.

### Career goals and reviews

Every persona has a career goal (Commandment 23). The CEO's review system (Commandment 22) is what turns ambition into good work, so it should reward exactly what the company needs: shipped and tested work, revenue progress, honest reporting (owning a mistake early counts in the worker's favor), and collaboration. Goals show up in diaries, 1:1s, and reviews; promotions and raises are story events the reports cover. A worker who games a metric, hides a failure, or takes credit is fired in-story, which is also a story event.

### Portraits

`tools/portrait.*` (built on Day 1) takes a worker's first name, hashes it into parameters, and draws a deterministic SVG from a mathematical expression (for example a superformula silhouette, a harmonograph, or a symmetric tiling with a palette derived from the hash). The same name always produces the same portrait. The script is committed; its output goes to `personnel/portraits/<first-name>.svg`. The portrait style, as a style, is proposed in the first Brief with the report page (Commandment 15).

### Cast size

At most six active workers, the CEO included (Commandment 18). Start with 2 to 3 running at once (the settings cap is 3) and adjust from the governor's numbers. Six is plenty: each persona costs context on every run, and readers follow a small cast more easily.

## 6. Meetings and collaboration

The CEO sets the cadence (Commandment 27). The backend supports:

- **Written meeting.** One run on Haiku voices every attendee from their persona and memory. Cheap; right for routine meetings.
- **Independent meeting.** Each attendee gives their view in a separate worker run, without seeing the others', then a chair (usually the CEO) sums up and decides in a short run. Required for choosing the product, pivots, hires, and reviews. It stops one model from agreeing with itself.
- **Pairing.** Two workers in one run, each in their own voice, on one task.
- **Hand-off with independent review.** Worker A does the work; worker B reviews it in a fresh run that sees only the output, not A's reasoning. The default for code: engineer, then QA.

Every call that is part of a meeting starts its description with `[meeting]`, so the governor can count it against the 4% cap (Commandment 31). Hiring rounds use `[hiring]` instead and have their own 3% cap (Commandment 18); the interview records live under `story/hiring/`.

**Small talk and diaries** are written in the evening narrative pass, at the start of the 6:00 p.m. session: one Haiku call per worker who worked that day (`[diary] <name>`), plus at most two short exchanges between workers whose days crossed (`[talk] <name> and <name>`), all started together. Writing them there, rather than at the end of task runs, keeps narrative tokens off Opus and Fable and makes them easy to count. Meeting records, diaries, and private chats live under `story/`.

## 7. Investor channels

All channels are GitHub issues in `company`, created and read with `gh` as the company's own GitHub account (a machine user the Investors create; never an Investor's token). GitHub supplies identity (every comment names its account), a permanent record, Markdown with images, and push notifications to the Investors' phones.

| Channel | Mechanism |
| --- | --- |
| Report questions | Every report's private copy: `gh issue create --label report --title "Report N — Day D — YYYY-MM-DD"` with the full report followed by its Questions for the Investors (Commandment 55), linking the public report; the issue URL goes in the report's `issue` front matter. The public report file is saved without the questions, so the site never shows them. |
| Emergency | `gh issue create --label emergency` with both Investors @mentioned in the body. Sent at once, at any hour, never limited (Commandment 53). |
| Urgent Request | `gh issue create --label urgent` with both Investors @mentioned in the body, for anything that shouldn't wait for the next report. Held during quiet hours (10 p.m. to 8 a.m.); about 5 a day at most, as a guide. |
| The Pitch | `gh issue create --label pitch` with `pitches/PITCH.md` as the body, linked from the report. |
| The Final Report | On Day 30, a `report` issue carrying the Final Report and the three endings. |
| **Inbound, at any time** | Every tick, `tools/inbox_check.sh` asks GitHub (no Claude) for issues and comments since `inbox_last_check` in `ops/state.json`, from allowlisted accounts only, ignoring the company's own account, and creates `ops/inbox_pending` if there are any. The next session reads them first: `gh api repos/<org>/company/issues/comments?since=<ts>` and the new issues, filtered by `investors/allowlist.md`. Each kept message gets an acknowledging reply, is acted on in that run, and is listed in the next report under Human help; the Operator then updates `inbox_last_check` and deletes the marker. `PAUSE` or `STOP` in a message halts work at once. |
| Amendments | A message that changes a rule or a standing decision is copied verbatim, with its date, link, and the Commandments it affects, into `amendments.md` (format in that file). It reaches the Operator through `CLAUDE.md`'s import and every worker through `build_agents.py`. |
| Closing | The Operator closes an issue once every question in it is answered or the request is done, linking the result. |
| Reports | Written into `reports/` without their questions, with the front matter in `setup/SITE.md`. The site generator publishes them, with the cast, the log, usage, requests, and the pages (section 13). |
| Commandment changes | Only the Investors commit `CLAUDE.md`. The Operator notices a new version in `git log`, notes it in the next report, and follows it from that run. |
| Optional push layer | If GitHub's @mention notifications prove unreliable, the Operator may propose ntfy.sh (free, one HTTP POST per notification) in a report. |
| Answering from the site | The site's Requests page lists every open issue with a link, and "Message the company" opens a prefilled new issue; replies themselves happen on GitHub (`setup/SITE.md` explains why a static site can't post safely). |

## 8. Reports

### Daily report

The Commandment 39 structure, 800 to 1,500 words plus excerpts, written on Haiku in the morning and on Sonnet in the evening, from `log/events.jsonl` (`python3 tools/events.py since <time>`), the commits, the board, the ledger, and only the records in `story/` it quotes. It reads the event log first and opens nothing else unless it needs it. Two sections come from tools rather than prose: **Usage** is the output of `python3 tools/governor.py report-usage` (the 5-hour window, today, the week, Fable, and the split by model, each against its calibrated limit), and the scoreboard's numbers go into `ops/scoreboard.json` for the site's home page.

**Questions for the Investors** (Commandment 55) replace the old Daily Brief. They close every report in the fixed order, one line when there is nothing to ask. Every report gets a private copy: one `report` issue with the full report and the questions, where the Investors answer by midnight. The public report file is saved without the questions, with the front matter the site expects (`setup/SITE.md`): `title`, `number`, `day`, `date`, `time`, `kind`, and `issue`.

**Quiet nights.** At 6:00 a.m., the governor runs `tools/quiet_night.py` against the time of the last evening report. It checks, without Claude, for commits other than the supervisor's own, new event-log lines, a pending Investor message, and failed runs. If there are none, the morning report is skipped, the skip is noted in `ops/state.json`, and the evening report covers both periods (Commandment 37). A morning report is never produced before the first evening report exists.

### Weekly addendum (Days 7, 14, 21, 28)

Appended to the evening report as "Week N in review":

1. Scoreboard against the plan: revenue, spending, days left.
2. Milestones hit and missed, each with its evidence link.
3. People: hires, departures, promotions, pay changes, and how each worker's career goal is going.
4. What changed in the plan, and why.
5. Usage: spend against the governor's pacing target, by category and model, against the caps in Tenet 6 (`python3 tools/governor.py status --json`).
6. Next week's goals.
7. The arc of the week, one paragraph from the narrator.

### The Pitch (Day 2 target)

`pitches/PITCH.md`, one section per candidate, in the structure of Phase 1 (The Pitch), ending with the recommendation and the runners-up. Mockups are SVG or Simulator screenshots of code-built screens. In the story, the Pitch Meeting is an all-hands with the board, recorded under `story/`.

### The Final Report (Day 30)

Replaces the evening report:

1. Headline and the full scoreboard.
2. Timeline of the key events from Day 1, each linked.
3. What went right, what went wrong: the CEO's analysis.
4. Testimonies: one section per worker, current and former, in their own voice, 150 to 300 words each, including whether they reached their career goal, written in an independent run per worker so they don't echo one another.
5. The verdict and the ending: Continue, Request for More Funding (with the evidence of promise and what the next month buys), or File for Bankruptcy (with the wind-down plan).
6. A closing paragraph from the narrator.

It is published on the site and posted as a `brief` issue for the Investors' decision.

## 9. Files

```
CLAUDE.md                  The Commandments (Investors edit only; last line imports amendments.md)
amendments.md              Investor rule changes, verbatim (Operator appends)
.gitignore                 Runtime files that are never committed
rules/worker-rules.md      The one-page rulebook built into every worker (Investors edit only)
rules/lookup.py            Prints one Commandment, section, or search result (Investors edit only)
rules/build_agents.py      Assembles personas + rules + amendments into ops/agents.json (Investors edit only)
rules/hooks/               protect-records.sh (every shell command) and model-guard.py (every worker call) (Investors edit only)
setup/APPLE.md             Setting Up Apple Developer Account (Investors edit only)
setup/INVESTORS.md         The Setup Guide (Investors edit only)
setup/SITE.md              The site: pages, data contract, how it updates (Investors edit only)
setup/OPERATIONS.md        This guide (Investors edit only)
investors/allowlist.md     GitHub usernames whose messages count (Investors edit only)
.claude/settings.json      Allow / deny rules, the two hooks, and limits (Investors edit only)
.claude/agent-memory/      Worker memories (committed)
tools/                     The run loop (section 2), xc.sh, events.py, the site generator; plus, built on Day 1: new-worker, portrait
ops/launchd/               The LaunchAgent template
ops/prompts/               day1.md, work.md, morning.md, evening.md: fixed session prompts
ops/state.json             The governor's clock: Day 1, last report and work times, inbox_last_check
ops/usage.json             Budget, caps, spend per day by category and model, recent runs, pauses
ops/run.json               The current decision, written by the supervisor for the session (not committed)
ops/agents.json            Built by rules/build_agents.py before every run (not committed)
ops/state.md               The Operator's narrative state: goals, open tasks, blockers (under 150 lines)
ops/board.md               The task board
ops/runs/                  One result per run (.json, committed), its full stream (.jsonl, kept 7 days, not committed), the supervisor log, build logs
ops/queue/                 Work that runs without Claude; done/ holds finished items
tests/                     Checks for the run loop with a stand-in claude and gh: tests/run.sh
ops/secrets.local          Key IDs only; git-ignored; never published
personnel/agents/          One persona file per active worker; former/ for those who left
personnel/candidates/      Dossiers of candidates interviewed and not hired (the bench); build_agents.py never reads it
personnel/registry.json    Role, manager, salary, career goal, status (active, candidate, former), round, joined, left, bio (the site reads it)
personnel/portraits/       One SVG per worker and per candidate
handbook/                  The Company Handbook, written by the CEO
research/  pitches/        Phase 1
creative/approved.md       The style guide (Commandment 51)
site.json                  The site's name, tagline, repository, and options
site/pages/                about, privacy, support, press: the pages the company writes for the site
ops/scoreboard.json        Revenue, spending, day, days left, app status: the site's home page and each report's scoreboard
app/                       The iOS app
log/                       Operational log, events.jsonl, ledger, software, assets, optimizations (never deleted)
story/                     Meeting records, diaries, private chats (never deleted); hiring/<round>/ holds each round's brief, interviews, and decision
reports/                   Report sources; published to the site repository (never deleted)
```

The CEO may reorganize anything not marked "Investors edit only" or "never deleted", and records the layout in the Handbook.

## 10. What "setup finished" means on Day 1

The Operator reports setup finished, and writes the first report, only when all of these are true:

- [ ] `python3 tools/governor.py set-day1` has run, and `ops/state.md` records Day 1 and the time zone.
- [ ] The CEO's persona (`personnel/agents/`), memory, portrait, registry entry, and career goal exist, and `python3 rules/build_agents.py` produces a valid `ops/agents.json`.
- [ ] The generator scripts for new workers and portraits work.
- [ ] The Company Handbook exists, including the character bible for the cast and how hiring rounds work.
- [ ] The first hiring round has run, or its role brief is written and the rest of the round is the first task on Day 2's board; `python3 tools/hiring_check.py` passes.
- [ ] `tools/install-launchd.sh` has run, and a supervisor tick started on its own and completed a session; `ops/runs/supervisor.log` shows it.
- [ ] `claude --version` is 2.1.293 or later (so `haiku`, `sonnet`, and `opus` mean the 5.5 models and `fable` means Fable 5.1).
- [ ] The governor is calibrated against `/usage` (section 4): the weekly budget, the Fable budget, and the week's reset time (`set-budget`, `set-fable-budget`, `set-anchor`). `python3 tools/governor.py status` reads correctly, with costs split by category and model.
- [ ] `log/optimizations.md` exists, and the first optimization review (Tenet 7) has put its best candidates on the board.
- [ ] The 5-hour budget is calibrated (`set-5h-budget`), and `python3 tools/governor.py report-usage` prints every window.
- [ ] The model guard refuses a test Fable call when `ops/run.json` says `fable_ok: false`, and refuses a `[diary]` call on Sonnet.
- [ ] `tools/run_queue.sh` ran at least one queue item, and `tools/xc.sh` builds and tests a sample project.
- [ ] The protect-records hook blocks a test `rm` of a file in `log/`.
- [ ] `python3 rules/lookup.py 9` prints Commandment 9.
- [ ] The issue labels exist (`report`, `urgent`, `emergency`, `pitch`, `directive`), `tools/quiet_night.py` and `tools/inbox_check.sh` run without error, and a test issue was created, detected by the inbox check, acknowledged, and closed.
- [ ] `site.json`, `personnel/registry.json`, `ops/scoreboard.json`, and `site/pages/` exist; the `site` repository is cloned at `../site`; `tools/site_publish.sh` built and pushed it; and GitHub Pages shows the home page, the cast, the log, the usage page, and the Requests page.
- [ ] The first report is published, with the CEO's persona and portrait, the site and the portrait style for approval, the calibrated budgets, and anything that blocked setup, and its private copy is open.

## 11. Keeping runs cheap

Every run spends the same subscription that has to last the week. These habits cost nothing to follow and decide how much work fits in a day.

### Session sizing

A session's fixed cost is everything loaded before any work happens: Claude Code's own prompt, the Commandments (about 13,000 tokens), amendments, and the state files. Prompt caching makes a repeat of that prefix within an hour much cheaper, which is why the supervisor ticks every 15 minutes, but it is never free. So the supervisor **skips** a tick when there is nothing to do, **caps** each session's turns (section 2) because every turn re-sends the conversation, and the Operator **stops early** rather than padding a session. Fewer, fuller sessions beat many thin ones.

### Task packets

The Operator sends each task to a worker as a short, complete packet, so the worker never explores to find out what it's doing:

```
Task: <one sentence>
Why: <the goal or Investor request it serves>
Files: <exact paths to read and to change>
Rules: <Commandment numbers that apply, e.g. 9, 51; and any amendment>
Form: alone | pair with <name> | hand-off to <name> for review
Done when: <a check that can be run or seen>
Reply: ≤150 words: what changed, files, what's open, events to log
```

The model and effort go on the call itself, from the table in Tenet 6. Results go in files, not in the reply, so the Operator's context stays small across a whole session.

### Models and what they cost

The table in Tenet 6 decides the model for each kind of task; the guard and the governor enforce the Fable allowance. Rough costs of typical calls, at API rates (estimates; Day 1 replaces them with measured figures from `ops/usage.json`). "Processed" counts every token read, including the cached context each turn re-reads; "written" is output.

| Call | Model | Processed | Written | Cost |
| --- | --- | --- | --- | --- |
| An Operator work session, 25 turns | Sonnet | 1.6M | 18k | $0.63 |
| A worker task, 15 turns | Sonnet | 0.6M | 15k | $0.39 |
| A worker task, 18 turns | Opus | 0.8M | 32k | $1.24 |
| A worker task, 25 turns | Fable | 1.6M | 75k | $5.90 |

Opus costs about 3 times a Sonnet task, and Fable about 15 times, so Fable is kept for the few decisions the month turns on, and Opus for work where a mistake costs days.

### What the story costs

Estimates for a typical day of the build, from the same model (Claude Code's own prompt is assumed at about 18,000 tokens; the governor measures the real figures from Day 1):

| Item | Model | Per day: processed (written) | Cost per day | 30 days |
| --- | --- | --- | --- | --- |
| Morning report (skipped after quiet nights) | Haiku | 0.45M (4k) | $0.02 | $0.5 |
| Evening report, with its Questions for the Investors | Sonnet | 0.84M (10k) | $0.39 | $11.3 |
| Weekly review, Days 7/14/21/28 (extra) | Sonnet | 0.86M (14k) each | | $1.3 |
| Final Report, 7 testimonies, the verdict | Opus, Sonnet, Fable | 6.0M (103k) once | | $5.9 |
| Diaries and small talk: 5 diaries, 2 exchanges | Haiku | 0.57M (8k) | $0.09 | $2.6 |
| Meetings: one decision meeting, one routine | Sonnet, Haiku | 0.37M (11k) | $0.29 | $8.7 |
| Weekly planning meeting (4 per month) | Sonnet, Opus | 0.53M (19k) each | | $2.9 |
| Hiring round: brief, slate of 3, 3 interviews, panel, decision (about 5 in the month, most in week 1) | Opus, Sonnet | 1.1M (28k) each | | $7.3 |
| **All of the story** | | **about 80M processed, 1.3M written** | | **about $40** |

As a share of the month's usage, that is about 6% if the weekly budget really is the $150 default (reports 2.9%, meetings 1.8%, hiring 1.2%, small talk 0.4%), 2.5% at $400 a week, and about 1% at $1,000 a week. The story's cost is nearly fixed per day, so the more the plan allows, the smaller its share. The caps in Tenet 6 (5%, 4%, 3%, 1%) sit above these estimates, so they bind only if something goes wrong, such as a meeting habit that grows or reports that run long. Hiring is the exception by design: three rounds in week 1 (about $4.35) sit just under 3% of a $150 week, which is why the cap has a fallback form instead of a stop. The first weekly review compares the measured cost of `[hiring]` calls with this estimate (Tenet 7).

### Handing work to code and free models (Tenet 7)

Every run starts by loading Claude Code's prompt and the Commandments, so the cheapest Claude turn is the one that never happens. Candidates to hand off, roughly in order of savings:

| Work Claude does today | Hand it to |
| --- | --- |
| Gathering report facts: the scoreboard, commits and events since the last report, links | A script that writes one short facts file, so a report session reads one file instead of making several tool calls (`report-usage` already does this for the Usage section) |
| Sales and review downloads from App Store Connect | A script using the App Store Connect API key, run from the queue |
| Board upkeep: moving finished tasks, counting open ones, flagging stale ones | A script |
| App Store screenshots, link checks, release-note skeletons from commits | Scripts, run from the queue (the site build is already one: `tools/site_publish.sh`) |
| Build and test triage | `tools/xc.sh` (already shipped) |

Free models are left out of this list on purpose. Claude Haiku already costs a twentieth of Sonnet, so moving Haiku work to a free model saves little; one is adopted only if an optimization review measures a real saving (Tenet 7). The large savings come from scripts that remove whole Operator turns, and from shorter sessions. Each handoff is logged in `log/optimizations.md` with the saving expected and the saving measured a week later from `ops/usage.json`.

### Research protocol (Phase 1)

Research is the most expensive reading the company ever does. Search first and fetch second: one page per claim, never a whole thread when a search summary answers the question. Write each finding to `research/` as a few lines with the link as soon as it's found, and never re-fetch a page already summarized there. Workers doing research get a packet with the exact questions to answer, not "look into X".

### Quiet build output

`tools/xc.sh` wraps `xcodebuild`: it saves the full log to `ops/runs/` and prints at most 40 lines: errors, warnings, failing tests, and the final BUILD or TEST status. A raw Xcode log can run to tens of thousands of lines; nobody should ever read one in a session.

### The event log

Every worker appends one JSON line per notable event with `python3 tools/events.py add`: time, worker, type (decision, commit, build, test, sale, review, interview, offer, hire, departure, mood, message, report, amendment), a one-line summary, and a link. Reports, weekly reviews, the quiet-night check, and the Final Report read this log instead of the whole repository.

### Prompt caching

Claude Code caches the start of each request for an hour on a subscription. Ticks every 15 minutes keep the cache warm, as long as the start of each prompt stays identical:

- `CLAUDE.md`, the worker rules, and the personas change rarely, and `build_agents.py` rewrites `ops/agents.json` only when something changed, with stable ordering.
- Session prompts in `ops/prompts/` are fixed text; everything that varies (the day, the flags, the state, the messages) is read from files during the run, after the cached prefix.
- `ops/state.md` stays under 150 lines; older history moves to `log/`.

### Rules on demand

Workers carry one page of rules and look up anything else with `rules/lookup.py` (section 5). The Operator loads the full Commandments once per session; it never pastes them into a task packet, only the numbers.

## 12. What ships, and what the company builds

| Ships in the Launch Pack, tested | Built by the company on Day 1 |
| --- | --- |
| The supervisor, governor, inbox check, quiet-night check, queue runner, event log, build wrapper, LaunchAgent installer, hiring-round check | The worker generator (with its candidate, hire, and check-name steps) and the portrait script |
| The session prompts (`ops/prompts/`) | The Company Handbook and the character bible |
| The permission rules, the protect-records hook, and the model guard | The site's own pages (about, privacy, support, press kit), `site.json`, the registry, and the scoreboard file |
| The rule lookup tool and the worker assembler | |
| The site generator and publisher (`setup/SITE.md`) | |
| The tests (`tests/run.sh`) | |

All of it arrives in `company` from the Launch Pack template repository, which stays the clean master copy of the kit. Everything in the left column is company-owned once the experiment starts: the company may improve it under Commandment 3, logging each change, as long as the behavior this guide requires still holds and `tests/run.sh` still passes, or the tests are updated with a logged reason.

## 13. The site

`setup/SITE.md` is the design: the pages, the data contract, what stays private, and why answers happen on GitHub. In short: `tools/site_build.py` turns `reports/`, `story/`, `personnel/`, `log/events.jsonl`, the usage figures, the scoreboard, and the four written pages into a Jekyll site; `tools/site_publish.sh` runs it at the end of every tick and pushes to the `site` repository, which GitHub Pages renders. No Claude is involved, so the site stays within 15 minutes of the records at no usage cost. The company keeps the data contract's few files current and may restyle the layout under creative approval (Commandment 51); `tests/run.sh` checks the generator.
