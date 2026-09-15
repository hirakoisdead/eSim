"""Loopback bridge between eSim files and Makerchip's browser plugin.

Makerchip's supported integration surface is a browser-side ES module.  A web
page cannot read or write an arbitrary local Verilog file, so eSim serves one
small page on the loopback interface.  The page embeds Makerchip, loads the
chosen file and autosaves edits through a token-protected same-origin endpoint.

The bridge deliberately owns no eSim UI state.  A write to the current Author
file is observed by :class:`DesignBus` like any other external-editor write,
which preserves its existing non-modal Reload / Keep mine conflict workflow.
"""
import hashlib
import json
import os
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MAX_SOURCE_BYTES = 10 * 1024 * 1024
PLUGIN_URL = "https://makerchip.com/dist/makerchip-plugin.js"


def _revision(data):
    return hashlib.sha256(data).hexdigest()


def _page_html(session_path, filename):
    """Return the local host page. Values cross into JS through JSON only."""
    endpoint = session_path + "/design"
    endpoint_js = json.dumps(endpoint)
    filename_js = json.dumps(os.path.basename(filename))
    plugin_js = json.dumps(PLUGIN_URL)
    page = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="referrer" content="no-referrer">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>eSim · Makerchip</title>
  <style>
    html, body { height: 100%; margin: 0; }
    body { display: grid; grid-template-rows: auto 1fr; background: #111820;
           color: #edf6ff; font: 14px system-ui, sans-serif; }
    #bar { display: flex; align-items: center; gap: 12px; padding: 9px 14px;
           background: #182532; border-bottom: 1px solid #365066; }
    #file { font-weight: 650; }
    #status { color: #a7c4d9; }
    #status.error { color: #ffadad; }
    #actions { margin-left: auto; display: flex; gap: 10px; align-items: center; }
    #open-log { display: none; border-color: #b96b6b; }
    #conflict { display: none; gap: 8px; align-items: center; }
    button { border: 1px solid #4f7895; border-radius: 5px; padding: 5px 9px;
             background: #20394b; color: #edf6ff; cursor: pointer; }
    #makerchip { min-height: 0; }
  </style>
</head>
<body>
  <div id="bar">
    <span id="file"></span>
    <span id="status">Loading Makerchip…</span>
    <span id="actions">
      <button id="open-log">Open compile log</button>
      <span id="conflict">
        The file changed outside this browser.
        <button id="reload">Reload file</button>
        <button id="overwrite">Keep browser edit</button>
      </span>
    </span>
  </div>
  <div id="makerchip"></div>
  <script type="module">
    const endpoint = __ESIM_ENDPOINT__;
    const filename = __ESIM_FILENAME__;
    const pluginUrl = __MAKERCHIP_PLUGIN__;
    const status = document.getElementById('status');
    const conflict = document.getElementById('conflict');
    const openLog = document.getElementById('open-log');
    document.getElementById('file').textContent = filename;

    let revision = null;
    let ide = null;
    let saveTimer = null;
    let saveInFlight = false;
    let saveAgain = false;
    let latestConflict = null;
    const compilationLogs = new Map();

    function setStatus(message, isError = false) {
      status.textContent = message;
      status.classList.toggle('error', isError);
    }

    async function request(url, options) {
      const response = await fetch(url, Object.assign({cache: 'no-store'}, options));
      let body = {};
      try { body = await response.json(); } catch (_) {}
      if (!response.ok && response.status !== 409) {
        throw new Error(body.error || ('HTTP ' + response.status));
      }
      return {response, body};
    }

    async function readFile() {
      return (await request(endpoint)).body;
    }

    function queueSave() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveNow, 450);
      setStatus('Browser edit pending…');
    }

    async function saveNow(force = false) {
      if (!ide) return;
      if (saveInFlight) { saveAgain = true; return; }
      saveInFlight = true;
      try {
        const result = await ide.getCode();
        const reply = await request(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({code: result.code || '', revision, force})
        });
        if (reply.response.status === 409) {
          latestConflict = reply.body;
          conflict.style.display = 'flex';
          setStatus('Autosave paused: edit conflict', true);
        } else {
          revision = reply.body.revision;
          latestConflict = null;
          conflict.style.display = 'none';
          setStatus('Saved locally · recompiling…');
        }
      } catch (error) {
        setStatus('Could not save: ' + error.message, true);
      } finally {
        saveInFlight = false;
        if (saveAgain) { saveAgain = false; queueSave(); }
      }
    }

    document.getElementById('reload').addEventListener('click', async () => {
      try {
        const current = latestConflict || await readFile();
        revision = current.revision;
        await ide.setCode(current.code, false);
        latestConflict = null;
        conflict.style.display = 'none';
        setStatus('Reloaded latest eSim file');
      } catch (error) {
        setStatus('Could not reload: ' + error.message, true);
      }
    });

    document.getElementById('overwrite').addEventListener('click', () => {
      if (latestConflict) revision = latestConflict.revision;
      saveNow(true);
    });

    openLog.addEventListener('click', async () => {
      if (!ide) return;
      try { await ide.api.activatePane('Log'); } catch (_) {}
    });

    try {
      const initial = await readFile();
      revision = initial.revision;
      const {default: IdePlugin} = await import(pluginUrl);
      class EsimMakerchip extends IdePlugin {
        onReady() { setStatus('Compiling simulation…'); }
        onCodeChange() { queueSave(); }
        openWaveform() {
          void this.api.activatePane('Waveform').then(() => {
            setStatus(
              'Simulation ready · Waveform opened · Diagram/Viz need TL-Verilog');
          }).catch(() => {
            setStatus('Simulation ready · open Waveform to inspect signals');
          });
        }
        onCompilationLog(id, log, complete, type) {
          const all = (compilationLogs.get(id) || '') + (log || '');
          compilationLogs.set(id, all);
          if (!complete) {
            setStatus('Compiling simulation…');
            return;
          }
          if (type === 'verilator') {
            const failed = /%Error|\bError:|Exiting due to [1-9]/i.test(all);
            if (failed) {
              openLog.style.display = 'inline-block';
              setStatus('Compilation failed · open the log for details', true);
            } else {
              openLog.style.display = 'none';
              setStatus('Simulation ready · opening Waveform…');
              // The completed Verilator callback is consistently available in
              // stable Makerchip releases. Give its pane a moment to ingest
              // the VCD before switching tabs.
              setTimeout(() => this.openWaveform(), 300);
            }
          }
        }
        onCompilationVcd() {
          openLog.style.display = 'none';
          this.openWaveform();
        }
      }
      ide = await EsimMakerchip.create('makerchip', {
        code: initial.code,
        readOnly: false
      });
    } catch (error) {
      setStatus('Makerchip failed to load: ' + error.message, true);
    }
  </script>
</body>
</html>
"""
    return (page.replace("__ESIM_ENDPOINT__", endpoint_js)
            .replace("__ESIM_FILENAME__", filename_js)
            .replace("__MAKERCHIP_PLUGIN__", plugin_js))


class MakerchipBridge:
    """Serve one file to one unguessable loopback Makerchip session."""

    def __init__(self, filename):
        self.filename = os.path.abspath(filename)
        self.token = secrets.token_urlsafe(32)
        self.session_path = "/session/" + self.token
        self._lock = threading.Lock()
        self._server = None
        self._thread = None

    @property
    def url(self):
        if self._server is None:
            return ""
        host, port = self._server.server_address[:2]
        return "http://%s:%d%s/" % (host, port, self.session_path)

    def start(self):
        if self._server is not None:
            return self.url
        if not os.path.isfile(self.filename):
            raise FileNotFoundError(self.filename)
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == bridge.session_path + "/":
                    bridge._send_html(self)
                elif self.path == bridge.session_path + "/design":
                    bridge._send_design(self)
                else:
                    bridge._send_json(self, HTTPStatus.NOT_FOUND,
                                      {"error": "Not found"})

            def do_POST(self):
                if self.path == bridge.session_path + "/design":
                    bridge._save_design(self)
                else:
                    bridge._send_json(self, HTTPStatus.NOT_FOUND,
                                      {"error": "Not found"})

            def log_message(self, _format, *_args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="eSim-Makerchip-bridge",
            daemon=True)
        self._thread.start()
        return self.url

    def stop(self):
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _read_locked(self):
        with open(self.filename, "rb") as fh:
            data = fh.read()
        return data.decode("utf-8", errors="replace"), _revision(data)

    @staticmethod
    def _common_headers(handler, content_type, length):
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(length))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("X-Content-Type-Options", "nosniff")

    @classmethod
    def _send_json(cls, handler, status, value):
        data = json.dumps(value).encode("utf-8")
        handler.send_response(status)
        cls._common_headers(handler, "application/json; charset=utf-8",
                            len(data))
        handler.end_headers()
        handler.wfile.write(data)

    def _send_html(self, handler):
        data = _page_html(self.session_path, self.filename).encode("utf-8")
        handler.send_response(HTTPStatus.OK)
        self._common_headers(handler, "text/html; charset=utf-8", len(data))
        handler.send_header("Content-Security-Policy",
                            "frame-ancestors 'none'; base-uri 'none'")
        handler.end_headers()
        handler.wfile.write(data)

    def _send_design(self, handler):
        try:
            with self._lock:
                code, revision = self._read_locked()
        except OSError as error:
            self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR,
                            {"error": str(error)})
            return
        self._send_json(handler, HTTPStatus.OK,
                        {"code": code, "revision": revision})

    def _save_design(self, handler):
        if not handler.headers.get("Content-Type", "").lower().startswith(
                "application/json"):
            self._send_json(handler, HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                            {"error": "Content-Type must be application/json"})
            return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if length < 0:
            self._send_json(handler, HTTPStatus.LENGTH_REQUIRED,
                            {"error": "Content-Length is required"})
            return
        if length > MAX_SOURCE_BYTES:
            self._send_json(handler, HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                            {"error": "Design is too large"})
            return
        try:
            payload = json.loads(handler.rfile.read(length).decode("utf-8"))
            code = payload["code"]
            expected = payload["revision"]
            force = payload.get("force") is True
            if not isinstance(code, str) or not isinstance(expected, str):
                raise (TypeError("code and revision must be strings"))
            data = code.encode("utf-8")
            if len(data) > MAX_SOURCE_BYTES:
                raise ValueError("Design is too large")
        except (KeyError, TypeError, ValueError, UnicodeError,
                json.JSONDecodeError) as error:
            self._send_json(handler, HTTPStatus.BAD_REQUEST,
                            {"error": str(error)})
            return

        try:
            with self._lock:
                current_code, current_revision = self._read_locked()
                if not force and expected != current_revision:
                    self._send_json(
                        handler, HTTPStatus.CONFLICT,
                        {"code": current_code, "revision": current_revision})
                    return
                with open(self.filename, "wb") as fh:
                    fh.write(data)
                revision = _revision(data)
        except OSError as error:
            self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR,
                            {"error": str(error)})
            return
        self._send_json(handler, HTTPStatus.OK, {"revision": revision})


__all__ = ["MakerchipBridge", "PLUGIN_URL"]
