# hermes-zoth

**Zoth Studio + ZOTHOS plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

Provides 7 tools and 1 skill for searching and inspecting [Zoth Studio](https://zoth.nullai.tech) (**85 open-access in-browser and local CLI tools**, 78 with public GitHub repositories), probing local **ZOTHOS** loopback services, cloning public tool repositories safely, broadcasting updates to the local Sovereign Agent Bridge (`:8102`), and checking Zoth/NullAI ecosystem targets and distribution channels.

> Independent community plugin by 1nc0gn30 (Zoth Studio). Not affiliated with or endorsed by Nous Research.

## Install

```bash
hermes plugins install https://github.com/1nc0gn30/hermes-zoth
hermes plugins enable zoth
hermes plugins list | grep zoth      # ✓ zoth 1.3.0 (7 tools)
```

Or copy this directory to `~/.hermes/plugins/zoth/` and run `hermes plugins enable zoth`.

Requirements:
- Hermes Agent `>=0.21.5`
- Python 3.10+ standard library only (zero third-party runtime dependencies, no API keys)
- `git` on `PATH` (only required for `zoth_pull_tool`)

## Tools

| Tool | Purpose | Network |
| --- | --- | --- |
| `zoth_studio_search` | Search the 85-tool catalog by keywords, category (exact or family prefix like `security`), or `execution_type` (`browser`, `local_cli`, `webgpu`, `hybrid`). Returns ranked results with `version`, `execution_type`, `local_port`, `studio_url`, and GitHub source flags. | none (bundled catalog) |
| `zoth_studio_tool` | Look up one tool by id or friendly name. Returns `studio_url`, `github`, `execution_type`, `local_port`, `pull_command`, and source flags. `check_live: true` checks HTTP status of the Studio page. | optional HTTPS GET to `zoth.nullai.tech` |
| `zoth_status` | Probe local ZOTHOS / Zoth services in parallel: Studio UI (`:3000`), Neuro memory daemon (`:8094`), agent/security suite (`:8095-8106`, including Sovereign Agent Bridge `:8102`), Chronicle memory vault (`:8161`), Zoth Bot OS (`:8190`), Vault daemon (`:8787`), WebGen (`:5173`), and Ollama (`:11434`, with installed model names). | `127.0.0.1` only (no proxies, no redirects) |
| `zoth_pull_tool` | Shallow-clone one published `NullAITech`/`1nc0gn30` repo into `<HERMES_HOME>/plugin-data/zoth/<dest_dir>/<repo>` (default `tools`), or fast-forward update an existing checkout. Optional `ref` pins a branch, tag, or 40-char SHA. | `github.com` via `git` |
| `zoth_bridge_post` | POST a structured JSON broadcast (`content` + `metadata`: `sender`, `recipient`, `topic`) to the local Sovereign Agent Bridge (`http://127.0.0.1:8102/api/broadcast` or `ZOTH_BRIDGE_URL`). | loopback only (no proxies, no redirects) |
| `zoth_ecosystem_targets` | Inspect the 6 Zoth/NullAI products (`zothos`, `zothos-lite`, `zothnet`, `zoth-studio`, `1nc0gn30`, `nullai`), resolving local workspace paths under `ZOTH_WORKSPACE_ROOT` (default `~/NullAITech`) and checking `robots.txt`, `sitemap.xml`, and `llms.txt`. | none (local filesystem) |
| `zoth_growth_directories` | List launch directories, communities, blogs, and GitHub Awesome Lists filterable by `channel_type` (`directory`, `awesome-list`, `community`, `blog`) with resolved pack paths under `ZOTH_GROWTH_HUB_DIR`. | none (offline catalog) |

Skill: `skill_view("zoth:zoth-studio")` guides the agent through tool search, local service verification, safe repo pulling, and Bridge updates.

## Environment Variables

All environment variables are optional:

| Variable | Default | Purpose |
| --- | --- | --- |
| `HERMES_HOME` | `~/.hermes` (or `get_hermes_home()`) | Base directory for `zoth_pull_tool` (`<HERMES_HOME>/plugin-data/zoth`). |
| `ZOTH_BRIDGE_URL` | `http://127.0.0.1:8102/api/broadcast` | Override Sovereign Agent Bridge broadcast endpoint (must resolve to loopback: `127.0.0.1`, `localhost`, or `::1`). |
| `ZOTH_WORKSPACE_ROOT` | `~/NullAITech` | Root directory inspected by `zoth_ecosystem_targets`. |
| `ZOTH_GROWTH_HUB_DIR` | `<ZOTH_WORKSPACE_ROOT>/growth-distribution` | Base directory for submission pack paths returned by `zoth_growth_directories`. |
| `ZOTH_WORLD_DIR` | `~/Desktop/world-of-zoth` | Local checkout path for the `1nc0gn30` ecosystem target. |

## Examples

Prompts that work directly in Hermes Agent:

```text
Find me a Zoth tool for building a regex and give me the link.
List local_cli tools in Zoth Studio related to Comfy or Bot OS.
Which Zoth services are running on this machine, and which Ollama models are installed?
Pull the osint-scout-skill repository into tools/.
Broadcast a status update to the Sovereign Agent Bridge on topic catalog-sync.
```

### Sample Tool Responses

`zoth_studio_search {"query": "bot os", "execution_type": "local_cli", "limit": 2}`

```json
{
  "ok": true,
  "count": 1,
  "results": [
    {
      "id": "zoth-bot-os",
      "name": "Zoth Bot OS",
      "category": "Swarm & Core",
      "description": "Mobile-first PWA and desktop Command Deck (:8190) unifying Hermes, Antigravity (AGY), Chronicle Vault, Social Teach-by-Recording Playbooks, and Netlify Cove over local loopback and Tailscale HTTPS.",
      "version": "1.4.0",
      "execution_type": "local_cli",
      "local_port": 8190,
      "studio_url": "https://zoth.nullai.tech/tools/zoth-bot-os/",
      "github": "https://github.com/1nc0gn30/zoth-bot-os",
      "published": false,
      "source_owner": "1nc0gn30",
      "source_repo": "zoth-bot-os",
      "third_party": false,
      "monorepo": false,
      "score": 450
    }
  ]
}
```

`zoth_studio_tool {"tool_id": "regex-droid"}` (typo returns suggestions)

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

`zoth_status {}` when no local services are started

```json
{
  "ok": true,
  "host": "127.0.0.1",
  "up": 0,
  "services": [
    {"name": "Zoth Studio UI", "port": 3000, "up": false},
    {"name": "Neuro memory daemon", "port": 8094, "up": false},
    {"name": "Zoth Bot OS", "port": 8190, "up": false}
  ],
  "kvm": true,
  "hint": "Nothing is running. Start Zoth Studio with `npx @nullaitech/zoth studio`."
}
```

`zoth_bridge_post {"sender": "hermes-auditor", "topic": "health-check", "body": "All 85 catalog entries verified."}`

```json
{
  "ok": true,
  "bridge_response": {
    "status": "ok",
    "broadcast": {"broadcast_id": "...", "content": "All 85 catalog entries verified."}
  }
}
```

In the Hermes CLI banner:

```text
  zoth: zoth_studio_search, zoth_studio_tool, zoth_status, zoth_pull_tool, zoth_bridge_post, zoth_ecosystem_targets, zoth_growth_directories
```

### Source Flags

Search and tool results include `source_owner`, `source_repo`, `third_party`, and `monorepo`:

- `third_party: true`: catalog entry points to an external project (currently `ghidra-mcp-bridge` → [LaurieWired/GhidraMCP](https://github.com/LaurieWired/GhidraMCP)). `zoth_pull_tool` returns `third_party_repo`; share the GitHub link instead.
- `monorepo: true`: tool lives inside `zoth-studio-v2` or `zoth-os`, so pulling clones the parent repository.
- `pull_command`: populated only for published `NullAITech` repos supported by `npx @nullaitech/zoth pull <repo>`.

### Errors

Every handler returns JSON and never raises. Failures have the shape `{"ok": false, "error": {"code": "...", "message": "..."}}`.

Error codes: `unknown_tool` (with `did_you_mean`), `unknown_category`, `bad_argument`, `not_published`, `bad_repo`, `git_missing`, `dest_outside_root`, `dest_exists`, `third_party_repo`, `git_failed`, `timeout`, `permission_denied`, `bridge_unreachable`, `catalog_unavailable`, `internal`.

## Keeping the Catalog Current

`data/studio_tools.json` is generated from Zoth Studio's registry (`src/data/toolsData.js` in [1nc0gn30/zoth-studio-v2](https://github.com/1nc0gn30/zoth-studio-v2), with automatic fallback to `public/api/tools.json`):

```bash
python3 scripts/sync_catalog.py --studio ../zoth-studio-v2           # regenerate + verify
python3 scripts/sync_catalog.py --studio ../zoth-studio-v2 --check   # CI: exit 1 if stale
```

The sync script keeps only public fields (`id`, `name`, `category`, `description`, `version`, `github`, `execution_type`, `local_port`, `published`, `studio_url`), verifies every Studio page returns HTTP 200 with a tool-specific `<title>`, runs `git ls-remote` on each repo (marking unreachable repos `published: false`), and scans fields for personal paths, emails, phone numbers, and tokens.

## Disclosures & Trust Model

- **What it reads:** bundled JSON catalog (`data/studio_tools.json`, public fields only), optional local workspace metadata in `zoth_ecosystem_targets` (`robots.txt`, `sitemap.xml`, `llms.txt` existence checks), and loopback TCP/HTTP on `127.0.0.1` in `zoth_status`.
- **Network boundaries:**
  - `zoth_studio_tool` with `check_live=true` sends one HTTPS GET to `https://zoth.nullai.tech/tools/...` and refuses cross-host or scheme-changing redirects.
  - `zoth_status` and `zoth_bridge_post` strictly enforce loopback hosts (`127.0.0.1`, `localhost`, `::1`), bypass `HTTP_PROXY`/`HTTPS_PROXY`, refuse all HTTP redirects, and cap response reads at 64 KB.
  - `zoth_pull_tool` invokes `git` against `github.com` only for catalog entries owned by `NullAITech` or `1nc0gn30`.
  - No telemetry, no background daemons, no self-updating code, no stored credentials.
- **Filesystem boundaries:** `zoth_pull_tool` writes only inside `<HERMES_HOME>/plugin-data/zoth/`. Relative `dest_dir` resolves against that root, never process cwd. Absolute paths, `..`, and symlinks resolving outside that root (including `~/.hermes/skills` and `~/.hermes/plugins`) are refused with `dest_outside_root`. Existing non-git directories and mismatched git remotes are never overwritten.
- **Git hardening:** fixed argv (no shell), `--` before URLs, strict ref validation, minimal environment (shell tokens and `GIT_*` overrides stripped, `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`), `core.hooksPath=/dev/null`, `core.fsmonitor=false`, `protocol.file.allow=never`, `protocol.ext.allow=never`, `submodule.recurse=false`, 180 s timeout.

## Changelog

### 1.3.0

- Synced `data/studio_tools.json` to all **85 open-access Zoth Studio v2 tools** (78 public repos verified), adding `zoth-bot-os` (`:8190`) and `zoth-comfy-foundry`, plus `execution_type` and `local_port` fields on every entry.
- Added optional `execution_type` filtering to `zoth_studio_search` and projected `execution_type` / `local_port` in search and tool responses.
- Removed all hardcoded personal paths from `tools.py`, replacing them with `os.path.expanduser` / `Path.home()` and `ZOTH_WORKSPACE_ROOT`, `ZOTH_GROWTH_HUB_DIR`, and `ZOTH_WORLD_DIR` environment overrides.
- Hardened SSRF and loopback guards: loopback requests (`zoth_status`, `zoth_bridge_post`) now bypass proxies and refuse redirects; `ZOTH_BRIDGE_URL` enforces loopback-only hosts; `check_live` validates `STUDIO_BASE` and rejects HTTPS-to-HTTP downgrades.
- Added Zoth Bot OS (`:8190`) and Chronicle memory vault (`:8161`) to `zoth_status`.
- Expanded pytest suite covering 85-tool catalog integrity, SSRF/loopback safety, mocked bridge/daemon HTTP paths, dynamic workspace resolution, and repository-wide secret/PII hygiene.

### 1.2.0

- Added `zoth_bridge_post` (`http://127.0.0.1:8102/api/broadcast`), `zoth_ecosystem_targets`, and `zoth_growth_directories`.
- Synced catalog to 83 tools and aligned attribution to `1nc0gn30 (Zoth Studio)`.

### 1.1.4

- Fixed `ref` cloning/updating for branches, tags, and 40-char SHAs.
- Added `source_owner`, `source_repo`, `third_party`, and `monorepo` flags; blocked cloning third-party repos (`third_party_repo`).
- Added git hardening, parallel `zoth_status` probing with 4 s budget, 64 KB response cap, and catalog reload on mtime change.

### 1.1.3

- Synced catalog with Zoth Studio main (+6 tools) and merged into the Hermes plugin catalog.

## Development

```bash
python3 -m pytest -c tests/pytest.ini --rootdir tests tests -v
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

## License

MIT © 2026 1nc0gn30
