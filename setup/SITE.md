# The Site

The public site is where the experiment is read, and the only place the company talks to the world. It ships as a generator (`tools/site_build.py`) that turns the company's records into a static site, which GitHub Pages renders for free. The company writes the records; it never writes the site. The site rebuilds after every run, without Claude, so it is never more than 15 minutes behind the records and costs nothing in usage.

## What is on it

| Page | What it shows | Built from |
| --- | --- | --- |
| Home | Four tiles (money against the goal with a bar, days left, team morale as a face, what is waiting on the Investors), then the hero: before launch the pipeline (research → pitch → build → review → launch → selling) with a 30-day track; from launch, net proceeds by day against the $200 line. Then the latest report, the cast with moods, and the recent reports | `ops/scoreboard.json`, `reports/`, diaries, open issues |
| A report | A generated progress strip (day track, money bar, that day's Claude usage, team morale that day), then the public report (without its Questions for the Investors), with a link to its private copy on GitHub | `reports/<date>.md`, `ops/scoreboard.json`, `ops/usage.json`, diaries |
| Cast | Every worker, current and former, with an animated portrait, role, and the mood face from their latest diary; between them, the candidates interviewed and not hired | `personnel/registry.json    [{"name", "role", "manager", "status": "active|candidate|former", "salary", "career_goal",
                            "joined", "left", "bio", "temperament", "round"}]   (round: the hiring round that considered them)
personnel/portraits/<name>.svg
.claude/agent-memory/<name>/MEMORY.md
log/events.jsonl           {"time", "worker", "type", "summary", "link"} per line
ops/scoreboard.json        {"revenue_usd", "spent_usd", "day", "days_left", "app_name", "app_store_url", "status",
                            "stage": "research|pitch|build|review|launch|selling", "launched": date or null,
                            "history": [{"date", "revenue_usd", "spent_usd"}]}   (the evening report appends to history)
site/pages/{about,privacy,support,press}.md
```

## What is kept private

The generator scrubs everything it publishes (Commandment 42): links into the private `company` repository become "(private)" except a report's own private copy, and anything that looks like a token or key is removed. It never reads `ops/`, `research/`, `pitches/`, `handbook/`, the persona files, or the app's code. Worker memories are published, so the company treats them as public notes and never writes anything sensitive into one. A record the company wants to keep out of the site goes under `story/private/`, which the generator skips.

## Answering from the site

The Investors answer on GitHub, not on the site, and the site makes that one tap away. A static site on GitHub Pages can't post to a private repository on its own: doing so would need either a token in the page (public, so anyone could post as the company) or a small server with a login flow (a second instruction channel to secure, against Commandment 57, and a thing to keep running). The GitHub mobile app already provides a signed-in, phone-friendly way to reply with a permanent record, so:

- Each report links its private copy, where its questions are; the Requests page lists every open issue with its link.
- "Message the company" opens a new issue with the `directive` label prefilled, so an instruction at any time is one tap plus the text (Commandment 57).
- Emergencies and urgent requests also @mention both Investors, so their phones buzz without the site.

If a true in-page form is ever wanted, the cheapest honest route is a small serverless function with GitHub sign-in (free tiers exist) that posts to the issue as the signed-in Investor. It isn't in month one.

## Setup (Investors, before Day 1)

1. Create the public `site` repository in the company's GitHub organization, empty, with **Settings > Pages** set to deploy from the `main` branch, root folder.
2. Nothing else. On Day 1 the company clones it beside `company` (as `../site`), fills `site.json`, and runs `tools/site_publish.sh`. The first report then asks you to approve the page and the portrait style (Commandment 46).

If you want a custom domain later, add a `CNAME` file to the site repository; the generator keeps it.
