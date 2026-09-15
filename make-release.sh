#!/bin/bash
#=============================================================================
#          FILE: make-release.sh
#
#         USAGE: ./make-release.sh [<ref>]     # default: HEAD
#                ./make-release.sh origin/dev
#                ./make-release.sh --dirty     # include uncommitted edits
#
#   DESCRIPTION: Freeze a COMMITTED eSim tree into a versioned, self-contained
#                release zip for Ubuntu — the artifact users download and
#                install, instead of cloning a moving master.
#
#                What lands in the zip is decided by ONE file: .gitattributes.
#                This script builds the payload with `git archive`, and so does
#                GitHub when Ubuntu/bootstrap.sh curls the branch tarball —
#                both honour `export-ignore`, so the zip and the curl install
#                can never ship a different set of files. Add an exclusion
#                there, not here.
#
#                Building from a commit (not the working tree) is deliberate:
#                a release must never pick up half-finished local edits or
#                stray files sitting in the checkout. Pass --dirty to override
#                that for a local test build.
#
#                Output layout matches the FOSSEE release convention so the
#                same artifact also feeds the Windows packaging pipeline:
#                  eSim-<VERSION>/
#                    install-eSim.sh            (at root)
#                    install-eSim-scripts/...   (none — unified installer)
#                    nghdl.zip                  (nghdl/ zipped)
#                    library/kicadLibrary.tar.xz
#                    library/sky130_fd_pr.tar.xz
#                    src/  Examples/  images/  ihp/  ...
#                    RELEASE                    (provenance stamp)
#
#  ORGANIZATION: eSim Team, FOSSEE, IIT Bombay
#=============================================================================

set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo"

command -v zip >/dev/null || { echo "ERROR: zip required (sudo apt install zip)"; exit 1; }
git rev-parse --is-inside-work-tree &>/dev/null \
    || { echo "ERROR: not a git checkout — make-release.sh archives a commit"; exit 1; }

# Resolve what we are packaging.
#
# --dirty: `git stash create` bottles the working tree up as a real (dangling)
# commit, so uncommitted edits go through the exact same `git archive` filter
# as everything else. Untracked files stay out either way — that is the point.
ref="${1:-HEAD}"
dirty=""
if [ "$ref" = "--dirty" ]; then
    ref="$(git stash create)" || true
    if [ -n "$ref" ]; then
        dirty=" + uncommitted changes"
    else
        ref="HEAD"    # nothing to stash; tree is clean
    fi
fi
git rev-parse --verify --quiet "$ref^{commit}" >/dev/null \
    || { echo "ERROR: '$ref' is not a commit"; exit 1; }

if [ -z "$dirty" ] && [ -n "$(git status --porcelain)" ]; then
    echo ">>> NOTE: working tree has local changes; they are NOT in this build."
    echo "          (packaging $ref — pass --dirty to include them)"
fi

VERSION="$(cat VERSION 2>/dev/null || echo 0.0)"
commit="$(git rev-parse --short "$ref")"
date_str="$(date -u +%Y-%m-%d)"

name="eSim-${VERSION}"
out="$repo/dist"
stage="$(mktemp -d)"
top="$stage/$name"
mkdir -p "$top" "$out"
trap 'rm -rf "$stage"' EXIT

echo ">>> Exporting $ref -> $name (excludes come from .gitattributes)"
git archive "$ref" | tar -x -C "$top"

echo ">>> Flattening installer to release root"
# Release convention puts install-eSim.sh at the top level. The unified
# installer resolves the eSim root from its own location, so dropping the
# Ubuntu/ wrapper dir is safe. bootstrap.sh is a curl-path entry point and has
# no job inside an already-downloaded zip.
if [ -f "$top/Ubuntu/install-eSim.sh" ]; then
    cp "$top/Ubuntu/install-eSim.sh" "$top/install-eSim.sh"
    chmod +x "$top/install-eSim.sh"
    rm -rf "$top/Ubuntu"
fi

echo ">>> Packing nghdl/ -> nghdl.zip"
if [ -d "$top/nghdl" ]; then
    ( cd "$top" && zip -qr nghdl.zip nghdl && rm -rf nghdl )
fi

echo ">>> Packing kicadLibrary/ -> kicadLibrary.tar.xz"
if [ -d "$top/library/kicadLibrary" ] && [ ! -f "$top/library/kicadLibrary.tar.xz" ]; then
    ( cd "$top/library" && tar -cJf kicadLibrary.tar.xz kicadLibrary && rm -rf kicadLibrary )
fi

echo ">>> Writing provenance stamp (RELEASE)"
cat > "$top/RELEASE" << EOF
eSim release
version    : $VERSION
git_commit : $commit$dirty
built      : $date_str (UTC)
target     : Ubuntu 24.04 / 25.04 / 26.04
installer  : unified (./install-eSim.sh --install | --uninstall)
EOF

final="$out/${name}-ubuntu.zip"
echo ">>> Zipping -> $final"
rm -f "$final"
( cd "$stage" && zip -qr "$final" "$name" )

sha="$(sha256sum "$final" | cut -d' ' -f1)"
echo "$sha  ${name}-ubuntu.zip" > "$final.sha256"

echo
echo "==================== release built ===================="
echo " artifact : $final"
echo " size     : $(du -h "$final" | cut -f1)"
echo " sha256   : $sha"
echo " commit   : $commit$dirty"
echo "======================================================="
echo "Test:  cd /tmp && unzip -q $final && cd $name && ./install-eSim.sh --dry-run"
