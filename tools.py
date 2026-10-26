"""Handlers for the Zoth plugin. Each returns a JSON string and never raises."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

STUDIO_BASE = "https://zoth.nullai.tech"
_CATALOG_PATH = Path(__file__).parent / "data" / "studio_tools.json"
_catalog = None

# Loopback services documented in Zoth Studio's server/studio-api.mjs.
SERVICES = [
    ("Zoth Studio UI", 3000, "/"),
    ("Neuro memory daemon", 8094, "/health"),
    ("Agent egress sentinel", 8095, "/api/stats"),
    ("Agent mock twin", 8097, "/api/stats"),
    ("Agent prompt firewall", 8098, "/api/stats"),
    ("Sovereign agent bridge", 8102, "/api/health"),
    ("Agent flight recorder", 8104, "/api/stats"),
    ("Agent capsule jail", 8105, "/api/stats"),
    ("Agent policy auditor", 8106, "/api/stats"),
    ("Vault daemon", 8787, "/health"),
    ("Zoth WebGen (Bolt.DIY)", 5173, "/"),
    ("Ollama", 11434, "/api/tags"),
]


def _err(code, message, **extra):
    return json.dumps({"ok": False, "error": {"code": code, "message": message, **extra}})


def _tools():
    global _catalog
    if _catalog is None:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("bundled catalog is not a list")
        _catalog = data
    return _catalog


def _suggest(tool_id):
    import difflib
    ids = [t["id"] for t in _tools()]
    return difflib.get_close_matches((tool_id or "").lower(), ids, n=3, cutoff=0.4)


def _find(tool_id):
    tid = (tool_id or "").strip().lower()
    for t in _tools():
        if t["id"].lower() == tid:
            return t
    return None


def studio_search(args: dict, **kwargs) -> str:
    try:
        q = str(args.get("query") or "").lower().split()
        cat = str(args.get("category") or "").strip().lower()
        try:
            limit = max(1, min(int(args.get("limit") or 10), 100))
        except (TypeError, ValueError):
            return _err("bad_argument", "limit must be an integer")
        hits = []
        for t in _tools():
            if cat and t["category"].lower() != cat:
                continue
            hay = " ".join([t["id"], t["name"], t["category"], t["description"]]).lower()
            score = sum(hay.count(w) for w in q) if q else 1
            if score:
                hits.append((score, t))
        hits.sort(key=lambda h: -h[0])
        out = [{k: t[k] for k in ("id", "name", "category", "description", "studio_url", "github", "published")} for _, t in hits[:limit]]
        cats = sorted({t["category"] for t in _tools()})
        if cat and not any(c.lower() == cat for c in cats):
            return _err("unknown_category", f"no category {args.get('category')!r}", categories=cats)
        return json.dumps({"ok": True, "count": len(hits), "results": out, "categories": cats})
    except (OSError, ValueError) as e:
        return _err("catalog_unavailable", f"could not read bundled catalog: {e}")
    except Exception as e:  # noqa: BLE001
        return _err("internal", f"search failed: {e}")


def studio_tool(args: dict, **kwargs) -> str:
    try:
        t = _find(args.get("tool_id"))
        if not t:
            return _err("unknown_tool", f"unknown tool id {args.get('tool_id')!r}; use zoth_studio_search",
                        did_you_mean=_suggest(args.get("tool_id")))
        res = {"ok": True, **t}
        res["pull_command"] = f"npx @nullaitech/zoth pull {t['id']}" if t["published"] else None
        if args.get("check_live"):
            try:
                req = urllib.request.Request(t["studio_url"], headers={"User-Agent": "hermes-zoth-plugin"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    res["live_status"] = r.status
            except urllib.error.HTTPError as e:
                res["live_status"] = e.code
            except Exception as e:  # noqa: BLE001
                res["live_status"] = f"unreachable: {e}"
        return json.dumps(res)
    except Exception as e:  # noqa: BLE001
        return _err("internal", str(e))


def _probe(port, path):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            pass
    except OSError:
        return False, None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1.5) as r:
            body = r.read(200_000)
        try:
            return True, json.loads(body)
        except ValueError:
            return True, None
    except urllib.error.HTTPError:
        return True, None
    except Exception:  # noqa: BLE001
        return True, None


def status(args: dict, **kwargs) -> str:
    try:
        rows = []
        for name, port, path in SERVICES:
            up, body = _probe(port, path)
            row = {"name": name, "port": port, "up": up}
            if name == "Ollama" and up and isinstance(body, dict):
                row["models"] = [m.get("name") for m in body.get("models", [])]
            rows.append(row)
        return json.dumps({"ok": True, "host": "127.0.0.1", "up": sum(r["up"] for r in rows), "services": rows,
                           "kvm": Path("/dev/kvm").exists(),
                           "hint": None if any(r["up"] for r in rows) else
                           "Nothing is running. Start Zoth Studio with `npx @nullaitech/zoth studio`."})
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
    """True only when ``dest`` is inside the clone root and not under skills/plugins.

    The skills/plugins check still applies when ``plugin-data/zoth`` itself is a
    symlink into one of those directories: ``resolve()`` would otherwise treat
    that target as the allowed root.
    """
    if not _strict_child(dest, root):
        return False
    try:
        top = dest.relative_to(hermes).parts[0]
    except (ValueError, IndexError):
        return True
    return top not in {"skills", "plugins"}


def _resolve_clone_dest(dest_dir, repo: str) -> Path:
    """Resolve ``dest_dir / repo`` under the clone root, never against the process cwd.

    Relative values (including the default ``tools``) join onto
    ``<HERMES_HOME>/plugin-data/zoth``. Absolute values are kept only for the
    containment check that follows.
    """
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


def pull_tool(args: dict, **kwargs) -> str:
    try:
        t = _find(args.get("tool_id"))
        if not t:
            return _err("unknown_tool", f"unknown tool id {args.get('tool_id')!r}",
                        did_you_mean=_suggest(args.get("tool_id")))
        if not t["published"] or not t["github"].startswith("https://github.com/"):
            return _err("not_published", f"{t['id']} has no public GitHub repo; use its Studio page instead",
                        studio_url=t["studio_url"])
        repo = t["github"].rstrip("/").split("/")[-1]
        if repo in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", repo):
            return _err("bad_repo", f"unexpected repo name {repo!r}")
        root = _clone_root()
        hermes = _hermes_home().resolve()
        dest = _resolve_clone_dest(args.get("dest_dir"), repo)
        if not _clone_dest_allowed(dest, root, hermes):
            return _dest_refused(root)
        if shutil.which("git") is None:
            return _err("git_missing", "git is not installed or not on PATH")
        if (dest / ".git").exists():
            cmd = ["git", "-C", str(dest), "pull", "--ff-only"]
        elif dest.exists():
            return _err("dest_exists", f"{dest} exists and is not a git checkout; refusing to overwrite")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", "--depth", "1", t["github"] + ".git", str(dest)]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
        except subprocess.TimeoutExpired:
            return _err("timeout", "git took longer than 180 s", command=" ".join(cmd))
        out = (p.stdout + p.stderr)[-2000:]
        if p.returncode != 0:
            return _err("git_failed", f"git exited {p.returncode}", command=" ".join(cmd), output=out)
        return json.dumps({"ok": True, "path": str(dest), "command": " ".join(cmd), "output": out})
    except PermissionError as e:
        return _err("permission_denied", str(e))
    except Exception as e:  # noqa: BLE001
        return _err("internal", str(e))
