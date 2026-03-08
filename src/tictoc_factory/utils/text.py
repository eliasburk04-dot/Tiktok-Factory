from __future__ import annotations

import re


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
