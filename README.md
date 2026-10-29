# hermes-zoth

**Zoth Studio + ZOTHOS for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

Gives Hermes four tools and a skill for working with [Zoth Studio](https://zoth.nullai.tech), a collection of 71 in-browser developer, security, agent-safety and creator tools (59 with a public GitHub source), and with the local Zoth services that run on **ZOTHOS** ("Zoth O-S"), the Debian-based AI Linux distro, or on any machine with Zoth installed.

> Independent community plugin by Neal Frazier / NullAITech. Not affiliated with or endorsed by Nous Research.

## Install

```bash
hermes plugins install https://github.com/1nc0gn30/hermes-zoth
hermes plugins enable zoth
hermes plugins list | grep zoth      # ✓ zoth 1.1.4 (4 tools)
```

Or copy the folder to `~/.hermes/plugins/zoth/` and run `hermes plugins enable zoth`.

Needs Hermes `>=0.21.5`. No API keys, no Python dependencies. `zoth_pull_tool` needs `git`.

## Tools

| Tool | Use it for | Network |
| --- | --- | --- |
| `zoth_studio_search` | Find a Studio tool by keywords or category. Returns its Studio URL and GitHub source. | none (bundled catalog) |
| `zoth_studio_tool` | Details for one tool id: Studio URL, repo, `npx @nullaitech/zoth pull` command. `check_live: true` confirms the page is up. | optional HTTPS GET to zoth.nullai.tech |
| `zoth_status` | Which Zoth services are up on this machine: Studio UI :3000, memory :8094, agent and security services :8095-8106 (including bridge :8102), vault :8787, WebGen :5173, Ollama :11434 (with model names). Note up=true indicates a TCP connection was accepted on 127.0.0.1. | 127.0.0.1 only |
| `zoth_pull_tool` | Shallow-clone one published NullAITech tool repo into `<HERMES_HOME>/plugin-data/zoth/tools/<repo>` (or update it if present). Optional `ref` pins a branch, tag or full SHA. | github.com via `git` |

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
  "did_you_mean": ["regex-droid-builder"]
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


### Source flags

Search and tool results include `source_owner`, `source_repo`, `third_party` and `monorepo`:

- `third_party: true`: the catalog links to someone else's project (today only `ghidra-mcp-bridge`, which points at [LaurieWired/GhidraMCP](https://github.com/LaurieWired/GhidraMCP)). `zoth_pull_tool` refuses it with `third_party_repo`; give the user the link instead.
- `monorepo: true`: the tool lives inside a larger repo (`zoth-studio-v2` or `zoth-os`), so pulling it fetches the whole project.
- `pull_command` is set only for NullAITech repos, because that's what `npx @nullaitech/zoth pull <repo>` lists. It uses the repo name, which differs from the tool id for some tools (e.g. `hexstrike-arsenal` → `NullAI-HexStrike-AI-Terminal`).

### Errors

Every tool returns JSON and never raises. Failures look like `{"ok": false, "error": {"code": ..., "message": ...}}`. Codes: `unknown_tool` (with `did_you_mean`), `unknown_category`, `bad_argument`, `not_published`, `bad_repo`, `git_missing`, `dest_outside_root`, `dest_exists`, `third_party_repo`, `git_failed`, `timeout`, `permission_denied`, `catalog_unavailable`, `internal`.

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

## Trust model

- **What it reads:** a bundled JSON catalog (`data/studio_tools.json`, public fields only) and TCP/HTTP on `127.0.0.1` for `zoth_status`.
- **What it calls out to:** `zoth.nullai.tech` (only with `check_live`, same-host redirects only) and `github.com` via `git` (only `zoth_pull_tool`). Nothing else. No telemetry, no background work, no self-update.
- **What it writes:** only `<HERMES_HOME>/plugin-data/zoth/`. Paths that resolve elsewhere (including Hermes `skills/` and `plugins/`) and existing non-git folders are refused. An existing checkout is only updated if its `origin` is the catalog repo.
- **Whose code it clones:** only repos owned by `NullAITech` or `1nc0gn30` (both the author's accounts). Third-party catalog entries are link-only.
- **How git runs:** fixed argv, no shell, `--` before the URL, refs validated (no leading `-`, no `..`, `@{`, `//` or `.lock`), a minimal environment (no tokens or `GIT_*` overrides from your shell, `GIT_TERMINAL_PROMPT=0`, no system git config), `core.hooksPath=/dev/null`, `protocol.file.allow=never`, `protocol.ext.allow=never`, timeouts of 180 s per clone/fetch.
- **Status checks:** run in parallel with a 4 s total budget; responses are capped at 64 KB. `up: true` means a TCP connection was accepted, not that the service is healthy.

## Changelog

### 1.1.4

- `ref` actually works: branches and tags clone with `--branch`, full SHAs use `fetch --depth 1` + `checkout --detach FETCH_HEAD`, and a pinned checkout can be re-pinned or moved back to the default branch. Covered by tests against a real local git repo.
- `pull_command` uses the repo name and is only shown for NullAITech repos.
- New `source_owner` / `source_repo` / `third_party` / `monorepo` fields; third-party repos are no longer cloned (`third_party_repo`).
- git hardening: minimal env, hooks off, file/ext transports off, refs with `..` rejected, origin check before updating a checkout.
- `zoth_status` probes in parallel with a total timeout; 64 KB response cap. `check_live` refuses cross-host redirects.
- Roadmap fixes Z-01–Z-12: category family filters, `limit` clamping, ranked search, better `did_you_mean`, friendly-name lookup, accurate counts and port coverage, `version` in results, full error-code list, catalog reload on change.
- Catalog resynced from Zoth Studio (`zoth-os` → 3.3.0). CI runs the tests and `sync_catalog.py --check`.

### 1.1.3

- Catalog synced with Zoth Studio main (+6 tools). Merged into the Hermes plugin catalog.

## Development

```bash
python -m pytest -c tests/pytest.ini --rootdir tests tests
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

## License

MIT © 2026 Neal Frazier
