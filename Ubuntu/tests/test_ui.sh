#!/bin/bash
# Harness for the installer's terminal-UI block.
#
# The block runs inside --install's `set -e` / `set -E` / `trap ... ERR`
# region, so the property that actually matters is: NOTHING in it can return
# non-zero. Every case below therefore runs under exactly that regime with an
# ERR trap that fails the test loudly.
UI_SRC="${UI_SRC:?set UI_SRC to the ui block}"

pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  FAIL %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want [$3] got [$2])"; fi; }

echo "== 1. sources cleanly under set -euE + ERR trap =="
(
    set -eE
    trap 'echo "ERR TRAP FIRED at line $LINENO"; exit 99' ERR
    # shellcheck disable=SC1090
    . "$UI_SRC"
    ui_detect; ui_palette
    ui_plan 5
    ui_step "First"; ui_log "detail"; ui_warn "careful"
    ui_step "Second"; ui_step_close
    ui_box "$C_OK" "ok" "Done" "Key" "value"
    ui_banner "2.6" "sub"
    ui_end
) >/dev/null 2>&1
check "no helper returns non-zero under set -e" "$?" "0"

echo
echo "== 2. the set -e landmine this block was written to avoid =="
# Documents WHY ui_step uses x=$((x+1)): the postfix form aborts on the first
# increment because its value is 0. If this ever stops failing, the guard
# comment in the UI block can go.
( set -e; i=0; (( i++ )); echo reached ) >/dev/null 2>&1
check "(( i++ )) at 0 really does abort under set -e" "$?" "1"
( set -e; i=0; i=$((i+1)); [ "$i" = 1 ] ) >/dev/null 2>&1
check "assignment form is safe"                       "$?" "0"

echo
echo "== 3. unit behaviour =="
set +e
# shellcheck disable=SC1090
. "$UI_SRC"
UI_LEVEL=2; ui_palette
check "ui_rep 5"          "$(ui_rep 5 '#')"        "#####"
check "ui_rep 0 is empty" "$(ui_rep 0 '#')"        ""
check "ui_rep -3 is empty" "$(ui_rep -3 '#')"      ""
check "ui_hms 0"          "$(ui_hms 0)"            "0m00s"
check "ui_hms 95"         "$(ui_hms 95)"           "1m35s"
check "ui_hms 3725"       "$(ui_hms 3725)"         "1h02m"
check "ui_visible strips" "$(ui_visible "$(printf '\033[36mab\033[0mc')")" "abc"
check "ui_visible plain"  "$(ui_visible 'abc')"    "abc"
check "ui_visible empty"  "$(ui_visible '')"       ""
# Malformed sequence must terminate rather than spin forever.
timeout 5 bash -c ". '$UI_SRC'; UI_LEVEL=2; ui_palette; ui_visible \"\$(printf '\033[36mabc')\"" >/dev/null 2>&1
check "ui_visible terminates on truncated CSI" "$?" "0"

echo
echo "== 4. level 0 is escape-free (the ESIM_NO_FANCY kill switch) =="
out=$(ESIM_NO_FANCY=1 bash -c '
    . "'"$UI_SRC"'"; ui_detect; ui_palette; ui_plan 2
    ui_banner 2.6 x; ui_step "One"; ui_log "d"; ui_warn "w"; ui_step "Two"
    ui_box "" "" "T" "K" "v"' 2>&1)
if printf '%s' "$out" | grep -q $'\033'; then bad "level 0 emitted an escape"; else ok "level 0 emitted no escapes"; fi
if printf '%s' "$out" | grep -q '>>> \[1/2\] One'; then ok "level 0 keeps the original >>> step format"; else bad "level 0 step format changed"; fi

echo
echo "== 5. NO_COLOR / TERM=dumb / no-tty all fall back =="
for env in 'NO_COLOR=1' 'TERM=dumb' 'ESIM_NO_FANCY=1'; do
    lvl=$(env $env bash -c ". '$UI_SRC'; ui_detect; echo \$UI_LEVEL" 2>/dev/null)
    check "$env -> level 0" "$lvl" "0"
done
# setsid actually detaches the controlling terminal; a mere `< /dev/null`
# does not, and /dev/tty stays open.
lvl=$(setsid bash -c ". '$UI_SRC'; ui_detect; echo \$UI_LEVEL" < /dev/null 2>/dev/null)
check "no controlling tty -> level 0" "$lvl" "0"
# Degenerate terminal (openable /dev/tty, nonsense window size) must also
# fall back rather than paint a bar onto a 1x1 pty.
lvl=$(script -qec "stty rows 1 cols 1 </dev/tty; . '$UI_SRC'; ui_detect; echo LVL=\$UI_LEVEL" /dev/null 2>/dev/null | tr -d '\r' | grep -o 'LVL=[0-9]' | cut -d= -f2)
check "1x1 degenerate tty -> level 0" "$lvl" "0"

echo
echo "== 6. real pty: detection, sticky bar, cursor + region restored =="
# `script` sizes its pty from the parent, and a CI/agent shell often has a
# nonsense window size -- which ui_detect now (rightly) refuses. Give every
# pty an explicit 24x80 so these cases test the UI, not the harness.
PTY_ROWS=24
pty() { script -qec "stty rows $PTY_ROWS cols 80 </dev/tty; $1" /dev/null 2>/dev/null; }
mark() { printf '%s' "$1" | tr -d '\r' | grep -o "$2" | tail -1 | cut -d= -f2; }

lvl=$(mark "$(pty ". '$UI_SRC'; ui_detect; echo LVL=\$UI_LEVEL")" 'LVL=[0-9]')
check "utf-8 colour pty -> level 2" "$lvl" "2"
lvl=$(mark "$(pty "export LC_ALL=C LANG=C; . '$UI_SRC'; ui_detect; echo LVL=\$UI_LEVEL")" 'LVL=[0-9]')
check "LANG=C pty -> level 1 (ascii)" "$lvl" "1"

# A full run on a pty, then assert the terminal was handed back intact.
trace=$(pty ". '$UI_SRC'; ui_detect; ui_palette; ui_plan 3; ui_begin
             ui_step A; ui_log hello; ui_step B; ui_step C; ui_step_close; ui_end")
case "$trace" in *$'\033[?25l'*) ok "cursor was hidden while running" ;; *) bad "cursor never hidden" ;; esac
case "$trace" in *$'\033[?25h'*) ok "cursor restored on exit"        ;; *) bad "CURSOR LEFT HIDDEN" ;; esac
case "$trace" in *$'\033[1;'*'r'*) ok "scroll region was armed"      ;; *) bad "scroll region never armed" ;; esac
# The disarm writes the full-window region as the LAST region command, so the
# final value must be the terminal's real row count -- not ROWS-2, which would
# mean the user was left with two dead rows at the bottom of their shell.
last_region=$(printf '%s' "$trace" | grep -oE $'\033\\[1;[0-9]+r' | tail -1 | grep -oE '[0-9]+;[0-9]+r')
check "final scroll region is the full window" "$last_region" "1;${PTY_ROWS}r"

echo
echo "== 7. Ctrl-C mid-run still restores the terminal =="
trace=$(pty ". '$UI_SRC'; ui_detect; ui_palette; ui_plan 3; ui_begin; ui_step A; kill -INT \$\$; sleep 5")
case "$trace" in *$'\033[?25h'*) ok "SIGINT restored the cursor" ;; *) bad "SIGINT LEFT CURSOR HIDDEN" ;; esac

echo
echo "== 8. the bar has exactly ONE writer =="
# Regression guard. A background ticker used to repaint the bar once a second;
# because DECSC/DECRC (ESC 7 / ESC 8) is a single terminal-wide cursor slot,
# it raced the installer's own output and dropped whole rows on the floor --
# the banner lost a line on nearly every run. The bar must only ever be
# painted from the main shell.
if grep -qE '^\s*\)\s*&' "$UI_SRC"; then
    bad "UI block backgrounds a subshell again"
else
    ok "no background subshell in the UI block"
fi
for dead in ui_ticker_start ui_ticker_stop UI_STATE; do
    grep -q "$dead" "$UI_SRC" && bad "stale ticker machinery: $dead" \
                              || ok "no $dead"
done
# No stray processes and no tmpfiles either way.
pty ". '$UI_SRC'; ui_detect; ui_palette; ui_plan 2; ui_begin; ui_step A; ui_end" >/dev/null
sleep 1
if [ -z "$(pgrep -u "$(id -u)" -f 'ui-block' 2>/dev/null | head -1)" ]; then
    ok "no orphan process survived"
else
    bad "orphan process left behind"
fi

echo
echo "== 9. ESIM_UI_STICKY=0 keeps colour but drops the bar =="
trace=$(pty "export ESIM_UI_STICKY=0; . '$UI_SRC'; ui_detect; ui_palette; ui_plan 2; ui_begin; ui_step A; ui_end")
case "$trace" in *$'\033[1;'*'r'*) bad "sticky bar armed despite ESIM_UI_STICKY=0" ;; *) ok "ESIM_UI_STICKY=0 armed no region" ;; esac
case "$trace" in *$'\033[3'*) ok "colour still present with the bar off" ;; *) bad "colour lost with the bar off" ;; esac

echo
echo "== 10. narrow + huge terminals =="
# The marker cannot be anchored to start-of-line: the bar's cursor-restore
# leaves the caret mid-row, so it lands after escape bytes. Match it anywhere.
for size in "10 40" "60 200" "12 64" "24 80"; do
    r=${size%% *}; c=${size##* }
    rc=$(pty "stty rows $r cols $c </dev/tty; . '$UI_SRC'; ui_detect; ui_palette; ui_plan 2; ui_begin; ui_step 'Installing KiCad'; ui_log detail; ui_box \"\$C_OK\" ok Done K v; ui_end; echo XRC=\$?" \
         | tr -d '\r' | grep -o 'XRC=[0-9]*' | tail -1 | cut -d= -f2)
    check "${r}x${c} renders without error" "$rc" "0"
done

echo
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
