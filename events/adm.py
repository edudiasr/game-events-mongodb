"""Transforma linhas do .ADM (log de administração do DayZ) em documentos.

Cada linha vira um documento com o tipo do evento, o horário, o jogador e a posição no
mapa. As coordenadas do ADM vêm como <x, y, altura>, em metros (Chernarus vai de 0 a 15360).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timedelta

HEADER = re.compile(r"^AdminLog started on (\d{4})-(\d{2})-(\d{2}) at (\d{2}):(\d{2}):(\d{2})")
LINE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}) \| (.*)$")
PLAYER = re.compile(
    r'^Player "(?P<name>[^"]*)"(?: \(DEAD\))? \(id=(?P<id>[^ )]+)'
    r"(?: pos=<(?P<x>[-\d.]+), (?P<y>[-\d.]+), (?P<alt>[-\d.]+)>)?"
)
KILLER = re.compile(
    r'killed by Player "(?P<name>[^"]*)"(?: \(DEAD\))? \(id=(?P<id>[^ )]+)'
    r"(?: pos=<(?P<x>[-\d.]+), (?P<y>[-\d.]+), (?P<alt>[-\d.]+)>)?"
)
AI_KILLER = re.compile(r'killed by AI "(?P<name>[^"]*)"')
WEAPON = re.compile(r" with (?P<weapon>.+?)(?: from (?P<dist>[\d.]+) meters)?\s*$")
HIT = re.compile(r"hit by (?P<source>\S+)")
HIT_PART = re.compile(r" into (?P<part>\w+)\(\d+\) for (?P<damage>[\d.]+) damage")
CHAT = re.compile(r'^Chat\("(?P<name>[^"]*)"\(id=(?P<id>[^ )]+)\)\): (?P<text>.*)$')
OTHER_KILLER = re.compile(r"killed by (?P<killer>[^ (]+)")


def parse(lines: Iterator[str] | list[str], source: str = "adm") -> Iterator[dict]:
    """Gera um documento por linha que interessa. Linhas de IA, de mods e de status são ignoradas."""
    day: datetime | None = None
    previous: tuple[int, int, int] | None = None

    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        header = HEADER.match(line)
        if header:
            y, mo, d, h, mi, s = map(int, header.groups())
            day = datetime(y, mo, d)
            previous = (h, mi, s)
            continue

        m = LINE.match(line)
        if not m or day is None:
            continue
        clock = (int(m[1]), int(m[2]), int(m[3]))
        # o log passa da meia-noite sem avisar: 23:59 -> 00:01
        if previous and clock[0] * 3600 + clock[1] * 60 + 3600 < previous[0] * 3600 + previous[1] * 60:
            day += timedelta(days=1)
        previous = clock
        ts = day + timedelta(hours=clock[0], minutes=clock[1], seconds=clock[2])

        doc = _event(m[4])
        if doc is not None:
            doc["ts"] = ts
            doc["src"] = {"file": source, "line": number}
            yield doc


def _person(match: re.Match) -> dict:
    return {"id": match["id"], "name": match["name"]}


def valid_coord(value: float) -> bool:
    return 0 <= value <= 20480


def _position(doc: dict, match: re.Match) -> None:
    if match["x"] is None:
        return
    x, y = float(match["x"]), float(match["y"])
    # Quando a posição é desconhecida (desconexão durante crash, por exemplo) o jogo escreve
    # pos=<-3.40282e+38, ...>, o menor float. Achei isso nos logs reais: o evento entra sem posição.
    if valid_coord(x) and valid_coord(y):
        doc["pos"] = [x, y]
        doc["alt"] = float(match["alt"])


def _event(text: str) -> dict | None:
    chat = CHAT.match(text)
    if chat:
        return {"type": "chat", "player": _person(chat), "text": chat["text"]}

    subject = PLAYER.match(text)
    if not subject:
        return None  # IA, mensagens de mods, lista de jogadores...
    doc: dict = {"player": _person(subject)}
    _position(doc, subject)

    if (k := KILLER.search(text)) is not None:
        doc["type"] = "kill"
        doc["killer"] = _person(k)
        if k["x"] is not None and valid_coord(float(k["x"])) and valid_coord(float(k["y"])):
            doc["killer"]["pos"] = [float(k["x"]), float(k["y"])]
        _weapon(doc, text[k.end():])
    elif (k := AI_KILLER.search(text)) is not None:
        doc["type"] = "kill"
        doc["killer"] = {"ai": True, "name": k["name"]}
        _weapon(doc, text[k.end():])
    elif (h := HIT.search(text)) is not None:
        doc["type"] = "hit"
        source = h["source"]
        doc["source"] = "player" if source == "Player" else "ai" if source == "AI" else source
        if (p := HIT_PART.search(text, h.end())) is not None:
            doc["part"] = p["part"]
            doc["damage"] = float(p["damage"])
    elif " is connected" in text:
        doc["type"] = "connect"
    elif "has been disconnected" in text:
        doc["type"] = "disconnect"
    elif " died." in text:
        doc["type"] = "death"
    elif "committed suicide" in text:
        doc["type"] = "suicide"
    elif "bled out" in text:
        doc["type"] = "bleedout"
    elif (o := OTHER_KILLER.search(text)) is not None:
        doc["type"] = "killed_by_env"
        doc["cause"] = "infected" if o["killer"].startswith("Zmb") else "animal" if o["killer"].startswith("Animal") else o["killer"]
    else:
        return None
    return doc


def _weapon(doc: dict, rest: str) -> None:
    w = WEAPON.search(rest)
    if w:
        doc["weapon"] = w["weapon"].strip()
        if w["dist"]:
            doc["distance"] = float(w["dist"])
