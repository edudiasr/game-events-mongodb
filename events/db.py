"""Conexão e criação da coleção: validação por schema e índices."""

from __future__ import annotations

import os

from pymongo import ASCENDING, DESCENDING, GEO2D, MongoClient
from pymongo.database import Database
from pymongo.errors import CollectionInvalid

MAP_SIZE = 15360   # Chernarus tem 15,36 km de lado
TYPES = ["kill", "death", "hit", "connect", "disconnect", "chat", "suicide", "bleedout", "killed_by_env"]

NUMBER = {"bsonType": ["double", "int", "long"]}
POSITION = {"bsonType": "array", "minItems": 2, "maxItems": 2,
            "items": {**NUMBER, "minimum": 0, "maximum": 20480}}
PERSON = {"bsonType": "object", "required": ["name"],
          "properties": {"id": {"bsonType": "string"}, "name": {"bsonType": "string"},
                         "ai": {"bsonType": "bool"}, "pos": POSITION}}

# O Mongo não exige schema, mas aceitar qualquer coisa vira bagunça. O validador barra
# documento sem tipo, com tipo desconhecido, posição fora do mapa ou distância negativa.
VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["type", "ts"],
        "properties": {
            "type": {"enum": TYPES},
            "ts": {"bsonType": "date"},
            "player": PERSON,
            "killer": PERSON,
            "pos": POSITION,
            "distance": {**NUMBER, "minimum": 0},
            "damage": {**NUMBER, "minimum": 0},
            "weapon": {"bsonType": "string"},
            "src": {"bsonType": "object", "required": ["file", "line"]},
        },
    }
}


def client() -> MongoClient:
    return MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"), tz_aware=False)


def database(mongo: MongoClient | None = None, name: str | None = None) -> Database:
    return (mongo or client())[name or os.environ.get("EVENTS_DB", "game_events")]


def setup(db: Database, ttl_days: int | None = None) -> None:
    """Cria a coleção com validação e os índices. Pode rodar de novo sem problema."""
    ttl_days = ttl_days or int(os.environ.get("EVENTS_TTL_DAYS", "365"))
    try:
        db.create_collection("events", validator=VALIDATOR, validationLevel="strict")
    except CollectionInvalid:
        db.command("collMod", "events", validator=VALIDATOR, validationLevel="strict")

    events = db.events
    # consultas por tipo num período (kills da semana, mortes de hoje...)
    events.create_index([("type", ASCENDING), ("ts", DESCENDING)], name="type_ts")
    # histórico de um jogador
    events.create_index([("player.id", ASCENDING), ("ts", DESCENDING)], name="player_ts")
    events.create_index([("killer.id", ASCENDING), ("ts", DESCENDING)], name="killer_ts", sparse=True)
    # coordenadas planas do mapa (não é latitude/longitude, por isso 2d e não 2dsphere)
    events.create_index([("pos", GEO2D)], name="pos_2d", min=0, max=20480)
    # eventos velhos somem sozinhos
    events.create_index("ts", name="ts_ttl", expireAfterSeconds=ttl_days * 86400)
    # importar o mesmo log de novo não duplica: cada linha de cada arquivo entra uma vez
    events.create_index([("src.file", ASCENDING), ("src.line", ASCENDING)], name="src_unique", unique=True,
                        partialFilterExpression={"src": {"$exists": True}})
