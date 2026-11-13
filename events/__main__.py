"""Linha de comando.

    python -m events setup
    python -m events ingest caminho/profiles
    python -m events generate --count 200000
    python -m events report weapons|deaths-by-hour|sessions|top-players|rollup
    python -m events heatmap --out heatmap.svg
    python -m events explain
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import db as dbmod
from . import heatmap, reports
from .generate import generate
from .ingest import ingest_paths, insert_many


def main() -> None:
    parser = argparse.ArgumentParser(prog="events")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    ing = sub.add_parser("ingest")
    ing.add_argument("paths", nargs="+", type=Path)
    gen = sub.add_parser("generate")
    gen.add_argument("--count", type=int, default=100_000)
    gen.add_argument("--seed", type=int, default=42)
    rep = sub.add_parser("report")
    rep.add_argument("name", choices=["weapons", "deaths-by-hour", "sessions", "top-players", "rollup"])
    hm = sub.add_parser("heatmap")
    hm.add_argument("--out", type=Path, default=Path("heatmap.svg"))
    hm.add_argument("--cell", type=int, default=512)
    sub.add_parser("explain")
    args = parser.parse_args()

    db = dbmod.database()
    dbmod.setup(db)

    if args.cmd == "setup":
        print("coleção e índices prontos")
    elif args.cmd == "ingest":
        started = time.perf_counter()
        r = ingest_paths(db, args.paths)
        print(f"{r.inserted} eventos novos, {r.duplicates} já existiam, {r.rejected} recusados pela validação "
              f"({time.perf_counter() - started:.1f} s)")
    elif args.cmd == "generate":
        started = time.perf_counter()
        r = insert_many(db, generate(args.count, seed=args.seed))
        print(f"{r.inserted} eventos gerados ({time.perf_counter() - started:.1f} s)")
    elif args.cmd == "report":
        fn = {"weapons": reports.weapons, "deaths-by-hour": reports.deaths_by_hour, "sessions": reports.sessions,
              "top-players": reports.top_players, "rollup": reports.rollup_hourly}[args.name]
        print(json.dumps(fn(db), ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "heatmap":
        args.out.write_text(heatmap.render(reports.heatmap(db, args.cell), args.cell), encoding="utf-8")
        print(f"mapa salvo em {args.out}")
    elif args.cmd == "explain":
        sample = db.events.find_one({"player.id": {"$exists": True}}, {"player.id": 1})
        cases = [
            ("histórico de um jogador", {"player.id": sample["player"]["id"]}, [("ts", -1)], "player_ts"),
            ("todas as kills (20% da coleção)", {"type": "kill"}, [("ts", -1)], "type_ts"),
        ]
        for title, query, sort, index in cases:
            print(f"\n{title}")
            print("  sem índice:", reports.explain(db, query, sort, hint={"$natural": 1}))
            print("  com índice:", reports.explain(db, query, sort, hint=index))


if __name__ == "__main__":
    main()
