#!/usr/bin/env bash
# Sign a published release's SHA256SUMS with your offline minisign key.
#
# Usage:  scripts/sign_release.sh v1.4.0 <commit>
#
# <commit> is the full 40-character SHA of the commit you reviewed and meant
# to release, from your own copy of the repository, for example:
#     scripts/sign_release.sh v1.4.0 "$(git rev-parse origin/main)"
# after git fetch and checking that origin/main is the code you merged.
#
# 1. Checks that the tag on GitHub points at exactly that commit. Everything
#    else here comes from GitHub, so this is what stops someone who takes over
#    the GitHub account from getting their own code signed: they could move
#    the tag and upload a matching SHA256SUMS, but not change your commit.
# 2. Downloads the files at that commit and hashes them yourself.
# 3. Downloads the SHA256SUMS the release workflow attached.
# 4. Refuses to sign unless the two match exactly.
# 5. Signs SHA256SUMS with minisign, naming the tag in the trusted comment
#    (the updater checks for it), and saves SHA256SUMS.minisig here.
# Then attach SHA256SUMS.minisig to the release on GitHub.
#
# Needs: git, curl, python3, sha256sum, minisign, and your key in
# ~/.minisign/minisign.key. Run it on your own computer, never in CI.
set -euo pipefail

REPO="SBK008/orbit-coordinate-converter"
tag="${1:-}"
expected="${2:-}"
if [[ ! "$tag" =~ ^v[0-9]+(\.[0-9]+){1,3}$ ]] || [[ ! "$expected" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 vX.Y.Z <full commit SHA you reviewed>" >&2
  echo "For example: $0 v1.4.0 \"\$(git rev-parse origin/main)\"" >&2
  exit 1
fi
for tool in git curl python3 sha256sum minisign; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Install it first." >&2; exit 1; }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Getting $tag from GitHub..."
# Fetch the tag by its full name, so a branch with the same name can't stand in for it
git init --quiet "$work/src"
git -C "$work/src" fetch --quiet --depth 1 "https://github.com/$REPO.git" "+refs/tags/$tag:refs/tags/$tag"
actual="$(git -C "$work/src" rev-parse "refs/tags/$tag^{commit}")"
if [ "$actual" != "$expected" ]; then
  echo "STOP: $tag on GitHub points at $actual, not the commit you gave ($expected)." >&2
  echo "The tag may have been moved. Do not sign until you know why." >&2
  exit 1
fi
git -C "$work/src" -c advice.detachedHead=false checkout --quiet "$actual"
echo "$tag is commit $actual, as expected."

# Hash the same file list the release workflow and updater use
read -ra files <<< "$(cd "$work/src" && python3 -I -c "import ast; t = ast.parse(open('updater.py').read()); print(' '.join(next(ast.literal_eval(n.value) for n in t.body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'UPDATE_FILES')))")"
(cd "$work/src" && sha256sum "${files[@]}") > "$work/SHA256SUMS.mine"

echo "Downloading the release's SHA256SUMS..."
if ! curl --fail --silent --show-error --location --proto '=https' \
     -o "$work/SHA256SUMS" "https://github.com/$REPO/releases/download/$tag/SHA256SUMS"; then
  echo "The release has no SHA256SUMS yet. Wait for the release workflow to finish." >&2
  exit 1
fi

if ! cmp -s "$work/SHA256SUMS" "$work/SHA256SUMS.mine"; then
  echo "STOP: the release's SHA256SUMS does not match the files at $tag." >&2
  diff "$work/SHA256SUMS.mine" "$work/SHA256SUMS" >&2 || true
  exit 1
fi
echo "SHA256SUMS matches the files at $tag:"
cat "$work/SHA256SUMS"

minisign -S -m "$work/SHA256SUMS" -t "orbit-converter $tag"
cp "$work/SHA256SUMS.minisig" ./SHA256SUMS.minisig
echo
echo "Saved SHA256SUMS.minisig. Now attach it to the release:"
echo "  https://github.com/$REPO/releases/edit/$tag"
