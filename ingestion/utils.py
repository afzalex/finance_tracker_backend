"""Shared regex helpers used by the classifier and parser."""

from __future__ import annotations

import re
from typing import Dict, Optional


def match_regex(
    pattern: Optional[str],
    text: str,
    *,
    empty_means_match: bool = True,
) -> Optional[bool]:
    """Evaluate a regex pattern against text.

    Returns:
        True   — pattern matched (or pattern is empty and empty_means_match=True).
        False  — pattern did not match.
        None   — pattern is empty/None and empty_means_match=False (no constraint).
    """
    if not pattern or not str(pattern).strip():
        return True if empty_means_match else None
    return re.search(pattern, text or "", re.IGNORECASE | re.DOTALL) is not None


def merge_extract_groups(
    body_match: Optional[re.Match],
    subject_match: Optional[re.Match],
    snippet_match: Optional[re.Match],
) -> Dict[str, str]:
    """Merge named groups from body, subject, snippet matches.

    Precedence: body > subject > snippet.
    Empty strings are ignored; only non-empty values are written.
    """
    out: Dict[str, str] = {}
    for match in (body_match, subject_match, snippet_match):
        if not match:
            continue
        for name, val in match.groupdict().items():
            if val is not None:
                v = str(val).strip()
                if v and name not in out:
                    out[name] = v
    return out
