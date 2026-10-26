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
    desc = mod.schemas.PULL_TOOL["description"]
    assert "plugin-data/zoth" in desc
    assert "./tools" not in desc
    assert "skills" in desc and "plugins" in desc


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


_PUBLISHED = "osint-scout-skill"
_REPO = "osint-scout-skill"


class _GitResult:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def _hermes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    hermes = home / ".hermes"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    monkeypatch.delenv("HERMES_DATA_DIR_SUFFIX", raising=False)
    cwd = tmp_path / "gateway-cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return hermes.resolve(), cwd


def _block_git(monkeypatch):
    def _run(*_a, **_k):
        raise AssertionError("git must not run")
    monkeypatch.setattr(tools.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(tools.subprocess, "run", _run)


def _capture_git(monkeypatch):
    captured = {}

    def _run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _GitResult()

    monkeypatch.setattr(tools.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(tools.subprocess, "run", _run)
    return captured


def test_pull_allows_dest_under_clone_root(tmp_path, monkeypatch):
    hermes, _cwd = _hermes(tmp_path, monkeypatch)
    captured = _capture_git(monkeypatch)
    parent = hermes / "plugin-data" / "zoth" / "vendor"
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED, "dest_dir": str(parent)}))
    dest = (parent / _REPO).resolve()
    assert r["ok"] is True
    assert Path(r["path"]) == dest
    assert captured["cmd"] == ["git", "clone", "--depth", "1", f"https://github.com/NullAITech/{_REPO}.git", str(dest)]
    assert captured["kwargs"].get("shell") is not True
    assert dest.is_relative_to(hermes / "plugin-data" / "zoth")


def test_pull_refuses_escape_into_hermes_skills_or_plugins(tmp_path, monkeypatch):
    hermes, _cwd = _hermes(tmp_path, monkeypatch)
    _block_git(monkeypatch)
    attacks = [
        "~/.hermes/skills",
        str(hermes / "skills"),
        str(hermes / "plugins"),
        "../../skills",
        "../../plugins",
        "tools/../../../skills",
    ]
    for dest_dir in attacks:
        r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED, "dest_dir": dest_dir}))
        assert r["ok"] is False, dest_dir
        assert r["error"]["code"] == "dest_outside_root", dest_dir
    assert not (hermes / "skills").exists()
    assert not (hermes / "plugins").exists()
    assert not (hermes / "tools").exists()


def test_pull_refuses_absolute_path_outside_root(tmp_path, monkeypatch):
    hermes, _cwd = _hermes(tmp_path, monkeypatch)
    _block_git(monkeypatch)
    outside = tmp_path / "outside"
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED, "dest_dir": str(outside)}))
    assert r["ok"] is False
    assert r["error"]["code"] == "dest_outside_root"
    assert not outside.exists()
    assert not (hermes / "skills").exists()


def test_pull_refuses_symlink_that_resolves_outside_root(tmp_path, monkeypatch):
    hermes, _cwd = _hermes(tmp_path, monkeypatch)
    _block_git(monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = hermes / "plugin-data" / "zoth" / "linked"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED, "dest_dir": "linked"}))
    assert r["ok"] is False
    assert r["error"]["code"] == "dest_outside_root"
    assert list(outside.iterdir()) == []


def test_pull_relative_dest_lands_under_clone_root(tmp_path, monkeypatch):
    hermes, cwd = _hermes(tmp_path, monkeypatch)
    captured = _capture_git(monkeypatch)
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED, "dest_dir": "vendor"}))
    dest = (hermes / "plugin-data" / "zoth" / "vendor" / _REPO).resolve()
    assert r["ok"] is True
    assert Path(r["path"]) == dest
    assert captured["cmd"][-1] == str(dest)
    assert cwd not in dest.parents


def test_pull_refuses_when_data_root_symlink_points_at_skills(tmp_path, monkeypatch):
    hermes, _cwd = _hermes(tmp_path, monkeypatch)
    _block_git(monkeypatch)
    skills = hermes / "skills"
    skills.mkdir(parents=True)
    link_parent = hermes / "plugin-data"
    link_parent.mkdir(parents=True)
    (link_parent / "zoth").symlink_to(skills, target_is_directory=True)
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED, "dest_dir": "tools"}))
    assert r["ok"] is False
    assert r["error"]["code"] == "dest_outside_root"
    assert list(skills.iterdir()) == []


def test_pull_refuses_dotdot_repo_name(tmp_path, monkeypatch):
    _hermes(tmp_path, monkeypatch)
    _block_git(monkeypatch)
    monkeypatch.setattr(tools, "_find", lambda _tool_id: {
        "id": "x",
        "published": True,
        "github": "https://github.com/NullAITech/..",
    })
    r = json.loads(tools.pull_tool({"tool_id": "x", "dest_dir": "tools"}))
    assert r["ok"] is False
    assert r["error"]["code"] == "bad_repo"


def test_pull_prefers_get_hermes_home(tmp_path, monkeypatch):
    import types
    profile = tmp_path / "profile-home"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "env-home"))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    fake = types.ModuleType("hermes_constants")
    fake.get_hermes_home = lambda: profile
    monkeypatch.setitem(sys.modules, "hermes_constants", fake)
    captured = _capture_git(monkeypatch)
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED}))
    dest = (profile / "plugin-data" / "zoth" / "tools" / _REPO).resolve()
    assert r["ok"] is True
    assert Path(r["path"]) == dest
    assert captured["cmd"][-1] == str(dest)
    assert "env-home" not in str(dest)


def test_pull_default_lands_under_plugin_data_root(tmp_path, monkeypatch):
    hermes, cwd = _hermes(tmp_path, monkeypatch)
    captured = _capture_git(monkeypatch)
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED}))
    dest = (hermes / "plugin-data" / "zoth" / "tools" / _REPO).resolve()
    assert r["ok"] is True
    assert Path(r["path"]) == dest
    assert captured["cmd"][-1] == str(dest)
    assert cwd not in dest.parents
    assert not (cwd / "tools").exists()
    assert not (hermes / "tools").exists()


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
