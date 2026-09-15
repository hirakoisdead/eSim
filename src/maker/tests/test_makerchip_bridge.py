"""Contract tests for the supported Makerchip browser-plugin bridge."""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from maker.MakerchipBridge import MakerchipBridge, PLUGIN_URL


@pytest.fixture
def running_bridge(tmp_path):
    design = tmp_path / "counter.v"
    design.write_text("module counter; endmodule\n", encoding="utf-8")
    bridge = MakerchipBridge(str(design))
    bridge.start()
    yield bridge, design
    bridge.stop()


def _json(url, payload=None):
    request = Request(url)
    if payload is not None:
        request.data = json.dumps(payload).encode("utf-8")
        request.method = "POST"
        request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=3) as response:
        return response.status, json.load(response)


def test_bridge_binds_only_to_loopback_and_uses_secret_session_path(
        running_bridge):
    bridge, _design = running_bridge
    assert bridge.url.startswith("http://127.0.0.1:")
    assert bridge.token in bridge.url
    assert len(bridge.token) >= 32


def test_host_page_uses_supported_v2_plugin_and_autosave(running_bridge):
    bridge, _design = running_bridge
    with urlopen(bridge.url, timeout=3) as response:
        page = response.read().decode("utf-8")
        assert response.headers["Referrer-Policy"] == "no-referrer"
    assert PLUGIN_URL in page
    assert "IdePlugin.create" not in page  # subclass factory is used below
    assert "EsimMakerchip.create('makerchip'" in page
    assert "onCodeChange()" in page
    assert "onCompilationLog(" in page
    assert "onCompilationVcd()" in page
    assert "Open compile log" in page
    assert "Simulation ready · Waveform opened" in page
    assert "setTimeout(() => this.openWaveform(), 300)" in page
    assert "this.api.activatePane('Waveform')" in page


def test_browser_save_writes_the_exact_design_file(running_bridge):
    bridge, design = running_bridge
    endpoint = bridge.url + "design"
    _, current = _json(endpoint)
    new_code = "module counter; wire edited; endmodule\n"
    status, saved = _json(endpoint, {
        "code": new_code,
        "revision": current["revision"],
        "force": False,
    })
    assert status == 200
    assert design.read_text(encoding="utf-8") == new_code
    assert saved["revision"] != current["revision"]


def test_stale_browser_edit_gets_conflict_instead_of_clobbering_file(
        running_bridge):
    bridge, design = running_bridge
    endpoint = bridge.url + "design"
    _, initial = _json(endpoint)
    design.write_bytes(b"module changed_in_esim; endmodule\n")

    with pytest.raises(HTTPError) as caught:
        _json(endpoint, {
            "code": "module stale_browser; endmodule\n",
            "revision": initial["revision"],
            "force": False,
        })
    assert caught.value.code == 409
    conflict = json.load(caught.value)
    assert conflict["code"] == "module changed_in_esim; endmodule\n"
    assert design.read_text(encoding="utf-8") == conflict["code"]


def test_explicit_keep_browser_edit_resolves_conflict(running_bridge):
    bridge, design = running_bridge
    endpoint = bridge.url + "design"
    _, initial = _json(endpoint)
    design.write_bytes(b"module changed_in_esim; endmodule\n")
    browser_code = "module browser_wins; endmodule\n"

    status, _saved = _json(endpoint, {
        "code": browser_code,
        "revision": initial["revision"],
        "force": True,
    })
    assert status == 200
    assert design.read_text(encoding="utf-8") == browser_code


def test_untrusted_content_type_is_rejected(running_bridge):
    bridge, design = running_bridge
    request = Request(bridge.url + "design", data=b"not-json", method="POST")
    request.add_header("Content-Type", "text/plain")
    with pytest.raises(HTTPError) as caught:
        urlopen(request, timeout=3)
    assert caught.value.code == 415
    assert "module counter" in design.read_text(encoding="utf-8")


def test_wrong_session_token_cannot_read_design(running_bridge):
    bridge, _design = running_bridge
    wrong = bridge.url.replace(bridge.token, "not-the-session-token") + "design"
    with pytest.raises(HTTPError) as caught:
        urlopen(wrong, timeout=3)
    assert caught.value.code == 404
