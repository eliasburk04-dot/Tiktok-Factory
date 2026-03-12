from __future__ import annotations

import re

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", re.IGNORECASE)
_RAW_URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MARKDOWN_DECORATION_PATTERN = re.compile(r"[*_`~>#]+")
_NAVIGATION_SEPARATOR_PATTERN = re.compile(r"\s*(?:[-|/]|\\-)\s*")
_NAVIGATION_FRAGMENT_PATTERN = re.compile(r"(?:part|chapter|episode|pt)\s+[ivxlcdm0-9]+", re.IGNORECASE)


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "item"


def first_sentence(value: str) -> str:
    for separator in [". ", "! ", "? "]:
        if separator in value:
            return value.split(separator)[0].strip()
    return value.strip()


def summarize_text(value: str, word_limit: int = 18) -> str:
    words = value.replace("\n", " ").split()
    return " ".join(words[:word_limit]).strip()


def chunk_words(value: str, chunk_size: int = 5) -> list[str]:
    words = value.split()
    return [" ".join(words[index : index + chunk_size]) for index in range(0, len(words), chunk_size)]


def normalize_spacing(value: str) -> str:
    return " ".join(value.replace("\n", " ").split()).strip()


def sanitize_narration_text(value: str, *, drop_navigation_lines: bool = False) -> str:
    cleaned_lines: list[str] = []
    for raw_line in value.splitlines():
        cleaned_line = _sanitize_narration_line(raw_line)
        if not cleaned_line:
            continue
        if drop_navigation_lines and _looks_like_navigation_line(cleaned_line, raw_line):
            continue
        cleaned_lines.append(cleaned_line)
    if not cleaned_lines:
        return ""
    return "\n".join(cleaned_lines).strip()


def _sanitize_narration_line(value: str) -> str:
    cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", value)
    cleaned = _RAW_URL_PATTERN.sub(" ", cleaned)
    cleaned = cleaned.replace("\\-", "-").replace("\\", " ")
    cleaned = _MARKDOWN_DECORATION_PATTERN.sub("", cleaned)
    cleaned = cleaned.replace("[", " ").replace("]", " ").replace("(", " ").replace(")", " ")
    return normalize_spacing(cleaned)


def _looks_like_navigation_line(cleaned_line: str, raw_line: str) -> bool:
    if "http" not in raw_line.lower() and "www." not in raw_line.lower():
        return False
    fragments = [fragment.strip(" .,!?:;") for fragment in _NAVIGATION_SEPARATOR_PATTERN.split(cleaned_line) if fragment.strip()]
    return len(fragments) >= 2 and all(_NAVIGATION_FRAGMENT_PATTERN.fullmatch(fragment) for fragment in fragments)
