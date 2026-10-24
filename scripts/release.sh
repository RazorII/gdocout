#!/usr/bin/env bash
# Tag a gdocout release, push it, and prove the tag reached GitHub.
#
# The plugin's skill installs gdocout pinned to its release tag, so a tag that
# never reached GitHub breaks every new install. `git push --follow-tags` skips
# lightweight tags, which is how v0.1.1 to v0.1.3 stayed local for a day.
set -euo pipefail
v="${1:?usage: scripts/release.sh X.Y.Z}"
cd "$(git rev-parse --show-toplevel)"
grep -q "__version__ = \"$v\"" src/gdocout/__init__.py || { echo "src/gdocout/__init__.py is not at $v" >&2; exit 1; }
"${PYTHON:-python3}" -m pytest -q -p no:cacheprovider tests/test_release.py
[ -z "$(git status --porcelain)" ] || { echo "commit everything first" >&2; exit 1; }
# gdocout is published as RazorII. A fresh clone takes the global git name, so
# check every commit and the name the tag will carry before anything is pushed.
publisher="RazorII"
names="$( { git log --format='%an%n%cn'; git config user.name; } | sort -u)"
[ "$names" = "$publisher" ] || { echo "commits and the tag must be by $publisher (git config user.name $publisher); found: $(echo $names)" >&2; exit 1; }
git tag -a "v$v" -m "gdocout $v"
git push origin HEAD "refs/tags/v$v"
git ls-remote --exit-code --tags origin "refs/tags/v$v" >/dev/null || { echo "v$v did not reach GitHub" >&2; exit 1; }
echo "v$v is on GitHub"
