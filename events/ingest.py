"""Importação em lote. Re-importar o mesmo arquivo não duplica nada (índice único em src.file + src.line)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from pymongo.database import Database
from pymongo.errors import BulkWriteError

from . import adm

BATCH = 5000
DUPLICATE_KEY = 11000
VALIDATION_FAILED = 121


@dataclass
class IngestResult:
    inserted: int = 0
    duplicates: int = 0
    rejected: int = 0


def insert_many(db: Database, docs: Iterable[dict]) -> IngestResult:
    result = IngestResult()
    it = iter(docs)
    while batch := list(islice(it, BATCH)):
        try:
            # ordered=False: um documento com problema não impede os outros do lote de entrar
            result.inserted += len(db.events.insert_many(batch, ordered=False).inserted_ids)
        except BulkWriteError as e:
            errors = e.details.get("writeErrors", [])
            codes = [err.get("code") for err in errors]
            if any(c not in (DUPLICATE_KEY, VALIDATION_FAILED) for c in codes):
                raise
            result.inserted += e.details.get("nInserted", 0)
            result.duplicates += codes.count(DUPLICATE_KEY)
            result.rejected += codes.count(VALIDATION_FAILED)
    return result


def ingest_file(db: Database, path: Path) -> IngestResult:
    with path.open(encoding="utf-8", errors="replace") as f:
        return insert_many(db, adm.parse(f, source=path.name))


def ingest_paths(db: Database, paths: Iterable[Path]) -> IngestResult:
    total = IngestResult()
    for path in paths:
        files = sorted(p for p in path.iterdir() if p.suffix.lower() == ".adm") if path.is_dir() else [path]
        for file in files:
            r = ingest_file(db, file)
            total.inserted += r.inserted
            total.duplicates += r.duplicates
            total.rejected += r.rejected
    return total
