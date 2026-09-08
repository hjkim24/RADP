"""Overlay device labels on the processed testbed photo (fig_testbed.jpg -> fig_testbed_labeled.jpg)."""
from PIL import Image, ImageDraw, ImageFont
im = Image.open("fig_testbed.jpg").convert("RGB"); W, H = im.size
draw = ImageDraw.Draw(im)
try: font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 34)
except OSError: font = ImageFont.load_default()
LABELS = [  # (text, x_center, y_center) in image pixels (2000 x 1080)
 ("ao-1", 330, 205), ("ax-1", 120, 545), ("ao-2", 175, 800),
 ("on-1", 655, 215), ("on-2", 835, 810), ("on-3", 1065, 810), ("on-4", 1320, 810), ("on-5", 1570, 810), ("on-6", 1845, 810),
 ("switch", 1280, 270),
]
for text, cx, cy in LABELS:
    l, t, r, b = draw.textbbox((0, 0), text, font=font); w, h = r - l, b - t
    pad = 8
    box = (cx - w/2 - pad, cy - h/2 - pad, cx + w/2 + pad, cy + h/2 + pad)
    draw.rounded_rectangle(box, radius=8, fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    draw.text((cx - w/2 - l, cy - h/2 - t), text, font=font, fill=(0, 0, 0))
im.save("fig_testbed_labeled.jpg", quality=88, optimize=True); print("wrote fig_testbed_labeled.jpg", im.size)
