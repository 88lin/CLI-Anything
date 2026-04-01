"""
exa_backend.py — Exa API client wrapper.

Initialises the exa-py SDK client from EXA_API_KEY and exposes lightweight
helper functions used by the core modules.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from exa_py import Exa
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "exa-py is required: pip install exa-py"
    ) from exc


def get_client() -> Exa:
    """Return an authenticated Exa client.

    Raises:
        SystemExit: if EXA_API_KEY is not set in the environment.
    """
    api_key = os.environ.get("EXA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "EXA_API_KEY environment variable is not set.\n"
            "Get a free key at https://dashboard.exa.ai/api-keys"
        )
    return Exa(
        api_key=api_key,
        additional_headers={"x-exa-integration": "cli-anything"},
    )


def check_connectivity() -> dict[str, Any]:
    """Verify the API key is valid by running a minimal search.

    Returns a dict with keys: ok (bool), message (str).
    """
    try:
        client = get_client()
        client.search("test", num_results=1)
        return {"ok": True, "message": "API key valid — Exa reachable"}
    except RuntimeError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Exa API error: {exc}"}


def build_contents_param(
    content_mode: str,
    freshness: str = "smart",
) -> dict[str, Any] | None:
    """Translate CLI content/freshness flags into an exa-py `contents` dict.

    Args:
        content_mode: "text" | "highlights" | "summary" | "none"
        freshness:    "smart" | "always" | "never"

    Returns:
        A contents dict suitable for passing to exa.search() / exa.get_contents(),
        or None if content_mode is "none".
    """
    if content_mode == "none":  # noqa: SIM114
        return None

    contents: dict[str, Any] = {}

    if content_mode == "text":
        contents["text"] = {"max_characters": 10_000}
    elif content_mode == "highlights":
        contents["highlights"] = {"max_characters": 4_000}
    elif content_mode == "summary":
        contents["summary"] = True

    # Freshness maps to max_age_hours
    if freshness == "always":
        contents["max_age_hours"] = 0
    elif freshness == "never":
        contents["max_age_hours"] = -1
    # "smart" → omit max_age_hours (SDK default: cache + livecrawl fallback)

    return contents or None


# Category values accepted by the Exa API
VALID_CATEGORIES = {
    "company",
    "people",
    "research paper",
    "news",
    "personal site",
    "financial report",
}

# CLI slug → API value (hyphens to spaces for multi-word categories)
CATEGORY_SLUG_MAP: dict[str, str] = {
    "company": "company",
    "people": "people",
    "research-paper": "research paper",
    "news": "news",
    "personal-site": "personal site",
    "financial-report": "financial report",
}
