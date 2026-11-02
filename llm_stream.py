"""Small dependency-free helpers for OpenAI-compatible streamed responses."""
import json


def stream_content_piece(line: str) -> str | None:
    """Extract text from one OpenAI-compatible SSE or JSON response line."""
    if isinstance(line, str) and line.startswith("data:"):
        line = line[5:].strip()
    if line == "[DONE]":
        return None
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    choice = (event.get("choices") or [{}])[0]
    delta = choice.get("delta") or {}
    piece = delta.get("content")
    if piece is None:
        piece = (choice.get("message") or {}).get("content")
    if piece is None:
        piece = choice.get("text")
    return piece if isinstance(piece, str) else None
