#!/usr/bin/env bash
set -euo pipefail

# Bump the desktop app version in the manifests and lockfiles.
# Usage: ./scripts/bump-desktop-version.sh <semver>
# Example: ./scripts/bump-desktop-version.sh 1.0.1

if [ $# -ne 1 ]; then
  echo "Usage: $0 <version>"
  echo "Example: $0 1.0.1"
  exit 1
fi

VERSION="$1"

# Validate semver (major.minor.patch, optional pre-release)
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
  echo "Error: '$VERSION' is not a valid semver (expected X.Y.Z or X.Y.Z-pre)"
  exit 1
fi

FRONTEND_DIR="$(cd "$(dirname "$0")/../frontend" && pwd)"

node - "$FRONTEND_DIR" "$VERSION" <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const [frontendDir, version] = process.argv.slice(2);
const updates = new Map();

for (const filename of ['package.json', 'package-lock.json', 'src-tauri/tauri.conf.json']) {
  const filepath = path.join(frontendDir, filename);
  const manifest = JSON.parse(fs.readFileSync(filepath, 'utf8'));
  manifest.version = version;
  if (filename === 'package-lock.json') {
    manifest.packages[''].version = version;
  }
  updates.set(filepath, JSON.stringify(manifest, null, 2) + '\n');
}

for (const filename of ['src-tauri/Cargo.toml', 'src-tauri/Cargo.lock']) {
  const filepath = path.join(frontendDir, filename);
  const contents = fs.readFileSync(filepath, 'utf8');
  const entry = /^(name = "openjarvis-desktop"\r?\nversion = ")[^"\r\n]+(")$/m;
  if (!entry.test(contents)) throw new Error(`Desktop package entry missing from ${filename}`);
  updates.set(filepath, contents.replace(entry, (_, prefix, suffix) => prefix + version + suffix));
}

for (const [filepath, contents] of updates) {
  fs.writeFileSync(filepath, contents);
}
NODE

echo "Desktop manifests and lockfiles bumped to ${VERSION}."
echo ""
echo "Next steps:"
echo "  git add frontend/package{,-lock}.json frontend/src-tauri/{tauri.conf.json,Cargo.toml,Cargo.lock}"
echo "  git commit -m \"chore(desktop): bump version to ${VERSION}\""
echo "  git tag desktop-v${VERSION}"
echo "  git push origin main --tags"
