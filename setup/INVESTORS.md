# Setup Guide (for the Investors)

Everything in this guide needs a human: a password, a payment, an identity check, or admin rights. Do it in this order. The company builds everything else itself on Day 1.

**The gate.** Day 1 doesn't start until all five are true:

1. The Apple Developer Program membership is active.
2. The Paid Apps Agreement is accepted, tax and banking details are complete, and EU trader status is declared, in App Store Connect.
3. The Small Business Program enrollment is submitted.
4. The Mac mini is set up (sections 1 to 3).
5. GitHub is set up and both of your usernames are in `investors/allowlist.md` (section 4).

Start the Apple steps first (`setup/APPLE.md`). Individual enrollment usually takes a day or two, but identity verification can stretch to weeks. Setup time on Day 1 counts toward the 30 days, so nothing should be waiting on Apple once the first prompt runs.

## 1. Hardware

- [ ] **Mac mini (M1, 16 GB memory, 256 GB storage)**, used, about $320. The research behind this choice is in the appendix of the Launch Pack. Buy from a seller with returns; check the listing says 16 GB; confirm Activation Lock is off and the Mac isn't enrolled in a company's device management when it arrives; erase it and reinstall macOS before setup.
- [ ] Optional: **an external drive** for Time Machine backups. It isn't required. The company pushes everything that matters to GitHub after every run, so a dead disk costs a reinstall from this guide, not the company's work. And the 256 GB internal disk has room for macOS, Xcode, one iOS Simulator runtime, and a small app: about 70 to 100 GB in use. If you have a spare drive of 256 GB or more, use it; don't buy one for this.
- [ ] **Wired Ethernet** if you can. Wi-Fi works.
- [ ] A keyboard, mouse, and display for the setup day. After that the Mac can run with nothing attached.
- [ ] Optional: a small UPS (battery backup). With FileVault on, a power cut leaves the Mac waiting at the password screen until one of you unlocks it (section 2).

## 2. macOS

Create and use one account for the company. Only you two know its password.

- [ ] Update macOS to the current version. **System Settings > General > Software Update > Automatic Updates:** turn on security updates, turn **off** automatic macOS upgrades (a surprise major upgrade can break Xcode mid-month), and turn **off** automatic App Store app updates (an Xcode update can break the toolchain until its license is accepted).
- [ ] **Users & Groups:** create the company account as an Administrator (the company needs to install software; the Commandments forbid it from weakening security). Keep no personal data on this Mac.
- [ ] **Passwordless sudo** for the company account, so the company has full control of the Mac with nobody at the keyboard (Commandment 2). In Terminal, in the company account, run `sudo visudo -f /etc/sudoers.d/company` and add this one line, replacing `<account>` with the output of `whoami`:

  ```
  <account> ALL=(ALL) NOPASSWD: ALL
  ```

  It's your choice, and it carries a risk: a web page the company reads could try to steer a session into admin commands. With passwordless sudo, nothing on the Mac is tamper-proof. The guard hooks and auto mode's classifier protect against accidents and confused sessions, the checks on every tick detect a change within 15 minutes, and the watchdog runs outside the Mac.
- [ ] **Privacy & Security > FileVault:** turn on. **Firewall:** turn on.
- [ ] **Energy:** turn on "Start up automatically after a power failure" and "Prevent automatic sleeping when the display is off". **Lock Screen:** never start the screen saver; never turn the display off on power adapter.
- [ ] **General > Sharing:** turn on **Screen Sharing** and **Remote Login** (SSH), so you can reach the Mac from your own computers. Allow access for the company account only.
- [ ] **Time Machine**, if you have an external drive: back up to it, automatically.
- [ ] Know the FileVault caveat: after a power cut or a restart, the Mac waits at the FileVault screen, and nothing on it runs until someone unlocks it. The watchdog on GitHub alerts you within about an hour (section 4). On macOS 26 or later you can unlock it over SSH from a computer on the same network: run `ssh <account>@<mac-name>.local` and enter the account password. Remote Login must be on, and Ethernet is more reliable than Wi-Fi for this. Otherwise, type the password at the Mac. Apple's guide: [Unlock FileVault using SSH](https://support.apple.com/guide/platform-support/sup909bba3a2).

## 3. Software

Open Terminal in the company account and run these one at a time.

- [ ] **Xcode.** Install it from the Mac App Store, signed in to the App Store only (not iCloud) with the developer Apple Account (`setup/APPLE.md`), or download it from developer.apple.com/download. Leave the Mac signed out of iCloud. Open Xcode once, accept the license, and let it install its components.

  In Xcode, open **Settings > Components** and install the **iOS** platform and the current iOS Simulator runtime (one runtime is enough). Then, in **Settings > Accounts**, add the developer Apple Account.

- [ ] **Homebrew**, from brew.sh, then the command-line tools the company uses:

  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```

  When it finishes, the installer prints the commands that put Homebrew on the PATH. Run them:

  ```bash
  echo >> ~/.zprofile
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  eval "$(/opt/homebrew/bin/brew shellenv)"
  ```

  Then install the tools. Git comes with Xcode; add `git` to this line only if you prefer the current version:

  ```bash
  brew install gh jq
  ```

- [ ] **Point the command-line tools at Xcode**, after Homebrew, because its installer can switch the active developer folder to a separate Command Line Tools package:

  ```bash
  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
  sudo xcodebuild -license accept
  xcodebuild -runFirstLaunch
  ```

- [ ] **Claude Code** (native installer, auto-updates off):

  ```bash
  curl -fsSL https://claude.ai/install.sh | bash
  ```

  It installs to `~/.local/bin`. Put that folder on the PATH, then open a new Terminal window:

  ```bash
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
  ```

  Confirm with `claude --version`: it must be 2.1.293 or later, so that `opus`, `sonnet`, and `haiku` mean the 5.5 models and `fable` means Fable 5.1. Claude Code requires macOS 13 or later.

  Turn off its auto-updates for the experiment, because a future release may change how headless runs behave (`setup/OPERATIONS.md`, section 3). Create the file `~/.claude/settings.json` with this content, making the `~/.claude` folder first if it doesn't exist, or add the `env` entry if the file already exists:

  ```json
  {"env": {"DISABLE_AUTOUPDATER": "1"}}
  ```

  `claude doctor` should then show "Auto-updates: disabled". Then run `claude` once and log in with the company's Claude Max account (section 4).

- [ ] **Claude desktop app** (for the one interactive session on Day 1 and for Computer Use if a task ever needs the screen): download from claude.ai, sign in with the same account.

## 4. Accounts

### Claude

- [ ] A **Claude Max (20x) subscription ($200/month)** on an account nobody uses for anything else. Usage limits are shared between claude.ai and Claude Code, so a personal chat on the same account eats the company's budget.
- [ ] **Leave usage credits off** (claude.ai, Settings > Usage). The plan includes Fable, the most capable model, up to half of the weekly limit; past that, and past any limit, usage credits bill real money. The company's governor stops Fable well before its ceiling, but credits switched off is the guarantee that nothing is ever billed. The Commandments count credits as spending, which needs your approval. This matters even more because the company deliberately uses its whole weekly limit every week (Tenet 7): with credits off, reaching a limit just pauses plan sessions until the reset, while the included API credits keep some work going (below). The governor reads the plan's meter every tick and opens an emergency if it ever finds usage credits switched on.
- [ ] **Claim the API credits** included with the plan. The company uses them only as overflow when a plan limit has paused work: Opus, Sonnet, or Haiku, never Fable, at most $50 a week (Tenet 6). On claude.ai, open **Settings > Billing** and link a Claude Console organization. In the Console, create a workspace for the company and set its monthly spend limit to $180, a hard cap that holds even if the company's own count is wrong; then create an API key in that workspace. Leave auto-reload off and buy no credits, so the worst case is the month's included credits, never a charge. On the Mac mini, in the company account, store the key in the Keychain; the command prompts for it:

  ```bash
  security add-generic-password -s company-api-credits -a company -T /usr/bin/security -w
  ```

  Sessions can't read it: the permission rules and the security guard block that. To stop overflow at any time, set `api_overflow` to false in `investors/billing.json` on github.com.

### Apple

- [ ] Follow **Setting Up Apple Developer Account** (`setup/APPLE.md`): who owns the membership, which Apple Account goes where (including on the Mac mini), and the step-by-step checklist through TestFlight. Start it before anything else in this guide.

### GitHub

- [ ] Both Investors can open the Launch Pack repository, [friesevan/autonomous-company-launch-pack](https://github.com/friesevan/autonomous-company-launch-pack). It is private; its owner adds the other Investor under **Settings > Collaborators**.
- [ ] A **GitHub organization** for the company (free plan). Give it a neutral name, for example after the experiment rather than a brand: its name becomes the site's address (`https://<org>.github.io`) before the company has a name, and a custom domain can carry the brand later. It holds two repositories:
    - `company` (private): all code, logs, records, and the Investor channels. Create it from the Launch Pack template, not empty. First merge the Launch Pack's working branch into `main`, because **Use this template** copies only the default branch. Then, on GitHub, open the Launch Pack repository, then **Use this template > Create a new repository**, with owner = the organization, name = `company`, **Private**. Or run `gh repo create <org>/company --private --template friesevan/autonomous-company-launch-pack`. It arrives with every Launch Pack file in place, the scripts already executable, and a fresh history.
    - `<org>.github.io` (public): the public site, served free by **GitHub Pages** at `https://<org>.github.io`. Create it with a README, so its `main` branch exists, then turn on Pages (**Settings > Pages**, deploy from the `main` branch, root folder). Naming it `site` also works; the address is then `https://<org>.github.io/site`. The company builds it on Day 1 from the shipped generator (`setup/SITE.md`), and it goes online when you set `publish` to true in `investors/site/settings.json` (below).
- [ ] A **separate GitHub account for the company** (a "machine user", free), added to the organization with write access to both repositories. The company posts and replies from this account, so its comments are never confused with yours. Create its **fine-grained personal access token** with the organization as its **resource owner** (an organization owner may need to approve it), covering both repositories, with read and write access to **Contents**, **Issues**, and **Variables** (Variables is for the heartbeat), and no **Workflows** or **Administration** permission. On the Mac mini, in the company account, run `gh auth login` (choose HTTPS, then paste the token), then `gh auth setup-git`, and set the machine user's git identity, with its noreply address from **Settings > Emails** on GitHub:

  ```bash
  git config --global user.name "<machine user>"
  git config --global user.email "<its noreply address>"
  ```

  Put the token's expiry in your calendar.
- [ ] **Both Investors:** install the GitHub mobile app, **watch** the `company` repository (all activity), and turn on push notifications for issues and mentions. This is how emergencies and urgent requests reach you.
- [ ] **The watchdog** comes with `company` (`.github/workflows/watchdog.yml`). GitHub runs it every 30 minutes, outside the Mac, and it opens an `emergency` issue when the Mac's heartbeat stops for 45 minutes. It uses about 1,500 of the 2,000 free GitHub Actions minutes a month for private repositories; nothing else in `company` uses Actions. You test it in the hand-off (section 5).
- [ ] Write both of your GitHub usernames into `investors/allowlist.md`. Only comments and issues from these accounts count as instructions.

### Email and domain

- [ ] A **business email address** (for the developer Apple Account, support, and the App Store listing). A free address is fine.
- [ ] Optional: register a **domain** for the app and the site (approved by default in the Commandments, about $10–15/year) and point it at GitHub Pages; then put the domain in a file named `CNAME` in `investors/site/files/`.

## 5. Hand-off

- [ ] In the `company` repository, put your two GitHub usernames in `investors/allowlist.md` (editing it on github.com is fine) and commit.
- [ ] On the Mac mini, in the company account: `gh repo clone <org>/company`, then `cd company`. Run `tests/run.sh` once: it checks the run loop in about a minute, uses no Claude usage, and should end with "All tests passed." If any script shows up without execute permission (`ls -l tools`), run `chmod +x rules/*.py rules/*.sh rules/hooks/*.sh rules/hooks/*.py tools/*.sh tools/*.py tests/*.sh tests/*.py`, then commit and push.
- [ ] In the `company` folder, run `claude` once, accept the trust dialog, and type `/exit`. Headless runs use the project's allow rules only after that.
- [ ] Run `tools/smoke_test.sh` from Terminal in the same folder: one tiny real run that checks the subscription login, auto mode, the hooks canary, and that `CLAUDE.md` loaded. It prints a pass or what to fix.
- [ ] Test the watchdog: in `company` on github.com, open **Actions > Watchdog > Run workflow**, check "test", and run it. It opens and closes a test issue, so you both get the push notification.
- [ ] Check the gate (top of this guide). If anything is still pending with Apple, wait.
- [ ] Open Terminal in the repository folder, run `claude --model opus`, and paste the contents of `ops/prompts/day1.md`. Day 1 writes the CEO and the Handbook, which shape the whole month, so it runs on Opus. This is the first prompt. It records today as Day 1 and starts the 30 days.
- Usage needs nothing from you: the governor reads the plan's meter itself. If it can't read it, the governor falls back to its estimate and says so on the usage page.
- [ ] Watch the first hour. Approve permission prompts if any appear (the first interactive session may ask; later runs don't). Then step back. The first report is published at 6:00 p.m., and its questions arrive as a GitHub issue.

## 6. Running the experiment

**The reports.** The CEO writes you a report at 6:00 p.m. Eastern every day, and at 6:00 a.m. unless nothing happened overnight; a quiet night means no morning report, and the evening report covers both. A report is her business update: what got done on the product, what's blocked, and what comes next, with one line of usage as percentages of the plan's limits. The company's story, the workers' diaries, conversations, and hiring rounds, is in the site's Records section instead. Each report ends with its **Questions for the Investors**: approvals, outreach proposals, builds to test, numbered questions with options and a recommendation, decisions since the last report, spending, upcoming needs. The questions appear only in the report's private copy on GitHub, never on the public site. The site also updates between reports: every worker's page, the combined log, usage, and open requests are rebuilt from the records after every run, about every 15 minutes.

**Answering a report's questions.** Every report has a private copy: a GitHub issue labeled `report` with the full report and its questions, linked from the report and listed on the site's Requests page. Reply there as a comment by midnight on the day it's posted. Plain language works. For numbered questions, a short convention helps the company parse your answer: "1: A", "2: no, because...", "APPROVE 3", "REJECT 2: too busy". If you don't answer by the deadline, the company takes the default action it stated, unless the question was creative, outreach, or spending, which never default. You can answer as many times as you like: your latest answer counts, and an answer that comes after a default still counts, so the company reverses the default if it can. Every message gets a reply confirming it arrived and saying what the company understood, and the company may ask a follow-up in the same thread. Anything that must stay private is in the issue only, never on the site.

**Message the company at any time.** Open a new issue in `company` (any label; `directive` is suggested) or comment on any existing issue; the site's Requests page has a "Message the company" link that opens one prefilled. The company reads every new comment and issue from your accounts within about 15 minutes, replies to confirm it arrived and say what it will do, acts on it from that run, and notes it in the next report. If no session can reply right away, because of a usage limit, a logged-out Claude Code, or a report in progress, a short receipt says when it will reply (for example, "Received (Tue 9:42 PM ET). The company is at its 5-hour usage limit until Tue 3:00 PM ET and will reply then."). Announcements, questions, feedback, and new rules all work this way.

**Publishing and changing the site.** The site stays offline until you approve it. After the first report, open `investors/site/settings.json` in the `company` repository on github.com, set `"publish": true`, and commit; the site is live within about 15 minutes. Set it back to `false` to take it offline. The same folder lets you post an announcement banner on every page, restyle the site (`theme.css`), add or replace pages (`pages/`), and add files such as a favicon or a `CNAME` for a custom domain (`files/`); its README explains each. The company never edits that folder, and hand edits in the site repository are replaced at the next build.

**Getting notified.** The site has three feeds: `feed.xml` for the reports, `feed/updates.xml` for product updates such as builds, TestFlight, the App Store, and sales, and `feed/records.xml` for the records. Its Subscribe page, under About, lists their addresses. Add a feed to a reader app with notifications. NetNewsWire (free) supports notifications per feed, but iOS decides when it checks, so alerts can lag. For near-instant alerts, a paid service such as Feedbin with its notifier app would need spending approval. The site itself updates about every 15 minutes.

**Emergencies.** An issue labeled `emergency` @mentions you both, at any hour: a security problem, an unexpected charge, a legal threat, a suspension, harm to a customer, or the company having stopped. When the Mac itself has gone silent, the watchdog on GitHub sends that last one. Whoever is free first handles it.

**Urgent requests.** An issue labeled `urgent` @mentions you both when the company needs something that shouldn't wait for the next report because it blocks work: a CAPTCHA, a code, a signature, a blocking question or approval. Do the thing or answer, and comment "done". They are held during quiet hours (10 p.m. to 8 a.m.), and there should be no more than about 5 a day; follow-up questions in an existing thread don't count. Every open one is also listed on the site's Requests page. The company never depends on a fast answer. Change any of these rules whenever you like, in any reply.

**Real-world help.** The company may ask you for any real-world task it can't do from the Mac mini (Commandment 61): in a report, or as an urgent request when an early answer helps. A heavy computing job comes as a package from the repository with the command to run, how long it takes, and where to put the output, for example to run on the M2 Max MacBook Pro. It never asks for access to your computer or anything on it.

**Changing a rule.** Say it in any comment or issue, for example "RULE: from now on the 6 a.m. report may be skipped on quiet nights." The company copies your exact words into `amendments.md`, which overrides the Commandments from the next run. To make it permanent and tidy, edit `CLAUDE.md` yourself and commit; the company notices the new version and follows it.

**TestFlight builds.** When a report lists a build to test, open TestFlight on your iPhone, install it, and put your feedback in your reply to that report's questions.

**Customer support.** The support inbox is yours until you hand it to workers in a reply to a report's issue.

**Pausing and stopping.** Start a comment or a new issue with `PAUSE` or `STOP`, and the company stops within about 5 minutes, with no Claude session needed (the supervisor checks at every tick, and every 5 minutes during a session, which it ends), and confirms it in the thread: no sessions or queued jobs run until you send `RESUME` the same way. The heartbeat continues while paused, so the watchdog stays quiet. When the experiment ends or is paused for a long time, turn off the watchdog too: in `company` on github.com, open **Actions > Watchdog** and choose **Disable workflow**. Stopping the loop at the machine level also stops the heartbeat, so disable the watchdog first, then run:

```bash
launchctl bootout gui/$(id -u)/com.company.supervisor
```

**When something looks wrong:**

| Symptom | What to do |
| --- | --- |
| No 6 p.m. report, or no commits for several hours (a missing 6 a.m. report after a quiet night is normal) | Check the Mac: is it at the FileVault screen (power cut or restart)? Unlock it over SSH or type the password (section 2). Otherwise open Terminal in the repo and run `python3 tools/governor.py status` and `tail -50 ops/runs/supervisor.log`. |
| "You've hit your weekly limit" in the run log | Expected near the end of each week: the company aims to use the whole limit (Tenet 7). It runs its no-Claude queue, and overflow sessions on the included API credits, until the reset. If it happens a day or more early, the governor lowers its budget to what was really spent, so the next week paces correctly. |
| An emergency issue: "Claude Code is logged out on the Mac mini" | On the Mac mini, in the company account, open Terminal, run `claude`, type `/login`, and sign in with the company's Claude account. Work resumes within an hour. |
| An emergency issue: "The company has stopped: no heartbeat from the Mac mini since ..." | The watchdog on GitHub hasn't heard from the Mac for 45 minutes. Check the likely causes the issue lists and follow its steps: a restart or power cut that left the Mac at the FileVault screen (unlock it, section 2), the network, an expired GitHub token (make a new one and run `gh auth login`, section 4), or a stopped run loop. When the heartbeat returns, the watchdog comments "back online" and closes the issue. |
| You want to know where the usage goes | The site's Usage page, or `python3 tools/governor.py status`: the week by category (project, reports, meetings, hiring, small talk), product work by kind, and Fable's allowance; the weekly report summarizes it. |
| An App Review rejection email | Nothing to do; the company reads it from App Store Connect, fixes, and resubmits. It'll be in the next report. |
| Apple asks for a two-factor code | That's an Urgent Request. Enter the code where Apple asks; comment "done". |
| The company asks for money | It's in a report's questions, with the cost, reason, and the free alternative it tried. Approve or reject there. |
| You want to see everything the company did today | The repository's commit history and `ops/runs/`, plus the evening report. |

## 7. Where credentials live

| Credential | Where | Who can see it |
| --- | --- | --- |
| Company account password (macOS) | Your password managers | Investors only |
| Claude Max login | Claude Code and the desktop app, signed in once | The company uses it; never reads it |
| Apple Account password and 2FA | Your password managers and phones | Investors only |
| App Store Connect API key (`.p8`, Key ID, Issuer ID, Team ID) | `~/.appstoreconnect/private_keys/` and `ops/secrets.local` on the Mac mini | The company's tools use it; the Commandments forbid publishing it |
| API key for the included API credits | The company account's Keychain, item `company-api-credits` | Only sessions on the credits use it, through `rules/api-settings.json`; the permission rules and the security guard keep sessions from reading it |
| GitHub token | `gh auth` on the Mac mini | The company uses it |
| Everything else the company creates | The company account's Keychain | Reported in a report |
