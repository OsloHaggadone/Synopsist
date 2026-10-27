"""Draw the Home Screen icon of the public iPhone app (player/images/app-icon-*.png, named in
player/manifest.webmanifest and index.html): the artist's profile picture as a big diamond, nearly
corner to corner, with a thin blue frame, on the night's dark blue. (The private copy draws its own,
on the light side's pale blue, so the two apps can sit side by side on the Home Screen.)

Run it again after changing player/images/profile.jpg:  python scripts/make_app_icons.py
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist.config import PLAYER_DIR  # noqa: E402

SIZES = (180, 192, 512)  # iPhones' Home Screen; the manifest's two
NIGHT = (5, 11, 21)  # --bg, dark side (player/style.css)
FRAME = (67, 171, 245)  # --accent, dark side


def icon(picture: Image.Image, size: int) -> Image.Image:
    big = size * 4  # drawn four times bigger, then scaled down, for smooth edges
    middle, radius = big / 2, big * 0.45
    canvas = Image.new("RGB", (big, big), NIGHT)
    art = picture.resize((round(2 * radius), round(2 * radius)), Image.LANCZOS)
    mask = Image.new("L", art.size, 0)
    ImageDraw.Draw(mask).polygon([(radius, 0), (2 * radius, radius), (radius, 2 * radius), (0, radius)], fill=255)
    canvas.paste(art, (round(middle - radius), round(middle - radius)), mask)
    frame = radius * 1.08
    ImageDraw.Draw(canvas).polygon([(middle, middle - frame), (middle + frame, middle), (middle, middle + frame),
                                    (middle - frame, middle)], outline=FRAME, width=max(2, big // 160))
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    picture = Image.open(PLAYER_DIR / "images" / "profile.jpg").convert("RGB")
    for size in SIZES:
        path = PLAYER_DIR / "images" / f"app-icon-{size}.png"
        icon(picture, size).save(path, optimize=True)
        print(f"{path} ({path.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main()
