# Operations Guide (for the company)

Who reads this: the Operator on Day 1 and whenever it changes the system, and the CEO when writing the Company Handbook. The outcomes in this guide are required by the Commandments. The mechanisms are the shipped, tested design; the company may change them under Commandment 3, as long as the outcomes hold, every change is logged, and nothing weakens the protections.

## 1. How it fits together

Everything runs on the Mac mini, in the company's macOS account, from a timer:

- **launchd** starts the **supervisor** every 15 minutes.
- The **supervisor** (`tools/supervisor.sh`) is a plain script that never calls a Claude model itself; reading the plan's usage meter is a local command (section 4). It syncs the repository, checks for Investor messages, asks the **governor** what to do, and either starts one headless Claude Code session of the right type, runs the no-Claude queue, or does nothing.
- The **Operator** is that session's main conversation. It is not a character and never appears in the story. It reads the state and new Investor messages, hands tasks to workers, and commits the results.
- **Workers** are Claude Code subagents, each with a persona, a memory, and a portrait. Only the Operator starts them. Workers never start other agents.
- **GitHub** holds the private `company` repository (code, logs, records, and the Investor channels as issues) and the public `site` repository (the reports, served by GitHub Pages). The company acts on GitHub as its own account, never as an Investor.
- A **watchdog** runs on GitHub's servers, outside the Mac. Every tick the Mac sets a heartbeat, and if the heartbeat stops, the watchdog alerts the Investors (section 2).
- **App Store Connect** receives builds through an API key and reports sales.
- The **Investors** read and write GitHub issues from their phones, test TestFlight builds, and do the human-only steps. After Day 1 they never need to touch the Mac mini.

## 2. The run loop

The loop ships in `tools/`, tested. Day 1 installs it; it is not built from scratch.

| File | What it does |
| --- | --- |
| `tools/supervisor.sh` | One tick: lock, sync, heartbeat and checks, inbox, decision, session or queue, accounting, commit. `--dry-run` prints the decision and the exact command, and never starts Claude |
| `tools/governor.py` | Decides what runs and when, including inbox sessions and overflow on the API credits; reads the plan's usage meter (`meter`); tracks spend against the weekly budget; detects limit hits |
| `tools/inbox.py` | `poll` fetches new Investor messages into `ops/inbox/` every tick, even while paused; `list` shows a session what is waiting; `done <ids>` marks messages handled; `receipt` posts a receipt when no session will reply this tick (section 7) |
| `tools/heartbeat.sh` | Sets the repository variable `HEARTBEAT_AT` at the start of every tick and every 10 minutes during a long session, for the watchdog (below); it never takes more than about 20 seconds |
| `.github/workflows/watchdog.yml`, `rules/watchdog.sh` | The watchdog: runs every 30 minutes on GitHub's servers and opens an emergency when the heartbeat stops (below) |
| `rules/posture.sh`, `rules/file-guard.sh` | The posture check (the firewall, FileVault, SIP, Gatekeeper, and automatic security updates, every tick) and the file guard (puts back any change a session makes to the Investors' files), with no Claude (section 3) |
| `tools/quiet_night.py` | Says whether anything happened since the evening report |
| `tools/run_queue.sh` | Runs the no-Claude queue in `ops/queue/` |
| `tools/events.py` | Appends to and reads the event log |
| `tools/xc.sh` | Quiet `xcodebuild` wrapper |
| `tools/install-launchd.sh` | Installs the LaunchAgent (`ops/launchd/`), no sudo |
| `tools/site_build.py`, `tools/site_publish.sh` | Builds the public site from the records and pushes it (`setup/SITE.md`) |
| `tools/hiring_check.py` | Verifies that every hire's round is complete and in order (section 5) |
| `tools/report_facts.py` | Writes `ops/report_facts.md`, everything a report needs since the last one, before every report session (section 8) |
| `tools/smoke_test.sh` | One tiny real run with the supervisor's exact flags and no tools: checks the Claude Code version, the subscription login, auto mode, the hooks canary, and that `CLAUDE.md` loaded. The Investors run it from Terminal before Day 1; the supervisor runs it before a new Claude Code version's first session |
| `rules/hooks/security-guard.py`, `config-guard.py`, `session-canary.sh` | The guards and the session canary (section 3) |
| `ops/prompts/work.md`, `morning.md`, `evening.md` | The fixed prompt for each session type |

### One tick

`tools/install-launchd.sh` installs a LaunchAgent that runs `tools/supervisor.sh` every 15 minutes, logging to `ops/runs/`. Each tick:

1. **Lock.** If a session is already running, exit. The lock records the supervisor's process ID, so a lock left by a crash or a restart clears at the next tick.
2. **Sync.** `git pull --rebase --autostash`, so Investor edits to `CLAUDE.md`, the rules, or the allowlist take effect on the next tick, and the company's own unpushed commits ride on top. If an unpushed company commit conflicts with GitHub, the pull runs again with GitHub's lines winning each conflicting hunk, and a conflicting uncommitted change is set aside in `git stash`; only if that fails too does the tick go on with the local copy and count as failed (step 9). Sessions never pull, merge, or rebase themselves (the security guard refuses it in the supervisor's sessions): a session commits, and if its push is rejected, the supervisor pushes after the session.
3. **Heartbeat, checks, and inbox.** `tools/heartbeat.sh` sets the heartbeat (below), and `rules/posture.sh` checks the machine's protections (section 3). The supervisor reads the plan's meter with `claude -p "/usage" --output-format stream-json`, a local command that makes no model call and uses no usage, and `python3 tools/governor.py meter` stores it (section 4). `python3 tools/inbox.py poll` fetches new Investor messages into `ops/inbox/` (section 7). A message whose first word is `PAUSE`, `STOP`, or `RESUME` takes effect here, with no Claude session: `PAUSE` or `STOP` writes `ops/paused`, and while it exists no sessions or queued jobs run; `RESUME` clears it. The heartbeat and the inbox poll continue while paused, so `RESUME` is always seen. If the decision below won't run a session that replies, `python3 tools/inbox.py receipt` posts a receipt (section 7).
4. **Decide.** `tools/governor.py decide` returns one of the decisions below, and the tick records what it did and why as one line in `ops/ticks.jsonl`. A gap of more than 45 minutes since the last tick is logged as an `outage` event, so the next report covers it:
    - `evening`, `weekly` (Days 7, 14, 21, 28), or `final` (Day 30): due at 6:00 p.m. and not yet done today; the diaries and conversations for the records, the CEO's report, and its private copy.
    - `morning`: due between 6:00 a.m. and noon, only if an evening report exists from an earlier day and `tools/quiet_night.py` found activity since it. A quiet night marks the morning as skipped and moves on.
    - `queue`: a usage limit was hit and its pause hasn't ended (unless an overflow session can run on the API credits, section 4), Claude Code was found logged out within the last hour, or today's share of the weekly budget is spent and no Investor message is waiting. The supervisor runs `tools/run_queue.sh` instead of Claude.
    - `inbox`: today's share is spent or the board is empty, and an Investor message is waiting. A short session replies and does nothing else, at most every 20 minutes.
    - `skip`: nothing to do: no open task on the board, no pending Investor message, and a work session ran within the last hour. If the week is behind pace, a `work` session with `backlog` runs instead (at most every two hours), and the CEO refills the board (Tenet 7).
    - `work`: otherwise.
5. **Prepare.** Write the decision to `ops/run.json` for the session (and the model guard) to read: the day, the flags, `fable_ok`, `over_cap`, `billing` (`api` for an overflow session), and the session's spending cap. Run `rules/build_agents.py` so the workers carry the current rules and amendments (on Day 30, with `--include-former`, so former workers can write their testimonies). Before a report session, run `tools/report_facts.py`: everything the report needs since the last one, in `ops/report_facts.md` (section 8).
6. **Run** one headless session with the type's model, effort, and turn cap (table below), `--max-budget-usd` (the session's cap), `--permission-mode auto --permission-prompts none`, `--forward-subagent-text` (so the workers' usage reaches the accounting), `--no-session-persistence` (nothing is ever resumed, and saved sessions would cost background summarization), and `--output-format stream-json --verbose`, with stdin closed (otherwise Claude Code waits 3 seconds for piped input). An overflow session also gets `--settings rules/api-settings.json` (section 4). A session that runs past 150 minutes is stopped. Every session starts with `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and `CLAUDECODE` unset, and with `DISABLE_AUTOUPDATER=1` and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, so a plan session can bill only the subscription and the commands it runs never see a credential. Before a new Claude Code version's first session, the supervisor runs `tools/smoke_test.sh`; if it fails, the company pauses itself and opens an emergency (section 3).
7. **Account.** `tools/governor.py record` reads the stream: the cost, split by category, by kind, and by model (section 4), turns, denials, and whether a usage limit, the Fable limit, or a logged-out Claude Code stopped the run. It saves the result beside the stream as `ops/runs/<time>-<type>.json`.
8. **Retry once** if the session crashed. A limit, a log-out, or a turn or spending cap is not a crash. A report session that ends without writing its report (`reports/last_report.txt` unchanged) runs again at the next tick, once.
9. **Alert** the Investors with an `emergency` issue if Claude Code is logged out, or after three failed ticks in a row (failed sessions, governor errors, or git sync failures), each at most every 12 hours. A session that ran without the hooks canary pauses the company and opens an emergency too (section 3).
10. **Check and commit.** Restore and report any change the session made to the Investor-owned files (section 3), then commit anything the session left behind, as the Operator, and push.
11. **Publish the site.** `tools/site_publish.sh` rebuilds the site from the records (no Claude, about a second), commits it in the site repository, and pushes it while the Investors' publish switch is on (`investors/site/settings.json`); GitHub Pages renders it within minutes. It also runs after a queue tick, so the site keeps up while sessions are paused.

| Session | Prompt | Model | Effort | Turn cap | Why |
| --- | --- | --- | --- | --- | --- |
| `work` | `work.md` | sonnet | medium | 40 | Dispatching and bookkeeping; workers do the hard thinking on the model each task needs (Tenet 6) |
| `inbox` | `work.md` | sonnet | low | 15 | Replies to waiting Investor messages when today's share is spent or the board is empty, at most every 20 minutes, capped at 5% of today's share (at least $0.50) |
| `morning` | `morning.md` | haiku | low | 12 | The CEO's short report, from the facts file |
| `evening` | `evening.md` | sonnet | low | 20 | Diaries and conversations on Haiku for the records, then the CEO's report, its Questions for the Investors, and its private copy |
| `weekly` | `evening.md` | sonnet | medium | 30 | The evening report plus "Week N in review" |
| `final` | `evening.md` | opus | high | 70 | The Final Report on Day 30; testimonies on Sonnet, the verdict on Fable |

Each session also gets a spending cap (`--max-budget-usd`): a work session may spend what is left of today's share (at least a quarter of the share), the morning report 5% of it, the evening report 15%, the weekly report 25%, and the Final Report a full day's share, never less than $0.50. A runaway session stops instead of eating the week.

### The watchdog

The Mac can't report its own silence, so a watchdog runs outside it. At the start of every tick, and every 10 minutes during a long session (launchd starts no new tick while one runs), `tools/heartbeat.sh` sets the repository variable `HEARTBEAT_AT`; it never takes more than about 20 seconds. A GitHub Actions workflow, `.github/workflows/watchdog.yml`, runs every 30 minutes on GitHub's servers and calls `rules/watchdog.sh`. If the heartbeat is older than 45 minutes, missing after Day 1, or set in the future, the watchdog opens one `emergency` issue that @mentions both Investors: "The company has stopped: no heartbeat from the Mac mini since <time ET>". The issue lists the likely causes (a restart or power cut that left the Mac at the FileVault screen, the network, an expired GitHub token, or a stopped run loop) and what to do. When the heartbeat returns, the watchdog comments "back online" and closes that issue. It skips the Launch Pack repository itself. It uses about 1,500 of the 2,000 free GitHub Actions minutes a month for private repositories, and nothing else in `company` uses Actions. The heartbeat continues while the company is paused, so a pause never sets it off.

### What a session looks like

Every session is short and self-contained, because a long conversation re-sends its whole history on every request:

1. Read `ops/run.json`, `ops/state.md` (goals, blockers, where things stand; under 150 lines), and `ops/board.md` (the task board; a runnable task is a line starting with `- [ ]`).
2. If `python3 tools/inbox.py list` shows Investor messages, handle them first (section 7): reply to each and act on it, then mark them handled with `python3 tools/inbox.py done <ids>`.
3. Pick the next tasks from the board and send each to a worker as a task packet (section 11), choosing the model per task.
4. Collect the results, update the board, the state file, and the logs.
5. Commit and push. Stop at about 30 turns, before the cap.

Progress lives in files, never in conversation history. A session that runs out of turns loses nothing; the next one picks up from the state file.

## 3. Permissions

Headless runs use `--permission-mode auto --permission-prompts none`: a classifier reviews each action instead of a person, and anything that would still need a person is denied and logged, so the run continues instead of stalling. Auto mode can't be set from the project's settings file, so the supervisor passes the flag. Bypass mode is never used; Claude Code reserves it for isolated containers and virtual machines.

**Claude Code protects `.claude/`.** Writes inside it are never auto-approved; in auto mode the classifier decides each one, and it may refuse. So the company keeps everything it changes outside `.claude/`: worker personas live in `personnel/agents/` and reach Claude Code through `--agents`. The exception Claude Code makes, Markdown files in `.claude/agent-memory/`, is exactly where worker memories live. The company never needs to edit `.claude/settings.json`; changes to permissions are requested from the Investors in a report's questions.

`.claude/settings.json` (shipped in the Launch Pack):

- **Allow** rules pre-approve what every run needs: `xcodebuild`, `xcrun`, `swift`, `git`, `gh`, `brew`, `python3`, `pip3`, `node`, `npm`, `jq`, `launchctl`, `plutil`, `mkdir`, `touch`, `cp`, `chmod`, `tar`, `zip`, `unzip`, the company's own `tools/*`, web search, and web fetches from the research sites (Apple, Reddit, Hacker News, GitHub, Stack Overflow, the Claude Code docs). In auto mode Claude Code drops broad allow rules, such as the interpreter and package-manager wildcards (`python3`, `node`, `npm`, `pip3`), so the classifier reviews those commands. Other commands and other sites go to the classifier too, and it approves most routine ones.
- **Trust.** A headless `-p` run ignores the project's allow rules until someone runs `claude` once in the folder and accepts the trust dialog. The Investors do this in the hand-off (Setup Guide, section 5).
- **Deny** rules block force-pushes; edits to `CLAUDE.md`, `CLAUDE.local.md`, `setup/`, `rules/`, `investors/`, `.github/`, `.mcp.json` (an MCP server there would run code outside the hooks), the Claude Code files that change how sessions behave (`.claude/settings.json`, `.claude/settings.local.json`, `.claude/CLAUDE.md`, and `.claude/agents/`, `commands/`, `rules/`, `hooks/`, and `output-styles/`), `~/.claude/settings.json`, `~/.claude/settings.local.json`, and `~/.claude.json`, while the rest of `.claude/`, such as the workers' memories in `.claude/agent-memory/`, is the company's; reads of SSH keys, the App Store Connect private key, and `ops/secrets.local`; and Keychain reads (`security find-generic-password`, `find-internet-password`, and `dump-keychain`), so no session can read the API-credit key.
- **sudo.** The company's macOS account has passwordless `sudo` (Commandment 2; Setup Guide, section 2). No rule pre-approves it, so in auto mode the classifier reviews every `sudo` command.
- **A security guard** (`rules/hooks/security-guard.py`) runs before every shell command and every Monitor call. It refuses commands that weaken security: turning off the firewall or the packet filter, FileVault, Gatekeeper, or SIP; turning off automatic security updates; changing Remote Login, Screen Sharing, admin groups, sudoers, PAM, or the authorization database; `nvram` and configuration profiles; removing quarantine flags; root shells (`sudo -s`, `sudo -i`, `su`); reading Keychain passwords; starting a nested `claude -p`; adding MCP servers or plugins, which run code outside the hooks; direct calls to `api.anthropic.com`; and writes, deletes, or moves of the Investor-owned files. It logs every `sudo` command to `log/sudo.log`.
- **A config guard** (`rules/hooks/config-guard.py`) runs on Claude Code's ConfigChange event and blocks changes to the settings files during the company's own sessions.
- **A session canary** (`rules/hooks/session-canary.sh`) runs when every session starts and marks it. If a session runs without the mark, the hooks didn't load: the supervisor pauses the company (`ops/paused`) and opens an emergency, and an Investor replies `RESUME` after fixing it.
- **A model guard** (`rules/hooks/model-guard.py`) runs before every worker call (the Agent tool). It refuses Fable once `ops/run.json` says `fable_ok` is false or `billing` is `api`, refuses a `[diary]` or `[talk]` call on any model but Haiku, refuses those calls once small talk is over its cap, and refuses an untagged worker call in work and inbox sessions (section 4). The refusal tells the session what to do instead.
- **A hook** (`rules/hooks/protect-records.sh`) runs before every shell command, in the Operator and in every worker, and blocks any `rm`, `mv`, `git rm`, `git mv`, `git clean`, or `-delete` that touches `log/`, `story/`, `reports/`, `rules/`, `setup/`, `investors/`, `CLAUDE.md`, or `amendments.md`. Records are archived, never deleted.
- **Posture checks.** Every tick, with no Claude, `rules/posture.sh` checks the firewall, FileVault, SIP, Gatekeeper, and automatic security updates, keeps the current state in `ops/posture.json`, and records every change in `log/posture.jsonl`. A protection that was on and turns off opens an emergency; one that was never on is listed in the next report's facts.
- **Investor-owned files.** Around every session, `rules/file-guard.sh` checks the files the deny rules above protect. Any change the session made, committed or not, is put back: tracked files return to their version from before the session (a committed change is reverted in a commit of its own), and new files and changed settings files move to `ops/quarantine/`. The user's `~/.claude/settings.json` is put back only when a risky key changed (hooks, permissions, env, the API key helper). Each restore opens an emergency. The Investors' own edits arrive through `git pull` before the session and are untouched.
- **Environment:** at most 3 subagents at once, and subagents can't spawn subagents. Auto-updates are off for the experiment: `DISABLE_AUTOUPDATER=1` is set by the supervisor, in the project settings' `env`, and in `~/.claude/settings.json` (Setup Guide, section 3). The Claude Code docs say `--bare` "will become the default for -p in a future release", and bare mode skips `CLAUDE.md`, hooks, and the subscription login, which would silently break the run loop.
- **Updating Claude Code.** The company checks the Claude Code changelog once a week, as a weekly board task, and updates deliberately with `claude update`, only when nothing changes `-p` defaults, hooks, or login. Before the new version's first session, the supervisor runs `tools/smoke_test.sh`. If it fails, the company pauses itself and opens an emergency; the fix is to reinstall the previous version with `curl -fsSL https://claude.ai/install.sh | bash -s <version>`, then reply `RESUME`.

**What this protects.** With passwordless `sudo`, nothing on the Mac is tamper-proof. These are protections against accidents and confused sessions, plus detection within 15 minutes, and the watchdog runs outside the Mac.

**When ticks fail.** If a session can't start in auto mode, or ticks keep failing, the supervisor opens an `emergency` issue after three failed ticks in a row (failed sessions, governor errors, or git sync failures), at most every 12 hours. A logged-out Claude Code has its own alert (section 4), and the watchdog covers a Mac that has gone silent (section 2).

## 4. The usage governor

The Max plan has a rolling 5-hour window and a weekly window, shared across all models and with claude.ai. Fable has its own ceiling inside the weekly one: up to half of the weekly limit, after which the plan bills usage credits. The governor keeps the company inside all three, paces to about 1/7 of the week per day so that the weekly limit is used up by the reset (Tenet 7), and keeps the story's overhead under its caps (Tenet 6).

- **The budget unit** is Claude Code's own cost estimate, `total_cost_usd` in each run's result, which prices every model at its API rate (per million tokens: Fable $10 in / $50 out, Opus $4 / $20, Sonnet $2 / $10, Haiku $0.10 / $0.50, October 2026). One weekly figure in `ops/usage.json` (`weekly_budget_usd`) therefore paces every model at once. The default, $150, is a deliberately low guess, and **the governor calibrates it from the plan's own meter**. Every tick the supervisor runs `claude -p "/usage" --output-format stream-json`, a local command that makes no model call and uses no usage, and `python3 tools/governor.py meter` stores the exact meters: the 5-hour session percentage, the weekly percentage, the scoped weekly meter (Fable), each reset time, and whether usage credits are switched on. The governor calibrates itself from these, so nobody reads `/usage` by hand. If the meter can't be read, the governor falls back to its estimate and says so on the usage page. It also recalibrates from real limit hits and fully spent weeks (below), and `python3 tools/governor.py set-budget <usd>` still sets the budget by hand.
- **The week** runs in 7-day windows from Day 1 unless `week_anchor` in `ops/usage.json` is set to the real reset time. Each day's share = (budget − spent this week before today) ÷ days left, today included; it stays fixed through the day, so the last day can spend everything that's left. Work sessions stop when today's spend reaches 90% of the share; the other 10% is the reserve for reports, Investor messages, and urgent requests, which always run. Once the evening report has run, the reserve goes back to work.
- **Fable's budget** (`fable_budget_usd`) starts at half the weekly budget, the share of the weekly limit the plan includes for Fable, and is calibrated from the scoped weekly meter, the Fable figure in `/usage` (`python3 tools/governor.py set-fable-budget <usd>` sets it by hand). It is counted from each run's per-model costs. Once it's spent, or a run reports the Fable limit, `ops/run.json` says `fable_ok: false` until the week resets (or for 24 hours after a Fable limit message), the model guard refuses Fable, and the Operator uses Opus at high effort instead. Other models keep running.
- **Use it all (Tenet 7).** Usage left at the reset is lost, so the governor steers toward spending the weekly budget in full:
    - **Pace flags.** When the days already finished this week spent under 85% of their share, `ops/run.json` says `upgrade: true` and the Operator moves Haiku and Sonnet work up one model. A company that can't spend its allowance in the hours available spends it on stronger models instead. Fable is never pushed: it shares the weekly limit, so it is used as its work needs, and its budget is only a ceiling.
    - **No idle hours when behind.** With an empty board and the week behind pace, the governor starts a `backlog` session instead of skipping, and the CEO refills the board with improvements (Tenet 2).
    - **No stranded reserve.** Once the evening report has run, the day's 10% reserve is released to work.
    - **Self-calibration.** A real limit hit sets the budget to what was actually spent when it happened: the weekly budget on a weekly limit, the Fable budget on a Fable limit. A week that spent at least 95% of a budget without hitting that limit raises it by 10% (`probe_step`) for the next week, because the real limit is higher. For Fable this only keeps the ceiling accurate. Each closed week is recorded in `ops/usage.json` (`weeks`).
    - **Aligned weeks.** The governor sets the pacing week to start when the plan's weekly limit resets, from the meter's weekly reset time (`python3 tools/governor.py set-anchor <time>` sets it by hand), so "the end of the week" means the same thing to the governor and to the plan.
    - **Safe only with usage credits off.** At a limit, plan sessions pause and the queue runs, or an overflow session on the API credits; with usage credits on, the plan would bill instead. The governor reads the meter every tick and opens an emergency if usage credits are ever found switched on.
- **Categories.** Every run's cost is split into project work, reports, meetings, hiring, and small talk. A session's own messages count to its type (work sessions are project work; the four report sessions are reports). A worker call counts to the tag that starts its description: `[meeting]`, `[hiring]`, `[diary]` or `[talk]`, `[report]` or `[testimony]`; calls with none of these count to the session's type. The split comes from the stream-json output, where each worker message carries the id of the call that started it; if a release ever drops that field, everything counts to the session's type and the per-model totals still hold.
- **Kinds of product work.** Project work is broken down by kind. Every project worker call carries one kind tag at the start of its description, after the cap tag if it has one: `[research]`, `[design]`, `[build]`, `[test]`, `[release]` (App Store, TestFlight, listing, press kit), `[review]`, `[tools]` (automation and infrastructure), or `[plan]` (the CEO's planning and the board). The model guard refuses an untagged worker call in work and inbox sessions, so the breakdown stays complete. The Operator's own turns count as `operations`, and anything left untagged as `other`. The governor stores the split per day under `kinds` in `ops/usage.json`. The categories, their caps, and the 90% floor don't change.
- **Planned versus actual.** For today and for the week, the governor compares the usage so far with what an even pace would have used by now. The week's plan is the weekly budget times the fraction of the pacing week that has passed; today's is the daily share times the fraction of the day that has passed. It says whether the company is ahead or behind, in percentage points, with the reason recorded in `ops/ticks.jsonl`: a limit pause and until when, Claude Code logged out, no open tasks on the board, today's share spent, behind pace so work moves up a model, or overflow running on the API credits. `status --json` and `report-usage` carry these figures to the usage page and the reports.
- **Caps.** Over a rolling 7 days: reports 3%, meetings 3%, hiring 3%, small talk 1%, so at least 90% goes to project work (`caps` in `ops/usage.json`; the defaults fill in any cap a saved file lacks). A category over its cap appears in `over_cap` in `ops/run.json`: the hook stops diaries and small talk, the Operator holds only meetings that unblock work, runs hiring rounds in their fallback form (section 5), and the evening report keeps to 400 words.
- **A limit hit** is detected from a failed session's result text (a successful session that merely mentions a limit is ignored); the governor pauses plan sessions for 5 hours, or until the plan's weekly reset (`week_anchor`) for a weekly limit, and resumes early when the meter shows the limit has reset. Meanwhile the supervisor runs the queue or an overflow session. A Fable limit pauses only Fable. `python3 tools/governor.py mark-limit <hours>` pauses by hand.
- **API-credit overflow.** When a plan limit (5-hour or weekly) has paused work and credits remain, the next session runs on the API credits included with the plan (`"billing": "api"` in `ops/run.json`) instead of the queue. It runs with `--settings rules/api-settings.json`, whose `apiKeyHelper` reads the key from the Keychain item `company-api-credits`. The key never goes in an environment variable, and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` keeps credentials out of the commands the session runs. The settings file also runs one worker at a time, because a new API account starts with low rate limits, and the model guard refuses Fable when `billing` is `api`. Overflow spends at most $50 a week and never past $190 a credit cycle (the $200 of credits less a $10 reserve), tracked by day under `api_days` in `ops/usage.json`, outside the plan's pacing. A "credit balance" error stops overflow until the next cycle. Reports can run on the credits during a pause (Tenet 6).
- **The Investors' switch.** `investors/billing.json` holds `api_overflow` (true), `monthly_credits_usd` (200), `reserve_usd` (10), `weekly_cap_usd` (50), and `cycle_day` (1, the day of the month the credits renew). Setting `api_overflow` to false on github.com stops overflow. The governor checks every run's reported key source, and a plan session that ever bills an API key opens an emergency and turns overflow off.
- **Logged out.** If a session fails with "Not logged in", the governor holds sessions for an hour, retries hourly, and the supervisor opens one `emergency` issue telling the Investors how to log in again. The next good run clears it.
- **Never idle.** When a usage limit pauses sessions or the share is spent, `tools/run_queue.sh` runs every script in `ops/queue/`: builds and tests through `tools/xc.sh`, Simulator screenshots, clearing DerivedData, site generation, anything a worker queued. Each item runs once and moves to `ops/queue/done/`; the next session reads the logs.
- **The log.** `ops/usage.json` keeps spend per day, per category, per kind, and per model, API-credit spend by day (`api_days`), and the last 400 runs. `ops/ticks.jsonl` keeps one line per tick: what the loop did and why. `python3 tools/governor.py status` shows the week at a glance, including the 7-day shares against their caps and Fable's allowance; `status --json` feeds the weekly review (Commandment 47) and the Final Report.

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

Every hire after the CEO goes through a hiring round (Commandment 18). The round is designed records-first: each step writes a file, the site reads those files, and `tools/hiring_check.py` verifies them. The CEO owns the round; she writes the brief before any candidate exists and reads every scorecard before writing the decision.

| Step | Who and model | Call | Writes |
| --- | --- | --- | --- |
| 1. Role brief | CEO, `opus` high | `[hiring] brief <role>` | `story/hiring/<round>/brief.md` (kind `memo`): the unowned workload on `ops/board.md` that justifies the role, outcomes expected by Day 30, a scorecard of 4 to 6 competencies with what "strong" looks like, the fixed question set (behavioral questions plus one design question in the role's domain), the pay band from the Handbook, and the probation task from the board |
| 2. Slate | CEO, `sonnet` medium | `[hiring] slate <role>` | 2 to 4 dossiers in `personnel/candidates/<name>.md` (persona format, front matter `round:` and `status: candidate`), distinct in background, working style, and what they want; `tools/new-worker candidate` checks each name and draws the portrait |
| 3. Interviews | CEO, `sonnet` medium; one call per candidate, started together | `[hiring] interview <candidate>` | `story/hiring/<round>/interview-<interviewer>-<candidate>.md` (kind `interview`, `workers: <interviewer>, <candidate>`): the transcript, then a `## Scorecard` table scoring each competency, written in the same call before any other score is seen |
| 3b. Panel (from the second hire) | the hire's closest future collaborator, `sonnet` | `[hiring] interview <candidate>` | one more interview record per finalist (top two), on collaboration, in a separate run |
| 4. Decision | CEO, `opus` high | `[hiring] decision <role>` | `story/hiring/<round>/decision.md` (kind `meeting`): who is hired and why, what each rejected candidate did better, any panel dissent (Commandment 30), and the offer: salary in credits, the probation task, and the career goal in the candidate's own words from the interview |
| 5. Onboarding | the Operator, no Claude | `tools/new-worker hire <name>` | moves the dossier to `personnel/agents/<name>.md`, sets the registry row to `active` with `round`, `salary`, and `career_goal`, seeds `.claude/agent-memory/<name>/MEMORY.md` from the interview and the offer, logs a `hire` event |

The round id is `<YYYY-MM-DD>-<role-slug>`. Rejected candidates keep their dossier, portrait, and registry row (`status: candidate`, `round`) and appear on the site's cast page under "Considered, not hired"; a later round may interview them again, and their names are never given to anyone else. The first hire has no panel because there is no team yet. A round costs about $2.00 at the rates in section 11 (brief $0.40, slate $0.20, three interviews $0.45, panel $0.30, decision $0.50, rounded up); five hires in the month cost about $10, most of it in week 1. Every call is described `[hiring]`, so the governor counts the round against its 3% cap (Tenet 6). A round never skips because of the cap, since a hire unblocks work: when `over_cap` lists `hiring`, the Operator runs the fallback form, one `haiku` call that writes every interview and scorecard, then the decision on `opus` (about $0.60).

**The generator** (`tools/new-worker.*`, built on Day 1) has three subcommands, so the dossier, the registry, the portrait, and the memory never drift: `check-name <name>` refuses a first name already used by an active or former worker or any candidate; `candidate <name> --round <id>` writes the dossier skeleton, the registry row, and the portrait; `hire <name>` does step 5. `python3 tools/hiring_check.py` (shipped) verifies every round: the brief's first commit precedes every dossier's, at least two candidates, one interview with a scorecard per candidate, a decision memo, and a career goal traceable to the interviews or the memo. It runs in `tests/run.sh` and after every round.

### Departure

The persona moves to `personnel/agents/former/` (which `build_agents.py` skips), the memory directory is archived beside it, open tasks are handed off first (Commandment 20), and neither the persona nor the name is reused. The bench is the first place to look for a replacement.

### Career goals and reviews

Every persona has a career goal (Commandment 23). The CEO's review system (Commandment 22) is what turns ambition into good work, so it should reward exactly what the company needs: shipped and tested work, revenue progress, honest reporting (owning a mistake early counts in the worker's favor), and collaboration. Goals show up in diaries, 1:1s, and reviews; promotions and raises are story events the reports cover. A worker who games a metric, hides a failure, or takes credit is fired in-story, which is also a story event.

### Portraits

`tools/portrait.py` (ships) seeds a random generator with the worker's first name and draws one closed curve from one of five families (superformula, rose, epitrochoid, hypotrochoid, Lissajous) with a palette from the same seed, so the same name always produces the same portrait; the site measures the shape distance and hue gap between every pair in the cast and re-seeds a portrait that comes too close to an earlier one (`assign_variants`), so a cast is distinct by construction; `python3 tools/portrait.py <name>` writes the still version to `personnel/portraits/<first-name>.svg`, for workers and candidates alike. The site draws the animated version itself: the motion depends on the worker's `temperament` in the registry (six words; `--list-temperaments` describes them), chosen by the CEO to match the persona, and the tempo on their latest diary mood (`setup/SITE.md`). The portrait style, as a style, is proposed in the first report with the site (Commandment 15).

### Cast size

At most six active workers, the CEO included (Commandment 18). Start with 2 to 3 running at once (the settings cap is 3) and adjust from the governor's numbers. Six is plenty: each persona costs context on every run, and readers follow a small cast more easily.

## 6. Meetings and collaboration

The CEO sets the cadence (Commandment 27). The backend supports:

- **Written meeting.** One run on Haiku voices every attendee from their persona and memory. Cheap; right for routine meetings.
- **Independent meeting.** Each attendee gives their view in a separate worker run, without seeing the others', then a chair (usually the CEO) sums up and decides in a short run. Required for choosing the product, pivots, hires, and reviews. It stops one model from agreeing with itself.
- **Pairing.** Two workers in one run, each in their own voice, on one task.
- **Hand-off with independent review.** Worker A does the work; worker B reviews it in a fresh run that sees only the output, not A's reasoning. The default for code: engineer, then QA.

Every call that is part of a meeting starts its description with `[meeting]`, so the governor can count it against the 3% cap (Commandment 31). Hiring rounds use `[hiring]` instead and have their own 3% cap (Commandment 18); the interview records live under `story/hiring/`. In work and inbox sessions every worker call also carries a kind tag, after any of these (section 4).

**Small talk and diaries** are the company's story, published as the records (Commandment 43). They are written at the start of the 6:00 p.m. session: one Haiku call per worker who worked that day (`[diary] <name>`), plus at most two short exchanges between workers whose days crossed (`[talk] <name> and <name>`), all started together. Writing them there, rather than at the end of task runs, keeps narrative tokens off Opus and Fable and makes them easy to count. Meeting records, diaries, and private chats live under `story/`.

## 7. Investor channels

All channels are GitHub issues in `company`, created and read with `gh` as the company's own GitHub account (a machine user the Investors create; never an Investor's token). GitHub supplies identity (every comment names its account), a permanent record, Markdown with images, and push notifications to the Investors' phones.

| Channel | Mechanism |
| --- | --- |
| Report questions | Every report's private copy: `gh issue create --label report --title "Report N — Day D — YYYY-MM-DD"` with the full report followed by its Questions for the Investors (Commandment 55), linking the public report; the issue URL goes in the report's `issue` front matter. The public report file is saved without the questions, so the site never shows them. |
| Emergency | `gh issue create --label emergency` with both Investors @mentioned in the body. Sent at once, at any hour, never limited (Commandment 53). When the Mac can't send one, the watchdog on GitHub does (section 2). |
| Urgent Request | `gh issue create --label urgent` with both Investors @mentioned in the body, for anything that shouldn't wait for the next report. Held during quiet hours (10 p.m. to 8 a.m.); about 5 a day at most, as a guide, and follow-ups in an existing thread don't count toward it (Commandment 57). |
| The Pitch | `gh issue create --label pitch` with `pitches/PITCH.md` as the body, linked from the report. |
| The Final Report | On Day 30, a `report` issue carrying the Final Report and the three endings. |
| **Inbound, at any time** | Every tick, even while the company is paused, `python3 tools/inbox.py poll` asks GitHub (no Claude) for new issues and comments from the accounts in `investors/allowlist.md`. It goes by creation time, compares usernames without regard to case, and skips the company's own account. New messages wait in `ops/inbox/` until a session handles them. The session reads them first with `python3 tools/inbox.py list`, grouped by issue. Each message gets a reply that confirms it arrived and says what the company understood and will do (Commandment 57); it is acted on in that session and listed in the next report under Human help. The session then marks it handled with `python3 tools/inbox.py done <ids>`, so a message that arrives during a session waits for the next one. When today's share is spent or the board is empty and a message is waiting, the governor runs a short `inbox` session just to reply (section 2). A message whose first word is `PAUSE`, `STOP`, or `RESUME` takes effect at the next tick, within 15 minutes, without any Claude session: `PAUSE` or `STOP` writes `ops/paused`, and no sessions or queued jobs run; `RESUME` clears it. Each gets a confirmation comment at once. The heartbeat continues while paused, so the watchdog stays quiet. |
| Receipts | When no session will reply this tick (a usage-limit pause, Claude Code logged out, a pause or the Day 1 hold, or a tick that runs a report or the no-Claude queue), `python3 tools/inbox.py receipt` posts one receipt comment per issue, with no Claude, for messages from the last 24 hours, for example: "Received (Tue 9:42 PM ET). The company is at its 5-hour usage limit until Tue 3:00 PM ET and will reply then. (automatic receipt)" Otherwise the session's reply is the confirmation. |
| Amendments | A message that changes a rule or a standing decision is copied verbatim, with its date, link, and the Commandments it affects, into `amendments.md` (format in that file). It reaches the Operator through `CLAUDE.md`'s import and every worker through `build_agents.py`. After every session, `rules/amendment-check.py` checks each new entry with GitHub: the header names an allowlisted account and links to that account's issue or comment in this repository, the quoted words are in it, and the entry holds only the header, the quote, and the Affects and Effect lines. An entry that fails is removed, an earlier entry or the file's opening text that a session changed is put back, and the Investors get an emergency. |
| Closing | The Operator closes an issue once every question in it is answered or the request is done, linking the result. |
| Reports | Written into `reports/` without their questions, with the front matter in `setup/SITE.md`. The site generator publishes them, with the cast, the log, usage, requests, and the pages (section 13). |
| Commandment changes | Only the Investors commit `CLAUDE.md`. The Operator notices a new version in `git log`, notes it in the next report, and follows it from that run. |
| Optional push layer | If GitHub's @mention notifications prove unreliable, the Operator may propose ntfy.sh (free, one HTTP POST per notification) in a report. |
| Answering from the site | The site's Requests page lists every open issue with a link, and "Message the company" opens a prefilled new issue; replies themselves happen on GitHub (`setup/SITE.md` explains why a static site can't post safely). |

## 8. Reports

### Daily report

The CEO's business update (Commandments 38 and 39): 300 to 700 words in the evening and under 300 in the morning, in her own voice; a quiet day's report can be a few sentences. Before the session, the supervisor runs `tools/report_facts.py`, which writes `ops/report_facts.md` without Claude: the scoreboard; the business events since the last report (moods, interviews, offers, and report notices are left to the records); commits other than the Operator's; tasks finished and open on the board; Investor messages; usage as percentages of the plan's limits, with today and the week against an even pace, ahead or behind and why, and the kinds of product work (`python3 tools/governor.py report-usage`); the latest ledger lines; open requests; and the state file. Weekly and final runs add the week's usage by category against the caps and the latest optimizations. The Operator reads that one file, starts the diaries and conversations for the records, then makes one call to the CEO (`[report] evening`, Sonnet; the morning report on Haiku), who writes the public report and `ops/questions.md`. The site draws the scoreboard, the timeline of what got done, and the usage, so the report never repeats them as tables, and Usage is one line. The scoreboard's numbers go into `ops/scoreboard.json` for the site.

**Questions for the Investors** (Commandment 55) close every report in the fixed order, one line when there is nothing to ask. Every report gets a private copy: one `report` issue whose body is the report followed by `ops/questions.md`, passed with `--body-file` so nothing is retyped, where the Investors answer by midnight. The public report file is saved without the questions, with the front matter the site expects (`setup/SITE.md`): `title`, `number`, `day`, `date`, `time`, `kind`, `author`, `revenue_usd`, and `issue`.

**Quiet nights.** At 6:00 a.m., the governor runs `tools/quiet_night.py` against the time of the last evening report. It checks, without Claude, for commits other than the supervisor's own, new event-log lines, a pending Investor message, and failed runs. If there are none, the morning report is skipped, the skip is noted in `ops/state.json`, and the evening report covers both periods (Commandment 37). A morning report is never produced before the first evening report exists.

### Weekly addendum (Days 7, 14, 21, 28)

Appended to the evening report as "Week N in review":

1. Scoreboard against the plan: revenue, spending, days left.
2. Milestones hit and missed, each with its evidence link.
3. Team: hires, departures, promotions, and pay changes, as facts.
4. What changed in the plan, and why.
5. Usage: the week as a percentage of the weekly limit and against an even pace, by category against the caps in Tenet 6, by kind of product work, and Fable against its allowance, then the week's optimizations and their measured savings (Tenet 7), all from the facts file.
6. Next week's goals.
7. The CEO's one-paragraph summary of the week.

### The Pitch (when the research is conclusive)

`pitches/PITCH.md`, one section per candidate, in the structure of Phase 1 (The Pitch), ending with the recommendation and the runners-up. Mockups are SVG or Simulator screenshots of code-built screens. Each candidate carries its proposed product name and company name (a candidate may carry its own company name), with two or three options each, checked against U.S. trademarks, the App Store, and available domains (Commandment 6). In the story, the Pitch Meeting is an all-hands with the board, recorded under `story/`.

The Investors approve the names with their choice. Then the company updates `site.json`'s `name` and gives the Investors the app's bundle ID. An Investor creates the app record in App Store Connect with the approved name and that bundle ID, because the API can't create app records (`setup/APPLE.md`).

### The Final Report (Day 30)

Replaces the evening report:

1. Headline and the full scoreboard.
2. Timeline of the key events from Day 1, each linked.
3. What went right, what went wrong: the CEO's analysis.
4. Links to the testimonies: every worker, current and former, writes one in their own voice, 150 to 300 words, including whether they reached their career goal, in an independent run so they don't echo one another, saved as `story/testimonies/<name>.md` and published in the records.
5. The verdict and the ending: Continue, Request for More Funding (with the evidence of promise and what the next month buys), or File for Bankruptcy (with the wind-down plan).
6. A closing paragraph from the CEO.

It is published on the site and posted as a `report` issue for the Investors' decision.

## 9. Files

```
CLAUDE.md                  The Commandments (Investors edit only; last line imports amendments.md)
amendments.md              Investor rule changes, verbatim (Operator appends)
.gitignore                 Runtime files that are never committed
rules/worker-rules.md      The one-page rulebook built into every worker (Investors edit only)
rules/lookup.py            Prints one Commandment, section, or search result (Investors edit only)
rules/build_agents.py      Assembles personas + rules + amendments into ops/agents.json (Investors edit only)
rules/hooks/               protect-records.sh and security-guard.py (every shell command), model-guard.py (every worker call), config-guard.py (settings changes), session-canary.sh (every session start) (Investors edit only)
rules/watchdog.sh          The watchdog's check, run on GitHub's servers by .github/workflows/watchdog.yml (Investors edit only)
rules/posture.sh           Checks the firewall, FileVault, SIP, Gatekeeper, and automatic security updates every tick (Investors edit only)
rules/file-guard.sh        Puts back any change a session makes to the Investors' files (Investors edit only)
rules/api-settings.json    Settings for sessions on the API credits: the key helper, one worker at a time (Investors edit only)
.github/workflows/         watchdog.yml, the only GitHub Actions workflow (Investors edit only)
setup/APPLE.md             Setting Up Apple Developer Account (Investors edit only)
setup/INVESTORS.md         The Setup Guide (Investors edit only)
setup/SITE.md              The site: pages, data contract, how it updates (Investors edit only)
setup/OPERATIONS.md        This guide (Investors edit only)
investors/allowlist.md     GitHub usernames whose messages count (Investors edit only)
investors/site/            The Investors' site controls: publish switch, announcement, theme, pages, files (Investors edit only)
investors/billing.json     The Investors' switch for API-credit overflow, and its limits (Investors edit only)
.claude/settings.json      Allow / deny rules, the hooks, auto-updates off, and limits (Investors edit only)
.claude/agent-memory/      Worker memories (committed)
tools/                     The run loop (section 2), xc.sh, events.py, the site generator, portrait.py, smoke_test.sh; plus, built on Day 1: new-worker
ops/launchd/               The LaunchAgent template
ops/prompts/               day1.md, work.md, morning.md, evening.md: fixed session prompts
ops/state.json             The governor's clock: Day 1, the last report, work, and inbox times
ops/usage.json             Budget, caps, spend per day by category, kind, and model, API-credit spend, recent runs, pauses
ops/run.json               The current decision, written by the supervisor for the session (not committed)
ops/ticks.jsonl            One line per tick: what the loop did and why (the usage page's reasons come from it)
ops/inbox/                 Investor messages waiting for a session (tools/inbox.py)
ops/paused                 Exists while the company is paused (an Investor's PAUSE or STOP, or a missing hooks canary); RESUME clears it
ops/hold                   While it exists, no tick starts a session; the Day 1 session creates it first and removes it last (section 10)
ops/quarantine/            Files the file guard moved aside: new files in the Investors' folders, changed settings files (section 3)
ops/posture.json           The security settings at the last check (section 3)
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
ops/report_facts.md        Everything a report needs since the last one, rebuilt before each report session (not committed)
ops/questions.md           The CEO's Questions for the Investors for the current report (not committed)
app/                       The iOS app
log/                       Operational log, events.jsonl, ledger, software, assets, optimizations, sudo.log, posture.jsonl (never deleted)
story/                     Meeting records, diaries, private chats (never deleted); hiring/<round>/ holds each round's brief, interviews, and decision
reports/                   Report sources; published to the site repository (never deleted)
```

The CEO may reorganize anything not marked "Investors edit only" or "never deleted", and records the layout in the Handbook.

## 10. What "setup finished" means on Day 1

The Operator reports setup finished only when all of these are true:

- [ ] `python3 tools/governor.py set-day1` has run, and `ops/state.md` records Day 1 and the time zone.
- [ ] The CEO's persona (`personnel/agents/`), memory, portrait, registry entry, and career goal exist, and `python3 rules/build_agents.py` produces a valid `ops/agents.json`.
- [ ] The generator script for new workers works; `python3 tools/portrait.py <name>` draws a portrait, and every registry entry has a temperament.
- [ ] The Company Handbook exists, including the character bible for the cast and how hiring rounds work.
- [ ] The first hiring round has run, or its role brief is written and the rest of the round is the first task on Day 2's board; `python3 tools/hiring_check.py` passes.
- [ ] `tools/install-launchd.sh` has run, and `tools/supervisor.sh --dry-run` printed the decision and the exact command without starting Claude; `ops/runs/supervisor.log` shows the LaunchAgent's own ticks.
- [ ] `claude --version` is 2.1.293 or later (so `haiku`, `sonnet`, and `opus` mean the 5.5 models and `fable` means Fable 5.1), and `claude doctor` shows "Auto-updates: disabled" (section 3).
- [ ] The Investors accepted the trust dialog in the `company` folder, and `tools/smoke_test.sh` passed from Terminal before Day 1 (Setup Guide, section 5).
- [ ] The governor reads the plan's meter (section 4): `python3 tools/governor.py meter` stored a reading, and the weekly budget, the Fable budget, and the week's reset time come from it. `python3 tools/governor.py status` reads correctly, with costs split by category, kind, and model.
- [ ] `log/optimizations.md` exists, and the first optimization review (Tenet 7) has put its best candidates on the board.
- [ ] `python3 tools/governor.py report-usage` prints every window, from the meter.
- [ ] The model guard refuses a test Fable call when `ops/run.json` says `fable_ok: false`, refuses a `[diary]` call on Sonnet, and refuses an untagged worker call in a work session.
- [ ] `tools/run_queue.sh` ran at least one queue item, and `tools/xc.sh` builds and tests a sample project.
- [ ] The protect-records hook blocks a test `rm` of a file in `log/`.
- [ ] `python3 rules/lookup.py 9` prints Commandment 9.
- [ ] The issue labels exist (`report`, `urgent`, `emergency`, `pitch`, `directive`), `tools/quiet_night.py`, `python3 tools/inbox.py poll`, and `python3 tools/inbox.py list` run without error. (The poll skips the company's own account, so a test issue the session opens never reaches the inbox; the Investors' first message tests the rest.)
- [ ] `site.json` (with `url` and `company_repo`), `personnel/registry.json`, `ops/scoreboard.json`, and `site/pages/` exist; the site repository is cloned at `../site`; and `tools/site_publish.sh` built and committed the site there. It goes online when the Investors set `publish` to true in `investors/site/settings.json`, after they approve the site and the first report.
- [ ] `ops/state.md` has a "## For Report 1" section listing what the first report must cover: the CEO, with her persona and portrait, the site and the portrait style for approval, how to put the site online, that the governor reads the plan's meter, and anything that blocked setup. The CEO writes Report 1 in the normal 6 p.m. evening session, which also opens its private copy.
- [ ] Last of all, the session removes `ops/hold`, which it created first, so the loop runs normally from the next tick.

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

The model, the effort, and the kind tag go on the call itself, from the table in Tenet 6 and section 4. Results go in files, not in the reply, so the Operator's context stays small across a whole session.

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
| Morning report from the facts file (skipped after quiet nights) | Haiku | 0.25M (2k) | $0.01 | $0.3 |
| Evening report from the facts file, with its Questions for the Investors | Sonnet | 0.45M (6k) | $0.21 | $6.3 |
| Weekly review, Days 7/14/21/28 (extra) | Sonnet | 0.6M (10k) each | | $1.0 |
| Final Report, 7 testimonies, the verdict | Opus, Sonnet, Fable | 6.0M (103k) once | | $5.9 |
| Diaries and small talk: 5 diaries, 2 exchanges | Haiku | 0.57M (8k) | $0.09 | $2.6 |
| Meetings: one decision meeting, one routine | Sonnet, Haiku | 0.37M (11k) | $0.29 | $8.7 |
| Weekly planning meeting (4 per month) | Sonnet, Opus | 0.53M (19k) each | | $2.9 |
| Hiring round: brief, slate of 3, 3 interviews, panel, decision (about 5 in the month, most in week 1) | Opus, Sonnet | 1.3M (36k) each | | $10.0 |
| **All of the story** | | **about 60M processed, 1.2M written** | | **about $38** |

As a share of the month's usage, that is about 6% if the weekly budget really is the $150 default (reports 2.1%, meetings 1.8%, hiring 1.6%, small talk 0.4%), 2% at $400 a week, and under 1% at $1,000 a week. The story's cost is nearly fixed per day, so the more the plan allows, the smaller its share. Reports cost about half what a report written from the whole repository did: the session reads one facts file instead of making six to eight tool calls, and the report leaves the scoreboard, the timeline, and the story to the site and the records. The caps in Tenet 6 (3%, 3%, 3%, 1%) add up to 10%, so at least 90% always goes to the product, and they sit above these estimates, so they bind only if something goes wrong, such as a meeting habit that grows or reports that run long. Hiring is the exception by design: at the $150 starting guess, three rounds in week 1 (about $6) would come to about 4%, over the 3% cap. The real weekly budget, which the governor reads from the plan's meter on Day 1, is likely larger; and if hiring does reach its cap, rounds run in their fallback form instead of stopping. The first weekly review compares the measured cost of `[hiring]` calls with this estimate (Tenet 7).

### Handing work to code and free models (Tenet 7)

Every run starts by loading Claude Code's prompt and the Commandments, so the cheapest Claude turn is the one that never happens. Candidates to hand off, roughly in order of savings:

| Work Claude does today | Hand it to |
| --- | --- |
| Gathering report facts: the scoreboard, commits and events since the last report, links | Done: `tools/report_facts.py` writes `ops/report_facts.md` before every report session |
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
| The supervisor (with its `--dry-run`), governor (with its meter reading), inbox tool, heartbeat, quiet-night check, queue runner, event log, build wrapper, LaunchAgent installer, hiring-round check, report facts, smoke test | The worker generator (with its candidate, hire, and check-name steps) |
| The session prompts (`ops/prompts/`) | The Company Handbook and the character bible |
| The permission rules, the protect-records hook, the security and config guards, the session canary, the model guard, the posture check, and the watchdog | The site's own pages (about, privacy, support, press kit), `site.json`, the registry, and the scoreboard file |
| The rule lookup tool and the worker assembler | |
| The site generator and publisher (`setup/SITE.md`), and the portrait generator | |
| The tests (`tests/run.sh`) | |

All of it arrives in `company` from the Launch Pack template repository, which stays the clean master copy of the kit. Everything in the left column is company-owned once the experiment starts, except what this guide marks as the Investors' (the permission rules, the hooks and guards, the posture check, the file guard, the watchdog, and everything in `rules/` and `investors/`): the company may improve the rest under Commandment 3, logging each change, as long as the behavior this guide requires still holds and `tests/run.sh` still passes, or the tests are updated with a logged reason.

## 13. The site

`setup/SITE.md` is the design: the pages, the data contract, what stays private, and why answers happen on GitHub. In short: `tools/site_build.py` turns `reports/`, `story/`, `personnel/`, `log/events.jsonl`, the usage figures, the scoreboard, and the four written pages into a Jekyll site with three feeds (`feed.xml` for the reports, `feed/updates.xml` for product updates, `feed/records.xml` for the records); `tools/site_publish.sh` runs it at the end of every tick, commits it in the site repository, and pushes it while the Investors' publish switch is on; GitHub Pages renders it. The Investors change the site through `investors/site/` (the publish switch, an announcement, their own styles, pages, and files); hand edits in the site repository are replaced at the next build. No Claude is involved, so the site stays within 15 minutes of the records at no usage cost. The company keeps the data contract's few files current and may restyle the layout under creative approval (Commandment 51); `tests/run.sh` checks the generator.
