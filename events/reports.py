"""Relatórios com aggregation pipeline. Cada função monta o pipeline e roda no servidor:
só o resultado agregado volta pro Python, não os eventos."""

from __future__ import annotations

from datetime import datetime

from pymongo.database import Database

from .db import MAP_SIZE


def _period(since: datetime | None, until: datetime | None) -> dict:
    ts = {}
    if since:
        ts["$gte"] = since
    if until:
        ts["$lt"] = until
    return {"ts": ts} if ts else {}


def deaths_by_hour(db: Database, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    """Em que hora do dia mais gente morre (0 a 23)."""
    return list(db.events.aggregate([
        {"$match": {"type": "death", **_period(since, until)}},
        {"$group": {"_id": {"$hour": "$ts"}, "deaths": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "hour": "$_id", "deaths": 1}},
    ]))


def weapons(db: Database, limit: int = 10) -> list[dict]:
    """Armas que mais mataram, com distância média e máxima."""
    return list(db.events.aggregate([
        {"$match": {"type": "kill", "weapon": {"$exists": True}}},
        {"$group": {
            "_id": "$weapon",
            "kills": {"$sum": 1},
            "avg_distance": {"$avg": "$distance"},
            "max_distance": {"$max": "$distance"},
            "by_ai": {"$sum": {"$cond": [{"$eq": ["$killer.ai", True]}, 1, 0]}},
        }},
        {"$sort": {"kills": -1, "_id": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "weapon": "$_id", "kills": 1, "by_ai": 1,
                      "avg_distance": {"$round": ["$avg_distance", 1]}, "max_distance": 1}},
    ]))


def heatmap(db: Database, cell: int = 512, event_type: str = "kill") -> list[dict]:
    """Conta eventos por quadrado do mapa (onde a vítima estava)."""
    return list(db.events.aggregate([
        {"$match": {"type": event_type, "pos": {"$exists": True}}},
        {"$group": {
            "_id": {"x": {"$floor": {"$divide": [{"$arrayElemAt": ["$pos", 0]}, cell]}},
                    "y": {"$floor": {"$divide": [{"$arrayElemAt": ["$pos", 1]}, cell]}}},
            "count": {"$sum": 1},
        }},
        {"$project": {"_id": 0, "x": {"$toInt": "$_id.x"}, "y": {"$toInt": "$_id.y"}, "count": 1}},
        {"$sort": {"count": -1}},
    ]))


def in_area(db: Database, x1: float, y1: float, x2: float, y2: float, event_type: str = "kill") -> int:
    """Quantos eventos dentro de um retângulo do mapa (usa o índice 2d)."""
    return db.events.count_documents({"type": event_type, "pos": {"$geoWithin": {"$box": [[x1, y1], [x2, y2]]}}})


def sessions(db: Database, limit: int = 10) -> list[dict]:
    """Tempo jogado por jogador. Cada desconexão é pareada com o evento anterior do mesmo
    jogador usando $setWindowFields; se o anterior foi uma conexão, isso é uma sessão."""
    return list(db.events.aggregate([
        {"$match": {"type": {"$in": ["connect", "disconnect"]}}},
        {"$setWindowFields": {
            "partitionBy": "$player.id",
            "sortBy": {"ts": 1},
            "output": {"previous": {"$shift": {"output": {"type": "$type", "ts": "$ts"}, "by": -1}}},
        }},
        {"$match": {"type": "disconnect", "previous.type": "connect"}},
        {"$group": {
            "_id": "$player.id",
            "name": {"$last": "$player.name"},
            "sessions": {"$sum": 1},
            "seconds": {"$sum": {"$dateDiff": {"startDate": "$previous.ts", "endDate": "$ts", "unit": "second"}}},
            "longest": {"$max": {"$dateDiff": {"startDate": "$previous.ts", "endDate": "$ts", "unit": "second"}}},
        }},
        {"$sort": {"seconds": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "player_id": "$_id", "name": 1, "sessions": 1, "seconds": 1, "longest": 1}},
    ]))


def top_players(db: Database, limit: int = 10) -> list[dict]:
    """Kills, mortes e K/D por jogador. As kills vêm do campo killer e as mortes do campo
    player, então o pipeline junta as duas listas com $unionWith antes de agrupar."""
    return list(db.events.aggregate([
        {"$match": {"type": "kill", "killer.id": {"$exists": True}}},
        {"$project": {"_id": 0, "id": "$killer.id", "name": "$killer.name", "kills": {"$literal": 1}, "deaths": {"$literal": 0}}},
        {"$unionWith": {"coll": "events", "pipeline": [
            {"$match": {"type": "death"}},
            {"$project": {"_id": 0, "id": "$player.id", "name": "$player.name", "kills": {"$literal": 0}, "deaths": {"$literal": 1}}},
        ]}},
        {"$group": {"_id": "$id", "name": {"$last": "$name"}, "kills": {"$sum": "$kills"}, "deaths": {"$sum": "$deaths"}}},
        {"$set": {"kd": {"$round": [{"$divide": ["$kills", {"$max": ["$deaths", 1]}]}, 2]}}},
        {"$sort": {"kills": -1, "kd": -1, "_id": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "player_id": "$_id", "name": 1, "kills": 1, "deaths": 1, "kd": 1}},
    ]))


def rollup_hourly(db: Database) -> int:
    """Materializa contagens por hora e tipo numa coleção separada com $merge.
    Rodar de novo atualiza em vez de duplicar, então dá pra agendar."""
    db.events.aggregate([
        {"$group": {"_id": {"type": "$type", "hour": {"$dateTrunc": {"date": "$ts", "unit": "hour"}}},
                    "count": {"$sum": 1}}},
        {"$merge": {"into": "events_hourly", "on": "_id", "whenMatched": "replace", "whenNotMatched": "insert"}},
    ])
    return db.events_hourly.count_documents({})


def explain(db: Database, query: dict, sort: list[tuple[str, int]] | None = None, hint: str | dict | None = None) -> dict:
    """Resumo do plano de execução: qual estágio, quantos documentos e chaves lidos."""
    cursor = db.events.find(query)
    if sort:
        cursor = cursor.sort(sort)
    if hint:
        cursor = cursor.hint(hint)
    stats = cursor.explain()["executionStats"]

    def stages(stage: dict) -> list[str]:
        out = [stage["stage"]]
        for key in ("inputStage", "inputStages"):
            child = stage.get(key)
            for c in child if isinstance(child, list) else [child] if child else []:
                out += stages(c)
        return out

    return {
        "stages": stages(stats["executionStages"]),
        "returned": stats["nReturned"],
        "docs_examined": stats["totalDocsExamined"],
        "keys_examined": stats["totalKeysExamined"],
        "ms": stats["executionTimeMillis"],
    }


__all__ = ["MAP_SIZE", "deaths_by_hour", "weapons", "heatmap", "in_area", "sessions", "top_players",
           "rollup_hourly", "explain"]
