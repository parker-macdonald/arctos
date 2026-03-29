"""Validation for match names and team pseudonyms (reserved punctuation for parsing/exports)."""

from __future__ import annotations

from typing import Optional


def match_name_char_error(name: str) -> Optional[str]:
    """Return an error message if ``name`` contains forbidden characters, else ``None``."""
    if "," in name:
        return 'Match names cannot contain ",".'
    if "::" in name:
        return 'Match names cannot contain "::".'
    return None


def team_pseudonym_char_error(pseudonym: str) -> Optional[str]:
    """Return an error message if ``pseudonym`` contains forbidden characters, else ``None``."""
    if "," in pseudonym:
        return 'Team pseudonyms cannot contain ",".'
    if "::" in pseudonym:
        return 'Team pseudonyms cannot contain "::".'
    return None
