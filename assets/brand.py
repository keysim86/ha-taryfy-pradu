"""Generator brandu integracji: ikona (tarcza doby ze strefami + błyskawica) i logo z napisem.

Uruchom z katalogu repozytorium:  python3 assets/brand.py
Wymaga: PyMuPDF (render SVG), Pillow, fontTools + brotli (font WOFF2 -> TTF).
Wynik: custom_components/taryfy_pradu/brand/{icon,logo,dark_logo}[@2x].png i assets/ikona.svg.
Font: Bricolage Grotesque (SIL OFL 1.1, assets/fonts/OFL-bricolagegrotesque.txt).
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import fitz  # PyMuPDF
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

KATALOG = Path(__file__).resolve().parent
WYJSCIE = KATALOG.parent / "custom_components" / "taryfy_pradu" / "brand"

# kolory stref jak w panelu Hearth (noc / pozaszczyt / szczyt)
NOC, POZA, SZCZYT = "#6a55c9", "#008c82", "#b8501c"
# plan G13s zimą: (od, do, kolor) w godzinach
PLAN = [(21, 31, NOC), (7, 10, SZCZYT), (10, 15, POZA), (15, 21, SZCZYT)]


def _luk(cx: float, cy: float, r: float, od_h: float, do_h: float) -> str:
    """Łuk tarczy 24 h (0:00 u góry, zgodnie z zegarem)."""
    a1 = math.radians(od_h / 24 * 360 - 90)
    a2 = math.radians(do_h / 24 * 360 - 90)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
    duzy = 1 if (do_h - od_h) > 12 else 0
    return f"M{x1:.2f} {y1:.2f} A{r} {r} 0 {duzy} 1 {x2:.2f} {y2:.2f}"


def ikona_svg() -> str:
    cx = cy = 128
    r, grub, przerwa = 98, 30, 0.35  # przerwa między strefami w godzinach
    luki = "\n".join(
        f'  <path d="{_luk(cx, cy, r, od + przerwa / 2, do - przerwa / 2)}" fill="none" '
        f'stroke="{kolor}" stroke-width="{grub}" stroke-linecap="butt"/>'
        for od, do, kolor in PLAN
    )
    kreski = "\n".join(
        f'  <line x1="{cx + 64 * math.cos(math.radians(h * 15 - 90)):.2f}" '
        f'y1="{cy + 64 * math.sin(math.radians(h * 15 - 90)):.2f}" '
        f'x2="{cx + 72 * math.cos(math.radians(h * 15 - 90)):.2f}" '
        f'y2="{cy + 72 * math.sin(math.radians(h * 15 - 90)):.2f}" '
        f'stroke="#9aa3b2" stroke-width="5" stroke-linecap="round"/>'
        for h in (0, 6, 12, 18)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="blysk" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffd27a"/>
      <stop offset="1" stop-color="#ff8a3d"/>
    </linearGradient>
  </defs>
{luki}
{kreski}
  <path d="M142 58 L92 136 H124 L110 198 L166 112 H132 Z" fill="#ffb03a"
        stroke="#cf4f17" stroke-width="6" stroke-linejoin="round"/>
</svg>
"""


def _png_z_svg(svg: str, bok: int) -> Image.Image:
    doc = fitz.open(stream=svg.encode(), filetype="svg")
    strona = doc[0]
    skala = bok / strona.rect.width
    pix = strona.get_pixmap(matrix=fitz.Matrix(skala, skala), alpha=True)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")


class Pismo:
    """Napis z dwóch podzbiorów fontu (latin + latin-ext) -- znak po znaku z tego, który go ma."""

    def __init__(self, rozmiar: int, waga: int) -> None:
        self.czesci = []
        for nazwa in ("bricolage-grotesque-var-latin.woff2", "bricolage-grotesque-var-latin-ext.woff2"):
            tt = TTFont(KATALOG / "fonts" / nazwa)
            tt.flavor = None
            bufor = io.BytesIO()
            tt.save(bufor)
            font = ImageFont.truetype(io.BytesIO(bufor.getvalue()), rozmiar)
            try:
                osie = font.get_variation_axes()
                wartosci = [
                    waga if b"eight" in (o.get("name") or b"") else o.get("default", o["minimum"])
                    for o in osie
                ]
                font.set_variation_by_axes(wartosci)
            except OSError:
                pass
            self.czesci.append((set(tt.getBestCmap()), font))

    def _font(self, znak: str) -> ImageFont.FreeTypeFont:
        for cmap, font in self.czesci:
            if ord(znak) in cmap:
                return font
        return self.czesci[0][1]

    def szerokosc(self, tekst: str) -> float:
        return sum(self._font(z).getlength(z) for z in tekst)

    def rysuj(self, rys: ImageDraw.ImageDraw, xy: tuple[float, float], tekst: str, kolor: str) -> None:
        x, y = xy
        for z in tekst:
            f = self._font(z)
            rys.text((x, y), z, font=f, fill=kolor, anchor="ls")
            x += f.getlength(z)


def logo(szer: int, wys: int, ciemne: bool) -> Image.Image:
    k = wys / 128
    obraz = Image.new("RGBA", (szer, wys), (0, 0, 0, 0))
    ik = _png_z_svg(ikona_svg(), int(112 * k))
    obraz.alpha_composite(ik, (int(6 * k), int(8 * k)))
    rys = ImageDraw.Draw(obraz)
    tytul = Pismo(int(50 * k), 700)
    podpis = Pismo(int(21 * k), 500)
    x = 128 * k
    tytul.rysuj(rys, (x, 66 * k), "Taryfy prądu", "#eef1f6" if ciemne else "#1d2430")
    podpis.rysuj(rys, (x + 2 * k, 98 * k), "strefy · ceny · koszty", "#9aa3b2" if ciemne else "#5b6474")
    return obraz


def main() -> None:
    WYJSCIE.mkdir(parents=True, exist_ok=True)
    svg = ikona_svg()
    (KATALOG / "ikona.svg").write_text(svg)
    _png_z_svg(svg, 256).save(WYJSCIE / "icon.png", optimize=True)
    _png_z_svg(svg, 512).save(WYJSCIE / "icon@2x.png", optimize=True)
    logo(448, 128, False).save(WYJSCIE / "logo.png", optimize=True)
    logo(896, 256, False).save(WYJSCIE / "logo@2x.png", optimize=True)
    logo(448, 128, True).save(WYJSCIE / "dark_logo.png", optimize=True)
    logo(896, 256, True).save(WYJSCIE / "dark_logo@2x.png", optimize=True)
    print("zapisano:", ", ".join(sorted(p.name for p in WYJSCIE.glob("*.png"))))


if __name__ == "__main__":
    main()
