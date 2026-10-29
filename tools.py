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
_catalog_mtime = 0

# Loopback services documented in Zoth Studio's server/studio-api.mjs.
# Covers UI :3000, memory :8094, the full :8095-8106 agent/security suite, vault :8787, WebGen :5173, and Ollama :11434.
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
    ("Vault daemon", 8787, "/health"),
    ("Zoth WebGen (Bolt.DIY)", 5173, "/"),
    ("Ollama", 11434, "/api/tags"),
]


def _err(code, message, **extra):
    return json.dumps({"ok": False, "error": {"code": code, "message": message, **extra}})


def _tools():
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


def _suggest(tool_id):
    import difflib
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
    try:
        raw_q = str(args.get("query") or "").strip().lower()
        q_words = re.findall(r"[a-z0-9]+", raw_q)
        cat = str(args.get("category") or "").strip().lower()
        raw_limit = args.get("limit")
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

        hits = []
        for t in catalog:
            if cat and not _match_category(cat, t["category"]):
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
                "studio_url": t["studio_url"],
                "github": t["github"],
                "published": t["published"],
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
    try:
        raw_id = args.get("tool_id")
        t = _find(raw_id)
        if not t:
            display_id = "<missing>" if raw_id is None else repr(raw_id)
            return _err(
                "unknown_tool",
                f"unknown tool id {display_id}; use zoth_studio_search",
                did_you_mean=_suggest(raw_id),
            )
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
        return json.dumps({
            "ok": True,
            "host": "127.0.0.1",
            "up": sum(r["up"] for r in rows),
            "services": rows,
            "kvm": Path("/dev/kvm").exists(),
            "hint": None if any(r["up"] for r in rows) else
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


def pull_tool(args: dict, **kwargs) -> str:
    try:
        raw_id = args.get("tool_id")
        t = _find(raw_id)
        if not t:
            display_id = "<missing>" if raw_id is None else repr(raw_id)
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
        repo = t["github"].rstrip("/").split("/")[-1]
        if repo in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", repo):
            return _err("bad_repo", f"unexpected repo name {repo!r}")

        ref = args.get("ref")
        if ref is not None:
            ref_str = str(ref).strip()
            if not ref_str or not re.fullmatch(r"[A-Za-z0-9._/-]+", ref_str):
                return _err("bad_argument", f"invalid ref {ref!r}")
        else:
            ref_str = None

        root = _clone_root()
        hermes = _hermes_home().resolve()
        dest = _resolve_clone_dest(args.get("dest_dir"), repo)
        if not _clone_dest_allowed(dest, root, hermes):
            return _dest_refused(root)
        if shutil.which("git") is None:
            return _err("git_missing", "git is not installed or not on PATH")

        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if (dest / ".git").exists():
            cmd = ["git", "-C", str(dest), "pull", "--ff-only"]
        elif dest.exists():
            return _err("dest_exists", f"{dest} exists and is not a git checkout; refusing to overwrite")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", "--depth", "1", t["github"] + ".git", str(dest)]

        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
        except subprocess.TimeoutExpired:
            return _err("timeout", "git took longer than 180 s", command=" ".join(cmd))
        out = (p.stdout + p.stderr)[-2000:]
        if p.returncode != 0:
            return _err("git_failed", f"git exited {p.returncode}", command=" ".join(cmd), output=out)

        # Optional explicit ref checkout
        if ref_str:
            checkout_cmd = ["git", "-C", str(dest), "checkout", ref_str]
            try:
                p_ref = subprocess.run(checkout_cmd, capture_output=True, text=True, timeout=60, env=env)
            except subprocess.TimeoutExpired:
                return _err("timeout", f"git checkout {ref_str} took longer than 60 s", command=" ".join(checkout_cmd))
            out += "\n" + (p_ref.stdout + p_ref.stderr)[-1000:]
            if p_ref.returncode != 0:
                return _err("git_failed", f"git checkout {ref_str} exited {p_ref.returncode}", command=" ".join(checkout_cmd), output=out)

        # Inspect resulting commit SHA if destination is a git repo
        commit_sha = None
        if (dest / ".git").exists():
            try:
                p_sha = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, env=env)
                if p_sha.returncode == 0 and len(p_sha.stdout.strip()) == 40:
                    commit_sha = p_sha.stdout.strip()
            except Exception:
                pass

        res = {"ok": True, "path": str(dest), "command": " ".join(cmd), "commit": commit_sha, "output": out}
        if ref_str:
            res["ref"] = ref_str
        return json.dumps(res)
    except PermissionError as e:
        return _err("permission_denied", str(e))
    except Exception as e:  # noqa: BLE001
        return _err("internal", str(e))

