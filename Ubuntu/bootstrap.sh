#!/bin/bash
#=============================================================================
#          FILE: bootstrap.sh
#
#         USAGE: curl -fsSL https://raw.githubusercontent.com/FOSSEE/eSim/v2.6/Ubuntu/bootstrap.sh \
#                  | ESIM_BRANCH=v2.6 bash
#                # Development snapshot: curl -fsSL https://raw.githubusercontent.com/FOSSEE/eSim/master/Ubuntu/bootstrap.sh | bash
#                curl -fsSL .../bootstrap.sh | bash -s -- --uninstall
#                curl -fsSL .../bootstrap.sh | bash -s -- --dry-run
#
#   DESCRIPTION: One-line bootstrap for the eSim Ubuntu installer. The eSim
#                source tree IS the installed application (the launcher runs
#                src/frontEnd/Application.py out of it), so this script
#                downloads the tree to a durable location ($ESIM_DIR, default
#                ~/eSim) and hands off to Ubuntu/install-eSim.sh there. ALL
#                install/uninstall logic lives in install-eSim.sh — this
#                script only fetches, locates and dispatches, so the zip and
#                curl install paths can never drift apart.
#
#                Re-running the one-liner updates a bootstrap-managed tree in
#                place (user-built NgVeri/NGHDL model XML is preserved); a
#                git checkout or hand-extracted zip at $ESIM_DIR is reused
#                as-is and never overwritten.
#
#     OVERRIDES: ESIM_DIR    where the eSim tree lives   (default ~/eSim)
#                ESIM_BRANCH branch/tag to download      (default master)
#                ESIM_REPO   GitHub owner/repo           (default FOSSEE/eSim)
#=============================================================================
set -euo pipefail

ESIM_REPO="${ESIM_REPO:-FOSSEE/eSim}"
ESIM_BRANCH="${ESIM_BRANCH:-master}"
ESIM_DIR="${ESIM_DIR:-$HOME/eSim}"
MARKER=".esim-bootstrap"          # stamped only on trees THIS script created

#-----------------------------------------------------------------------------
# Terminal UI (compact)
#-----------------------------------------------------------------------------
# A deliberately small copy of install-eSim.sh's UI block rather than a shared
# file: this script is fetched by `curl ... | bash`, so at the moment it runs
# there is no eSim tree on disk to source anything from. It shows a compact
# header only -- the full wordmark belongs to install-eSim.sh, which takes
# over a few seconds later, and printing it in both places would just look
# like a stutter.
#
# Same rules as the installer's block: every helper returns 0, every read is
# ${x:-}, and detection probes /dev/tty (this script's own stdin is the
# download pipe, so `[ -t 0 ]` is always false here). It must survive the
# `set -euo pipefail` above.
UI_ON=0
C_RESET=''; C_DIM=''; C_BOLD=''; C_ACCENT=''; C_OK=''; C_WARN=''; C_ERR=''
G_ARROW='>'; G_OK='ok'; G_ERR='x'; G_RULE='-'; G_DOT='-'

ui_detect() {
    [ -n "${ESIM_NO_FANCY:-}" ] && return 0
    [ -n "${NO_COLOR:-}" ]      && return 0
    case "${TERM:-dumb}" in dumb|"") return 0 ;; esac
    { : > /dev/tty; } 2>/dev/null || return 0

    local ncolors=0
    ncolors=$(tput colors 2>/dev/null) || ncolors=0
    [ "${ncolors:-0}" -ge 8 ] 2>/dev/null || return 0

    # Same brand gold as install-eSim.sh (sampled from images/esim_text.png):
    # the two run back to back, so a different accent here would read as two
    # unrelated tools rather than one install.
    UI_ON=1
    C_RESET=$'\033[0m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'
    C_ACCENT=$'\033[33m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'
    if [ "${ncolors:-0}" -ge 256 ] 2>/dev/null; then
        C_ACCENT=$'\033[38;5;214m'; C_OK=$'\033[38;5;114m'
        C_WARN=$'\033[38;5;208m';   C_ERR=$'\033[38;5;203m'
    fi
    case "${COLORTERM:-}" in
        truecolor|24bit)
            C_ACCENT=$'\033[38;2;240;160;48m'; C_OK=$'\033[38;2;126;211;133m'
            C_WARN=$'\033[38;2;255;140;26m';   C_ERR=$'\033[38;2;235;110;110m' ;;
    esac

    local charmap=""
    charmap=$(locale charmap 2>/dev/null) || charmap=""
    case "${charmap}:${LC_ALL:-}:${LC_CTYPE:-}:${LANG:-}" in
        *UTF-8*|*utf8*|*UTF8*|*utf-8*)
            G_ARROW='▸'; G_OK='✔'; G_ERR='✖'; G_RULE='─'; G_DOT='·' ;;
    esac
    return 0
}

ui_header() {
    if [ "$UI_ON" = 0 ]; then
        printf '\n=== eSim EDA Suite -- bootstrap ===\n'
        return 0
    fi
    local rule='' i=0
    while [ "$i" -lt 46 ]; do rule="$rule$G_RULE"; i=$((i + 1)); done
    printf '\n  %s%seSim EDA Suite%s %s%s bootstrap%s\n  %s%s%s\n' \
        "$C_BOLD" "$C_ACCENT" "$C_RESET" "$C_DIM" "$G_DOT" "$C_RESET" \
        "$C_ACCENT" "$rule" "$C_RESET"
    return 0
}

log()  { if [ "$UI_ON" = 1 ]; then printf '  %s%s%s %s\n' "$C_ACCENT" "$G_ARROW" "$C_RESET" "$*"
         else echo -e "\n>>> $*"; fi; return 0; }
note() { if [ "$UI_ON" = 1 ]; then printf '  %s%s %s%s\n' "$C_OK" "$G_OK" "$*" "$C_RESET"
         else echo ">>> $*"; fi; return 0; }
die()  {
    if [ "$UI_ON" = 1 ]; then
        printf '\n  %s%s %s%s\n\n' "$C_ERR" "$G_ERR" "$*" "$C_RESET" >&2
    else
        echo -e "\n[ERROR] $*\n" >&2
    fi
    exit 1
}

_tmpdirs=()
cleanup() { rm -rf "${_tmpdirs[@]}" 2>/dev/null || true; }
trap cleanup EXIT

# A tree is valid in either layout: the git/tarball layout keeps the
# installer under Ubuntu/, the release zip hoists it to the root. Accepting
# both lets `--uninstall` recognise a zip-installed tree instead of
# downloading a fresh copy just to run its uninstaller.
is_esim_tree() {
    [ -f "$1/VERSION" ] && [ -d "$1/src" ] \
        && { [ -f "$1/Ubuntu/install-eSim.sh" ] || [ -f "$1/install-eSim.sh" ]; }
}

# Relative path of the installer inside a valid tree (layout-dependent).
installer_path() {
    if [ -f "$1/Ubuntu/install-eSim.sh" ]; then
        echo "Ubuntu/install-eSim.sh"
    else
        echo "install-eSim.sh"
    fi
}

# install/uninstall prompt for proxy, sudo password, IHP, etc. Under
# `curl | bash` stdin is the script pipe, so those reads must come from the
# terminal instead.
require_tty() {
    { : < /dev/tty; } 2>/dev/null \
        || die "No terminal available for the installer's prompts.
       Run this from an interactive terminal (not cron/CI)."
}

# Download the eSim source tarball and extract it into a scratch dir NEXT TO
# $ESIM_DIR (the tree is ~700 MB — /tmp is often a small tmpfs, and a same-
# filesystem mv into place is instant). Sets FETCHED_TREE to the tree's path.
FETCHED_TREE=""
fetch_tree() {
    local tmp sub
    mkdir -p "$(dirname "$ESIM_DIR")"
    tmp=$(mktemp -d "$(dirname "$ESIM_DIR")/.esim-download-XXXXXX")
    _tmpdirs+=("$tmp")
    # ESIM_BRANCH may name a branch OR a release tag (a tag is what pins an
    # install to one reviewed commit), and the two live under different refs,
    # so ask GitHub which exists rather than guessing. Tags are tried FIRST:
    # this repo carries both a v2.4 branch and a v2.4 tag, and someone who
    # passes a version number wants the release, not a stale branch of that name.
    local base="https://codeload.github.com/$ESIM_REPO/tar.gz/refs" url=""
    for ref in "tags/$ESIM_BRANCH" "heads/$ESIM_BRANCH"; do
        if curl -fsIL -o /dev/null "$base/$ref" 2>/dev/null; then
            url="$base/$ref"
            break
        fi
    done
    [ -n "$url" ] || die "No branch or tag '$ESIM_BRANCH' at https://github.com/$ESIM_REPO"

    # curl's own --progress-bar is left in charge of the download: it is the
    # only thing here that knows the byte count, and it writes to stderr (the
    # terminal) rather than into the tar pipe.
    log "Downloading eSim ($ESIM_REPO @ $ESIM_BRANCH) $G_DOT a couple hundred MB," \
        "this can take a while"
    curl -fL --progress-bar "$url" | tar -xz -C "$tmp" \
        || die "Download or extraction failed. Check your connection and that
       '$ESIM_BRANCH' exists at https://github.com/$ESIM_REPO"
    note "Downloaded and extracted"
    sub=$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    [ -n "$sub" ] && is_esim_tree "$sub" \
        || die "Downloaded archive does not look like an eSim source tree."
    printf 'repo=%s\nbranch=%s\ndate=%s\n' \
        "$ESIM_REPO" "$ESIM_BRANCH" "$(date -Is)" > "$sub/$MARKER"
    FETCHED_TREE="$sub"
}

# Make sure a usable eSim tree exists at $ESIM_DIR (download/refresh as
# needed) — used by --install and --dry-run.
ensure_tree() {
    local fresh keep d
    if is_esim_tree "$ESIM_DIR"; then
        if [ -d "$ESIM_DIR/.git" ]; then
            log "Reusing the git checkout at $ESIM_DIR (left untouched —" \
                "use git to update it)"
        elif [ -f "$ESIM_DIR/$MARKER" ]; then
            log "Updating the bootstrap-managed eSim tree at $ESIM_DIR"
            fetch_tree; fresh="$FETCHED_TREE"
            # Keep the user's runtime-built NGHDL / NgVeri / Dual Co-sim
            # model XML: eSim writes it into the tree, and their symbols and
            # models in ~/.esim would dangle without it. NgVeriCosim is the
            # source of truth for d_cosim model existence (model_teardown,
            # NgVeri._list_models) — dropping it orphans every d_cosim model.
            keep=$(mktemp -d)
            _tmpdirs+=("$keep")
            for d in Nghdl Ngveri NgVeriCosim; do
                [ -d "$ESIM_DIR/library/modelParamXML/$d" ] \
                    && cp -a "$ESIM_DIR/library/modelParamXML/$d" "$keep/"
            done
            rm -rf "$ESIM_DIR"
            mv "$fresh" "$ESIM_DIR"
            for d in Nghdl Ngveri NgVeriCosim; do
                [ -d "$keep/$d" ] \
                    && cp -a "$keep/$d/." "$ESIM_DIR/library/modelParamXML/$d/"
            done
        else
            log "Reusing the existing eSim tree at $ESIM_DIR (not managed by" \
                "this script — delete it or set ESIM_DIR for a fresh copy)"
        fi
    elif [ -e "$ESIM_DIR" ]; then
        die "$ESIM_DIR exists but is not an eSim source tree.
       Move it aside, or point ESIM_DIR at another location:
       curl ... | ESIM_DIR=\$HOME/esim-app bash"
    else
        fetch_tree; fresh="$FETCHED_TREE"
        mv "$fresh" "$ESIM_DIR"
        log "eSim source installed at $ESIM_DIR (keep this directory — the" \
            "application runs from it)"
    fi
}

# For --uninstall: find the tree the current install actually points at.
# Priority: the recorded eSim_HOME in ~/.esim/config.ini, then $ESIM_DIR.
find_installed_tree() {
    local cfg="$HOME/.esim/config.ini" home="" d
    [ -f "$cfg" ] && home=$(sed -n 's/^eSim_HOME[[:space:]]*=[[:space:]]*//p' "$cfg" | head -n 1)
    for d in "$home" "$ESIM_DIR"; do
        if [ -n "$d" ] && is_esim_tree "$d"; then
            echo "$d"
            return 0
        fi
    done
    return 1
}

main() {
    local action="${1:---install}" tree
    ui_detect
    ui_header
    case "$action" in
        --install|--uninstall|--dry-run) ;;
        *) die "Unknown option: $action
       Usage: curl ... | bash [-s -- --install | --uninstall | --dry-run]" ;;
    esac

    [ "$(id -u)" -eq 0 ] \
        && die "Run as a normal user, not root — the installer calls sudo itself."
    grep -qs '^ID=ubuntu' /etc/os-release \
        || die "This bootstrap supports Ubuntu only (see INSTALL for other platforms)."
    command -v curl >/dev/null || die "curl is required."

    case "$action" in
        --install)
            require_tty
            ensure_tree
            log "Handing off to install-eSim.sh --install"
            ( cd "$ESIM_DIR" && bash "$(installer_path "$ESIM_DIR")" --install < /dev/tty )
            ;;
        --dry-run)
            ensure_tree
            ( cd "$ESIM_DIR" && bash "$(installer_path "$ESIM_DIR")" --dry-run < /dev/null )
            ;;
        --uninstall)
            require_tty
            if tree=$(find_installed_tree); then
                log "Uninstalling via $tree"
            else
                # Tree already deleted — the uninstaller only needs the
                # script itself, so run it from a throwaway download.
                log "No local eSim tree found — fetching one just to run its uninstaller"
                fetch_tree; tree="$FETCHED_TREE"
            fi
            ( cd "$tree" && bash "$(installer_path "$tree")" --uninstall < /dev/tty )
            ;;
    esac
}

main "$@"
