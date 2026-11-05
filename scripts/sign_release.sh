#!/usr/bin/env bash
# Sign a published release's SHA256SUMS with your offline minisign key.
#
# Usage:  scripts/sign_release.sh v1.4.0
#
# 1. Downloads the files at that tag from GitHub and hashes them yourself.
# 2. Downloads the SHA256SUMS the release workflow attached.
# 3. Refuses to sign unless the two match exactly.
# 4. Signs SHA256SUMS with minisign, naming the tag in the trusted comment
#    (the updater checks for it), and saves SHA256SUMS.minisig here.
# Then attach SHA256SUMS.minisig to the release on GitHub.
#
# Needs: git, curl, python3, sha256sum, minisign, and your key in
# ~/.minisign/minisign.key. Run it on your own computer, never in CI.
set -euo pipefail

REPO="SBK008/orbit-coordinate-converter"
tag="${1:-}"
if [[ ! "$tag" =~ ^v[0-9]+(\.[0-9]+){1,3}$ ]]; then
  echo "Usage: $0 vX.Y.Z" >&2
  exit 1
fi
for tool in git curl python3 sha256sum minisign; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Install it first." >&2; exit 1; }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Getting $tag from GitHub..."
git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$tag" "https://github.com/$REPO.git" "$work/src"

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
