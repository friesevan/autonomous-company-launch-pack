# Autonomous Company Launch Pack

Start here. This repository holds everything needed to start the experiment: an AI-run company with one Mac mini, one Claude Max subscription, and 30 days to build and sell an iOS app that earns $200.

## Where this lives, and how to get it

**This repository is the master copy of the kit**: [friesevan/autonomous-company-launch-pack](https://github.com/friesevan/autonomous-company-launch-pack), private, set up as a GitHub template. The company doesn't run from it. Before Day 1, the Investors create the company's own private repository, `company`, from this template (Setup Guide, section 4). It starts with every file below in place, the scripts already executable, and a fresh history. From then on the company commits to `company` every 15 minutes, and this repository stays clean for the next month or the next run. An improvement worth keeping is copied back here by the Investors.

| To | Do this |
| --- | --- |
| Create the company's repository | On GitHub, open this repository, then **Use this template > Create a new repository**: owner = the company's organization, name = `company`, **Private**. Or, from a terminal: `gh repo create <org>/company --private --template friesevan/autonomous-company-launch-pack` |
| Get it onto the Mac mini | In the company's macOS account: `gh repo clone <org>/company` |
| Read or edit the kit itself | `gh repo clone friesevan/autonomous-company-launch-pack` |
| Check the run loop | `tests/run.sh` (about a minute, uses no Claude usage; see `tests/README.md`) |

The repository is private. Its owner adds the other Investor under **Settings > Collaborators**, so both can read it and create from it. The Launch Pack doc on claude.ai mirrors these guides and has two extra tabs that aren't needed to start: the review and recommendations, and the hardware research.

**Two outputs, one priority.** The company must produce a business, and an honest, readable story of how it was built. When the two compete, the business wins.

## The timeline

| When | What happens | Who |
| --- | --- | --- |
| Before Day 1 | The Setup Guide: hardware, macOS, software, Apple, GitHub. The gate must be fully passed. | Investors |
| Day 1 | The company sets itself up: the CEO, the Handbook, the run loop, the channels, the site. First report at 6 p.m. | The company |
| Day 2 (target) | The Pitch: the top product candidates, presented to the Investors | The company; Investors choose |
| Days 3 to about 16 | Build, TestFlight builds to the Investors, press kit and launch plan drafted | The company; Investors test |
| About Day 17 | App Store submission; App Review usually takes 1 to 3 days | The company |
| Launch to Day 30 | Sell and keep improving; the Investors announce the launch | Both |
| Days 7, 14, 21, 28 | Weekly report inside the evening report | The company |
| Day 30 | The Final Report, with every worker's testimony, and one of three endings: Continue, Request for More Funding, or File for Bankruptcy | The company proposes; Investors decide |

The CEO's reports publish on a public site at 6 p.m. Eastern every day, and at 6 a.m. unless the night was quiet. Each report is her business update, with the company's usage as percentages of the plan's limits, and ends with its Questions for the Investors, answered on the report's private copy, a GitHub issue linked from it; the public site never shows the questions. The company's story, the workers' diaries, conversations, and hiring rounds, is in the site's Records section. Between reports the records, cast pages, log, usage, and open requests update after every run. The site goes online when the Investors switch it on in `investors/site/settings.json`. The Investors can message the company at any time through a GitHub issue.

## The gate (before Day 1)

Day 1 does not start until all five are true. Setup time on Day 1 counts toward the 30 days, so nothing should still be waiting on Apple.

1. The Apple Developer Program membership is active (individual enrollment; one day to several weeks).
2. The Paid Apps Agreement is accepted, and tax and banking are complete, in App Store Connect.
3. The Small Business Program enrollment is submitted.
4. The Mac mini is set up with Xcode, Homebrew, Claude Code, and the Claude desktop app.
5. GitHub is set up and both Investors' usernames are in `investors/allowlist.md`.

## Reading order

1. `setup/APPLE.md`: Setting Up Apple Developer Account. Start it first; Apple's identity check is the longest wait.
2. `setup/INVESTORS.md`: the Setup Guide. Do it in order.
3. `CLAUDE.md`: the Commandments, the rules the company lives by. Read them once in full.
4. `setup/OPERATIONS.md`: how the company runs itself. Read it to know what to expect; the company builds it.
5. `rules/worker-rules.md`: the one-page rulebook every worker carries.
6. `ops/prompts/day1.md`: the first prompt. You paste it into Claude Code once.

## The files

| File | What it is | Who edits it |
| --- | --- | --- |
| `README.md` | This page | Investors |
| `CLAUDE.md` | The Commandments, loaded into every Operator session | Investors |
| `amendments.md` | Investor rule changes, recorded verbatim; loads with the Commandments | The company appends; Investors may edit |
| `rules/worker-rules.md` | The one-page rulebook built into every worker, including No AI Art in full | Investors |
| `rules/lookup.py` | Prints one Commandment, section, or search result, with any amendment that changes it | Investors |
| `rules/build_agents.py` | Combines each worker's persona with the worker rules and amendments before every run | Investors |
| `rules/hooks/protect-records.sh` | Blocks deleting or moving logs, story, reports, and the Investors' files | Investors |
| `rules/hooks/model-guard.py` | Refuses Fable once its weekly allowance is used, and keeps diaries and small talk on Haiku | Investors |
| `setup/APPLE.md` | Setting Up Apple Developer Account: who owns it, which Apple Account goes where, the steps | Investors |
| `setup/INVESTORS.md` | The Setup Guide | Investors |
| `setup/SITE.md` | The site: pages, data contract, how it updates, answering on GitHub | Investors |
| `setup/OPERATIONS.md` | The Operations Guide | Investors |
| `investors/allowlist.md` | GitHub usernames whose messages count as instructions | Investors |
| `investors/site/` | The Investors' site controls: the publish switch, an announcement, styles, pages, and files | Investors |
| `.claude/settings.json` | Permission allow and deny rules, the two hooks, subagent limits | Investors |
| `ops/prompts/day1.md` | The first prompt | Investors |
| `ops/prompts/work.md`, `morning.md`, `evening.md` | The fixed prompts for each session type | The company may improve |
| `tools/supervisor.sh`, `governor.py`, `inbox_check.sh`, `quiet_night.py`, `run_queue.sh`, `events.py`, `xc.sh`, `install-launchd.sh` | The run loop and usage governor, tested and ready to install on Day 1 | The company may improve |
| `tools/site_build.py`, `tools/site_publish.sh`, `tools/portrait.py` | The public site generator and publisher, and the animated portrait generator, tested | The company may improve |
| `tools/hiring_check.py` | Checks that every hire went through a complete hiring round, in order (Commandment 18) | The company may improve |
| `tools/report_facts.py` | Gathers everything a report needs into one file before each report session, without Claude | The company may improve |
| `ops/launchd/` | The LaunchAgent template (every 15 minutes) | The company may improve |
| `tests/run.sh`, `tests/*_test.sh`, stand-ins | 197 checks of the run loop, governor, model guard, site generator, portraits, report facts, and hiring-round check, run with a stand-in `claude` and `gh` | The company may improve |
| `.gitignore`, `ops/queue/README.md` | Housekeeping | The company may improve |

The `company` repository, created from this template, starts with all of these. The company creates everything else. Every worker has a first name only.

## Two blanks to fill before Day 1

- The two GitHub usernames in `investors/allowlist.md`, edited in the `company` repository.
- Nothing else. Day 1's date is recorded by the company when the first prompt runs.
