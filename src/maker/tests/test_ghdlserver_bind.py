"""ghdlserver bind-address regression guard.

Every NGHDL co-simulation starts one VHDL-testbench TCP server per model
instance on port ``5000 + instance_id``. That server used to bind
``INADDR_ANY``, so it listened on every interface for the whole run even
though the only client is the generated code model dialling ``127.0.0.<n>``
on the same machine: pure exposure on a LAN, plus the Windows firewall
consent dialog on the first simulation (cancelling it breaks the run in a
way nobody connects back to the popup).

``ghdlserver.c`` is compiled per model by the C toolchain at upload time and
has no unit-test harness in this repo, so this is a source guard on the
invariant — the same shape as the ``createKicadLibrary`` parity guard in
``test_port_parsing.py``.
"""
import os

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_GHDLSERVER_C = os.path.join(_REPO_ROOT, "nghdl", "src", "ghdlserver",
                             "ghdlserver.c")


def _create_server_body():
    """Source text of create_server(), comments stripped.

    Comments are dropped so the assertions below describe the code, not the
    prose around it (the fix explains INADDR_ANY in a comment on purpose).
    """
    with open(_GHDLSERVER_C, "r", encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    start = src.index("static int create_server(")
    body = src[start:src.index("\n}", start)]
    lines = []
    in_block = False
    for line in body.splitlines():
        if in_block:
            if "*/" in line:
                line = line.split("*/", 1)[1]
                in_block = False
            else:
                continue
        if "/*" in line:
            head, rest = line.split("/*", 1)
            if "*/" in rest:
                line = head + rest.split("*/", 1)[1]
            else:
                line, in_block = head, True
        lines.append(line.split("//", 1)[0])
    return "\n".join(lines)


def test_server_never_binds_the_wildcard_address():
    """No live INADDR_ANY anywhere in create_server()."""
    assert "INADDR_ANY" not in _create_server_body()


def test_server_binds_the_address_the_client_dials():
    """my_ip (the generated cfunc's 127.0.0.<n>) is what gets bound."""
    body = _create_server_body()
    assert "inet_addr(my_ip)" in body
    assert "serv_addr.sin_addr.s_addr = bind_ip;" in body


def test_non_loopback_and_unparsable_addresses_fall_back_to_loopback():
    """A bad/absent/LAN my_ip must degrade to 127.0.0.1, never to the
    wildcard, and a failed alias bind must retry on 127.0.0.1."""
    body = _create_server_body()
    assert "INADDR_NONE" in body            # unparsable my_ip
    assert ">> 24) != 127" in body          # anything outside 127.0.0.0/8
    assert body.count("htonl(INADDR_LOOPBACK)") >= 3  # coerce + retry guard
