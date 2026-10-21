"""Tool schemas for the Zoth plugin."""

STUDIO_SEARCH = {
    "name": "zoth_studio_search",
    "description": (
        "Search the Zoth Studio tool catalog (https://zoth.nullai.tech, by NullAITech). "
        "Returns matching tools with their Studio page URL, GitHub source and category. "
        "Use when the user wants a Zoth Studio tool (regex builder, JWT inspector, PWA manifest "
        "builder, cron studio, security sentinels, POD/e-commerce connectors, etc.). "
        "Empty query lists every tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words to match against name, id, category and description."},
            "category": {"type": "string", "description": "Optional exact category filter, e.g. 'Security'."},
            "limit": {"type": "integer", "description": "Max results (default 10, max 62)."},
        },
        "required": [],
    },
}

STUDIO_TOOL = {
    "name": "zoth_studio_tool",
    "description": (
        "Get one Zoth Studio tool by id: its in-browser Studio URL to hand the user, GitHub repo, "
        "and the `npx @nullaitech/zoth pull` command. Set check_live=true to confirm the page "
        "answers on zoth.nullai.tech."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string", "description": "Tool id from zoth_studio_search, e.g. 'regex-droid-builder'."},
            "check_live": {"type": "boolean", "description": "HTTP GET the Studio page and report status (default false)."},
        },
        "required": ["tool_id"],
    },
}

STATUS = {
    "name": "zoth_status",
    "description": (
        "Probe local Zoth / ZOTHOS services on 127.0.0.1 (memory daemon, agent bridge, vault, "
        "agent sentinels, Zoth Studio UI on :3000, Ollama with its local models) and report "
        "which are up. Loopback only; nothing leaves the machine."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

PULL_TOOL = {
    "name": "zoth_pull_tool",
    "description": (
        "git clone (shallow) one published Zoth/NullAITech tool repo from the catalog into a local "
        "directory, or fast-forward it if already cloned. Only catalog repos on github.com are allowed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string", "description": "Tool id from zoth_studio_search."},
            "dest_dir": {"type": "string", "description": "Parent directory (default ./tools). The repo goes in <dest_dir>/<repo>."},
        },
        "required": ["tool_id"],
    },
}
