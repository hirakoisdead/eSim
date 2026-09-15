"""Repo-wide pytest guardrails.

Every test gets a throwaway user home. Without this, any test that reaches
``paths.user_home()`` (directly or through Appconfig/bootstrap) reads and
WRITES the developer's real ``~/.esim`` — on Windows ``os.path.expanduser``
resolves ``USERPROFILE`` and ignores ``HOME``, so a test that only patched
``HOME`` silently escaped its sandbox. One such escape wrote a pytest tmp
path into the real ``workspace.txt`` and bricked every subsequent eSim
launch for the non-elevated user (GUI-thread hang persisting the project
registry into an admin-owned, since-deleted directory).

The same class of escape also reached the developer's real KiCad profile:
``maker.kicad_symlib._kicad_config_dir`` reads ``%APPDATA%\\kicad`` directly on
Windows, which ``expanduser`` does NOT cover, so a test that only redirected
HOME still appended bogus ``sym-lib-table`` entries into the real config. That
hole is closed at the source instead — the only tests that reach
``ensure_lib_registered`` redirect %APPDATA% themselves (see
``maker/tests/test_kicad_symlib_paths.py``).

Do NOT redirect %APPDATA% / %LOCALAPPDATA% globally here: on Windows the
per-user site-packages dir lives under ``%APPDATA%\\Python`` and is inherited by
any test that spawns a subprocess (e.g. test_verifier_lazy_matplotlib). Pointing
APPDATA at an empty tmp dir makes those child interpreters unable to import
user-site packages like PyQt6 — a cure worse than the disease. Keep the KiCad
redirect scoped to the handful of tests that actually write config.

Patching these variables here makes home isolation automatic for the whole
suite instead of a per-test convention that will be forgotten again.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_user_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("user-home")
    monkeypatch.setenv("HOME", str(home))          # POSIX expanduser
    monkeypatch.setenv("USERPROFILE", str(home))   # Windows expanduser
    # USERPROFILE wins in ntpath.expanduser, but keep the pair consistent so
    # code reading HOMEDRIVE/HOMEPATH directly cannot escape either.
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    yield home


@pytest.fixture(autouse=True)
def _detach_appconfig_gui_sinks():
    """Stop a torn-down GUI console/status bar from crashing a LATER test.

    ``configuration.Appconfig`` keeps GUI state in CLASS attributes shared by
    every instance. ``frontEnd.Application`` replaces the class-level log sink
    with a live QTextEdit (``Appconfig.noteArea['Note'] = self.noteArea``) and
    wires ``Appconfig.statusbar``. When the test that built that Application
    tears the widgets down, the C++ objects are deleted but the class
    attributes still point at them. The next MODULE's plotWindow.__init__ then
    calls ``print_info`` -> ``_append_note`` -> ``QTextEdit.append()`` on the
    dead object and dies with ``RuntimeError: wrapped C/C++ object of type
    QTextEdit has been deleted`` — reproduced as 17 ngspiceSimulation "ERROR at
    setup" failures that only appear in a full-suite run.

    Detaching both sinks back to their pre-GUI baseline after every test makes
    the sink-replacement local to the test that did it, so the leak cannot
    cross module boundaries. A test that legitimately builds an Application
    re-attaches its own sink during its own run, so this is invisible to it.
    """
    yield
    try:
        from configuration.Appconfig import Appconfig
    except Exception:
        return
    # Back to the plain-list / None state the class starts in.
    Appconfig.noteArea['Note'] = []
    Appconfig.statusbar = None
