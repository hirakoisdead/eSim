"""Regression guards for install-nghdl.sh hardening.

Shell that only runs on a real Ubuntu box, so these are a syntax check plus
structural guards on the three behaviours that bite the user:

* ``--uninstall`` purged ghdl/verilator (packages shared with anything
  else on the machine) without asking, and removed /usr/bin/ngspice without
  saying that nothing replaced it.
* The Icarus fallback cloned ~200 MB of history to check out one pinned
  commit, on exactly the slow machines that path exists for.
* The simulator upgrade deleted the working tree BEFORE proving the new
  one had been extracted, and swallowed the failure with ``|| true``: a failed
  upgrade left the user with no simulator at all.

The extraction-order guard is executable: the real snippet is replayed against
a fixture tree, once with a good tarball and once with a broken one.
"""
import os
import shutil
import subprocess
import tarfile
import textwrap

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_SCRIPT = os.path.join(_REPO_ROOT, "nghdl", "install-nghdl.sh")

bash = shutil.which("bash")
needs_bash = pytest.mark.skipif(bash is None, reason="bash not available")


def _source():
    with open(_SCRIPT, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _strip_comments(text):
    """Drop whole-line shell comments: they quote the very code that was
    removed, so an ordering assertion must judge the commands only."""
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))


def _function(name):
    """Commands of a top-level shell function, up to the column-0 brace."""
    text = _source()
    start = text.index(name + "() {")
    return _strip_comments(text[start:text.index("\n}", start)])


@needs_bash
def test_script_parses():
    assert subprocess.run([bash, "-n", _SCRIPT]).returncode == 0


# Shared-package uninstall behavior


def test_uninstall_asks_before_purging_shared_packages():
    text = _source()
    start = text.index("--uninstall)")
    body = _strip_comments(text[start:text.index(";;", start)])

    purge = "apt-get purge -y ghdl-llvm ghdl-gcc verilator"
    assert purge in body
    # The purge sits behind an interactive confirmation…
    prompt = body.index("read -rp")
    assert prompt < body.index(purge)
    assert body[prompt:body.index(purge)].count("if ") >= 1
    # …and a non-interactive run (CI, piped stdin) keeps the packages.
    assert "[ -t 0 ]" in body


def test_uninstall_says_ngspice_is_gone():
    text = _source()
    start = text.index("--uninstall)")
    body = _strip_comments(text[start:text.index(";;", start)])
    assert "/usr/bin/ngspice" in body
    assert "sudo apt install ngspice" in body


# ---------------------------------------------------------------- M20a


def test_icarus_fallback_fetches_only_the_pinned_commit():
    body = _function("installIcarus")
    assert 'fetch -q --depth 1 origin "$ICARUS_REF"' in body
    assert "checkout -q FETCH_HEAD" in body
    # The full clone survives only as the fallback for a server that refuses
    # fetch-by-SHA, i.e. it must be inside the failure branch.
    shallow = body.index("--depth 1")
    clone = body.index("git clone")
    assert shallow < clone
    assert "else" in body[shallow:clone]


# ---------------------------------------------------------------- M20b


def test_extraction_replaces_the_old_tree_only_after_the_new_one_is_proven():
    body = _function("installNGHDL")
    assert 'mv "$staged" "$HOME/$nghdl"' in body
    # No swallowed move.
    assert "|| true" not in body.split("log \"Extracted")[0]
    # Order: extract -> verify -> remove old -> move into place.
    assert (body.index("tar -xJf")
            < body.index('[ ! -f "$staged/configure" ]')
            < body.index('rm -rf "$HOME/$nghdl"')
            < body.index('mv "$staged"'))


_REPLAY = textwrap.dedent("""
    set -e
    nghdl="nghdl-simulator"
    HOME="$1"
    src_dir="$1/src"
    cd "$src_dir"
    staged="$HOME/${nghdl}-source"
    rm -rf "$staged"
    tar -xJf "${nghdl}-source.tar.xz" -C "$HOME"
    if [ ! -f "$staged/configure" ]; then
        echo "ERROR: extraction produced no usable tree"
        exit 1
    fi
    rm -rf "$HOME/$nghdl"
    mv "$staged" "$HOME/$nghdl"
    echo OK
""")


def _replay(tmp_path, payload_dir, marker="configure"):
    """Run the (verbatim) extraction sequence against a fake home whose
    simulator tree already holds a file we can look for afterwards."""
    home = tmp_path / "home"
    src = home / "src"
    src.mkdir(parents=True)

    # The installed tree that must survive a failed upgrade.
    old = home / "nghdl-simulator"
    old.mkdir()
    (old / "IAM_THE_WORKING_TREE").write_text("keep me")

    # Build the tarball payload: <payload_dir>/ with or without ./configure.
    # tarfile, not the tar CLI: MSYS tar reads a "C:\…" -f argument as a remote
    # host spec and refuses it.
    payload = tmp_path / "payload" / payload_dir
    payload.mkdir(parents=True)
    (payload / marker).write_text("#!/bin/sh\n")
    tarball = str(src / "nghdl-simulator-source.tar.xz")
    with tarfile.open(tarball, "w:xz") as tf:
        tf.add(str(payload), arcname=payload_dir)

    script = tmp_path / "replay.sh"
    script.write_text(_REPLAY)
    proc = subprocess.run(
        [bash, str(script), str(home).replace("\\", "/")],
        capture_output=True, text=True)
    return proc, old


@needs_bash
def test_replay_good_tarball_upgrades(tmp_path):
    proc, old = _replay(tmp_path, "nghdl-simulator-source")
    assert proc.returncode == 0, proc.stderr
    assert (old / "configure").is_file()          # new tree is in place
    assert not (old / "IAM_THE_WORKING_TREE").exists()


@needs_bash
def test_replay_broken_tarball_keeps_the_working_tree(tmp_path):
    """The pre-fix order (extract, rm -rf, mv || true) destroyed the install
    here and failed later with an unrelated-looking error."""
    proc, old = _replay(tmp_path, "some-other-name")
    assert proc.returncode == 1
    assert "no usable tree" in proc.stdout
    assert (old / "IAM_THE_WORKING_TREE").is_file()
