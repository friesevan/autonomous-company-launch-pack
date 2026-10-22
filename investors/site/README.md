# The Investors' site controls

This folder belongs to the Investors. The company never edits it: the permission settings deny its edit tools here, and the protect-records hook blocks deleting or moving anything in `investors/`. Edit these files on github.com (the mobile site works), commit, and the change is on the site within about 15 minutes, at the company's next run.

| File | What it does |
| --- | --- |
| `settings.json` | `"publish": true` puts the site online; `false` keeps it offline (the company still builds it, so nothing is lost). `"announcement"` shows a banner on every page; leave it empty for none. |
| `theme.css` | Your styles, added after the site's own, so they win. The colors are variables on `:root` (for example `--accent`, `--ink`, `--bg`). |
| `pages/<name>.md` | Your pages. A file named `about.md`, `privacy.md`, `support.md`, or `press.md` replaces the company's page of that name; any other name adds a page under the About tab. Start the file with front matter (`---`, `title: FAQ`, `---`) and write Markdown. |
| `files/` | Files copied to the site as they are, last, so they win: a `favicon.ico`, images your pages use, or a `CNAME` file holding a custom domain. |

Don't edit the site repository itself: the company rebuilds it from the records every 15 minutes, and anything changed there by hand is replaced. Everything here survives every rebuild.

The site is a creative decision (Commandment 51), so anything here also counts as the Investors' approved style.
