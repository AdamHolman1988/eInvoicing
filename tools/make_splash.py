"""Render the startup splash image shown by the exe while it unpacks (PyInstaller --splash).

python tools/make_splash.py  ->  assets/splash.png
"""
import pathlib

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parents[1] / "assets" / "splash.png"
W, H = 520, 220
BLUE, GREEN, WHITE = (40, 87, 175), (121, 255, 140), (255, 255, 255)


def font(size, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), BLUE)
d = ImageDraw.Draw(img)
d.rectangle([0, H - 8, W, H], fill=GREEN)
d.text((32, 40), "MsgValidator", font=font(38, True), fill=WHITE)
d.text((34, 98), "Validace a gap analýza e-fakturačních zpráv", font=font(17), fill=WHITE)
d.text((34, 128), "EDIFACT · UBL · CII · Peppol BIS 3 · SK CIUS · KoSIT", font=font(14), fill=(210, 222, 245))
OUT.parent.mkdir(exist_ok=True)
img.save(OUT)
print(OUT)
