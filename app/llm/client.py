"""Thin wrapper around the google-genai SDK for calling Gemma 4.

All instructions go inside the user content (Gemma doesn't rely on a system-instruction field).
"""
import asyncio
import logging
import re
import time

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

_client: genai.Client | None = None


class LLMError(Exception):
    """The model failed or returned something we could not use."""


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _contents(prompt: str, image: bytes | None) -> list:
    parts = []
    if image:
        parts.append(types.Part.from_bytes(data=image, mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text=prompt))
    return [types.Content(role="user", parts=parts)]


async def generate_text(prompt: str, image: bytes | None = None, temperature: float = 0.6,
                        purpose: str = "text") -> str:
    # Minimal thinking: ~1 s per chat reply instead of ~10-15 s, and it read the sample routine
    # just as accurately in our tests.
    config = types.GenerateContentConfig(temperature=temperature,
                                         thinking_config=types.ThinkingConfig(thinking_level="minimal"))
    start = time.monotonic()
    for attempt in range(2):
        try:
            resp = await asyncio.wait_for(
                get_client().aio.models.generate_content(
                    model=settings.GEMMA_MODEL,
                    contents=_contents(prompt, image),
                    config=config,
                ),
                timeout=90,
            )
            break
        except errors.ServerError as e:   # occasional 500/503 from the API: retry once
            log.warning("LLM %s server error (attempt %d): %s", purpose, attempt + 1, e)
            if attempt:
                raise LLMError(str(e)) from e
            await asyncio.sleep(2)
        except Exception as e:  # network, quota (429), timeout...
            log.warning("LLM %s failed: %s", purpose, e)
            raise LLMError(str(e)) from e
    usage = getattr(resp, "usage_metadata", None)
    log.info("LLM %s %.1fs tokens=%s", purpose, time.monotonic() - start,
             getattr(usage, "total_token_count", "?"))
    if not resp.text:
        raise LLMError("empty response")
    return resp.text


def extract_json(text: str) -> str:
    """Pull the JSON object out of a model reply (handles ``` fences and chatter around it)."""
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    return text[start:end + 1]


async def generate_json(prompt: str, schema: type[BaseModel], image: bytes | None = None,
                        purpose: str = "json") -> BaseModel:
    """Ask for JSON, validate it with Pydantic, retry once with the error if it is invalid."""
    current = prompt
    for attempt in range(2):
        raw = await generate_text(current, image=image, temperature=0.3, purpose=purpose)
        try:
            return schema.model_validate_json(extract_json(raw))
        except (ValueError, ValidationError) as e:
            log.warning("LLM %s invalid JSON (attempt %d): %s", purpose, attempt + 1, e)
            current = (f"{prompt}\n\nYour previous output was invalid: {str(e)[:500]}\n"
                       "Return ONLY valid JSON.")
    raise LLMError("model returned invalid JSON twice")
