"""Zoth plugin for Hermes: Zoth Studio tool catalog + ZOTHOS local services."""

from pathlib import Path

from . import schemas, tools


def register(ctx):
    ctx.register_tool(name="zoth_studio_search", toolset="zoth", schema=schemas.STUDIO_SEARCH, handler=tools.studio_search)
    ctx.register_tool(name="zoth_studio_tool", toolset="zoth", schema=schemas.STUDIO_TOOL, handler=tools.studio_tool)
    ctx.register_tool(name="zoth_status", toolset="zoth", schema=schemas.STATUS, handler=tools.status)
    ctx.register_tool(name="zoth_pull_tool", toolset="zoth", schema=schemas.PULL_TOOL, handler=tools.pull_tool)
    skills = Path(__file__).parent / "skills"
    for child in sorted(skills.iterdir()):
        if (child / "SKILL.md").exists():
            ctx.register_skill(child.name, child / "SKILL.md")
