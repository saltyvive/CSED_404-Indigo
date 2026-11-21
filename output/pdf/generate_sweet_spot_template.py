#!/usr/bin/env python3
"""Generate the 1:1 A4 sweet spot print template. Requires reportlab."""

import argparse
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


PAGE_WIDTH_MM, PAGE_HEIGHT_MM = 297, 210
LEFT_MM, BOTTOM_MM = 115, 55
WIDTH_MM, HEIGHT_MM = 50, 30
PITCH_MM = 2.5
DOT_DIAMETER_MM = 0.45
BORDER_WIDTH_MM = 0.20
FILENAME = "sweet_spot_50x30mm_pitch2p5mm_a4_landscape.pdf"


def generate(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(
        str(output),
        pagesize=(PAGE_WIDTH_MM * mm, PAGE_HEIGHT_MM * mm),
        pageCompression=1,
        invariant=1,
    )
    pdf.setTitle("Sweet spot - 50 x 30 mm - 2.5 mm grid - A4 landscape")
    pdf.setAuthor("CSED 404 - Team Indigo")
    pdf.setSubject(
        "273 points; paper-bottom-left origin; x=115 mm, y=55 mm; print at 100%."
    )
    pdf.setViewerPreference("PrintScaling", "None")

    # Rectangle coordinates describe the stroke centerline. Boundary dot centers
    # lie on that same line; four corners are included exactly once.
    pdf.setStrokeColorRGB(1, 0, 0)
    pdf.setLineWidth(BORDER_WIDTH_MM * mm)
    pdf.setDash([])
    pdf.rect(LEFT_MM * mm, BOTTOM_MM * mm, WIDTH_MM * mm, HEIGHT_MM * mm,
             stroke=1, fill=0)
    pdf.setFillColorRGB(0, 0, 0)
    columns = round(WIDTH_MM / PITCH_MM) + 1
    rows = round(HEIGHT_MM / PITCH_MM) + 1
    for row in range(rows):
        for column in range(columns):
            pdf.circle(
                (LEFT_MM + column * PITCH_MM) * mm,
                (BOTTOM_MM + row * PITCH_MM) * mm,
                DOT_DIAMETER_MM / 2 * mm,
                stroke=0,
                fill=1,
            )

    pdf.showPage()
    pdf.save()
    print(f"Created {output}: {columns} x {rows} = {columns * rows} points")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name(FILENAME))
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()
