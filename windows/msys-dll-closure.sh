#!/bin/sh
# Copy the transitive MinGW runtime-DLL closure of the given seed binaries
# into <dest-dir>, so they run WITHOUT tools\msys64 on PATH -- the same
# trick the official ngspice Windows zip uses. Run inside MINGW64.
#
# Windows resolves the dependencies of a LoadLibrary'd module (a .vpi, .tgt
# or .cm) from the loading EXE's directory and PATH -- never from the
# module's own directory. So the closure must land in every directory that
# hosts a loading exe: ngspice's install_dir/bin, iverilog's bin (vvp.exe)
# and iverilog's lib/ivl (ivl.exe, vhdlpp.exe).
#
#   usage: msys-dll-closure.sh <dest-dir> <seed-file>...
set -e
dest="$1"; shift
[ -n "$dest" ] && [ -d "$dest" ] || { echo "usage: $0 <dest-dir> <seed-file>..." >&2; exit 2; }
[ $# -gt 0 ] || { echo "$0: no seed files given" >&2; exit 2; }

deps() { objdump -p "$@" 2>/dev/null | grep 'DLL Name' | awk '{print $3}' | sort -u; }

seen=""
queue=$(deps "$@")
while [ -n "$queue" ]; do
    next=""
    for d in $queue; do
        case " $seen " in *" $d "*) continue ;; esac
        seen="$seen $d"
        if [ -f "/mingw64/bin/$d" ]; then
            cp -n "/mingw64/bin/$d" "$dest/" && echo "staged runtime DLL: $dest/$d"
            next="$next $(deps /mingw64/bin/$d)"
        fi
    done
    queue=$(echo "$next" | tr ' ' '\n' | sort -u | grep . || true)
done
