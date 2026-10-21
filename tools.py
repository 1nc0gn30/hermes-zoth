"""Handlers for the Zoth plugin. Each returns a JSON string and never raises."""

import json
import socket
import subprocess
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


def _tools():
    global _catalog
    if _catalog is None:
        _catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    return _catalog


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
        limit = max(1, min(int(args.get("limit") or 10), 62))
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
        return json.dumps({"count": len(hits), "results": out, "categories": cats})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": f"search failed: {e}"})


def studio_tool(args: dict, **kwargs) -> str:
    try:
        t = _find(args.get("tool_id"))
        if not t:
            return json.dumps({"error": f"unknown tool id {args.get('tool_id')!r}; use zoth_studio_search"})
        res = dict(t)
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
        return json.dumps({"error": str(e)})


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
        return json.dumps({"host": "127.0.0.1", "up": sum(r["up"] for r in rows), "services": rows,
                           "kvm": Path("/dev/kvm").exists()})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": str(e)})


def pull_tool(args: dict, **kwargs) -> str:
    try:
        t = _find(args.get("tool_id"))
        if not t:
            return json.dumps({"error": f"unknown tool id {args.get('tool_id')!r}"})
        if not t["published"] or not t["github"].startswith("https://github.com/"):
            return json.dumps({"error": f"{t['id']} has no published GitHub repo"})
        repo = t["github"].rstrip("/").split("/")[-1]
        dest = Path(args.get("dest_dir") or "tools").expanduser().resolve() / repo
        if (dest / ".git").exists():
            cmd = ["git", "-C", str(dest), "pull", "--ff-only"]
        elif dest.exists():
            return json.dumps({"error": f"{dest} exists and is not a git checkout; refusing to overwrite"})
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", "--depth", "1", t["github"] + ".git", str(dest)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return json.dumps({"ok": p.returncode == 0, "path": str(dest), "command": " ".join(cmd),
                           "output": (p.stdout + p.stderr)[-2000:]})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": str(e)})
