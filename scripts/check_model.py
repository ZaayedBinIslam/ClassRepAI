"""Run this first: lists Gemma models for your key and tests GEMMA_MODEL with text + image.

    python scripts/check_model.py
"""
import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm.client import generate_text, get_client  # noqa: E402


def test_image() -> bytes:
    img = Image.new("RGB", (320, 120), "white")
    ImageDraw.Draw(img).text((10, 40), "Sun 10:00 DBMS Room 305", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def main():
    if not settings.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is empty in .env")

    print("Gemma models available to this key:")
    for m in get_client().models.list():
        if "gemma" in m.name.lower():
            print("  ", m.name.removeprefix("models/"))

    if not settings.GEMMA_MODEL:
        sys.exit("\nSet GEMMA_MODEL in .env to one of the IDs above, then run again.")

    print(f"\nText test ({settings.GEMMA_MODEL}):")
    print(await generate_text("Reply with one short friendly sentence in Banglish."))

    print("\nImage test:")
    print(await generate_text("What text is written in this image? Answer briefly.", image=test_image()))

    print("\nJSON test:")
    print(await generate_text('Return ONLY this JSON with the value filled in: {"capital_of_bangladesh": ""}'))


if __name__ == "__main__":
    asyncio.run(main())
