"""Explicit live smoke check: python tests/smoke_live.py (uses Groq quota)."""
import io
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from api.ai import extract, rephrase

image = Image.new("RGB", (1100, 800), "white")
draw = ImageDraw.Draw(image)
try:
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 30)
except OSError:
    font = ImageFont.load_default(size=30)
for i, text in enumerate([
    "NORTHSTAR BROADBAND - FICTIONAL TEST BILL",
    "Bill date: 2026-10-01", "Currency: INR", "",
    "Monthly broadband plan                         999.00",
    "GST (18% on INR 999.00)                        179.82",
    "Entertainment add-on                           200.00", "",
    "TOTAL                                          1378.82",
]):
    draw.text((50, 50 + i * 65), text, fill="black", font=font)
out = io.BytesIO()
image.save(out, "PNG")
target = Path(__file__).resolve().parents[1] / "docs" / "sample-bill.png"
target.write_bytes(out.getvalue())
result = extract(out.getvalue(), False)
print("Vision extracted", len(result["lines"]), "lines; printed total:", result.get("total"))
assert len(result["lines"]) == 3
assert str(result["total"]) in ("1378.82",)
draft = "Hello.\n\nMy bill is INR 1378.82. Expected INR 1178.82. Difference INR 200.00.\n\nPlease clarify."
revised = rephrase(draft, "polite")
assert all(value in revised for value in ("1378.82", "1178.82", "200.00"))
print("Live rephrasing preserved all computed amounts.")
