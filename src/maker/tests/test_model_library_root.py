"""eSim and its NGHDL window must mean the SAME library when they say "model".

The bug this pins: both Appconfigs used to compute ``xml_loc`` at import time
from ``eSim_HOME`` in ~/.esim/config.ini -- a file every launch REWRITES to
whatever root started it (windows_bootstrap). Start a second eSim from another
root (a dev checkout beside an install) and the running session ends up with
two different model libraries in one process:

* the Verilog side refuses to create a block because ``nand_gate`` "already
  exists in the eSim 'Nghdl' library", reading root A;
* the NGHDL page answers "There are no NGHDL models to remove", reading root B.

The model can then be neither built nor removed, and nothing on screen explains
why. Anchoring both to the RUNNING code (configuration.paths) removes the
possibility rather than the symptom, so this test asserts the anchor -- not the
message.
"""
import os

from configuration import paths


def _nghdl_appconfig():
    """The NGHDL window's Appconfig, imported the way eSim imports it (the
    NGHDL package is flat: ``from ngspice_ghdl import Mainwindow``)."""
    import sys
    nghdl_src = os.path.join(os.path.dirname(paths.repo_root()),
                             os.path.basename(paths.repo_root()),
                             "nghdl", "src")
    if nghdl_src not in sys.path:
        sys.path.insert(0, nghdl_src)
    import importlib
    return importlib.import_module("Appconfig").Appconfig


def test_esim_anchors_the_model_library_to_the_running_code():
    from maker.Appconfig import Appconfig
    assert Appconfig.xml_loc == paths.library_path("modelParamXML")


def test_the_nghdl_window_agrees_with_esim():
    from maker.Appconfig import Appconfig
    assert _nghdl_appconfig().xml_loc == Appconfig.xml_loc


def test_the_library_root_survives_a_rewritten_config(tmp_path, monkeypatch):
    """A second eSim rewriting eSim_HOME must not move a running session's
    library. The value is derived, not read, so there is nothing to poison."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cfg_dir = tmp_path / ".esim"
    cfg_dir.mkdir()
    (cfg_dir / "config.ini").write_text(
        "[eSim]\nesim_home = C:\\somewhere\\else\n")

    import importlib
    from maker import Appconfig as mod
    importlib.reload(mod)
    try:
        assert mod.Appconfig.xml_loc == paths.library_path("modelParamXML")
    finally:
        importlib.reload(mod)
