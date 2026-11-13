from datetime import datetime

import pytest
from pymongo.errors import WriteError

from events import heatmap, reports
from events.generate import generate
from events.ingest import ingest_file, insert_many


def test_schema_validator_rejects_bad_documents(db):
    now = datetime(2026, 11, 13)
    with pytest.raises(WriteError):
        db.events.insert_one({"ts": now})                                  # sem tipo
    with pytest.raises(WriteError):
        db.events.insert_one({"type": "explosao", "ts": now})              # tipo desconhecido
    with pytest.raises(WriteError):
        db.events.insert_one({"type": "kill", "ts": now, "pos": [99999, 1]})  # fora do mapa
    with pytest.raises(WriteError):
        db.events.insert_one({"type": "kill", "ts": "ontem"})               # data como texto
    db.events.insert_one({"type": "kill", "ts": now, "pos": [100, 200], "weapon": "AKM"})


def test_documents_that_fail_validation_are_counted_not_fatal(db):
    good = {"type": "death", "ts": datetime(2026, 11, 13), "player": {"id": "a", "name": "A"}}
    result = insert_many(db, [good, {"type": "death", "ts": datetime(2026, 11, 13), "pos": [-1, 5]}, dict(good)])
    assert (result.inserted, result.rejected) == (2, 1)


def test_ingesting_the_same_log_twice_does_not_duplicate(db, example_log):
    first = ingest_file(db, example_log)
    second = ingest_file(db, example_log)
    assert first.inserted > 0 and first.duplicates == 0
    assert (second.inserted, second.duplicates) == (0, first.inserted)
    assert db.events.count_documents({}) == first.inserted


def test_example_log_reports(db, example_log):
    ingest_file(db, example_log)

    weapons = {w["weapon"]: w for w in reports.weapons(db)}
    assert set(weapons) == {"AKM", "Mosin9130", "M4-A1"}
    assert weapons["M4-A1"]["by_ai"] == 1
    assert weapons["Mosin9130"]["max_distance"] == 462.3

    top = {p["name"]: p for p in reports.top_players(db)}
    assert top["Lobo"]["kills"] == 2

    sessions = {s["name"]: s for s in reports.sessions(db)}
    assert sessions["Raposa"]["seconds"] == 749          # 23:01:40 -> 23:14:09
    assert sessions["Corvo"]["sessions"] == 1


def test_sessions_pair_each_disconnect_with_the_previous_connect(db):
    base = {"player": {"id": "a", "name": "A"}}
    insert_many(db, [
        {**base, "type": "connect", "ts": datetime(2026, 11, 13, 10, 0)},
        {**base, "type": "disconnect", "ts": datetime(2026, 11, 13, 10, 30)},
        {**base, "type": "disconnect", "ts": datetime(2026, 11, 13, 10, 31)},   # desconexão solta, ignora
        {**base, "type": "connect", "ts": datetime(2026, 11, 13, 20, 0)},
        {**base, "type": "disconnect", "ts": datetime(2026, 11, 13, 22, 0)},
    ])
    [a] = reports.sessions(db)
    assert (a["sessions"], a["seconds"], a["longest"]) == (2, 9000, 7200)


def test_deaths_by_hour_and_area_query(db):
    insert_many(db, [
        {"type": "death", "ts": datetime(2026, 11, 13, 21, 5), "player": {"id": "a", "name": "A"}, "pos": [6700, 2500]},
        {"type": "death", "ts": datetime(2026, 11, 13, 21, 50), "player": {"id": "b", "name": "B"}, "pos": [6800, 2400]},
        {"type": "death", "ts": datetime(2026, 11, 13, 3, 0), "player": {"id": "c", "name": "C"}, "pos": [12000, 9000]},
    ])
    assert reports.deaths_by_hour(db) == [{"hour": 3, "deaths": 1}, {"hour": 21, "deaths": 2}]
    assert reports.in_area(db, 6000, 2000, 7500, 3000, "death") == 2


def test_rollup_is_idempotent(db):
    insert_many(db, generate(2000, players=20, seed=1, end=datetime(2026, 11, 13)))
    first = reports.rollup_hourly(db)
    second = reports.rollup_hourly(db)
    assert first == second > 0
    total = sum(d["count"] for d in db.events_hourly.find())
    assert total == db.events.count_documents({})


def test_index_turns_a_full_scan_into_an_index_scan(db):
    insert_many(db, generate(20_000, players=50, seed=7, end=datetime(2026, 11, 13)))
    query, sort = {"type": "kill", "ts": {"$gte": datetime(2026, 11, 12)}}, [("ts", -1)]

    scan = reports.explain(db, query, sort, hint={"$natural": 1})
    indexed = reports.explain(db, query, sort, hint="type_ts")

    assert "COLLSCAN" in scan["stages"]
    assert "IXSCAN" in indexed["stages"]
    assert scan["returned"] == indexed["returned"] > 0
    assert scan["docs_examined"] == db.events.count_documents({})
    assert indexed["docs_examined"] == indexed["returned"]   # só lê o que vai devolver


def test_heatmap_renders_svg(db):
    insert_many(db, generate(3000, players=30, seed=3, end=datetime(2026, 11, 13)))
    cells = reports.heatmap(db, cell=1024)
    assert sum(c["count"] for c in cells) == db.events.count_documents({"type": "kill"})
    svg = heatmap.render(cells, cell=1024)
    assert svg.startswith("<svg") and svg.count("<rect") == len(cells) + 1
