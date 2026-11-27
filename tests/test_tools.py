import importlib.util, json, os, re, sys, threading
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
    assert set(c.tools) == {
        "zoth_studio_search",
        "zoth_studio_tool",
        "zoth_status",
        "zoth_pull_tool",
        "zoth_bridge_post",
        "zoth_ecosystem_targets",
        "zoth_growth_directories",
    }
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
    assert r["results"][0]["execution_type"] == "browser"
    assert r["results"][0]["local_port"] == 8101
    t = json.loads(tools.studio_tool({"tool_id": "regex-droid-builder"}))
    assert t["studio_url"] == "https://zoth.nullai.tech/tools/regex-droid-builder/"
    assert t["local_port"] == 8101
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
    assert json.loads(tools.studio_search({"limit": True}))["error"]["code"] == "bad_argument"
    assert json.loads(tools.studio_search({"category": "nope"}))["error"]["code"] == "unknown_category"


def test_z01_category_filtering():
    # Exact category filter
    r1 = json.loads(tools.studio_search({"category": "Security & Recon"}))
    assert r1["ok"] is True
    assert r1["count"] >= 9
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
    # version, execution_type, local_port, and score are projected
    assert "version" in r_jwt["results"][0]
    assert "execution_type" in r_jwt["results"][0]
    assert "local_port" in r_jwt["results"][0]
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
    # Ports 8095-8106, Chronicle vault 8161, and Zoth Bot OS 8190 must all be covered in SERVICES
    ports = {port for _, port, _ in tools.SERVICES}
    for p in range(8095, 8107):
        assert p in ports, f"Port {p} missing from SERVICES"
    assert 8161 in ports
    assert 8190 in ports


def test_z10_errors_documented_in_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for code in (
        "bad_repo",
        "unknown_tool",
        "unknown_category",
        "bad_argument",
        "not_published",
        "git_missing",
        "bridge_unreachable",
        "dest_outside_root",
        "third_party_repo",
    ):
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
    assert json.loads(tools.studio_tool({"tool_id": "jwt-inspector-guard"}))["pull_command"] is None  # 1nc0gn30 repo: not in the CLI list
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


def test_check_live_refuses_cross_host_and_downgrade_redirects():
    import urllib.request as ur
    h = tools._SameHostRedirect()
    req = ur.Request("https://zoth.nullai.tech/tools/x/")
    for bad_target in ("https://evil.example/", "http://zoth.nullai.tech/tools/x/"):
        try:
            h.redirect_request(req, None, 302, "Found", {}, bad_target)
            assert False, f"should refuse {bad_target}"
        except tools.urllib.error.URLError:
            pass
    assert h.redirect_request(req, None, 302, "Found", {}, "https://zoth.nullai.tech/tools/x") is not None
    assert h.redirect_request(req, None, 302, "Found", {}, "/tools/x") is not None


def test_check_live_refuses_tampered_studio_url(monkeypatch):
    monkeypatch.setattr(tools, "_find", lambda _id: {
        "id": "tampered",
        "name": "Tampered",
        "category": "Test",
        "description": "Test",
        "version": "1.0.0",
        "github": "",
        "published": False,
        "studio_url": "http://169.254.169.254/latest/meta-data/",
    })
    r = json.loads(tools.studio_tool({"tool_id": "tampered", "check_live": True}))
    assert r["ok"] is True
    assert r["live_status"].startswith("refused:")


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
    text = (ROOT / "data" / "studio_tools.json").read_text(encoding="utf-8")
    assert not re.search(r"\+?1?[ (.-]*\d{3}[ ).-]*\d{3}[ .-]\d{4}", text)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text)
    assert not re.search(r"/(home|media|Users)/", text)
    assert not re.search(r"ghp_|github_pat_|sk-[A-Za-z0-9]{16}|AKIA[0-9A-Z]{16}|xox[bp]-", text)
    rows = json.loads(text)
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["studio_url"].startswith("https://zoth.nullai.tech/tools/") for r in rows)


def test_catalog_85_tool_integrity():
    rows = json.loads((ROOT / "data" / "studio_tools.json").read_text(encoding="utf-8"))
    assert len(rows) == 85
    by_id = {r["id"]: r for r in rows}
    assert len(by_id) == 85

    valid_exec_types = {"browser", "local_cli", "webgpu", "hybrid"}
    for r in rows:
        assert r["id"] and r["name"] and r["category"] and r["description"]
        assert r["execution_type"] in valid_exec_types, r["id"]
        port = r["local_port"]
        assert port is None or (isinstance(port, int) and 1 <= port <= 65535), (r["id"], port)
        assert isinstance(r["published"], bool)
        assert r["studio_url"] == f"https://zoth.nullai.tech/tools/{r['id']}/"

    # Explicitly assert newest 2 tools (84 & 85) are synced accurately
    assert "zoth-bot-os" in by_id
    assert by_id["zoth-bot-os"]["local_port"] == 8190
    assert by_id["zoth-bot-os"]["execution_type"] == "local_cli"
    assert by_id["zoth-bot-os"]["category"] == "Swarm & Core"

    assert "zoth-comfy-foundry" in by_id
    assert by_id["zoth-comfy-foundry"]["execution_type"] == "local_cli"
    assert by_id["zoth-comfy-foundry"]["category"] == "Media & 3D"


def test_studio_search_execution_type_and_none_args():
    r_cli = json.loads(tools.studio_search({"execution_type": "local_cli", "limit": 100}))
    assert r_cli["ok"] is True
    assert r_cli["count"] == 29
    assert all(item["execution_type"] == "local_cli" for item in r_cli["results"])
    cli_ids = {item["id"] for item in r_cli["results"]}
    assert "zoth-bot-os" in cli_ids and "zoth-comfy-foundry" in cli_ids

    r_bad = json.loads(tools.studio_search({"execution_type": "quantum"}))
    assert r_bad["ok"] is False and r_bad["error"]["code"] == "bad_argument"

    # Defensive handling of non-dict args
    r_none = json.loads(tools.studio_search(None))
    assert r_none["ok"] is True and r_none["count"] == 85


def test_bridge_post_targets_broadcast_route_and_payload(monkeypatch):
    # Regression guard: default route must be /api/broadcast, never /api/agents/message
    assert tools.BRIDGE_BROADCAST_URL == "http://127.0.0.1:8102/api/broadcast"
    assert "/api/agents/message" not in (ROOT / "tools.py").read_text(encoding="utf-8")
    monkeypatch.delenv("ZOTH_BRIDGE_URL", raising=False)

    received = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            received["path"] = self.path
            received["payload"] = payload
            if self.path != "/api/broadcast":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"not found"}')
                return
            if not payload.get("content"):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"Message \'content\' is required for broadcast"}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "broadcast": {"broadcast_id": "test-123", "content": payload["content"]},
            }).encode("utf-8"))

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(tools, "BRIDGE_BROADCAST_URL", f"http://127.0.0.1:{port}/api/broadcast")
        r = json.loads(tools.bridge_post({
            "body": "hello swarm",
            "sender": "hermes-auditor",
            "recipient": "all",
            "topic": "route-check",
        }))
    finally:
        srv.shutdown()

    assert r["ok"] is True
    assert received["path"] == "/api/broadcast"
    assert received["payload"] == {
        "content": "hello swarm",
        "metadata": {
            "sender": "hermes-auditor",
            "recipient": "all",
            "topic": "route-check",
        },
    }
    assert r["bridge_response"]["status"] == "ok"
    assert r["bridge_response"]["broadcast"]["content"] == "hello swarm"

    # Empty body rejected locally before any HTTP request
    bad = json.loads(tools.bridge_post({"body": "   "}))
    assert bad["ok"] is False
    assert bad["error"]["code"] == "bad_argument"


def test_bridge_post_loopback_guard_and_error_handling(monkeypatch):
    # SSRF guard: refuse non-loopback ZOTH_BRIDGE_URL values
    for bad_url in (
        "http://169.254.169.254/latest/meta-data/",
        "https://evil.example/api/broadcast",
        "file:///etc/passwd",
        "http://10.0.0.1:8102/api/broadcast",
    ):
        monkeypatch.setenv("ZOTH_BRIDGE_URL", bad_url)
        r = json.loads(tools.bridge_post({"body": "ping"}))
        assert r["ok"] is False and r["error"]["code"] == "bad_argument", bad_url

    # HTTP 500 error handled cleanly
    class ErrHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"bridge boom")
        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), ErrHandler)
    port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ZOTH_BRIDGE_URL", f"http://localhost:{port}/api/broadcast")
        r = json.loads(tools.bridge_post({"body": "ping"}))
    finally:
        srv.shutdown()
    assert r["ok"] is False
    assert r["error"]["code"] == "bridge_unreachable"
    assert r["error"]["status"] == 500


def test_probe_refuses_redirects_and_ignores_proxy(monkeypatch):
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        up, body = tools._probe(port, "/health")
    finally:
        srv.shutdown()
    # Port accepted TCP (up=True), redirect refused so body is None
    assert up is True
    assert body is None


def test_ecosystem_targets_and_growth_directories_dynamic_paths(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    pub = ws / "zoth-studio-v2" / "public"
    pub.mkdir(parents=True)
    (pub / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    (pub / "sitemap.xml").write_text("<urlset/>", encoding="utf-8")
    hub = tmp_path / "growth-hub"
    monkeypatch.setenv("ZOTH_WORKSPACE_ROOT", str(ws))
    monkeypatch.setenv("ZOTH_GROWTH_HUB_DIR", str(hub))

    eco = json.loads(tools.ecosystem_targets({"product": "zoth-studio"}))
    assert eco["ok"] is True and eco["count"] == 1
    p = eco["products"][0]
    assert p["id"] == "zoth-studio"
    assert "85" in p["name"]
    assert p["public_dir"] == str(pub)
    assert p["seo_health"] == {"robots_txt": True, "sitemap_xml": True, "llms_txt": False}
    assert p["existing_workspace_paths"] == [str(ws / "zoth-studio-v2")]

    eco_all = json.loads(tools.ecosystem_targets({}))
    assert eco_all["ok"] is True and eco_all["count"] == 6

    g = json.loads(tools.growth_directories({"channel_type": "awesome-list"}))
    assert g["ok"] is True and g["count"] == 4
    assert g["hub_dir"] == str(hub)
    assert all(c["type"] == "awesome-list" for c in g["channels"])
    assert all(c["pack"].startswith(str(hub)) for c in g["channels"])


def test_repo_has_no_hardcoded_personal_paths_or_secrets():
    checked_files = [
        ROOT / "__init__.py",
        ROOT / "tools.py",
        ROOT / "schemas.py",
        ROOT / "plugin.yaml",
        ROOT / "server.json",
        ROOT / "glama.json",
        ROOT / "README.md",
        ROOT / "skills" / "zoth-studio" / "SKILL.md",
        ROOT / "data" / "studio_tools.json",
        ROOT / "scripts" / "sync_catalog.py",
        ROOT / "bin" / "hermes-gateway",
        ROOT / ".github" / "workflows" / "ci.yml",
    ]
    personal_path_re = re.compile(r"/home/[a-zA-Z0-9._-]+|/Users/[a-zA-Z0-9._-]+")
    secret_re = re.compile(r"ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9-]+")
    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        assert not personal_path_re.search(text), f"Hardcoded personal path in {path}"
        assert not secret_re.search(text), f"Potential secret in {path}"


def test_hermes_gateway_port_parser_and_redaction():
    ss_out = (
        'LISTEN 0 128 0.0.0.0:59999 0.0.0.0:* users:(("hermes",pid=999,fd=4))\n'
        'LISTEN 0 2048 127.0.0.1:51234 0.0.0.0:* users:(("hermes",pid=1525,fd=5))\n'
    )
    assert tools._parse_hermes_loopback_port(ss_out, pid=1525) == 51234
    assert tools._parse_hermes_loopback_port(ss_out, pid=None) == 51234
    assert tools._parse_hermes_loopback_port('LISTEN 0 128 0.0.0.0:51234 0.0.0.0:* users:(("hermes",pid=1525,fd=5))', pid=1525) is None

    synth_bearer = "Bearer " + "-".join(["sk", "dummy", "1234567890abcdef"])
    redacted = tools._redact_hermes_value({
        "path": "/home/operator/.hermes/config.yaml",
        "token": synth_bearer,
    })
    assert redacted["path"] == "~/.hermes/config.yaml"
    assert "1234567890abcdef" not in redacted["token"]


def test_status_includes_hermes_gateway_live(monkeypatch):
    monkeypatch.setattr(tools, "SERVICES", [])
    monkeypatch.setattr(tools, "_probe_hermes_gateway", lambda: {
        "name": "Hermes Agent Gateway",
        "unit": "hermes-gateway.service",
        "port": 51234,
        "up": True,
        "active_state": "active",
        "sub_state": "running",
        "pid": 1525,
        "socket_exists": True,
        "socket_path": "~/.hermes/gateway.sock",
        "health": {"ok": True, "version": "0.23.3+1139", "auth_required": False},
    })
    res = json.loads(tools.status({}))
    assert res["ok"] is True
    assert res["hermes_gateway"]["up"] is True
    assert res["hermes_gateway"]["port"] == 51234
    assert res["hint"] is None


def test_hermes_gateway_probe_offline_fallback(monkeypatch):
    class _FailProc:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(tools.subprocess, "run", lambda *a, **kw: _FailProc())
    gw_off = tools._probe_hermes_gateway()
    assert gw_off["unit"] == "hermes-gateway.service"
    assert gw_off["port"] is None
    assert gw_off["up"] is False
    assert "/home/" not in json.dumps(gw_off)

