"""Tool schemas for the Zoth plugin."""

STUDIO_SEARCH = {
    "name": "zoth_studio_search",
    "description": (
        "Find tools in Zoth Studio (https://zoth.nullai.tech), a free, open-access collection of "
        "85 in-browser and local CLI developer, security, agent-safety, media, and creator tools by "
        "NullAITech. Offline: searches a bundled catalog. Returns id, name, category, description, "
        "version, execution_type, local_port, Studio page URL, and GitHub source. An empty query "
        "lists everything; results are ranked by keyword matches."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words to match against name, id, category and description."},
            "category": {
                "type": "string",
                "description": "Optional category filter, e.g. 'Security & Recon' or family prefix 'security'. See returned categories list.",
            },
            "execution_type": {
                "type": "string",
                "description": "Optional execution type filter: 'browser', 'local_cli', 'webgpu', or 'hybrid'.",
            },
            "limit": {"type": "integer", "description": "Max results (default 10, min 1, max 100)."},
        },
        "required": [],
    },
}

STUDIO_TOOL = {
    "name": "zoth_studio_tool",
    "description": (
        "Get details for one Zoth Studio tool by id or friendly name (from zoth_studio_search): "
        "Studio URL, GitHub repo, execution_type, local_port, `npx @nullaitech/zoth pull <repo>` "
        "command (NullAITech repos only), and source flags (source_owner, source_repo, third_party, "
        "monorepo). check_live=true makes one HTTPS GET request to zoth.nullai.tech without following "
        "cross-host or scheme-changing redirects. Unknown ids return did_you_mean suggestions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string", "description": "Tool id or friendly name from zoth_studio_search, e.g. 'regex-droid-builder'."},
            "check_live": {"type": "boolean", "description": "HTTP GET the Studio page and report status (default false)."},
        },
        "required": ["tool_id"],
    },
}

STATUS = {
    "name": "zoth_status",
    "description": (
        "Check which Zoth services are running on 127.0.0.1: Zoth Studio UI (:3000), neuro memory "
        "daemon (:8094), agent and security services (:8095-8106, including bridge :8102), "
        "Chronicle memory vault (:8161), Zoth Bot OS (:8190), vault (:8787), WebGen (:5173), and "
        "Ollama (:11434, with installed model names). up=true indicates a TCP connection was accepted "
        "on 127.0.0.1. Read-only, loopback-only, no proxies or redirects."
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

BRIDGE_POST = {
    "name": "zoth_bridge_post",
    "description": (
        "POST a structured message, progress update, audit report, or handoff to the local "
        "Sovereign Agent Bridge at http://127.0.0.1:8102/api/broadcast (or ZOTH_BRIDGE_URL if set "
        "to a loopback address). Loopback-only, no proxies, no redirects."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sender": {"type": "string", "description": "Sender agent handle (e.g. 'hermes-builder', 'hermes-auditor')."},
            "recipient": {"type": "string", "description": "Target agent or 'broadcast' (default 'broadcast')."},
            "topic": {"type": "string", "description": "Short topic slug (e.g. 'zothos-upgrade', 'seo-audit')."},
            "body": {"type": "string", "description": "Message or markdown report body."},
        },
        "required": ["body"],
    },
}

ECOSYSTEM_TARGETS = {
    "name": "zoth_ecosystem_targets",
    "description": (
        "Inspect the 6 Zoth / NullAI ecosystem products (ZothOS, ZothOS Lite, ZothNet, Zoth Studio, "
        "1nc0gn30 / World of Zoth, and NullAI Platform), returning resolved local workspace paths "
        "(under ZOTH_WORKSPACE_ROOT or ~/NullAITech), GitHub repositories, production domains, "
        "existing local checkouts, and SEO/AEO file presence (robots.txt, sitemap.xml, llms.txt)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product": {
                "type": "string",
                "description": "Optional filter: 'zothos', 'zothos-lite', 'zothnet', 'zoth-studio', '1nc0gn30', or 'nullai'. Empty lists all 6.",
            }
        },
        "required": [],
    },
}

GROWTH_DIRECTORIES = {
    "name": "zoth_growth_directories",
    "description": (
        "List launch directories, developer communities, blogs, and GitHub Awesome Lists for "
        "distributing ZothOS, ZothOS Lite, ZothNet, Zoth Studio, and hermes-zoth, returning "
        "submission URLs, channel types, status, and resolved submission copy paths under "
        "ZOTH_GROWTH_HUB_DIR (or ~/NullAITech/growth-distribution)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_type": {
                "type": "string",
                "description": "Optional filter: 'directory', 'awesome-list', 'community', or 'blog'.",
            }
        },
        "required": [],
    },
}
