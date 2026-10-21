# hermes-zoth

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin for **Zoth Studio** (https://zoth.nullai.tech) and **ZOTHOS** ("Zoth O-S"), by Neal Frazier / NullAITech. Independent community plugin; not affiliated with or endorsed by Nous Research.

## Tools

| Tool | What it does |
| --- | --- |
| `zoth_studio_search` | Searches the bundled catalog of 62 Zoth Studio tools (name, category, description) and returns each tool's Studio page URL and GitHub source. |
| `zoth_studio_tool` | Details for one tool: in-browser Studio URL, repo, `npx @nullaitech/zoth pull` command. `check_live: true` does one HTTPS GET to confirm the page answers. |
| `zoth_status` | Probes Zoth / ZOTHOS services on `127.0.0.1` (Studio UI :3000, memory daemon :8094, agent sentinels :8095-8106, bridge :8102, vault :8787, WebGen :5173, Ollama :11434 with its model list). Loopback only. |
| `zoth_pull_tool` | Shallow `git clone` (or `git pull --ff-only`) of one published catalog repo from github.com into `./tools/<repo>` or a directory you choose. Refuses to overwrite non-git directories. |

Bundled skill: `zoth:zoth-studio` (pick a Studio tool, hand over its link, check local services).

## Install

```bash
hermes plugins install https://github.com/<owner>/hermes-zoth
hermes plugins enable zoth
```

To run all of Zoth Studio locally: `npx @nullaitech/zoth studio` (http://127.0.0.1:3000).

## Disclosures

- **Network:** `zoth_studio_tool` with `check_live` makes one HTTPS GET to `zoth.nullai.tech`. `zoth_pull_tool` runs `git` against `github.com`. `zoth_status` connects only to `127.0.0.1`. No telemetry.
- **Shell:** `zoth_pull_tool` runs `git clone` / `git pull` as a subprocess (fixed argv, no shell), only for repos in the bundled catalog.
- **Files:** writes only into the clone destination. Reads nothing outside the plugin directory.
- No credentials, no background processes, no self-updating.

## Tests

```bash
python -m pytest -c tests/pytest.ini --rootdir tests tests
hermes plugins validate . --install-deps
```

MIT License.
