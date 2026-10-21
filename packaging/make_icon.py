"""Genera packaging/traffiqui.ico (el mismo dibujo que el icono de la bandeja)."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), 56, fill=(224, 165, 38, 255))
d.ellipse((68, 68, S - 68, S - 68), outline=(23, 32, 43, 255), width=24)
d.ellipse((108, 108, S - 108, S - 108), fill=(23, 32, 43, 255))
out = Path(__file__).with_name("traffiqui.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"Icono: {out}")
