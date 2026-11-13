"""Desenha o mapa de calor em SVG, sem biblioteca de gráfico: cada quadrado vira um <rect>."""

from __future__ import annotations

import math

from .db import MAP_SIZE
from .generate import HOTSPOTS


def render(cells: list[dict], cell: int = 512, size: int = 640, title: str = "Kills por região") -> str:
    grid = math.ceil(MAP_SIZE / cell)
    px = size / grid
    peak = max((c["count"] for c in cells), default=1)
    rects = []
    for c in cells:
        # escala logarítmica: sem ela, o ponto mais quente apaga todo o resto
        t = math.log1p(c["count"]) / math.log1p(peak)
        x = c["x"] * px
        y = (grid - 1 - c["y"]) * px  # no jogo o y cresce pro norte; no SVG cresce pra baixo
        rects.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{px:.1f}" height="{px:.1f}" '
                     f'fill="{_color(t)}" fill-opacity="{0.25 + 0.75 * t:.2f}"><title>{c["count"]}</title></rect>')

    labels = []
    for name, hx, hy, _ in HOTSPOTS:
        lx, ly = hx / MAP_SIZE * size, size - hy / MAP_SIZE * size
        labels.append(f'<circle cx="{lx:.0f}" cy="{ly:.0f}" r="2.5" fill="#e8eef8"/>'
                      f'<text x="{lx + 5:.0f}" y="{ly - 5:.0f}">{name}</text>')

    lines = "".join(
        f'<line x1="{i * size / 6:.0f}" y1="0" x2="{i * size / 6:.0f}" y2="{size}"/>'
        f'<line x1="0" y1="{i * size / 6:.0f}" x2="{size}" y2="{i * size / 6:.0f}"/>'
        for i in range(1, 6)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size + 34}" width="{size}" height="{size + 34}" font-family="system-ui, sans-serif">
  <rect width="{size}" height="{size + 34}" fill="#06080f"/>
  <g stroke="#1e293b" stroke-width="1">{lines}</g>
  <g>{"".join(rects)}</g>
  <g font-size="11" fill="#cbd5e1">{"".join(labels)}</g>
  <text x="12" y="{size + 22}" font-size="13" fill="#8b9bb4">{title} · quadrados de {cell} m · máximo {peak}</text>
</svg>
"""


def _color(t: float) -> str:
    # azul (frio) -> amarelo -> vermelho (quente)
    stops = [(56, 189, 248), (251, 191, 36), (248, 113, 113)]
    if t <= 0.5:
        a, b, k = stops[0], stops[1], t / 0.5
    else:
        a, b, k = stops[1], stops[2], (t - 0.5) / 0.5
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))
