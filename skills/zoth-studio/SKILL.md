---
name: zoth-studio
description: Search the 85-tool Zoth Studio catalog, check local ZOTHOS services, pull public tool repos, and post updates to the local Sovereign Agent Bridge.
---

# Zoth Studio + ZOTHOS

1. Call `zoth_studio_search` with task keywords (e.g. `"regex"`, `"jwt"`, `"comfy"`, `"bot os"`), optional `category`, or optional `execution_type` (`"browser"`, `"local_cli"`, `"webgpu"`, `"hybrid"`).
2. Call `zoth_studio_tool` on the best match and give the user its `studio_url`. Browser tools run directly at `zoth.nullai.tech`; `local_cli` tools report their `local_port` when applicable (e.g. `zoth-bot-os` on `:8190`).
3. If the user wants source locally, offer `zoth_pull_tool` (clones published NullAITech/1nc0gn30 repos under `<HERMES_HOME>/plugin-data/zoth/tools`) or `npx @nullaitech/zoth studio` to run Studio on `http://127.0.0.1:3000`.
4. On ZOTHOS or a local Zoth install, run `zoth_status` to verify which loopback services (Studio `:3000`, memory `:8094`, agent/security suite `:8095-8106`, Chronicle vault `:8161`, Bot OS `:8190`, Ollama `:11434`) are accepting connections.
5. Use `zoth_bridge_post` to broadcast structured status updates to the local Sovereign Agent Bridge (`http://127.0.0.1:8102/api/broadcast`).
6. Use `zoth_ecosystem_targets` and `zoth_growth_directories` to inspect the 6 Zoth/NullAI repositories and distribution directory channels.

If a result has `third_party: true`, note it is an external repository and share the GitHub link instead of pulling it. If `monorepo: true`, tell the user the pull clones the parent repository.

Never claim a local service is running unless `zoth_status` reports `up: true` for its port.
