"""Handlers for the Zoth plugin. Each returns a JSON string and never raises."""

import difflib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

STUDIO_BASE = "https://zoth.nullai.tech"
_CATALOG_PATH = Path(__file__).parent / "data" / "studio_tools.json"
_catalog = None
_catalog_mtime = 0

# Loopback services documented in Zoth Studio's server/studio-api.mjs and ZOTHOS.
# Covers UI :3000, memory :8094, the full :8095-8106 agent/security suite,
# Chronicle memory vault :8161, Zoth Bot OS :8190, vault :8787, WebGen :5173, and Ollama :11434.
SERVICES = [
    ("Zoth Studio UI", 3000, "/"),
    ("Neuro memory daemon", 8094, "/health"),
    ("Agent egress sentinel", 8095, "/api/stats"),
    ("AudioCipher stego engine", 8096, "/"),
    ("Agent mock twin", 8097, "/api/stats"),
    ("Agent prompt firewall", 8098, "/api/stats"),
    ("Schema illustrator studio", 8099, "/"),
    ("PWA manifest builder", 8100, "/"),
    ("Regex droid builder", 8101, "/"),
    ("Sovereign agent bridge", 8102, "/api/health"),
    ("Anderson security sentinel", 8103, "/"),
    ("Agent flight recorder", 8104, "/api/stats"),
    ("Agent capsule jail", 8105, "/api/stats"),
    ("Agent policy auditor", 8106, "/api/stats"),
    ("Chronicle memory vault", 8161, "/health"),
    ("Zoth Bot OS", 8190, "/health"),
    ("Vault daemon", 8787, "/health"),
    ("Zoth WebGen (Bolt.DIY)", 5173, "/"),
    ("Ollama", 11434, "/api/tags"),
]


# Repos the plugin will clone. Both are 1nc0gn30 (Zoth Studio) accounts.
ALLOWED_OWNERS = {"nullaitech", "1nc0gn30"}
# Repos that hold many tools; pulling one of these fetches the whole project.
MONOREPOS = {"zoth-studio-v2", "zoth-os"}
STATUS_TOTAL_TIMEOUT = 4.0
PROBE_MAX_BYTES = 64 * 1024
# Applied to every git call: no repo hooks, no fsmonitor, no file:// or ext:: transports.
GIT_SAFE_CONFIG = [
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "protocol.file.allow=never",
    "-c", "protocol.ext.allow=never",
    "-c", "submodule.recurse=false",
]
_ENV_PASSTHROUGH = (
    "PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP",
    "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "GIT_SSL_CAINFO",
)
_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
BRIDGE_BROADCAST_URL = "http://127.0.0.1:8102/api/broadcast"


def _source(t: dict) -> dict:
    """Owner/repo facts for a catalog entry, so the agent can tell users where code comes from."""
    gh = t.get("github") or ""
    parts = gh.rstrip("/").split("/")
    if not gh.startswith("https://github.com/") or len(parts) < 5:
        return {"source_owner": None, "source_repo": None, "third_party": False, "monorepo": False}
    owner, repo = parts[3], parts[4]
    return {
        "source_owner": owner,
        "source_repo": repo,
        "third_party": owner.lower() not in ALLOWED_OWNERS,
        "monorepo": repo in MONOREPOS,
    }


def _pull_command(t: dict):
    """`npx @nullaitech/zoth pull <repo>`; the CLI takes the repo name and lists NullAITech repos only."""
    src = _source(t)
    if not t.get("published") or (src["source_owner"] or "").lower() != "nullaitech":
        return None
    return f"npx @nullaitech/zoth pull {src['source_repo']}"


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Allow redirects only when scheme and netloc remain identical."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        orig = urllib.parse.urlsplit(req.full_url)
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        target = urllib.parse.urlsplit(resolved)
        if target.scheme != orig.scheme or target.netloc != orig.netloc:
            raise urllib.error.URLError(f"refusing cross-host or scheme-changing redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, resolved)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse all HTTP redirects on loopback requests to prevent SSRF."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError(f"refusing redirect on loopback request to {newurl}")


_same_host_opener = urllib.request.build_opener(_SameHostRedirect)
_loopback_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _is_loopback_url(url: str) -> bool:
    """Return True only for http(s) URLs targeting a local loopback host."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def _err(code: str, message: str, **extra) -> str:
    return json.dumps({"ok": False, "error": {"code": code, "message": message, **extra}})


def _tools() -> list[dict]:
    """Load the bundled Studio catalog, automatically reloading when its mtime changes."""
    global _catalog, _catalog_mtime
    try:
        mtime = _CATALOG_PATH.stat().st_mtime
    except OSError:
        mtime = 0
    if _catalog is None or mtime != _catalog_mtime:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("bundled catalog is not a list")
        _catalog = data
        _catalog_mtime = mtime
    return _catalog


def _suggest(tool_id) -> list[str]:
    raw = (tool_id or "").strip().lower()
    if not raw:
        return []
    catalog = _tools()
    ids = [t["id"] for t in catalog]

    # 1. Prefer prefix matches on id (e.g. 'regex-droid' -> 'regex-droid-builder')
    prefix = [t["id"] for t in catalog if t["id"].lower().startswith(raw)]
    if prefix:
        return prefix[:3]

    # 2. Check friendly name substring matches
    by_name = [t["id"] for t in catalog if raw in t["name"].lower()]
    if by_name:
        return by_name[:3]

    # 3. Fall back to close string matches with stricter cutoff 0.6 (filters noise)
    return difflib.get_close_matches(raw, ids, n=3, cutoff=0.6)


def _find(tool_id):
    if not tool_id:
        return None
    slug = str(tool_id).strip().lower()
    if not slug:
        return None
    # 1. Exact ID match (case-insensitive, whitespace-trimmed)
    for t in _tools():
        if t["id"].lower() == slug:
            return t
    # 2. Fall back to friendly name match (e.g. 'JWT Inspector Guard' -> 'jwt-inspector-guard')
    for t in _tools():
        if t["name"].strip().lower() == slug:
            return t
    return None


def _match_category(cat_filter: str, item_category: str) -> bool:
    if not cat_filter:
        return True
    cf = cat_filter.strip().lower()
    ic = item_category.strip().lower()
    if cf == ic:
        return True
    # Family prefix match: e.g. "security" matches "Security & Recon", "Security & OpSec", etc.
    if ic.startswith(cf + " &") or ic.startswith(cf + " "):
        return True
    return False


def _score_tool(t: dict, query_words: list[str], raw_query: str) -> int:
    if not query_words:
        return 1

    t_id = t["id"].lower()
    t_name = t["name"].lower()
    t_cat = t["category"].lower()
    t_desc = t["description"].lower()

    if raw_query == t_id:
        return 1000

    id_words = set(re.findall(r"[a-z0-9]+", t_id))
    name_words = set(re.findall(r"[a-z0-9]+", t_name))
    cat_words = set(re.findall(r"[a-z0-9]+", t_cat))
    desc_words = set(re.findall(r"[a-z0-9]+", t_desc))
    all_words = id_words | name_words | cat_words | desc_words

    # Require all query terms to match at least one field (AND requirement)
    for qw in query_words:
        if qw not in all_words and qw not in t_id:
            return 0

    score = 0
    if raw_query in t_id:
        score += 200
    if raw_query in t_name:
        score += 100

    for qw in query_words:
        if qw == t_id:
            score += 150
        elif qw in id_words:
            score += 80
        elif qw in t_id:
            score += 40

        if qw in name_words:
            score += 50
        elif qw in t_name:
            score += 25

        if qw in cat_words:
            score += 20

        if qw in desc_words:
            score += 5

    return score


def studio_search(args: dict, **kwargs) -> str:
    """Search the bundled Zoth Studio catalog by keyword, category, and/or execution_type."""
    try:
        args = args if isinstance(args, dict) else {}
        raw_q = str(args.get("query") or "").strip().lower()
        q_words = re.findall(r"[a-z0-9]+", raw_q)
        cat = str(args.get("category") or "").strip().lower()
        exec_type = str(args.get("execution_type") or "").strip().lower()
        raw_limit = args.get("limit")
        if isinstance(raw_limit, bool):
            return _err("bad_argument", "limit must be an integer")
        try:
            limit = 10 if raw_limit is None else max(1, min(int(raw_limit), 100))
        except (TypeError, ValueError):
            return _err("bad_argument", "limit must be an integer")

        catalog = _tools()
        cats = sorted({t["category"] for t in catalog})
        if cat:
            matching_cats = [c for c in cats if _match_category(cat, c)]
            if not matching_cats:
                return _err("unknown_category", f"no category {args.get('category')!r}", categories=cats)

        exec_types = sorted({str(t.get("execution_type") or "browser").lower() for t in catalog})
        if exec_type and exec_type not in exec_types:
            return _err(
                "bad_argument",
                f"unknown execution_type {args.get('execution_type')!r}",
                execution_types=exec_types,
            )

        hits = []
        for t in catalog:
            if cat and not _match_category(cat, t["category"]):
                continue
            if exec_type and str(t.get("execution_type") or "browser").lower() != exec_type:
                continue
            score = _score_tool(t, q_words, raw_q)
            if score > 0:
                hits.append((score, t))
        hits.sort(key=lambda h: -h[0])
        out = [
            {
                "id": t["id"],
                "name": t["name"],
                "category": t["category"],
                "description": t["description"],
                "version": t.get("version", "1.0.0"),
                "execution_type": t.get("execution_type", "browser"),
                "local_port": t.get("local_port"),
                "studio_url": t["studio_url"],
                "github": t["github"],
                "published": t["published"],
                **_source(t),
                "score": score,
            }
            for score, t in hits[:limit]
        ]
        return json.dumps({"ok": True, "count": len(hits), "results": out, "categories": cats})
    except (OSError, ValueError) as e:
        return _err("catalog_unavailable", f"could not read bundled catalog: {e}")
    except Exception as e:  # noqa: BLE001
        return _err("internal", f"search failed: {e}")


def studio_tool(args: dict, **kwargs) -> str:
    """Return full metadata for a single Zoth Studio tool by id or friendly name."""
    try:
        args = args if isinstance(args, dict) else {}
        raw_id = args.get("tool_id")
        t = _find(raw_id)
        if not t:
            display_id = "<missing>" if not raw_id or not str(raw_id).strip() else repr(raw_id)
            return _err(
                "unknown_tool",
                f"unknown tool id {display_id}; use zoth_studio_search",
                did_you_mean=_suggest(raw_id),
            )
        res = {"ok": True, **t, **_source(t)}
        res["pull_command"] = _pull_command(t)
        if args.get("check_live"):
            studio_url = str(t.get("studio_url") or "")
            if not studio_url.startswith(STUDIO_BASE + "/"):
                res["live_status"] = "refused: studio_url outside zoth.nullai.tech"
            else:
                try:
                    req = urllib.request.Request(studio_url, headers={"User-Agent": "hermes-zoth-plugin"})
                    with _same_host_opener.open(req, timeout=8) as r:
                        res["live_status"] = r.status
                except urllib.error.HTTPError as e:
                    res["live_status"] = e.code
                except Exception as e:  # noqa: BLE001
                    res["live_status"] = f"unreachable: {e}"
        return json.dumps(res)
    except Exception as e:  # noqa: BLE001
        return _err("internal", str(e))


def _probe(port: int, path: str):
    """Probe a single 127.0.0.1 service without proxies or HTTP redirects."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            pass
    except OSError:
        return False, None
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            headers={"User-Agent": "hermes-zoth-plugin"},
        )
        with _loopback_opener.open(req, timeout=1.5) as r:
            body = r.read(PROBE_MAX_BYTES)
        try:
            return True, json.loads(body)
        except ValueError:
            return True, None
    except Exception:  # noqa: BLE001
        return True, None


_HOME_PATH_RE = re.compile(r"(?:file://)?/(?:home|Users)/[A-Za-z0-9._-]+(?=/|\b)")
_HERMES_SECRET_RES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
)


def _redact_hermes_value(value):
    if isinstance(value, str):
        out = _HOME_PATH_RE.sub("~", value)
        for pat in _HERMES_SECRET_RES:
            out = pat.sub("[REDACTED]", out)
        return out
    if isinstance(value, list):
        return [_redact_hermes_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact_hermes_value(v) for k, v in value.items()}
    return value


def _parse_hermes_loopback_port(ss_output: str, pid: int | None = None) -> int | None:
    """Discover a 127.0.0.1 loopback TCP port owned by hermes-gateway (never 0.0.0.0)."""
    if not ss_output:
        return None
    pid_tag = f"pid={pid}" if pid else None
    fallback = None
    for line in ss_output.splitlines():
        if "127.0.0.1:" not in line:
            continue
        tokens = line.strip().split()
        local_addr = next((tok for tok in tokens if ":" in tok and not tok.startswith("users:")), None)
        if local_addr and not local_addr.startswith("127.0.0.1:"):
            continue
        m = re.search(r"\b127\.0\.0\.1:(\d{2,5})\b", line)
        if not m:
            continue
        port = int(m.group(1))
        if not (1024 <= port <= 65535):
            continue
        if pid_tag and pid_tag in line:
            return port
        if '"hermes"' in line and fallback is None:
            fallback = port
    return fallback


def _probe_hermes_gateway() -> dict:
    """Read-only probe of hermes-gateway.service, dynamic loopback port & /api/health."""
    unit = "hermes-gateway.service"
    systemd_active = False
    active_state = "unavailable"
    sub_state = "unknown"
    pid = None
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "ActiveState,SubState,MainPID", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            kv = {}
            for line in proc.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip()
            active_state = kv.get("ActiveState") or "unknown"
            sub_state = kv.get("SubState") or "unknown"
            systemd_active = active_state == "active"
            raw_pid = kv.get("MainPID", "")
            if raw_pid.isdigit() and int(raw_pid) > 0:
                pid = int(raw_pid)
    except (OSError, subprocess.TimeoutExpired):
        pass

    port = None
    try:
        ss_proc = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=1.5, check=False)
        if ss_proc.returncode == 0 and ss_proc.stdout:
            port = _parse_hermes_loopback_port(ss_proc.stdout, pid=pid)
    except (OSError, subprocess.TimeoutExpired):
        pass

    health = None
    health_up = False
    if port is not None:
        up, body = _probe(port, "/api/health")
        health_up = bool(up)
        if isinstance(body, dict):
            health = _redact_hermes_value({
                "ok": bool(body.get("ok")),
                "version": body.get("displayVersion") or body.get("version"),
                "auth_required": body.get("auth_required"),
            })

    socket_exists = False
    try:
        socket_exists = (_fallback_hermes_home() / "gateway.sock").exists()
    except OSError:
        pass

    return _redact_hermes_value({
        "name": "Hermes Agent Gateway",
        "unit": unit,
        "port": port,
        "up": bool(systemd_active or health_up),
        "active_state": active_state,
        "sub_state": sub_state,
        "pid": pid,
        "socket_exists": socket_exists,
        "socket_path": "~/.hermes/gateway.sock",
        "health": health,
    })


def status(args: dict, **kwargs) -> str:
    """Probe local ZOTHOS / Zoth loopback services in parallel (4 s total budget)."""
    try:
        pool = ThreadPoolExecutor(max_workers=len(SERVICES) + 1)
        futures = [pool.submit(_probe, port, path) for _, port, path in SERVICES]
        gw_future = pool.submit(_probe_hermes_gateway)
        wait([*futures, gw_future], timeout=STATUS_TOTAL_TIMEOUT)
        pool.shutdown(wait=False, cancel_futures=True)
        rows = []
        for (name, port, _), f in zip(SERVICES, futures):
            if f.done() and not f.cancelled() and f.exception() is None:
                up, body = f.result()
                row = {"name": name, "port": port, "up": up}
            else:
                up, body = False, None
                row = {"name": name, "port": port, "up": False, "timed_out": True}
            if name == "Ollama" and up and isinstance(body, dict):
                row["models"] = [m.get("name") for m in body.get("models", []) if isinstance(m, dict)]
            rows.append(row)
        if gw_future.done() and not gw_future.cancelled() and gw_future.exception() is None:
            hermes_gw = gw_future.result()
        else:
            hermes_gw = {
                "name": "Hermes Agent Gateway",
                "unit": "hermes-gateway.service",
                "port": None,
                "up": False,
                "timed_out": True,
                "socket_path": "~/.hermes/gateway.sock",
                "socket_exists": False,
                "health": None,
            }
        return json.dumps({
            "ok": True,
            "host": "127.0.0.1",
            "up": sum(r["up"] for r in rows),
            "services": rows,
            "hermes_gateway": hermes_gw,
            "kvm": Path("/dev/kvm").exists(),
            "hint": None if (any(r["up"] for r in rows) or hermes_gw.get("up")) else
            "Nothing is running. Start Zoth Studio with `npx @nullaitech/zoth studio`.",
        })
    except Exception as e:  # noqa: BLE001
        return _err("internal", str(e))


def _fallback_hermes_home() -> Path:
    """Used only when this plugin is imported outside Hermes (unit tests)."""
    raw = os.environ.get("HERMES_HOME", "").strip()
    if raw:
        return Path(os.path.expanduser(os.path.expandvars(raw)))
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "hermes"
    return Path.home() / ".hermes"


def _hermes_home() -> Path:
    """Active Hermes home: ``get_hermes_home()`` when Hermes is installed."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        return _fallback_hermes_home()
    return Path(get_hermes_home()).expanduser()


def _clone_root() -> Path:
    """Only tree ``zoth_pull_tool`` may write: ``<HERMES_HOME>/plugin-data/zoth``."""
    return (_hermes_home() / "plugin-data" / "zoth").resolve()


def _strict_child(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return bool(rel.parts)


def _clone_dest_allowed(dest: Path, root: Path, hermes: Path) -> bool:
    """True only when ``dest`` is inside the clone root and not under skills/plugins."""
    if not _strict_child(dest, root):
        return False
    try:
        top = dest.relative_to(hermes).parts[0]
    except (ValueError, IndexError):
        return True
    return top not in {"skills", "plugins"}


def _resolve_clone_dest(dest_dir, repo: str) -> Path:
    """Resolve ``dest_dir / repo`` under the clone root, never against the process cwd."""
    root = _clone_root()
    raw = dest_dir
    if raw is None or str(raw).strip() == "":
        raw = "tools"
    candidate = Path(os.path.expanduser(os.path.expandvars(str(raw).strip())))
    parent = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    return (parent / repo).resolve()


def _dest_refused(root: Path) -> str:
    return _err(
        "dest_outside_root",
        "refusing to clone outside the zoth plugin data directory "
        f"({root}). Pass a relative dest_dir such as 'tools', or an absolute path inside that directory. "
        "Paths under the Hermes skills or plugins directories are not allowed.",
        root=str(root),
    )


def _git_env() -> dict:
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_ASKPASS": "", "SSH_ASKPASS": ""})
    return env


def _repo_url(t: dict) -> str:
    return t["github"].rstrip("/") + ".git"


def _valid_ref(ref: str) -> bool:
    return (
        bool(ref)
        and not ref.startswith(("-", "/"))
        and not ref.endswith(("/", ".", ".lock"))
        and ".." not in ref
        and "//" not in ref
        and "@{" not in ref
        and re.fullmatch(r"[A-Za-z0-9._/-]+", ref) is not None
    )


class _GitError(Exception):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def _git(args, env, log, timeout=180):
    cmd = ["git", *GIT_SAFE_CONFIG, *args]
    shown = " ".join(["git", *args])
    log.append(shown)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise _GitError("timeout", f"git took longer than {timeout} s", command=shown)
    if p.returncode != 0:
        raise _GitError(
            "git_failed",
            f"git exited {p.returncode}",
            command=shown,
            output=(p.stdout + p.stderr)[-2000:],
        )
    return p.stdout


def pull_tool(args: dict, **kwargs) -> str:
    """Shallow-clone or fast-forward update one published NullAITech/1nc0gn30 repo under HERMES_HOME."""
    try:
        args = args if isinstance(args, dict) else {}
        raw_id = args.get("tool_id")
        t = _find(raw_id)
        if not t:
            display_id = "<missing>" if not raw_id or not str(raw_id).strip() else repr(raw_id)
            return _err(
                "unknown_tool",
                f"unknown tool id {display_id}; use zoth_studio_search",
                did_you_mean=_suggest(raw_id),
            )
        if not t["published"] or not t["github"].startswith("https://github.com/"):
            return _err(
                "not_published",
                f"{t['id']} has no public GitHub repo; use its Studio page instead",
                studio_url=t["studio_url"],
            )
        src = _source(t)
        repo = src["source_repo"] or ""
        if repo in {".", ".."} or repo.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._-]+", repo):
            return _err("bad_repo", f"unexpected repo name {repo!r}")
        if src["third_party"]:
            return _err(
                "third_party_repo",
                f"{t['id']} points to {src['source_owner']}/{repo}, which is not a NullAITech repo; "
                "this plugin only clones NullAITech/1nc0gn30 repos. Give the user the GitHub link instead.",
                github=t["github"],
            )

        ref = args.get("ref")
        ref_str = None
        if ref is not None and str(ref).strip() != "":
            ref_str = str(ref).strip()
            if not _valid_ref(ref_str):
                return _err("bad_argument", f"invalid ref {ref!r}")

        root = _clone_root()
        hermes = _hermes_home().resolve()
        dest = _resolve_clone_dest(args.get("dest_dir"), repo)
        if not _clone_dest_allowed(dest, root, hermes):
            return _dest_refused(root)
        if shutil.which("git") is None:
            return _err("git_missing", "git is not installed or not on PATH")

        env = _git_env()
        url = _repo_url(t)
        log = []
        d = str(dest)
        is_sha = bool(ref_str and _SHA_RE.fullmatch(ref_str))
        try:
            if (dest / ".git").exists():
                origin = _git(["-C", d, "remote", "get-url", "origin"], env, log, 10).strip()
                if origin.rstrip("/").removesuffix(".git").lower() != url.removesuffix(".git").lower():
                    return _err("dest_exists", f"{dest} is a checkout of {origin!r}, not {url}; refusing to touch it")
                if ref_str:
                    _git(["-C", d, "fetch", "--depth", "1", "origin", ref_str], env, log)
                    _git(["-C", d, "checkout", "--detach", "FETCH_HEAD"], env, log, 60)
                else:
                    try:
                        _git(["-C", d, "symbolic-ref", "-q", "HEAD"], env, log, 10)
                        on_branch = True
                    except _GitError:
                        on_branch = False
                    if on_branch:
                        _git(["-C", d, "pull", "--ff-only"], env, log)
                    else:
                        # Previously pinned (detached) checkout: move back to the default branch tip.
                        _git(["-C", d, "fetch", "--depth", "1", "origin", "HEAD"], env, log)
                        _git(["-C", d, "checkout", "--detach", "FETCH_HEAD"], env, log, 60)
            elif dest.exists():
                return _err("dest_exists", f"{dest} exists and is not a git checkout; refusing to overwrite")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if ref_str and not is_sha:
                    _git(["clone", "--depth", "1", "--branch", ref_str, "--", url, d], env, log)
                else:
                    _git(["clone", "--depth", "1", "--", url, d], env, log)
                    if is_sha:
                        _git(["-C", d, "fetch", "--depth", "1", "origin", ref_str], env, log)
                        _git(["-C", d, "checkout", "--detach", "FETCH_HEAD"], env, log, 60)
            sha = _git(["-C", d, "rev-parse", "HEAD"], env, log, 10).strip()
        except _GitError as e:
            return _err(e.code, e.message, **e.extra)

        res = {
            "ok": True,
            "path": d,
            "command": log[0] if log else None,
            "commands": log,
            "commit": sha if _SHA_RE.fullmatch(sha) else None,
            "source": f"github.com/{src['source_owner']}/{repo}",
            "monorepo": src["monorepo"],
        }
        if ref_str:
            res["ref"] = ref_str
        return json.dumps(res)
    except PermissionError as e:
        return _err("permission_denied", str(e))
    except Exception as e:  # noqa: BLE001
        return _err("internal", str(e))


def _workspace_root() -> Path:
    """Resolve local Zoth/NullAI workspace root via ZOTH_WORKSPACE_ROOT or ~/NullAITech."""
    raw = os.environ.get("ZOTH_WORKSPACE_ROOT", "").strip()
    if raw:
        return Path(os.path.expanduser(os.path.expandvars(raw)))
    return Path.home() / "NullAITech"


def _growth_hub_dir() -> Path:
    """Resolve local growth-distribution directory via ZOTH_GROWTH_HUB_DIR or <workspace>/growth-distribution."""
    raw = os.environ.get("ZOTH_GROWTH_HUB_DIR", "").strip()
    if raw:
        return Path(os.path.expanduser(os.path.expandvars(raw)))
    return _workspace_root() / "growth-distribution"


def _world_of_zoth_dir() -> Path:
    """Resolve local World of Zoth directory via ZOTH_WORLD_DIR or ~/Desktop/world-of-zoth."""
    raw = os.environ.get("ZOTH_WORLD_DIR", "").strip()
    if raw:
        return Path(os.path.expanduser(os.path.expandvars(raw)))
    return Path.home() / "Desktop" / "world-of-zoth"


ECOSYSTEM_PRODUCTS = [
    {
        "id": "zothos",
        "name": "ZOTHOS (Sovereign Debian 13 AI Workstation OS)",
        "domain": "https://zothos.nullai.tech",
        "github": "https://github.com/1nc0gn30/zoth-os",
        "website_github": "https://github.com/1nc0gn30/zoth-os-website",
        "workspace_repos": ["zoth-os", "zoth-os-website"],
        "public_relpath": "zoth-os-website/public",
        "focus": "Debian 13 Trixie Live ISO, KDE Plasma 6 + XFCE4 workstation, pre-wired local daemons (:8094-:8106, :8161, :8190), CLI binaries, and zothos.nullai.tech website.",
    },
    {
        "id": "zothos-lite",
        "name": "ZOTHOS Lite (Portable Browser & Sovereign OS)",
        "domain": "https://lite.zoth.nullai.tech",
        "github": "https://github.com/1nc0gn30/zothos-lite",
        "workspace_repos": ["zothos-lite"],
        "public_relpath": "zothos-lite/public",
        "focus": "Lightweight browser-accessible and portable desktop environment with terminal, VM harness, and local tool execution.",
    },
    {
        "id": "zothnet",
        "name": "ZothNet (Zero-Cloud Mesh & Encrypted Network)",
        "domain": "https://zothnet.nullai.tech",
        "github": "https://github.com/1nc0gn30/zothnet",
        "website_github": "https://github.com/1nc0gn30/zothnet-website",
        "workspace_repos": ["zothnet", "zothnet-website", "zothnet-android"],
        "public_relpath": "zothnet-website/public",
        "focus": "Encrypted P2P mesh networking, node discovery, agent transport, Android companion app, and zothnet.nullai.tech portal.",
    },
    {
        "id": "zoth-studio",
        "name": "Zoth Studio v2 (85 Open-Access In-Browser & Local Tools)",
        "domain": "https://zoth.nullai.tech",
        "github": "https://github.com/1nc0gn30/zoth-studio-v2",
        "workspace_repos": ["zoth-studio-v2"],
        "public_relpath": "zoth-studio-v2/public",
        "focus": "85 free, open-access in-browser and local CLI developer, security, AEO/SEO, media, and AI agent safety tools with local daemon bridges and zero paywalls.",
    },
    {
        "id": "1nc0gn30",
        "name": "1nc0gn30 · World of Zoth (Creator & Open-Source Hub)",
        "domain": "https://1nc0gn30.si",
        "github": "https://github.com/1nc0gn30",
        "workspace_repos": [],
        "use_world_dir": True,
        "public_relpath": "",
        "focus": "Interactive World of Zoth 3D/WebGL experience and @1nc0gn30 open-source engineering hub.",
    },
    {
        "id": "nullai",
        "name": "NullAI Platform (Local-First AI Research & Engineering)",
        "domain": "https://nullai.tech",
        "github": "https://github.com/1nc0gn30/nullai2026",
        "workspace_repos": ["nullai2026", "hermes-zoth"],
        "public_relpath": "nullai2026/public",
        "focus": "Umbrella local-first AI research platform uniting ZothOS, Zoth Studio, ZothNet, hermes-zoth plugin, and local agent infrastructure.",
    },
]

GROWTH_CHANNELS = [
    {"id": "product-hunt", "name": "Product Hunt", "type": "directory", "url": "https://www.producthunt.com", "status": "live", "products": ["zoth-studio", "zothos"], "notes": "Live on Product Hunt; publish changelog updates and media."},
    {"id": "hacker-news-show", "name": "Hacker News (Show HN)", "type": "community", "url": "https://news.ycombinator.com/submit", "status": "ready_to_post", "products": ["zoth-studio", "zothos", "zothnet", "hermes-zoth"], "pack_file": "submissions/show_hn.md"},
    {"id": "alternativeto", "name": "AlternativeTo", "type": "directory", "url": "https://alternativeto.net", "status": "ready_to_submit", "products": ["zothos", "zoth-studio", "zothnet"], "pack_file": "submissions/alternativeto.md"},
    {"id": "devhunt", "name": "DevHunt (Developer Tools Launchpad)", "type": "directory", "url": "https://devhunt.org", "status": "ready_to_submit", "products": ["zoth-studio", "hermes-zoth", "zothos"], "pack_file": "submissions/devhunt.md"},
    {"id": "saashub", "name": "SaaSHub", "type": "directory", "url": "https://www.saashub.com/submit", "status": "ready_to_submit", "products": ["zoth-studio", "zothos", "zothnet"], "pack_file": "submissions/saashub.md"},
    {"id": "betalist", "name": "BetaList", "type": "directory", "url": "https://betalist.com/submit", "status": "ready_to_submit", "products": ["zothos-lite", "zothnet", "zoth-studio"], "pack_file": "submissions/betalist.md"},
    {"id": "toolify", "name": "Toolify.ai", "type": "directory", "url": "https://www.toolify.ai/submit", "status": "ready_to_submit", "products": ["zoth-studio", "nullai"], "pack_file": "submissions/ai_directories.md"},
    {"id": "futurepedia", "name": "Futurepedia", "type": "directory", "url": "https://www.futurepedia.io/submit-tool", "status": "ready_to_submit", "products": ["zoth-studio", "nullai"], "pack_file": "submissions/ai_directories.md"},
    {"id": "taaft", "name": "There's An AI For That (TAAFT)", "type": "directory", "url": "https://theresanaiforthat.com/submit/", "status": "ready_to_submit", "products": ["zoth-studio", "zothos"], "pack_file": "submissions/ai_directories.md"},
    {"id": "uneed", "name": "Uneed.best", "type": "directory", "url": "https://www.uneed.best/submit-a-tool", "status": "ready_to_submit", "products": ["zoth-studio", "zothos-lite"], "pack_file": "submissions/devhunt.md"},
    {"id": "awesome-selfhosted", "name": "GitHub: awesome-selfhosted", "type": "awesome-list", "url": "https://github.com/awesome-selfhosted/awesome-selfhosted", "status": "pr_ready", "products": ["zoth-studio", "zothnet"], "pack_file": "submissions/awesome_lists_prs.md"},
    {"id": "awesome-mcp-servers", "name": "GitHub: punkpeye/awesome-mcp-servers", "type": "awesome-list", "url": "https://github.com/punkpeye/awesome-mcp-servers", "status": "pr_ready", "products": ["zoth-studio", "hermes-zoth"], "pack_file": "submissions/awesome_lists_prs.md"},
    {"id": "awesome-cli-apps", "name": "GitHub: agarrharr/awesome-cli-apps", "type": "awesome-list", "url": "https://github.com/agarrharr/awesome-cli-apps", "status": "pr_ready", "products": ["zothos", "zoth-studio"], "pack_file": "submissions/awesome_lists_prs.md"},
    {"id": "awesome-linux", "name": "GitHub: inputsh/awesome-linux", "type": "awesome-list", "url": "https://github.com/inputsh/awesome-linux", "status": "pr_ready", "products": ["zothos", "zothos-lite"], "pack_file": "submissions/awesome_lists_prs.md"},
    {"id": "reddit-selfhosted", "name": "Reddit: r/selfhosted", "type": "community", "url": "https://www.reddit.com/r/selfhosted/", "status": "ready_to_post", "products": ["zoth-studio", "zothos", "zothnet"], "pack_file": "submissions/reddit_launch_posts.md"},
    {"id": "reddit-localllama", "name": "Reddit: r/LocalLLaMA", "type": "community", "url": "https://www.reddit.com/r/LocalLLaMA/", "status": "ready_to_post", "products": ["zothos", "hermes-zoth", "zoth-studio"], "pack_file": "submissions/reddit_launch_posts.md"},
    {"id": "reddit-linux", "name": "Reddit: r/linux & r/commandline", "type": "community", "url": "https://www.reddit.com/r/linux/", "status": "ready_to_post", "products": ["zothos", "zothos-lite"], "pack_file": "submissions/reddit_launch_posts.md"},
    {"id": "devto-hashnode", "name": "Dev.to & Hashnode Technical Deep-Dives", "type": "blog", "url": "https://dev.to", "status": "ready_to_post", "products": ["zoth-studio", "zothos", "zothnet", "nullai"], "pack_file": "submissions/devto_hashnode_articles.md"},
    {"id": "indiehackers", "name": "IndieHackers", "type": "community", "url": "https://www.indiehackers.com", "status": "ready_to_post", "products": ["zoth-studio", "zothos", "nullai"], "pack_file": "submissions/devto_hashnode_articles.md"},
]


def _resolve_bridge_url() -> str:
    """Resolve the Sovereign Agent Bridge broadcast URL, honoring ZOTH_BRIDGE_URL if set."""
    env_url = os.environ.get("ZOTH_BRIDGE_URL", "").strip()
    return env_url if env_url else BRIDGE_BROADCAST_URL


def bridge_post(args: dict, **kwargs) -> str:
    """POST a structured broadcast message to the local Sovereign Agent Bridge (:8102/api/broadcast)."""
    try:
        args = args if isinstance(args, dict) else {}
        body = str(args.get("body") or "").strip()
        if not body:
            return _err("bad_argument", "body is required")
        target_url = _resolve_bridge_url()
        if not _is_loopback_url(target_url):
            return _err(
                "bad_argument",
                "bridge URL must target loopback (127.0.0.1, localhost, or ::1)",
            )
        sender = str(args.get("sender") or os.environ.get("HERMES_PROFILE") or "hermes-zoth").strip()
        recipient = str(args.get("recipient") or "broadcast").strip()
        topic = str(args.get("topic") or "hermes-swarm-update").strip()
        payload = json.dumps({
            "content": body,
            "metadata": {
                "sender": sender,
                "recipient": recipient,
                "topic": topic,
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            target_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "hermes-zoth-plugin"},
            method="POST",
        )
        with _loopback_opener.open(req, timeout=4.0) as r:
            raw = r.read(PROBE_MAX_BYTES).decode("utf-8", "replace")
        try:
            resp = json.loads(raw)
        except ValueError:
            resp = {"raw": raw[:512]}
        return json.dumps({"ok": True, "bridge_response": resp})
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read(1024).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return _err(
            "bridge_unreachable",
            f"Sovereign Agent Bridge returned HTTP {e.code}",
            status=e.code,
            detail=detail,
        )
    except Exception as e:  # noqa: BLE001
        return _err("bridge_unreachable", f"could not post to Sovereign Agent Bridge (:8102): {e}")


def ecosystem_targets(args: dict, **kwargs) -> str:
    """Inspect the 6 Zoth/NullAI ecosystem targets, resolving local workspace paths dynamically."""
    try:
        args = args if isinstance(args, dict) else {}
        filt = str(args.get("product") or "").strip().lower()
        ws_root = _workspace_root()
        world_dir = _world_of_zoth_dir()
        results = []
        for item in ECOSYSTEM_PRODUCTS:
            if filt and filt not in item["id"] and filt not in item["name"].lower():
                continue
            if item.get("use_world_dir"):
                workspace_paths = [str(world_dir)]
                pub = world_dir
            else:
                workspace_paths = [str(ws_root / repo) for repo in item["workspace_repos"]]
                pub = ws_root / item["public_relpath"]
            row = {
                "id": item["id"],
                "name": item["name"],
                "domain": item["domain"],
                "github": item["github"],
                "workspace_paths": workspace_paths,
                "public_dir": str(pub),
                "focus": item["focus"],
                "seo_health": {
                    "robots_txt": (pub / "robots.txt").exists(),
                    "sitemap_xml": (pub / "sitemap.xml").exists(),
                    "llms_txt": (pub / "llms.txt").exists(),
                },
                "existing_workspace_paths": [p for p in workspace_paths if Path(p).exists()],
            }
            if "website_github" in item:
                row["website_github"] = item["website_github"]
            results.append(row)
        return json.dumps({"ok": True, "count": len(results), "products": results})
    except Exception as e:  # noqa: BLE001
        return _err("internal", str(e))


def growth_directories(args: dict, **kwargs) -> str:
    """List launch directories, communities, awesome-lists, and resolved local submission pack paths."""
    try:
        args = args if isinstance(args, dict) else {}
        ctype = str(args.get("channel_type") or "").strip().lower()
        hub_dir = _growth_hub_dir()
        items = []
        for c in GROWTH_CHANNELS:
            if ctype and c["type"].lower() != ctype:
                continue
            row = {
                "id": c["id"],
                "name": c["name"],
                "type": c["type"],
                "url": c["url"],
                "status": c["status"],
                "products": list(c["products"]),
            }
            if "notes" in c:
                row["notes"] = c["notes"]
            if "pack_file" in c:
                row["pack"] = str(hub_dir / c["pack_file"])
            items.append(row)
        return json.dumps({
            "ok": True,
            "count": len(items),
            "channels": items,
            "hub_dir": str(hub_dir),
        })
    except Exception as e:  # noqa: BLE001
        return _err("internal", str(e))
