#!/bin/bash
# Rebuild the public site from the company's records and push it. No Claude.
# The site repository is a sibling clone (default ../site, or SITE_DIR). Silent
# when it isn't there, so the loop works before the site is set up. Company-owned.
#   tools/site_publish.sh
cd "$(dirname "$0")/.." || exit 1
SITE_DIR="${SITE_DIR:-$(pwd)/../site}"
[ -d "$SITE_DIR/.git" ] || exit 0
python3 -I tools/site_build.py --out "$SITE_DIR" ${SITE_NO_GH:+--no-gh} || { echo "site build failed"; exit 1; }
cd "$SITE_DIR" || exit 1
[ -n "$(git status --porcelain)" ] || exit 0
git add -A
git -c user.name=Operator -c user.email=operator@company commit -q -m "site: $(date '+%Y-%m-%d %H:%M')" || exit 0
git remote get-url origin >/dev/null 2>&1 && git push -q
exit 0
