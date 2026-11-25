#!/usr/bin/env python3
"""Regenerate data/studio_tools.json from Zoth Studio's catalog and verify every link.

    python scripts/sync_catalog.py --studio /path/to/zoth-studio-v2 [--no-verify] [--check]

Reads src/data/toolsData.js via `node` (Node 18+), falling back to public/api/tools.json
if toolsData.js or Node is unavailable, keeps only public fields, then checks each Studio
page (must return 200 and a tool-specific <title>) and each GitHub repo (`git ls-remote`).
A repo that does not answer is written with "published": false.
--check exits 1 if the bundled file would change (for CI).
"""
import argparse
import concurrent.futures as cf
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "studio_tools.json"
BASE = "https://zoth.nullai.tech/tools/"
GENERIC_TITLE = "Pantheon Matrix"  # the Studio home title, served for unknown routes
FIELDS = ("id", "name", "category", "description", "version", "github")
PII = [
    re.compile(p)
    for p in (
        r"\+?1?[ (.-]*\d{3}[ ).-]*\d{3}[ .-]\d{4}",
        r"[\w.+-]+@[\w-]+\.[\w.]+",
        r"/(home|media|Users)/",
        r"ghp_|github_pat_|sk-[A-Za-z0-9]{16}|AKIA[0-9A-Z]{16}|xox[bp]-",
    )
]


def load(studio: Path):
    js = (studio / "src/data/toolsData.js").resolve()
    if js.exists() and shutil.which("node"):
        code = f"import({json.dumps(js.as_uri())}).then(m=>process.stdout.write(JSON.stringify(m.microTools)))"
        return json.loads(subprocess.run(["node", "-e", code], check=True, capture_output=True, text=True).stdout)
    api_json = (studio / "public/api/tools.json").resolve()
    if api_json.exists():
        raw = json.loads(api_json.read_text(encoding="utf-8"))
        return raw.get("tools", raw) if isinstance(raw, dict) else raw
    raise FileNotFoundError(f"neither {js} (with node) nor {api_json} found")


def _normalize_port(val):
    if val is None or isinstance(val, bool):
        return None
    try:
        port = int(val)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def page_ok(url):
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hermes-zoth-sync"})
            with urllib.request.urlopen(req, timeout=15) as r:
                m = re.search(r"<title>([^<]*)", r.read(65536).decode("utf-8", "replace"))
                if r.status == 200 and bool(m) and GENERIC_TITLE not in m.group(1):
                    return True
        except Exception:
            pass
    return False


def repo_ok(url):
    if not url.startswith("https://github.com/"):
        return False
    base = re.sub(r"/(tree|blob)/.*$", "", url)
    env = {"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    for _ in range(2):
        try:
            if (
                subprocess.run(
                    ["git", "-c", "credential.helper=", "ls-remote", "-q", base, "HEAD"],
                    capture_output=True,
                    env=env,
                    timeout=30,
                ).returncode
                == 0
            ):
                return True
        except Exception:
            pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--studio", required=True, type=Path)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    tools = []
    for t in load(a.studio):
        row = {k: str(t.get(k, "")) for k in FIELDS}
        row["execution_type"] = str(t.get("executionType") or t.get("execution_type") or "browser")
        raw_port = t.get("localPort") if "localPort" in t else t.get("port")
        row["local_port"] = _normalize_port(raw_port)
        row["published"] = bool(t.get("published"))
        row["studio_url"] = BASE + row["id"] + "/"
        tools.append(row)
    problems = []
    if not a.no_verify:
        with cf.ThreadPoolExecutor(16) as ex:
            pages = list(ex.map(lambda t: page_ok(t["studio_url"]), tools))
            repos = list(ex.map(lambda t: repo_ok(t["github"]) if t["published"] else False, tools))
        for t, p, r in zip(tools, pages, repos):
            if not p:
                problems.append(f"page not live: {t['studio_url']}")
            if t["published"] and not r:
                t["published"] = False
                problems.append(f"repo unreachable, marked unpublished: {t['github']}")
    for t in tools:
        for field in ("name", "description", "category", "github", "studio_url"):
            if any(p.search(t[field]) for p in PII):
                problems.append(f"possible personal data in {t['id']}.{field}; review before committing")
    new = json.dumps(tools, indent=1, ensure_ascii=False) + "\n"
    for p in problems:
        print("WARN", p, file=sys.stderr)
    if a.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == new
        print("up to date" if same else "catalog is stale; run without --check")
        return 0 if same else 1
    OUT.write_text(new, encoding="utf-8")
    print(f"wrote {len(tools)} tools ({sum(t['published'] for t in tools)} published) to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
