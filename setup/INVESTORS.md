# Setup Guide (for the Investors)

Everything in this guide needs a human: a password, a payment, an identity check, or admin rights. Do it in this order. The company builds everything else itself on Day 1.

**The gate.** Day 1 doesn't start until all five are true:

1. The Apple Developer Program membership is active.
2. The Paid Apps Agreement is accepted, and tax and banking details are complete, in App Store Connect.
3. The Small Business Program enrollment is submitted.
4. The Mac mini is set up (sections 1 to 3).
5. GitHub is set up and both of your usernames are in `investors/allowlist.md` (section 4).

Start the Apple steps first. Individual enrollment usually takes a day or two, but identity verification can stretch to weeks. Setup time on Day 1 counts toward the 30 days, so nothing should be waiting on Apple once the first prompt runs.

## 1. Hardware

- [ ] **Mac mini (M1, 16 GB memory, 256 GB storage)**, used, about $320. The research behind this choice is in the appendix of the Launch Pack. Buy from a seller with returns; check the listing says 16 GB; confirm Activation Lock is off and the Mac isn't enrolled in a company's device management when it arrives; erase it and reinstall macOS before setup.
- [ ] **An external SSD (1 TB, about $75–130)** for Time Machine backups, and as overflow storage if Xcode fills the internal disk.
- [ ] **Wired Ethernet** if you can. Wi-Fi works.
- [ ] A keyboard, mouse, and display for the setup day. After that the Mac can run with nothing attached.
- [ ] Optional: a small UPS (battery backup). With FileVault on, a power cut leaves the Mac waiting at the password screen until one of you types it (section 2).

## 2. macOS

Create and use one account for the company. Only you two know its password.

- [ ] Update macOS to the current version. **System Settings > General > Software Update > Automatic Updates:** turn on security updates, turn **off** automatic macOS upgrades (a surprise major upgrade can break Xcode mid-month).
- [ ] **Users & Groups:** create the company account as an Administrator (the company needs to install software; the Commandments forbid it from weakening security). Keep no personal data on this Mac.
- [ ] **Privacy & Security > FileVault:** turn on. **Firewall:** turn on.
- [ ] **Energy:** turn on "Start up automatically after a power failure" and "Prevent automatic sleeping when the display is off". **Lock Screen:** never start the screen saver; never turn the display off on power adapter.
- [ ] **General > Sharing:** turn on **Screen Sharing** and **Remote Login** (SSH), so you can reach the Mac from your own computers. Allow access for the company account only.
- [ ] **Time Machine:** back up to the external SSD, automatically.
- [ ] Know the FileVault caveat: after a power cut, the Mac waits at the FileVault screen and Screen Sharing won't work until someone types the password at the keyboard. Nothing can alert you while it waits there, so a missing report is the sign. The company reports an unexpected stop as soon as it is running again.

## 3. Software

Open Terminal in the company account and run these one at a time.

- [ ] **Xcode.** Install from the Mac App Store, open it once, accept the license, and let it install its components. Then, in Terminal:

  ```bash
  xcode-select --install
  ```

  In Xcode, open **Settings > Components** and install the **iOS** platform and the current iOS Simulator runtime.

- [ ] **Homebrew**, then the command-line tools the company uses:

  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```

  ```bash
  brew install git gh jq
  ```

- [ ] **Claude Code** (native installer, auto-updates):

  ```bash
  curl -fsSL https://claude.ai/install.sh | bash
  ```

  Open a new Terminal window and confirm with `claude --version`: it must be 2.1.293 or later, so that `opus`, `sonnet`, and `haiku` mean the 5.5 models and `fable` means Fable 5.1. Then run `claude` once and log in with the company's Claude Max account (section 4). Claude Code requires macOS 13 or later.

- [ ] **Claude desktop app** (for the one interactive session on Day 1 and for Computer Use if a task ever needs the screen): download from claude.ai, sign in with the same account.

## 4. Accounts

### Claude

- [ ] A **Claude Max (20x) subscription ($200/month)** on an account nobody uses for anything else. Usage limits are shared between claude.ai and Claude Code, so a personal chat on the same account eats the company's budget.
- [ ] **Leave usage credits off** (claude.ai, Settings > Usage). The plan includes Fable, the most capable model, up to half of the weekly limit; past that, and past any limit, usage credits bill real money. The company's governor stops Fable well before its ceiling, but credits switched off is the guarantee that nothing is ever billed. The Commandments count credits as spending, which needs your approval. This matters even more because the company deliberately uses its whole weekly limit every week (Tenet 7): with credits off, reaching a limit just pauses work until the reset.

### Apple

- [ ] **Company Apple ID.** Create it with the business email address (below), on appleid.apple.com. Turn on two-factor authentication; the codes come to one of your phones.
- [ ] **Apple Developer Program ($99/year), as an individual.** Enroll at developer.apple.com/programs/enroll. There is no LLC, so the enrolling Investor's legal name appears as the seller on the App Store; the company's chosen name still appears inside the app and on its site. Make sure the Apple ID's name, region, and phone number match the ID you'll verify with. Expect anywhere from a day to several weeks.
- [ ] **App Store Connect agreements.** Once the membership is active, sign in to appstoreconnect.apple.com as the Account Holder, open **Business** (or **Agreements, Tax, and Banking**), accept the **Paid Apps Agreement**, and complete the tax forms and banking details. Nothing can be sold until these show as active.
- [ ] **Small Business Program.** Enroll at developer.apple.com/app-store/small-business-program/enroll as the Account Holder. New developers qualify. The 15% rate starts 15 days after the end of the Apple fiscal month in which you're approved, so month one will most likely be at 30%.
- [ ] **App Store Connect API key.** In App Store Connect, **Users and Access > Integrations > App Store Connect API**: generate a key with the **App Manager** role. Download the `.p8` file (it's offered once). On the Mac mini, place it at `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8` in the company account, and store the Key ID and Issuer ID in the Keychain or in `ops/secrets.local` (ignored by git). This lets the company upload builds and read sales without two-factor prompts.
- [ ] **Xcode sign-in.** In Xcode, **Settings > Accounts**, add the company Apple ID so builds are signed automatically. This asks for a two-factor code once.
- [ ] **The other Investor** as an App Store Connect user with the **App Manager** role (**Users and Access > Users**), so both of you can be internal TestFlight testers.
- [ ] **TestFlight** on both of your iPhones. Internal testers (members of the App Store Connect team, up to 100) get builds within minutes of upload with no Beta App Review. Builds expire after 90 days.

### GitHub

- [ ] Both Investors can open the Launch Pack repository, [friesevan/autonomous-company-launch-pack](https://github.com/friesevan/autonomous-company-launch-pack). It is private; its owner adds the other Investor under **Settings > Collaborators**.
- [ ] A **GitHub organization** for the company (free plan), with two repositories:
    - `company` (private): all code, logs, records, and the Investor channels. Create it from the Launch Pack template, not empty: on GitHub, open the Launch Pack repository, then **Use this template > Create a new repository**, with owner = the organization, name = `company`, **Private**. Or run `gh repo create <org>/company --private --template friesevan/autonomous-company-launch-pack`. It arrives with every Launch Pack file in place, the scripts already executable, and a fresh history.
    - `site` (public): the reports, cast page, privacy policy, and support page, served free by **GitHub Pages** (**Settings > Pages**, deploy from the `main` branch).
- [ ] A **separate GitHub account for the company** (a "machine user", free), added to the organization with write access to both repositories. The company posts and replies from this account, so its comments are never confused with yours. Create its **fine-grained personal access token** limited to these two repositories, with read and write access to **Contents** and **Issues**. On the Mac mini, run `gh auth login` and paste it. Put the token's expiry in your calendar.
- [ ] **Both Investors:** install the GitHub mobile app, **watch** the `company` repository (all activity), and turn on push notifications for issues and mentions. This is how emergencies and urgent requests reach you.
- [ ] Write both of your GitHub usernames into `investors/allowlist.md`. Only comments and issues from these accounts count as instructions.

### Email and domain

- [ ] A **business email address** (for the Apple ID, support, and App Store listing). A free address is fine.
- [ ] Optional: register a **domain** for the app and the site (approved by default in the Commandments, about $10–15/year) and point it at GitHub Pages.

## 5. Hand-off

- [ ] In the `company` repository, put your two GitHub usernames in `investors/allowlist.md` (editing it on github.com is fine) and commit.
- [ ] On the Mac mini, in the company account: `gh repo clone <org>/company`, then `cd company`. Run `tests/run.sh` once: it checks the run loop in about a minute, uses no Claude usage, and should end with "All tests passed." If any script shows up without execute permission (`ls -l tools`), run `chmod +x rules/*.py rules/hooks/*.sh rules/hooks/*.py tools/*.sh tools/*.py tests/*.sh tests/*.py`, then commit and push.
- [ ] Check the gate (top of this guide). If anything is still pending with Apple, wait.
- [ ] Open Terminal in the repository folder, run `claude --model opus`, and paste the contents of `ops/prompts/day1.md`. Day 1 writes the CEO and the Handbook, which shape the whole month, so it runs on Opus. This is the first prompt. It records today as Day 1 and starts the 30 days.
- [ ] When the first session asks, run `/usage` in an interactive `claude` session and tell it three things: the weekly percentage used, the Fable percentage used, and when the weekly limit resets. The governor calibrates from them.
- [ ] Watch the first hour. Approve permission prompts if any appear (the first interactive session may ask; later runs don't). Then step back. The first Daily Brief arrives at 6:00 p.m. as a GitHub issue.

## 6. Running the experiment

**The reports.** The public site gets a report at 6:00 p.m. Eastern every day, and at 6:00 a.m. unless nothing happened overnight; a quiet night means no morning report, and the evening report covers both.

**The Daily Brief.** Every day at 6:00 p.m. Eastern, an issue labeled `brief` appears in `company`, alongside the evening report on the site. Reply by midnight as a comment. Plain language works. For numbered questions, a short convention helps the company parse your answer:

```
APPROVE 1
REJECT 2: the name is too close to an existing app
3: option B
```

If you don't answer a question by midnight, the company takes the default action it stated, unless the question was creative, outreach, or spending, which never default.

**Message the company at any time.** Open a new issue in `company` (any label; `directive` is suggested) or comment on any existing issue. The company reads every new comment and issue from your accounts within about 15 minutes, replies to acknowledge it, acts on it from that run, and notes it in the next Brief. Announcements, questions, feedback, and new rules all work this way.

**Emergencies.** An issue labeled `emergency` @mentions you both, at any hour: a security problem, an unexpected charge, a legal threat, a suspension, harm to a customer, or the company having stopped. Whoever is free first handles it.

**Urgent requests.** An issue labeled `urgent` @mentions you both when the company needs something that shouldn't wait for the Brief because it blocks work: a CAPTCHA, a code, a signature, a blocking question or approval. Do the thing or answer, and comment "done". They are held during quiet hours (10 p.m. to 8 a.m.), and there should be no more than about 5 a day. The company never depends on a fast answer. Change any of these rules whenever you like, in any reply.

**Real-world help.** The company may ask you for any real-world task it can't do from the Mac mini (Commandment 61): in the Brief, or as an urgent request when an early answer helps. A heavy computing job comes as a package from the repository with the command to run, how long it takes, and where to put the output, for example to run on the M2 Max MacBook Pro. It never asks for access to your computer or anything on it.

**Changing a rule.** Say it in any comment or issue, for example "RULE: from now on the 6 a.m. report may be skipped on quiet nights." The company copies your exact words into `amendments.md`, which overrides the Commandments from the next run. To make it permanent and tidy, edit `CLAUDE.md` yourself and commit; the company notices the new version and follows it.

**TestFlight builds.** When the Brief lists a build to test, open TestFlight on your iPhone, install it, and put your feedback in your Brief reply.

**Customer support.** The support inbox is yours until you hand it to workers in a Brief reply.

**Pausing and stopping.** Comment `PAUSE` or `STOP` in any issue and the company stops at the start of its next run and saves its state. To stop the loop at the machine level:

```bash
launchctl bootout gui/$(id -u)/com.company.supervisor
```

**When something looks wrong:**

| Symptom | What to do |
| --- | --- |
| No 6 p.m. report or Brief, or no commits for several hours (a missing 6 a.m. report after a quiet night is normal) | Check the Mac: is it at the FileVault screen (power cut)? Type the password. Otherwise open Terminal in the repo and run `python3 tools/governor.py status` and `tail -50 ops/runs/supervisor.log`. |
| "You've hit your weekly limit" in the run log | Expected near the end of each week: the company aims to use the whole limit (Tenet 7). It runs its no-Claude queue until the reset. If it happens a day or more early, the governor lowers its budget to what was really spent, so the next week paces correctly. |
| An emergency issue: "Claude Code is logged out on the Mac mini" | On the Mac mini, in the company account, open Terminal, run `claude`, type `/login`, and sign in with the company's Claude account. Work resumes within an hour. |
| You want to know where the usage goes | `python3 tools/governor.py status` shows the week by category (project, reports, meetings, small talk) and Fable's allowance; the weekly report summarizes it. |
| An App Review rejection email | Nothing to do; the company reads it from App Store Connect, fixes, and resubmits. It'll be in the next report. |
| Apple asks for a two-factor code | That's an Urgent Request. Enter the code where Apple asks; comment "done". |
| The company asks for money | It's in the Brief with the cost, reason, and the free alternative it tried. Approve or reject there. |
| You want to see everything the company did today | The repository's commit history and `ops/runs/`, plus the evening report. |

## 7. Where credentials live

| Credential | Where | Who can see it |
| --- | --- | --- |
| Company account password (macOS) | Your password managers | Investors only |
| Claude Max login | Claude Code and the desktop app, signed in once | The company uses it; never reads it |
| Apple ID password and 2FA | Your password managers and phones | Investors only |
| App Store Connect API key (`.p8`, Key ID, Issuer ID) | `~/.appstoreconnect/private_keys/` and `ops/secrets.local` on the Mac mini | The company's tools use it; the Commandments forbid publishing it |
| GitHub token | `gh auth` on the Mac mini | The company uses it |
| Everything else the company creates | The company account's Keychain | Reported in the Brief |
