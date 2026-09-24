"""Sphinx configuration for the IMAS SimDB MCP documentation (Read the Docs)."""

import simdb_mcp

project = "IMAS SimDB MCP"
author = "ITER Organization"
copyright = "2026, ITER Organization"
release = simdb_mcp.__version__
version = ".".join(release.split(".")[:2])

extensions = ["myst_parser", "sphinx_immaterial"]
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3
source_suffix = {".md": "markdown"}
exclude_patterns = ["_build"]

html_theme = "sphinx_immaterial"
html_title = "IMAS SimDB MCP"
html_static_path = ["_static"]
html_theme_options = {
    "palette": [
        {
            "media": "(prefers-color-scheme: light)",
            "scheme": "default",
            "primary": "blue",
            "accent": "light-blue",
            "toggle": {"icon": "material/lightbulb-outline", "name": "Switch to dark mode"},
        },
        {
            "media": "(prefers-color-scheme: dark)",
            "scheme": "slate",
            "primary": "blue",
            "accent": "light-blue",
            "toggle": {"icon": "material/lightbulb", "name": "Switch to light mode"},
        },
    ],
    "features": ["navigation.top", "toc.follow", "content.code.copy", "search.share"],
    "repo_url": "https://github.com/prasad-sawantdesai/IMAS-SimDB-MCP",
    "repo_name": "IMAS-SimDB-MCP",
}
