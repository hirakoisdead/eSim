#!/bin/bash
#=============================================================================
#          FILE: Ubuntu/tests/run-tests.sh
#
#         USAGE: ./Ubuntu/tests/run-tests.sh
#
#   DESCRIPTION: Test suite for install-eSim.sh's terminal UI. Runs on any
#                Ubuntu (24.04 / 25.04 / 26.04) and, usefully, under WSL --
#                none of it installs anything, calls sudo, or touches the
#                network, so the whole suite finishes in well under a minute.
#
#                What it actually covers:
#                  test_ui.sh       the UI block in isolation: that no helper
#                                   can return non-zero under the `set -e` /
#                                   ERR-trap regime --install runs in, the
#                                   capability ladder (tty / colour / UTF-8),
#                                   and terminal restoration after SIGINT.
#                  test_install.sh  the REAL Main block end to end -- logging
#                                   pipeline, step loop, sticky bar, summary
#                                   and failure boxes -- with the install
#                                   steps replaced by fast stubs.
#                  check_align.py   every rendered box is a true rectangle at
#                                   terminal widths from 40 to 200 columns.
#
#                A real pty is needed (the UI deliberately refuses to draw
#                without one), which is what `script -qec` provides.
#
#  ORGANIZATION: eSim Team, FOSSEE, IIT Bombay
#=============================================================================
set -u

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
installer="$here/../install-eSim.sh"
[ -f "$installer" ] || { echo "ERROR: install-eSim.sh not found next to tests/"; exit 1; }
command -v script >/dev/null || { echo "ERROR: 'script' required (apt install bsdutils)"; exit 1; }

# The UI block is embedded in install-eSim.sh rather than kept in its own
# file -- make-release.sh deletes Ubuntu/ when it flattens the release zip,
# and bootstrap.sh runs from a curl pipe with no sibling files to source. So
# the unit suite carves the block back out instead of testing a stale copy.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
python3 - "$installer" "$work/ui-block.sh" <<'PY'
import sys
src, out = sys.argv[1], sys.argv[2]
s = open(src, encoding='utf-8').read()
start = s.index('# Terminal UI\n#---')
end = s.index('# Helpers\n#---', start)
end = s.rindex('#-----', start, end)
open(out, 'w', encoding='utf-8', newline='\n').write(s[start:end])
PY
bash -n "$work/ui-block.sh" || { echo "ERROR: extracted UI block does not parse"; exit 1; }

rc=0
echo "########## 1/3  UI block (unit) ##########"
UI_SRC="$work/ui-block.sh" bash "$here/test_ui.sh" || rc=1

echo
echo "########## 2/3  install path (stubbed) ##########"
SRC="$installer" bash "$here/test_install.sh" || rc=1

echo
echo "########## 3/3  box alignment, 40..200 columns ##########"
root=$HOME/esimtest
if [ ! -f "$root/VERSION" ]; then
    mkdir -p "$root/src" "$root/library" "$root/Ubuntu"
    echo 2.6 > "$root/VERSION"
fi
cp "$installer" "$root/Ubuntu/install-eSim.sh"
for cols in 40 56 64 72 80 96 120 200; do
    printf '%-4s ' "$cols"
    if script -qec "stty rows 40 cols $cols </dev/tty; cd $root && ./Ubuntu/install-eSim.sh --dry-run" \
         /dev/null 2>/dev/null | python3 "$here/check_align.py" | tail -1; then :; else rc=1; fi
done

echo
if [ "$rc" -eq 0 ]; then echo "ALL SUITES PASSED"; else echo "SOME SUITES FAILED"; fi
exit "$rc"
