#!/usr/bin/env python3
"""Regenerate data/studio_tools.json from Zoth Studio's catalog and verify every link.

    python scripts/sync_catalog.py --studio /path/to/zoth-studio-v2 [--no-verify] [--check]

Reads src/data/toolsData.js via `node` (Node 18+), keeps only public fields, then checks
each Studio page (must return 200 and a tool-specific <title>) and each GitHub repo
(`git ls-remote`). A repo that does not answer is written with "published": false.
--check exits 1 if the bundled file would change (for CI).
"""
import argparse, concurrent.futures as cf, json, re, subprocess, sys, urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "studio_tools.json"
BASE = "https://zoth.nullai.tech/tools/"
GENERIC_TITLE = "Pantheon Matrix"  # the Studio home title, served for unknown routes
FIELDS = ("id", "name", "category", "description", "version", "github")
PII = [re.compile(p) for p in (r"\+?1?[ (.-]*\d{3}[ ).-]*\d{3}[ .-]\d{4}", r"[\w.+-]+@[\w-]+\.[\w.]+",
       r"/(home|media|Users)/", r"ghp_|github_pat_|sk-[A-Za-z0-9]{16}|AKIA[0-9A-Z]{16}|xox[bp]-")]


def load(studio: Path):
    js = (studio / "src/data/toolsData.js").resolve()
    code = f"import({json.dumps(js.as_uri())}).then(m=>process.stdout.write(JSON.stringify(m.microTools)))"
    return json.loads(subprocess.run(["node", "-e", code], check=True, capture_output=True, text=True).stdout)


def page_ok(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hermes-zoth-sync"})
        with urllib.request.urlopen(req, timeout=15) as r:
            m = re.search(r"<title>([^<]*)", r.read(65536).decode("utf-8", "replace"))
            return r.status == 200 and bool(m) and GENERIC_TITLE not in m.group(1)
    except Exception:
        return False


def repo_ok(url):
    if not url.startswith("https://github.com/"):
        return False
    env = {"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    return subprocess.run(["git", "-c", "credential.helper=", "ls-remote", "-q", url, "HEAD"],
                          capture_output=True, env=env, timeout=30).returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--studio", required=True, type=Path)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    tools = []
    for t in load(a.studio):
        row = {k: str(t.get(k, "")) for k in FIELDS}
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
        for field in ("name", "description", "category"):
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
