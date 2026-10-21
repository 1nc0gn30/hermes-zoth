import importlib.util, json, sys, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("zoth_plugin", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
mod = importlib.util.module_from_spec(spec); sys.modules["zoth_plugin"] = mod; spec.loader.exec_module(mod)
tools = mod.tools


class Ctx:
    def __init__(self): self.tools, self.skills = {}, {}
    def register_tool(self, name, toolset, schema, handler): self.tools[name] = (schema, handler)
    def register_skill(self, name, path): self.skills[name] = path


def test_register():
    c = Ctx(); mod.register(c)
    assert set(c.tools) == {"zoth_studio_search", "zoth_studio_tool", "zoth_status", "zoth_pull_tool"}
    assert "zoth-studio" in c.skills
    for name, (schema, _) in c.tools.items():
        assert schema["name"] == name


def test_search_and_tool():
    r = json.loads(tools.studio_search({"query": "regex"}))
    assert r["results"][0]["id"] == "regex-droid-builder"
    t = json.loads(tools.studio_tool({"tool_id": "regex-droid-builder"}))
    assert t["studio_url"] == "https://zoth.nullai.tech/tools/regex-droid-builder/"
    assert "error" in json.loads(tools.studio_tool({"tool_id": "nope"}))


def test_status_detects_local_service(monkeypatch):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H); port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(tools, "SERVICES", [("Fake", port, "/health")])
    r = json.loads(tools.status({}))
    srv.shutdown()
    assert r["services"][0]["up"] is True


def test_pull_rejects_unpublished(tmp_path):
    r = json.loads(tools.pull_tool({"tool_id": "zoth-civilization", "dest_dir": str(tmp_path)}))
    assert "error" in r


def test_error_shapes():
    r = json.loads(tools.studio_tool({"tool_id": "regex-droid"}))
    assert r["ok"] is False and r["error"]["code"] == "unknown_tool"
    assert "regex-droid-builder" in r["error"]["did_you_mean"]
    assert json.loads(tools.studio_search({"limit": "x"}))["error"]["code"] == "bad_argument"
    assert json.loads(tools.studio_search({"category": "nope"}))["error"]["code"] == "unknown_category"


def test_bundled_catalog_has_no_personal_data():
    import re
    text = (ROOT / "data" / "studio_tools.json").read_text()
    assert not re.search(r"\+?1?[ (.-]*\d{3}[ ).-]*\d{3}[ .-]\d{4}", text)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text)
    assert not re.search(r"/(home|media|Users)/", text)
    assert not re.search(r"ghp_|github_pat_|sk-[A-Za-z0-9]{16}|AKIA[0-9A-Z]{16}|xox[bp]-", text)
    rows = json.loads(text)
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["studio_url"].startswith("https://zoth.nullai.tech/tools/") for r in rows)
