#!/bin/bash
# Rebuild the public site from the company's records and push it. No Claude.
# The site repository is a sibling clone (default ../site, or SITE_DIR). Silent
# when it isn't there, so the loop works before the site is set up.
#
# The Investors control publishing (Commandment 46): the site is always built and
# committed in the clone, but pushed to GitHub Pages only while "publish" is true
# in investors/site/settings.json, a file the company never edits. Company-owned.
#   tools/site_publish.sh
cd "$(dirname "$0")/.." || exit 1
SITE_DIR="${SITE_DIR:-$(pwd)/../site}"
[ -d "$SITE_DIR/.git" ] || exit 0
PUBLISH="$(python3 -I -c 'import json, sys
try:
    print("yes" if json.load(open(sys.argv[1], encoding="utf-8")).get("publish") is True else "no")
except Exception:
    print("no")' investors/site/settings.json 2>/dev/null)"
python3 -I tools/site_build.py --out "$SITE_DIR" ${SITE_NO_GH:+--no-gh} || { echo "site build failed"; exit 1; }
cd "$SITE_DIR" || exit 1
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git -c user.name=Operator -c user.email=operator@company commit -q -m "site: $(date '+%Y-%m-%d %H:%M')" || true
fi
if [ "$PUBLISH" != yes ]; then
  echo "site built and committed locally; unpublished until the Investors set publish to true in investors/site/settings.json"
  exit 0
fi
git remote get-url origin >/dev/null 2>&1 || exit 0
# Push when something is new: always on the first push to an empty repository, which
# has no upstream yet, and GitHub Pages serves the main branch.
[ "$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo new)" = 0 ] || git push -q -u origin HEAD:main
exit 0
