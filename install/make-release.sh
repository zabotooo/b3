#!/bin/bash
# make-release.sh EDITOR_BUILD_DIR OUT.tar.gz : pack hatd and an editor build into one release archive
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
editor=$(cd "$1" && pwd)
out=$2
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$repo/hatd/b3hatd/__init__.py")
[ -n "$version" ] || { echo "make-release: no __version__ in hatd/b3hatd/__init__.py" >&2; exit 1; }
[ -f "$editor/index.html" ] || { echo "make-release: $editor has no index.html" >&2; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/b3/hatd/b3hatd" "$work/b3/install"
cp "$repo"/hatd/b3hatd/*.py "$work/b3/hatd/b3hatd/"
cp -a "$editor" "$work/b3/editor"
find "$work/b3/editor" -name '*.map' -delete
cp "$repo/install/install.sh" "$repo/install/b3.service" "$work/b3/install/"
cp "$repo/editor/LICENSE" "$work/b3/LICENSE"
echo "$version" > "$work/b3/VERSION"
tar --owner=0 --group=0 --numeric-owner -czf "$out" -C "$work" b3
echo "make-release: $out (B3 $version)"
