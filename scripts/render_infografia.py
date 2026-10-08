"""Exporta `docs/infografia.html` a PNG para incrustarla en el README.

No es una dependencia del proyecto: usa Playwright solo cuando se regenera.

  uv run --with playwright python -m scripts.render_infografia \\
      [--chromium /ruta/a/chrome]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path("docs/infografia.html")
OUT = Path("docs/infografia.png")
WIDTH = 1200


def render(chromium: str | None = None) -> Path:
    """Renderiza la pagina completa a PNG y devuelve la ruta del archivo."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chromium, args=["--no-sandbox"]
        )
        page = browser.new_page(
            viewport={"width": WIDTH, "height": 900}, device_scale_factor=1
        )
        page.goto(SRC.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT), full_page=True)
        browser.close()
    return OUT


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la linea de comandos."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chromium", help="ejecutable de Chromium a usar")
    args = p.parse_args(argv)
    out = render(args.chromium)
    print(f"{out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
