#!/bin/bash
#=============================================================================
#          FILE: Ubuntu/tests/demo.sh
#
#         USAGE: ./Ubuntu/tests/demo.sh            # full run, ~25 s
#                ./Ubuntu/tests/demo.sh --fail     # the failure box
#                ./Ubuntu/tests/demo.sh --plain    # ESIM_NO_FANCY=1 fallback
#                ./Ubuntu/tests/demo.sh --dry-run  # just the plan box
#
#   DESCRIPTION: Watch install-eSim.sh's terminal UI without installing
#                anything. This runs the REAL script -- its Main block, step
#                loop, sticky progress bar, boxes and logging pipeline -- with
#                the install steps swapped for stubs that just sleep and print
#                plausible output.
#
#                Nothing outside a temp directory is touched: HOME is
#                redirected for the duration, so ~/.esim, the desktop entry
#                and ~/eSim-install.log are all left alone. No sudo, no apt,
#                no network.
#
#                Run it in a real terminal -- the UI deliberately prints plain
#                text when it cannot find a usable tty, so piping this into a
#                file or a pager shows you the fallback, not the design.
#
#  ORGANIZATION: eSim Team, FOSSEE, IIT Bombay
#=============================================================================
set -u

mode="${1:-}"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
installer="$here/../install-eSim.sh"
[ -f "$installer" ] || { echo "ERROR: install-eSim.sh not found next to tests/"; exit 1; }

if ! { : > /dev/tty; } 2>/dev/null; then
    echo "NOTE: no usable terminal detected -- you will see the plain-text"
    echo "      fallback, which is correct behaviour but not the point here."
fi

sandbox=$(mktemp -d)
trap 'rm -rf "$sandbox"' EXIT
root="$sandbox/eSim-2.6"
mkdir -p "$root/src" "$root/library" "$root/Ubuntu" "$root/nghdl"
echo 2.6 > "$root/VERSION"
: > "$root/nghdl/nghdl-simulator-source.tar.xz"
: > "$root/library/sky130_fd_pr.tar.xz"

# Inject stubs immediately before Main so they override the real definitions.
# Timings are rough impressions of a real run, compressed ~60x.
python3 - "$installer" "$root/Ubuntu/install-eSim.sh" "$mode" <<'PY'
import sys
src, out, mode = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(src, encoding='utf-8').read()

stubs = r'''
# ---- injected demo stubs (Ubuntu/tests/demo.sh) ----
preflightDisk() { :; }
setupProxy()    { log "Installing without proxy"; }
cleanLegacyEsim() {
    log "Checking for artifacts of an older eSim install"; sleep 1
    warn "Old eSim-era directory found: ~/eSim-2.4 (safe to delete)"; sleep 0.6
}
createConfigFile() { log "Writing ~/.esim/config.ini"; sleep 0.8; }
installDependency() {
    log "Updating apt index"
    for r in noble noble-updates noble-security; do
        echo "Get:1 http://archive.ubuntu.com/ubuntu $r InRelease [126 kB]"; sleep 0.35
    done
    log "Installing base system packages"
    for p in python3-full python3-venv xterm rsync git build-essential python3-numpy; do
        echo "Setting up $p (2.1.4-1) ..."; sleep 0.3
    done
    log "Creating virtualenv (with system site-packages)"; sleep 1
}
installQt() {
    log "Installing PyQt6 + QScintilla (apt)"; sleep 1.6
    warn "python3-pyqt6.qsci unavailable on this release - code editor disabled"
    sleep 0.5
}
installKicad() {
    log "Adding PPA ppa:kicad/kicad-9.0-releases"; sleep 1.2
    echo "Get:1 https://ppa.launchpadcontent.net/kicad/kicad-9.0-releases noble InRelease"
    sleep 0.8
    log "KiCad 9.0.2 installed"; sleep 0.6
}
copyKicadLibrary() {
    log "Installing eSim KiCad symbol library"; sleep 1.2
    log "Static eSim symbols -> /usr/share/kicad/symbols (root-owned)"; sleep 0.5
}
installNghdl() {
    log "Installing NGHDL (GHDL/Verilator co-simulation)"
    for f in ngspice_main cmpp d_cosim nghdl_sock verilator_shim; do
        echo "  CC  $f.o"; sleep 0.55
    done
    log "NGHDL installed"; sleep 0.4
}
installSky130Pdk() { log "Installing SKY130 PDK"; sleep 1.6; }
installIhpPdk()    { log "Skipping IHP Open PDK"; sleep 0.5; }
createDesktopStartScript() { log "Creating launcher (esim) + desktop entry"; sleep 1; }
runToolchainDoctor() {
    log "Running the simulation-toolchain doctor"; sleep 1.2
    echo "  ngspice   OK    /usr/local/bin/ngspice"
    echo "  ghdl      OK    /usr/bin/ghdl"
    echo "  verilator OK    /usr/bin/verilator"
    sleep 0.6
}
'''
if mode == '--fail':
    stubs += ('installKicad() { log "Adding PPA ppa:kicad/kicad-9.0-releases"; sleep 1.2; '
              'echo "E: The repository does not have a Release file."; sleep 0.5; false; }\n')

anchor = "#=============================================================================\n# Main"
open(out, 'w', encoding='utf-8', newline='\n').write(
    s.replace(anchor, stubs + "\n" + anchor, 1))
PY
chmod +x "$root/Ubuntu/install-eSim.sh"

# Redirect HOME so the demo cannot touch the real ~/.esim or ~/eSim-install.log.
export HOME="$sandbox/home"
mkdir -p "$HOME"

case "$mode" in
    --dry-run) ( cd "$root" && ./Ubuntu/install-eSim.sh --dry-run ) ;;
    --plain)   ( cd "$root" && ESIM_NO_FANCY=1 ./Ubuntu/install-eSim.sh --install ) ;;
    *)         ( cd "$root" && ./Ubuntu/install-eSim.sh --install ) ;;
esac
rc=$?

echo
echo "  (demo only -- nothing was installed, real \$HOME untouched)"
echo "  try: --fail   the failure box     --plain    the no-colour fallback"
echo "       --dry-run the plan box       ESIM_UI_STICKY=0  colour, no bottom bar"
exit "$rc"
