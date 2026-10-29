import importlib.util, json, os, sys, threading
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
        plain = [c for i, c in enumerate(cmd) if not (c == "-c" or (i and cmd[i - 1] == "-c"))]
        captured.setdefault("cmd", plain)
        captured.setdefault("kwargs", kwargs)
        captured.setdefault("all", []).append(plain)
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
    assert captured["cmd"] == ["git", "clone", "--depth", "1", "--", f"https://github.com/NullAITech/{_REPO}.git", str(dest)]
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
    assert r["error"]["did_you_mean"] == ["regex-droid-builder"]
    assert json.loads(tools.studio_search({"limit": "x"}))["error"]["code"] == "bad_argument"
    assert json.loads(tools.studio_search({"category": "nope"}))["error"]["code"] == "unknown_category"


def test_z01_category_filtering():
    # Exact category filter
    r1 = json.loads(tools.studio_search({"category": "Security & Recon"}))
    assert r1["ok"] is True
    assert r1["count"] == 9
    assert all(t["category"] == "Security & Recon" for t in r1["results"])

    # Family prefix filter: 'security' matches all 4 Security & * categories
    r2 = json.loads(tools.studio_search({"category": "security"}))
    assert r2["ok"] is True
    assert r2["count"] > 9
    assert all(t["category"].startswith("Security &") for t in r2["results"])

    # Invalid category returns unknown_category with full list
    r3 = json.loads(tools.studio_search({"category": "nope"}))
    assert r3["ok"] is False
    assert r3["error"]["code"] == "unknown_category"
    assert "Security & Recon" in r3["error"]["categories"]


def test_z02_limit_handling():
    # limit=0 is clamped to 1 (not swallowed into 10)
    r0 = json.loads(tools.studio_search({"limit": 0}))
    assert r0["ok"] is True
    assert len(r0["results"]) == 1

    # limit=None / absent defaults to 10
    r_def = json.loads(tools.studio_search({}))
    assert r_def["ok"] is True
    assert len(r_def["results"]) == 10

    # invalid limit returns bad_argument
    r_bad = json.loads(tools.studio_search({"limit": "invalid"}))
    assert r_bad["ok"] is False
    assert r_bad["error"]["code"] == "bad_argument"


def test_z03_search_ranking_and_projection():
    # Single term query
    r_jwt = json.loads(tools.studio_search({"query": "jwt"}))
    assert r_jwt["ok"] is True
    assert r_jwt["results"][0]["id"] == "jwt-inspector-guard"
    # Both version and score are projected
    assert "version" in r_jwt["results"][0]
    assert "score" in r_jwt["results"][0]
    assert r_jwt["results"][0]["score"] > 0

    # Multi-term query: AND logic filters unrelated single-term matches
    r_rb = json.loads(tools.studio_search({"query": "regex builder"}))
    assert r_rb["ok"] is True
    assert r_rb["results"][0]["id"] == "regex-droid-builder"
    # Ensure unrelated tools containing only 'builder' (like pwa-manifest-builder) without 'regex' are dropped
    ids = [t["id"] for t in r_rb["results"]]
    assert "pwa-manifest-builder" not in ids


def test_z04_suggest_noise_reduction():
    r = json.loads(tools.studio_tool({"tool_id": "regex-droid"}))
    assert r["ok"] is False
    assert r["error"]["code"] == "unknown_tool"
    assert r["error"]["did_you_mean"] == ["regex-droid-builder"]


def test_z05_friendly_name_resolution():
    # studio_tool accepts exact human name
    r = json.loads(tools.studio_tool({"tool_id": "JWT Inspector Guard"}))
    assert r["ok"] is True
    assert r["id"] == "jwt-inspector-guard"

    # studio_tool handles None, empty string, and whitespace gracefully as <missing>
    for empty_val in (None, "", "   "):
        r_none = json.loads(tools.studio_tool({"tool_id": empty_val}))
        assert r_none["ok"] is False
        assert "<missing>" in r_none["error"]["message"]


def test_z07_services_port_coverage():
    # Ports 8095-8106 must all be covered in SERVICES
    ports = {port for _, port, _ in tools.SERVICES}
    for p in range(8095, 8107):
        assert p in ports, f"Port {p} missing from SERVICES"


def test_z10_errors_documented_in_readme():
    readme = (ROOT / "README.md").read_text()
    for code in ("bad_repo", "unknown_tool", "unknown_category", "bad_argument", "not_published", "git_missing"):
        assert code in readme


def _bare_repo(tmp_path):
    """Local bare repo with main (2 commits), a tag v1.0.0 on the first commit and a branch dev."""
    import subprocess as sp
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull}
    work, bare = tmp_path / "work", tmp_path / "remote.git"
    run = lambda *a, cwd=work: sp.run(["git", *a], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()
    work.mkdir()
    run("init", "-q", "-b", "main")
    (work / "f.txt").write_text("one"); run("add", "."); run("commit", "-qm", "one")
    first = run("rev-parse", "HEAD"); run("tag", "v1.0.0")
    run("checkout", "-qb", "dev"); (work / "f.txt").write_text("dev"); run("commit", "-qam", "dev")
    dev = run("rev-parse", "HEAD"); run("checkout", "-q", "main")
    (work / "f.txt").write_text("two"); run("commit", "-qam", "two")
    second = run("rev-parse", "HEAD")
    run("clone", "-q", "--bare", str(work), str(bare), cwd=tmp_path)
    return bare, first, second, dev


def _use_local_remote(monkeypatch, bare):
    url = bare.resolve().as_uri()
    monkeypatch.setattr(tools, "_repo_url", lambda _t: url)
    # Tests only: allow file:// so we never touch the network. Hooks stay disabled.
    monkeypatch.setattr(tools, "GIT_SAFE_CONFIG", ["-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=always"])


def test_z11_real_git_ref_checkout(tmp_path, monkeypatch):
    hermes, _cwd = _hermes(tmp_path, monkeypatch)
    bare, first, second, dev = _bare_repo(tmp_path)
    _use_local_remote(monkeypatch, bare)
    dest = hermes / "plugin-data" / "zoth" / "tools" / _REPO
    pull = lambda **kw: json.loads(tools.pull_tool({"tool_id": _PUBLISHED, **kw}))

    r = pull(ref="v1.0.0")                      # fresh clone of a tag
    assert r["ok"] is True, r
    assert r["commit"] == first and (dest / "f.txt").read_text() == "one"

    r = pull(ref="dev")                         # re-pull a pinned checkout onto a branch
    assert r["ok"] is True, r
    assert r["commit"] == dev and (dest / "f.txt").read_text() == "dev"

    r = pull(ref=first)                         # full SHA on an existing checkout
    assert r["ok"] is True, r
    assert r["commit"] == first

    r = pull()                                  # unpinned re-pull of a detached checkout -> default branch tip
    assert r["ok"] is True, r
    assert r["commit"] == second and (dest / "f.txt").read_text() == "two"

    r = pull(ref="no-such-ref")
    assert r["ok"] is False and r["error"]["code"] == "git_failed"


def test_z11_real_git_fresh_clone_by_sha(tmp_path, monkeypatch):
    hermes, _cwd = _hermes(tmp_path, monkeypatch)
    bare, first, _second, _dev = _bare_repo(tmp_path)
    _use_local_remote(monkeypatch, bare)
    monkeypatch.setattr(tools, "GIT_SAFE_CONFIG", tools.GIT_SAFE_CONFIG + ["-c", "uploadpack.allowAnySHA1InWant=true"])
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED, "ref": first}))
    assert r["ok"] is True, r
    assert r["commit"] == first


def test_pull_refuses_checkout_of_another_remote(tmp_path, monkeypatch):
    hermes, _cwd = _hermes(tmp_path, monkeypatch)
    bare, *_ = _bare_repo(tmp_path)
    _use_local_remote(monkeypatch, bare)
    assert json.loads(tools.pull_tool({"tool_id": _PUBLISHED}))["ok"] is True
    monkeypatch.setattr(tools, "_repo_url", lambda _t: "https://github.com/NullAITech/other.git")
    r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED}))
    assert r["ok"] is False and r["error"]["code"] == "dest_exists"


def test_bad_refs_rejected(tmp_path, monkeypatch):
    _hermes(tmp_path, monkeypatch)
    _block_git(monkeypatch)
    for bad in ["-b", "--upload-pack=x", "a/../b", "..", "a//b", "main.lock", "x@{1}", "a b", "/abs", "a;rm"]:
        r = json.loads(tools.pull_tool({"tool_id": _PUBLISHED, "ref": bad}))
        assert r["ok"] is False and r["error"]["code"] == "bad_argument", bad


def test_git_env_is_minimal_and_hooks_disabled(tmp_path, monkeypatch):
    _hermes(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-leak")
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    captured = _capture_git(monkeypatch)
    json.loads(tools.pull_tool({"tool_id": _PUBLISHED}))
    env = captured["kwargs"]["env"]
    assert "GITHUB_TOKEN" not in env and "GIT_DIR" not in env
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "core.hooksPath=/dev/null" in tools.GIT_SAFE_CONFIG
    assert "protocol.file.allow=never" in tools.GIT_SAFE_CONFIG


def test_third_party_and_monorepo_flags(tmp_path, monkeypatch):
    _hermes(tmp_path, monkeypatch)
    _block_git(monkeypatch)
    g = json.loads(tools.studio_tool({"tool_id": "ghidra-mcp-bridge"}))
    assert g["third_party"] is True and g["pull_command"] is None
    r = json.loads(tools.pull_tool({"tool_id": "ghidra-mcp-bridge"}))
    assert r["error"]["code"] == "third_party_repo"
    w = json.loads(tools.studio_tool({"tool_id": "hexstrike-arsenal"}))
    assert w["pull_command"] == "npx @nullaitech/zoth pull NullAI-HexStrike-AI-Terminal"
    assert json.loads(tools.studio_tool({"tool_id": "bolt.diy"}))["pull_command"] is None  # 1nc0gn30 repo: not in the CLI list
    m = json.loads(tools.studio_tool({"tool_id": "webmcp-protocol-inspector"}))
    assert m["monorepo"] is True and m["third_party"] is False
    s = json.loads(tools.studio_search({"query": "ghidra"}))["results"][0]
    assert {"source_owner", "source_repo", "third_party", "monorepo"} <= set(s)


def test_pull_command_only_for_nullaitech_repos():
    for t in tools._tools():
        cmd = tools._pull_command(t)
        src = tools._source(t)
        if cmd:
            assert src["source_owner"] == "NullAITech" and cmd.endswith(" " + src["source_repo"])


def test_status_total_timeout(monkeypatch):
    import time
    monkeypatch.setattr(tools, "SERVICES", [("Slow", 1, "/"), ("Fast", 2, "/")])
    monkeypatch.setattr(tools, "STATUS_TOTAL_TIMEOUT", 0.3)
    monkeypatch.setattr(tools, "_probe", lambda port, path: (time.sleep(2), (True, None))[1] if port == 1 else (False, None))
    t0 = time.monotonic(); r = json.loads(tools.status({}))
    assert time.monotonic() - t0 < 1.5
    assert r["services"][0].get("timed_out") is True and r["services"][1]["up"] is False


def test_check_live_refuses_cross_host_redirect():
    import urllib.request as ur
    h = tools._SameHostRedirect()
    req = ur.Request("https://zoth.nullai.tech/tools/x/")
    try:
        h.redirect_request(req, None, 302, "Found", {}, "https://evil.example/")
        assert False, "should refuse"
    except tools.urllib.error.URLError:
        pass
    assert h.redirect_request(req, None, 302, "Found", {}, "https://zoth.nullai.tech/tools/x") is not None


def test_z12_catalog_cache_invalidation(tmp_path, monkeypatch):
    test_catalog = tmp_path / "studio_tools.json"
    test_catalog.write_text(json.dumps([{"id": "t1", "name": "Tool 1", "category": "Test", "description": "D1", "published": True, "github": "https://github.com/1/t1", "studio_url": "https://zoth.nullai.tech/tools/t1/", "version": "1.0.0"}]))
    monkeypatch.setattr(tools, "_CATALOG_PATH", test_catalog)
    monkeypatch.setattr(tools, "_catalog", None)

    # First load
    t = tools._tools()
    assert len(t) == 1 and t[0]["id"] == "t1"

    # Modify catalog file
    test_catalog.write_text(json.dumps([
        {"id": "t1", "name": "Tool 1", "category": "Test", "description": "D1", "published": True, "github": "https://github.com/1/t1", "studio_url": "https://zoth.nullai.tech/tools/t1/", "version": "1.0.0"},
        {"id": "t2", "name": "Tool 2", "category": "Test", "description": "D2", "published": True, "github": "https://github.com/1/t2", "studio_url": "https://zoth.nullai.tech/tools/t2/", "version": "1.0.0"}
    ]))
    # Touch mtime to ensure change
    os.utime(test_catalog, (test_catalog.stat().st_atime + 10, test_catalog.stat().st_mtime + 10))

    # Next call should reload automatically without restarting process
    t2 = tools._tools()
    assert len(t2) == 2



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
