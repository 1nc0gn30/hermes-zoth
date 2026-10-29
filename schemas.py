"""Tool schemas for the Zoth plugin."""

STUDIO_SEARCH = {
    "name": "zoth_studio_search",
    "description": (
        "Find tools in Zoth Studio (https://zoth.nullai.tech), a free collection of in-browser "
        "developer, security, agent-safety and creator tools by NullAITech. Use this first whenever "
        "the user needs a utility such as a regex builder, JWT decoder, PWA manifest builder, cron "
        "expression helper, robots.txt auditor, prompt-injection firewall or POD/e-commerce connector. "
        "Offline: searches a bundled catalog. Returns id, name, category, description, the Studio "
        "page URL and the GitHub source. An empty query lists everything; results are ranked by "
        "keyword matches."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words to match against name, id, category and description."},
            "category": {"type": "string", "description": "Optional category filter, e.g. 'Security & Recon' or family prefix 'security'. See returned categories list."},
            "limit": {"type": "integer", "description": "Max results (default 10, min 1, max 100)."},
        },
        "required": [],
    },
}

STUDIO_TOOL = {
    "name": "zoth_studio_tool",
    "description": (
        "Get the details for one Zoth Studio tool by id (from zoth_studio_search): the Studio URL "
        "the user can open to use it in their browser, its GitHub repo, and the "
        "`npx @nullaitech/zoth pull <repo>` command (NullAITech repos only), and source flags: "
        "source_owner, third_party (repo is not by NullAITech) and monorepo (the repo holds the whole "
        "project, not just this tool). check_live=true makes one HTTPS request to zoth.nullai.tech and "
        "does not follow redirects to other hosts. Unknown ids return did_you_mean suggestions."
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
        "Check which Zoth services are running on this machine (ZOTHOS or any box with Zoth "
        "installed): Zoth Studio UI (:3000), neuro memory daemon (:8094), agent and security services "
        "(:8095-8106, including bridge :8102), vault (:8787), WebGen (:5173) and Ollama (:11434, "
        "with installed model names). up=true indicates a TCP connection was accepted on 127.0.0.1. "
        "Read-only and loopback-only; use it before telling the user a local Zoth service is available."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

PULL_TOOL = {
    "name": "zoth_pull_tool",
    "description": (
        "Download the source of one published Zoth Studio tool: shallow `git clone` from github.com "
        "into <HERMES_HOME>/plugin-data/zoth/<dest_dir>/<repo> (default dest_dir is tools), or "
        "`git pull --ff-only` if that checkout is already there. Returns destination path and git commit SHA. "
        "dest_dir is resolved under that plugin data directory, not the process working directory. "
        "Absolute paths and `..` segments that resolve anywhere else — including ~/.hermes/skills and "
        "~/.hermes/plugins — are refused. Only repos listed in the catalog are allowed, and existing "
        "non-git folders are never overwritten. Only NullAITech/1nc0gn30 repos are cloned; third-party "
        "repos return third_party_repo. git runs with a minimal environment, repo hooks disabled and "
        "file:// / ext:: transports blocked. Use when the user wants to run or modify a tool locally."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string", "description": "Tool id or friendly name from zoth_studio_search."},
            "dest_dir": {
                "type": "string",
                "description": (
                    "Directory under HERMES_HOME/plugin-data/zoth (default tools). "
                    "The repo is cloned to <that directory>/<repo>. "
                    "Absolute paths are accepted only when they resolve inside the same directory."
                ),
            },
            "ref": {
                "type": "string",
                "description": (
                    "Optional branch, tag, or full 40-character commit SHA. The checkout is detached at "
                    "that ref; calling again without ref moves it back to the default branch tip."
                ),
            },
        },
        "required": ["tool_id"],
    },
}
