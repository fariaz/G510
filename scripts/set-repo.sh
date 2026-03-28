#!/usr/bin/env bash
# scripts/set-repo.sh — patch all placeholder values for your GitHub repo.
#
# Run this ONCE after cloning, before your first commit:
#
#   bash scripts/set-repo.sh YOUR_GITHUB_USERNAME your@email.com
#
# Example:
#   bash scripts/set-repo.sh alice alice@example.com
#
# What it patches:
#   - GitHub URLs  (fariaz → your username)
#   - Maintainer   (fariaz@users.noreply.github.com → your email)
#   - PPA path     (fariaz/g510 → your ppa path)
#   - Vcs-Git/Browser in debian/control

set -euo pipefail

GITHUB_USER="${1:-}"
EMAIL="${2:-}"

if [[ -z "$GITHUB_USER" || -z "$EMAIL" ]]; then
    echo "Usage: bash scripts/set-repo.sh <github-username> <email>"
    echo "Example: bash scripts/set-repo.sh alice alice@example.com"
    exit 1
fi

REPO_URL="https://github.com/${GITHUB_USER}/g510"

echo "Patching repository references:"
echo "  GitHub user : $GITHUB_USER"
echo "  Email       : $EMAIL"
echo "  Repo URL    : $REPO_URL"
echo

FILES=(
    README.md
    CONTRIBUTING.md
    CHANGELOG.md
    GITHUB_PUBLISH.md
    debian/control
    debian/changelog
    debian/copyright
    debian/watch
    build-deb.sh
    install.sh
    pyproject.toml
    .github/workflows/ci.yml
)

for f in "${FILES[@]}"; do
    [[ -f "$f" ]] || continue
    sed -i \
        -e "s|fariaz|${GITHUB_USER}|g" \
        -e "s|noreply@example\.com|${EMAIL}|g" \
        "$f"
    echo "  patched: $f"
done

# Update debian/changelog date to today
TODAY=$(date -R)
sed -i "s|Fri, 28 Mar 2026 00:00:00 +0000|${TODAY}|g" debian/changelog

echo
echo "Done. Check the changes with: git diff"
echo "Then: git add -A && git commit -m 'chore: set repository metadata'"
