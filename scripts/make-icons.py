"""Stu's browser icons from the header logo: the baby's face, lines made
heavier so they survive small sizes, on the header's cream circle with its
red ring.

    uv run --no-project --with pillow python scripts/make-icons.py \
        web/public/assets/figma/stu-logo.png web/src/app
"""
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageOps

src, out = sys.argv[1], sys.argv[2]
CREAM, RED = (255, 248, 239, 255), (199, 71, 50, 255)

logo = Image.open(src).convert("RGBA")
# Ink = the dark lines; white and transparent are background.
gray = Image.new("RGBA", logo.size, (255, 255, 255, 255))
gray.alpha_composite(logo)
ink = ImageOps.invert(gray.convert("L")).point(lambda v: 255 if v > 90 else 0)
box = ink.getbbox()
pad = 30
box = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)

def icon(size, bolder, ring=0.07, fill=0.70):
    mask = ink.filter(ImageFilter.MaxFilter(bolder)) if bolder > 1 else ink
    face = mask.crop(box)
    side = max(face.size)
    square = Image.new("L", (side, side), 0)
    square.paste(face, ((side - face.width) // 2, (side - face.height) // 2))
    big = 1024
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    width = int(big * ring)
    draw.ellipse((0, 0, big - 1, big - 1), fill=RED)
    draw.ellipse((width, width, big - 1 - width, big - 1 - width), fill=CREAM)
    inner = int(big * fill)
    lines = square.resize((inner, inner), Image.LANCZOS)
    ink_layer = Image.new("RGBA", (inner, inner), (53, 37, 31, 255))
    offset = (big - inner) // 2
    canvas.paste(ink_layer, (offset, offset + int(big * 0.015)), lines)
    return canvas.resize((size, size), Image.LANCZOS)

icon(512, 9).save(f"{out}/icon.png")
small = [icon(s, 27, ring=0.075, fill=0.78) for s in (16, 32, 48)]
small[-1].save(f"{out}/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=small[:-1])
# Apple icons are drawn square with rounded corners by the device: fill it.
apple = Image.new("RGBA", (180, 180), CREAM)
apple.alpha_composite(icon(180, 11, ring=0.0, fill=0.82))
apple.convert("RGB").save(f"{out}/apple-icon.png")
