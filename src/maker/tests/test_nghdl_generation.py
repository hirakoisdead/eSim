"""Regression tests for NGHDL model generation.

``nghdl/src/model_generation.py`` wrote every generated file (connection_info,
cfunc.mod, ifspec.ifs, the testbench, both shell scripts) into the CURRENT
WORKING DIRECTORY — eSim's launch directory — as a side effect of merely
constructing the class. That made the whole module difficult to test, and it
failed outright when eSim was launched from a read-only directory.
It now writes into a caller-supplied ``outdir``, which is what makes the rest
of these tests possible:

* The POSIX branch baked ``$HOME/nghdl-simulator/...`` into the generated
  cfunc instead of honouring config.ini's DIGITAL_MODEL.
* ``send_data``/``recv_data``/``temp_<port>`` were fixed 1024-byte
  buffers; a wide-enough model silently truncated its co-simulation messages.
"""
import importlib.util
import os

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_NGHDL_SRC = os.path.join(_REPO_ROOT, "nghdl", "src")

_VHDL = """entity adder is
port (
    clk : in std_logic;
    a : in std_logic_vector(3 downto 0);
    sum : out std_logic_vector(4 downto 0)
);
end entity;
"""

_GENERATED = ("connection_info.txt", "cfunc.mod", "ifspec.ifs",
              "adder_tb.vhdl", "start_server.sh", "sock_pkg_create.sh")


def _load():
    """Import nghdl/src/model_generation.py by path (stdlib-only module) with
    no sys.path pollution / vendored-module shadowing."""
    src = os.path.join(_NGHDL_SRC, "model_generation.py")
    spec = importlib.util.spec_from_file_location("nghdl_model_gen", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_home(tmp_path, monkeypatch, digital_root):
    """Point expanduser('~') at a throwaway home holding a real config.ini."""
    home = tmp_path / "home"
    (home / ".nghdl").mkdir(parents=True)
    nghdl_home = str(tmp_path / "nghdl-simulator").replace("\\", "/")
    src_home = str(tmp_path / "src").replace("\\", "/")
    (home / ".nghdl" / "config.ini").write_text(
        "[NGHDL]\n"
        "NGHDL_HOME = " + nghdl_home +
        "\nDIGITAL_MODEL = " + digital_root +
        "\nRELEASE = %(NGHDL_HOME)s/release\n"
        "[SRC]\n"
        "SRC_HOME = " + src_home + "\n"
        "LICENSE = %(SRC_HOME)s/LICENSE\n")
    # ntpath.expanduser reads USERPROFILE, posixpath reads HOME.
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return home


def _build(tmp_path, monkeypatch, vhdl=_VHDL,
           digital_root="/opt/relocated/nghdl/src/xspice/icm"):
    """Full constructor + every generator, into a dedicated outdir, with the
    CWD pointed somewhere else entirely so a stray relative write shows up."""
    mod = _load()
    _fake_home(tmp_path, monkeypatch, digital_root)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    src = tmp_path / "adder.vhdl"
    src.write_text(vhdl)
    outdir = tmp_path / "gen"

    model = mod.ModelGeneration(str(src), outdir=str(outdir))
    model.readPortInfo()
    model.createCfuncModFile()
    model.createIfSpecFile()
    model.createTestbench()
    model.createServerScript()
    model.createSockScript()
    return mod, model, outdir, cwd


# Output-directory isolation


def test_every_generated_file_lands_in_outdir(tmp_path, monkeypatch):
    _, _, outdir, cwd = _build(tmp_path, monkeypatch)

    for name in _GENERATED:
        assert (outdir / name).is_file(), name
    # Nothing leaked into the working directory (the old behaviour).
    assert list(cwd.iterdir()) == []


def test_outdir_is_created_on_demand(tmp_path, monkeypatch):
    mod = _load()
    _fake_home(tmp_path, monkeypatch, "/opt/icm")
    src = tmp_path / "adder.vhdl"
    src.write_text(_VHDL)

    nested = tmp_path / "does" / "not" / "exist"
    mod.ModelGeneration(str(src), outdir=str(nested))
    assert (nested / "connection_info.txt").is_file()


def test_ports_survive_the_round_trip(tmp_path, monkeypatch):
    """The parsed VHDL must reach connection_info.txt with the right widths."""
    _, model, outdir, _ = _build(tmp_path, monkeypatch)

    assert (outdir / "connection_info.txt").read_text().split() == [
        "clk", "in", "1", "a", "in", "4", "sum", "out", "5"]
    assert model.input_port == ["clk:1", "a:4"]
    assert model.output_port == ["sum:5"]

    testbench = (outdir / "adder_tb.vhdl").read_text()
    assert "entity adder_tb is" in testbench
    assert "a: in std_logic_vector(3 downto 0);" in testbench
    assert "sum: out std_logic_vector(4 downto 0)" in testbench


def test_upload_flow_no_longer_chdirs(tmp_path):
    """ngspice_ghdl.createModelFiles generated into the CWD
    and chdir'ed twice to do it. The method must now be chdir-free (it is a
    QWidget method, so this is a source guard rather than a call)."""
    # utf-8 explicitly: the file has non-ASCII text and this box's default
    # encoding is cp1252.
    with open(os.path.join(_NGHDL_SRC, "ngspice_ghdl.py"),
              encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("def createModelFiles(")
    body = text[start:text.index("\n    def ", start + 1)]
    # Comments explain the removed chdir, so judge the CODE only.
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "os.chdir" not in code
    assert "tempfile.mkdtemp" in body
    # and it hands that temp dir to the generator instead of using the CWD
    assert "outdir=workdir" in body


# Relocated digital-model path


def test_posix_start_server_command_honours_the_config(tmp_path, monkeypatch):
    """The generated INIT must launch the server from the CONFIGURED digital
    model root. Both branches are exercised directly: os.name cannot be
    monkeypatched (it makes pathlib build POSIX paths on Windows and breaks
    pytest itself), which is why the command builder is a separate method."""
    root = "/opt/relocated/nghdl/src/xspice/icm"
    _, model, outdir, _ = _build(tmp_path, monkeypatch, digital_root=root)

    posix_cmd = model._start_server_command(False)
    assert posix_cmd.startswith(root + "/ghdl/adder/DUTghdl/start_server.sh")
    assert "nghdl-simulator" not in posix_cmd     # the old baked-in path
    assert posix_cmd.endswith('%d %s &"')
    assert "\\" not in posix_cmd                  # POSIX target: no host sep

    windows_cmd = model._start_server_command(True)
    assert root + "/ghdl/adder/DUTghdl/start_server.sh" in windows_cmd
    assert "mintty.exe" in windows_cmd

    # And the cfunc actually contains the configured path, not $HOME/nghdl-…
    cfunc = (outdir / "cfunc.mod").read_text()
    assert root + "/ghdl/adder/DUTghdl/start_server.sh" in cfunc
    assert "/nghdl-simulator/src/xspice/icm/ghdl/" not in cfunc


def test_command_buffer_fits_the_command(tmp_path, monkeypatch):
    """A long install path used to be snprintf'ed into a fixed char[1024] and
    silently truncated into an unrunnable command."""
    root = "/opt/" + ("very_long_directory_name/" * 40) + "icm"
    _, model, outdir, _ = _build(tmp_path, monkeypatch, digital_root=root)

    cfunc = (outdir / "cfunc.mod").read_text()
    size = int(cfunc.split("char command[")[1].split("]")[0])
    assert size > len(model._start_server_command(False))
    assert "snprintf(command,sizeof(command)" in cfunc
    assert "snprintf(command,1024" not in cfunc


# Generated buffer sizing


def test_message_buffers_are_sized_from_the_ports(tmp_path, monkeypatch):
    _, _, outdir, _ = _build(tmp_path, monkeypatch)
    cfunc = (outdir / "cfunc.mod").read_text()

    # "clk:%s,a:%s" with a 1-bit and a 4-bit value -> 12 chars + NUL.
    assert "char send_data[13];" in cfunc
    # "sum:00000;" -> 10 chars + the NUL the client writes at [bytes_recieved].
    assert "char recv_data[11];" in cfunc
    # width + the '\0' the assignment loop writes at [PORT_SIZE].
    assert "char temp_clk[2];" in cfunc
    assert "char temp_a[5];" in cfunc
    assert "[1024]" not in cfunc

    # recv must leave room for that NUL: a full buffer would put it one past
    # the end of the array.
    assert "recv(socket_fd,recv_data,sizeof(recv_data)-1,0)" in cfunc


def test_oversized_model_is_refused_before_anything_is_written(
        tmp_path, monkeypatch):
    """Beyond the server's own limits the message cannot be delivered at all.
    Refuse with an explanation instead of truncating it into wrong data."""
    mod = _load()
    _fake_home(tmp_path, monkeypatch, "/opt/icm")
    src = tmp_path / "adder.vhdl"
    src.write_text(_VHDL)
    outdir = tmp_path / "gen"

    model = mod.ModelGeneration(str(src), outdir=str(outdir))
    model.readPortInfo()
    model.input_port = ["wide:%d" % (mod.SERVER_RECV_CAP + 1)]

    with pytest.raises(ValueError) as err:
        model.createCfuncModFile()
    assert str(mod.SERVER_RECV_CAP) in str(err.value)
    assert not (outdir / "cfunc.mod").exists()

    model.input_port = ["clk:1"]
    model.output_port = ["wide:%d" % (mod.SERVER_REPLY_CAP + 1)]
    with pytest.raises(ValueError) as err:
        model.createCfuncModFile()
    assert str(mod.SERVER_REPLY_CAP) in str(err.value)
    assert not (outdir / "cfunc.mod").exists()


def test_server_caps_match_the_c_sources():
    """The two limits are the server's, not ours — keep them in sync with
    ghdlserver.h/.c or the refusal above guards the wrong number."""
    mod = _load()
    with open(os.path.join(_NGHDL_SRC, "ghdlserver", "ghdlserver.h"),
              encoding="utf-8", errors="replace") as fh:
        header = fh.read()
    assert "#define MAX_BUF_SIZE " + str(mod.SERVER_RECV_CAP) in header
    with open(os.path.join(_NGHDL_SRC, "ghdlserver", "ghdlserver.c"),
              encoding="utf-8", errors="replace") as fh:
        assert "calloc(1, " + str(mod.SERVER_REPLY_CAP) + ")" in fh.read()


# ------------------------------------------------- event-storage indices

_VHDL_TWO_OUTPUTS = """entity adder is
port (
    clk : in std_logic;
    a : in std_logic_vector(3 downto 0);
    sum : out std_logic_vector(4 downto 0);
    carry : out std_logic
);
end entity;
"""


def test_output_storage_uses_timepoint_0_and_1(tmp_path, monkeypatch):
    """cm_event_get_ptr(tag, timepoint): the tag picks the port's storage,
    the timepoint picks how far BACK in the rotating state history to look --
    0 current, 1 previous. This generator carried a counter that made the
    timepoint climb with the tag, so port 1 got (1,1)/(1,2): it wrote into a
    stale block and compared against one aliasing it, and froze after its
    first transition. Same defect and same fix as the Verilog generator (see
    test_ngveri_event_ptrs.py)."""
    _, _, outdir, _ = _build(tmp_path, monkeypatch, vhdl=_VHDL_TWO_OUTPUTS)
    cfunc = (outdir / "cfunc.mod").read_text()

    for tag, name in enumerate(["sum", "carry"]):
        assert ("_op_%s = (Digital_State_t *) cm_event_get_ptr(%d,0);"
                % (name, tag)) in cfunc
        assert ("_op_%s_old = (Digital_State_t *) cm_event_get_ptr(%d,1);"
                % (name, tag)) in cfunc

    import re as _re
    timepoints = {int(m) for m in
                  _re.findall(r"cm_event_get_ptr\(\s*\d+\s*,\s*(\d+)\s*\)",
                              cfunc)}
    assert timepoints <= {0, 1}, sorted(timepoints)
