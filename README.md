# hermes-zoth

**Zoth Studio + ZOTHOS for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

Gives Hermes four tools and a skill for working with [Zoth Studio](https://zoth.nullai.tech), a collection of 62 in-browser developer, security, agent-safety and creator tools, and with the local Zoth services that run on **ZOTHOS** ("Zoth O-S"), the Debian-based AI Linux distro, or on any machine with Zoth installed.

> Independent community plugin by Neal Frazier / NullAITech. Not affiliated with or endorsed by Nous Research.

## Install

```bash
hermes plugins install https://github.com/1nc0gn30/hermes-zoth
hermes plugins enable zoth
hermes plugins list | grep zoth      # ✓ zoth 1.1.3 (4 tools)
```

Or copy the folder to `~/.hermes/plugins/zoth/` and run `hermes plugins enable zoth`.

Needs Hermes `>=0.21.5`. No API keys, no Python dependencies. `zoth_pull_tool` needs `git`.

## Tools

| Tool | Use it for | Network |
| --- | --- | --- |
| `zoth_studio_search` | Find a Studio tool by keywords or category. Returns its Studio URL and GitHub source. | none (bundled catalog) |
| `zoth_studio_tool` | Details for one tool id: Studio URL, repo, `npx @nullaitech/zoth pull` command. `check_live: true` confirms the page is up. | optional HTTPS GET to zoth.nullai.tech |
| `zoth_status` | Which Zoth services are up on this machine: Studio UI :3000, memory :8094, agent services :8095-8106, bridge :8102, vault :8787, WebGen :5173, Ollama :11434 (with model names). | 127.0.0.1 only |
| `zoth_pull_tool` | Shallow-clone one published tool repo into `<HERMES_HOME>/plugin-data/zoth/tools/<repo>` (or `git pull --ff-only` if present). | github.com via `git` |

Skill: `skill_view("zoth:zoth-studio")` walks the agent through picking a tool, giving the user its link, and checking local services.

## Examples

Prompts that work well:

```
Find me a Zoth tool for building a regex and give me the link.
I need to decode a JWT. Is there a Zoth Studio tool for that?
Which Zoth services are running on this box, and which Ollama models do I have?
Pull the PWA manifest builder source.
```

### What the agent sees (text screenshots)

`zoth_studio_search {"query": "jwt", "limit": 2}`

```json
{
 "ok": true,
 "count": 1,
 "results": [
  {
   "id": "jwt-inspector-guard",
   "name": "JWT Inspector Guard",
   "category": "Security & Recon",
   "description": "Zero-cloud in-browser JWT token decoder, cryptographic signature validator, HS256 dictionary cracker, DPoP proofer, and auth claim auditor.",
   "studio_url": "https://zoth.nullai.tech/tools/jwt-inspector-guard/",
   "github": "https://github.com/1nc0gn30/jwt-inspector-guard",
   "published": true
  }
 ]
}
```

`zoth_studio_tool {"tool_id": "regex-droid"}` (a typo)

```json
{
 "ok": false,
 "error": {
  "code": "unknown_tool",
  "message": "unknown tool id 'regex-droid'; use zoth_studio_search",
  "did_you_mean": ["regex-droid-builder", "sovereign-agent-bridge", "agent-gods-eye"]
 }
}
```

`zoth_status {}` on a machine with nothing started

```json
{
 "ok": true,
 "host": "127.0.0.1",
 "up": 0,
 "services": [
  {"name": "Zoth Studio UI", "port": 3000, "up": false},
  {"name": "Neuro memory daemon", "port": 8094, "up": false},
  "..."
 ],
 "kvm": true,
 "hint": "Nothing is running. Start Zoth Studio with `npx @nullaitech/zoth studio`."
}
```

In the CLI banner:

```
  zoth: zoth_studio_search, zoth_studio_tool, zoth_status, zoth_pull_tool
```

### Errors

Every tool returns JSON and never raises. Failures look like `{"ok": false, "error": {"code": ..., "message": ...}}`. Codes: `unknown_tool` (with `did_you_mean`), `unknown_category`, `bad_argument`, `not_published`, `git_missing`, `dest_outside_root`, `dest_exists`, `git_failed`, `timeout`, `permission_denied`, `catalog_unavailable`, `internal`.

## Keeping the catalog current

`data/studio_tools.json` is generated from Zoth Studio's own catalog (`src/data/toolsData.js` in [zoth-studio-v2](https://github.com/1nc0gn30/zoth-studio-v2)):

```bash
python scripts/sync_catalog.py --studio ../zoth-studio-v2           # regenerate + verify
python scripts/sync_catalog.py --studio ../zoth-studio-v2 --check   # CI: exit 1 if stale
```

The script keeps only public fields and checks that every Studio page answers with its own title. It runs `git ls-remote` on every repo and marks any that don't answer as unpublished. It also warns about anything that looks like a phone number, email address, local path or token.

## Disclosures

- **Network:** `zoth_studio_tool` with `check_live` does one HTTPS GET to `zoth.nullai.tech`. `zoth_pull_tool` runs `git` against `github.com`. `zoth_status` connects only to `127.0.0.1`. No telemetry.
- **Shell:** `zoth_pull_tool` runs `git clone --depth 1` / `git pull --ff-only` as a subprocess with a fixed argv (no shell), only for catalog repos, with `GIT_TERMINAL_PROMPT=0`.
- **Files:** `zoth_pull_tool` writes only under `<HERMES_HOME>/plugin-data/zoth/` (default `.../tools/<repo>`). A relative `dest_dir` is resolved against that directory, not the process working directory. Absolute paths, `..`, and symlinks that resolve anywhere else — including `~/.hermes/skills` and `~/.hermes/plugins` — are refused (`dest_outside_root`). Reads nothing outside the plugin directory.
- No credentials, no background processes, no self-updating code.

## Development

```bash
python -m pytest -c tests/pytest.ini --rootdir tests tests
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

## License

MIT © 2026 Neal Frazier
