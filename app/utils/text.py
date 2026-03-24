from __future__ import annotations


def normalize_text(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned

    cleaned = cleaned[0].upper() + cleaned[1:]
    if not cleaned.endswith((".", "!", "?")):
        cleaned += "."
    return cleaned
