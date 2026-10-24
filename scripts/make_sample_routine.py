"""Draws docs/sample_routine.png from the invented demo routine, for testing photo upload.

    python scripts/make_sample_routine.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from demo_data import CLASS_NAME, ROUTINE

DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu"]
TIMES = ["09:00", "10:00", "10:30", "11:30", "12:00"]
CELL_W, CELL_H, HEAD_W, TOP = 230, 90, 90, 110


def font(size):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def main():
    w, h = HEAD_W + CELL_W * len(TIMES) + 20, TOP + CELL_H * len(DAYS) + 40
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 20), f"Class Routine - {CLASS_NAME} - Fall 2026 (SAMPLE DATA)", fill="black", font=font(28))
    for i, t in enumerate(TIMES):
        d.rectangle([HEAD_W + i * CELL_W, TOP - 40, HEAD_W + (i + 1) * CELL_W, TOP], outline="black", fill="#dde")
        d.text((HEAD_W + i * CELL_W + 10, TOP - 32), t, fill="black", font=font(20))
    for r, day in enumerate(DAYS):
        y = TOP + r * CELL_H
        d.rectangle([10, y, HEAD_W, y + CELL_H], outline="black", fill="#dde")
        d.text((20, y + 30), day, fill="black", font=font(22))
        for i in range(len(TIMES)):
            d.rectangle([HEAD_W + i * CELL_W, y, HEAD_W + (i + 1) * CELL_W, y + CELL_H], outline="black")
        for wd, start, end, course, code, room, _ in ROUTINE:
            if wd == day and start in TIMES:
                x = HEAD_W + TIMES.index(start) * CELL_W + 8
                d.text((x, y + 8), code, fill="black", font=font(18))
                d.text((x, y + 32), course[:24], fill="black", font=font(15))
                d.text((x, y + 56), f"{start}-{end}  Rm {room}", fill="#333", font=font(15))
    out = Path(__file__).resolve().parent.parent / "docs" / "sample_routine.png"
    out.parent.mkdir(exist_ok=True)
    img.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
