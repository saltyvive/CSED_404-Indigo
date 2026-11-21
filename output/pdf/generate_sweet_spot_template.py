#!/usr/bin/env python3
"""Generate the 1:1 A4 sweet spot print template. Requires reportlab."""

import argparse
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


PAGE_WIDTH_MM, PAGE_HEIGHT_MM = 297, 210
LEFT_MM, BOTTOM_MM = 115, 55
WIDTH_MM, HEIGHT_MM = 50, 30
PITCH_MM = 2.5
DOT_DIAMETER_MM = 0.45
BORDER_WIDTH_MM = 0.20
FILENAME = "sweet_spot_50x30mm_pitch2p5mm_a4_landscape.pdf"


def generate(output: Path, font_path: Path) -> None:
    pdfmetrics.registerFont(TTFont("TemplateKorean", str(font_path)))
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

    def label(x_mm: float, y_mm: float, text: str, size: float = 8) -> None:
        pdf.setFont("TemplateKorean", size)
        pdf.drawString(x_mm * mm, y_mm * mm, text)

    pdf.setFillColorRGB(0.30, 0.30, 0.30)
    label(15, 193, "스윗 스팟 측정 도면", 12)
    label(15, 185, "A4 가로 297 × 210 mm  |  실제 크기 100%로 인쇄")
    label(15, 179, "영역 50 × 30 mm  |  점 간격 2.5 mm  |  21열 × 13행 = 273점 (경계 포함)")
    label(15, 173, "영역 좌하단: 용지 왼쪽에서 115 mm, 아래에서 55 mm")

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

    # Separate calibration rulers verify both print axes without adding marks
    # to the measurement region. Their lengths match the sweet spot dimensions.
    pdf.setStrokeColorRGB(0.35, 0.35, 0.35)
    pdf.setFillColorRGB(0.35, 0.35, 0.35)
    pdf.setLineWidth(0.15 * mm)
    pdf.line(20 * mm, 20 * mm, 70 * mm, 20 * mm)
    for x in (20, 45, 70):
        pdf.line(x * mm, 19 * mm, x * mm, 21 * mm)
    pdf.line(20 * mm, 20 * mm, 20 * mm, 50 * mm)
    for y in (20, 35, 50):
        pdf.line(19 * mm, y * mm, 21 * mm, y * mm)
    label(40, 15, "50 mm", 7)
    pdf.saveState()
    pdf.translate(16 * mm, 30 * mm)
    pdf.rotate(90)
    label(0, 0, "30 mm", 7)
    pdf.restoreState()
    label(85, 24, "인쇄 설정: 실제 크기 100% · 페이지 맞춤 / 자동 축소 끄기", 7.5)
    label(85, 18, "인쇄 후 기준선 길이와 용지 모서리 기준 오프셋을 확인하세요.", 7.5)

    pdf.showPage()
    pdf.save()
    print(f"Created {output}: {columns} x {rows} = {columns * rows} points")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name(FILENAME))
    parser.add_argument(
        "--font", type=Path,
        default=Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
        help="Korean TrueType font; defaults to AppleGothic on macOS.",
    )
    args = parser.parse_args()
    if not args.font.is_file():
        parser.error("Supply an installed Korean TrueType font with --font PATH.")
    generate(args.output, args.font)


if __name__ == "__main__":
    main()
