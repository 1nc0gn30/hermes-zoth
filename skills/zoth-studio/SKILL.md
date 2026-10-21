---
name: zoth-studio
description: Find the right Zoth Studio tool for a task, hand the user its in-browser link, and check local ZOTHOS services.
---

# Zoth Studio + ZOTHOS

1. Call `zoth_studio_search` with the user's task words (e.g. "regex", "jwt", "manifest", "cron").
2. Call `zoth_studio_tool` on the best match and give the user its `studio_url`. Studio tools run in the browser at zoth.nullai.tech.
3. If they want it locally, offer `zoth_pull_tool` (clones the public repo) or `npx @nullaitech/zoth studio` to run all of Studio on http://127.0.0.1:3000.
4. On a ZOTHOS / local Zoth install, `zoth_status` shows which loopback services and Ollama models are up.

Do not claim a tool is running locally unless `zoth_status` says its port is up.
