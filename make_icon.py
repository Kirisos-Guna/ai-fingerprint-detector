"""Generates assets/icon.ico programmatically (fingerprint-dot motif)."""
from PIL import Image, ImageDraw
from pathlib import Path

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

cx = cy = S // 2
NAVY = (15, 23, 42, 255)
CYAN = (34, 211, 238, 255)
BLUE = (59, 130, 246, 255)
GREEN = (52, 211, 153, 255)

# Rounded-square dark background
d.rounded_rectangle([16, 16, S - 16, S - 16], radius=180, fill=NAVY)

# Concentric fingerprint arcs (partial circles with gaps, like ridges)
import math
for i, (r, color, width) in enumerate([
    (120, CYAN, 34), (200, BLUE, 34), (280, CYAN, 34),
    (360, BLUE, 34), (440, GREEN, 34),
]):
    gap = math.radians(40 + 12 * i)
    d.arc([cx - r, cy - r, cx + r, cy + r], start=gap, end=360 - gap,
          fill=color, width=width)

# Center dot
d.ellipse([cx - 60, cy - 60, cx + 60, cy + 60], fill=CYAN)

out = Path("assets")
out.mkdir(exist_ok=True)
img.resize((256, 256), Image.LANCZOS).save(out / "icon_preview.png")
img.save(out / "icon.ico",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                (128, 128), (256, 256)])
print("icon written:", (out / "icon.ico").stat().st_size, "bytes")
