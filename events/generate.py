"""Gera eventos sintéticos pra ter volume (o log real de um servidor pequeno tem poucos mil).
Os jogadores se concentram perto de cidades e bases militares, como no jogo."""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import datetime, timedelta

# pontos de interesse aproximados de Chernarus (x, y em metros) e o "peso" de cada um
HOTSPOTS = [
    ("Chernogorsk", 6700, 2500, 6), ("Elektrozavodsk", 10300, 2300, 5), ("Berezino", 12900, 9500, 4),
    ("NWAF", 4500, 10200, 5), ("Stary Sobor", 6100, 7700, 3), ("Tisy", 1700, 14000, 3),
    ("Zelenogorsk", 2700, 5200, 3), ("Svetlojarsk", 13900, 13300, 2),
]
WEAPONS = [("M4-A1", 40, 300), ("AKM", 30, 250), ("Mosin9130", 100, 800), ("SVD", 150, 900),
           ("MP5K", 5, 60), ("Shotgun", 2, 25), ("FX-45", 3, 40)]


def generate(count: int, players: int = 200, days: int = 7, seed: int = 42,
             end: datetime | None = None) -> Iterator[dict]:
    rng = random.Random(seed)
    end = end or datetime.now().replace(microsecond=0)
    start = end - timedelta(days=days)
    people = [{"id": f"gen{i:04d}", "name": f"Jogador{i:04d}"} for i in range(players)]
    skill = [rng.random() ** 2 for _ in people]  # poucos jogadores bons, muitos medianos

    def spot() -> list[float]:
        name, x, y, _ = rng.choices(HOTSPOTS, weights=[h[3] for h in HOTSPOTS])[0]
        return [min(15359.0, max(0.0, rng.gauss(x, 500))), min(15359.0, max(0.0, rng.gauss(y, 500)))]

    def when() -> datetime:
        # mais movimento à noite (19h-23h)
        t = start + timedelta(seconds=rng.uniform(0, (end - start).total_seconds()))
        if rng.random() < 0.5:
            t = t.replace(hour=rng.choice([19, 20, 21, 22, 23]))
        return t

    for n in range(count):
        roll = rng.random()
        ts = when()
        src = {"file": f"generated-{seed}", "line": n + 1}
        if roll < 0.25:
            killer = rng.choices(people, weights=skill)[0]
            victim = rng.choice(people)
            if victim is killer:
                continue
            weapon, lo, hi = rng.choice(WEAPONS)
            pos = spot()
            yield {"type": "kill", "ts": ts, "src": src, "player": dict(victim), "pos": pos,
                   "killer": {**killer, "pos": [min(15359.0, max(0.0, pos[0] + rng.uniform(-200, 200))), pos[1]]},
                   "weapon": weapon, "distance": round(rng.uniform(lo, hi), 1)}
        elif roll < 0.45:
            yield {"type": "death", "ts": ts, "src": src, "player": dict(rng.choice(people)), "pos": spot()}
        elif roll < 0.75:
            yield {"type": "hit", "ts": ts, "src": src, "player": dict(rng.choice(people)), "pos": spot(),
                   "source": rng.choice(["Infectado", "player", "ai", "Lobo"]),
                   "part": rng.choice(["Torso", "Head", "LeftArm", "RightLeg"]), "damage": round(rng.uniform(1, 60), 1)}
        else:
            p = rng.choice(people)
            yield {"type": "connect", "ts": ts, "src": src, "player": dict(p), "pos": spot()}
            yield {"type": "disconnect", "ts": ts + timedelta(minutes=rng.uniform(5, 180)),
                   "src": {"file": src["file"], "line": -(n + 1)}, "player": dict(p), "pos": spot()}
