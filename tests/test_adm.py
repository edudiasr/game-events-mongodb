from datetime import datetime

from events import adm

HEADER = "AdminLog started on 2026-11-08 at 22:58:01\n"


def parse(text: str) -> list[dict]:
    return list(adm.parse((HEADER + text).splitlines(), source="t.ADM"))


def test_pvp_kill_keeps_both_positions_weapon_and_distance():
    [doc] = parse('23:10:35 | Player "Raposa" (DEAD) (id=r= pos=<6550.3, 2585.1, 7.2>) killed by Player "Lobo" '
                  '(id=l= pos=<6610.4, 2700.8, 12.0>) with AKM from 134.7 meters \n')
    assert doc["type"] == "kill"
    assert doc["player"] == {"id": "r=", "name": "Raposa"}
    assert doc["pos"] == [6550.3, 2585.1] and doc["alt"] == 7.2
    assert doc["killer"] == {"id": "l=", "name": "Lobo", "pos": [6610.4, 2700.8]}
    assert (doc["weapon"], doc["distance"]) == ("AKM", 134.7)
    assert doc["ts"] == datetime(2026, 11, 8, 23, 10, 35)
    assert doc["src"] == {"file": "t.ADM", "line": 2}


def test_ai_kill_is_marked():
    [doc] = parse('23:00:00 | Player "P" (DEAD) (id=p= pos=<1, 2, 3>) killed by AI "Manua" (group=1 faction="West" '
                  'pos=<4, 5, 6>) with AUR A1 from 41.0918 meters \n')
    assert doc["killer"] == {"ai": True, "name": "Manua"}
    assert doc["weapon"] == "AUR A1"


def test_hits_record_source_body_part_and_damage():
    docs = parse(
        '23:00:00 | Player "V" (id=v= pos=<1, 2, 3>)[HP: 70] hit by Player "S" (id=s= pos=<4, 5, 6>) into Head(0) '
        'for 30 damage (Bullet) with AKM from 50 meters\n'
        '23:00:01 | Player "V" (id=v= pos=<1, 2, 3>)[HP: 60] hit by Infectado into LeftArm(18) for 5.85 damage (MeleeInfected)\n'
        '23:00:02 | Player "V" (id=v= pos=<1, 2, 3>)[HP: 59] hit by OffroadHatchback with TransportHit\n')
    assert [(d["source"], d.get("part"), d.get("damage")) for d in docs] == [
        ("player", "Head", 30.0), ("Infectado", "LeftArm", 5.85), ("OffroadHatchback", None, None)]


def test_other_event_kinds_and_ignored_lines():
    docs = parse(
        '23:00:00 | Player "A" (id=a= pos=<1, 2, 3>) is connected\n'
        '23:00:01 | Chat("A"(id=a=)): boa noite\n'
        '23:00:02 | AI "Kaito" (group=5) is unconscious\n'
        '23:00:03 | [AlgumMod] carregado\n'
        '23:00:04 | Player "A" (id=a=) committed suicide\n'
        '23:00:05 | Player "A" (DEAD) (id=a=) died. Stats> Water: 1\n'
        '23:00:06 | Player "A" (DEAD) (id=a=) killed by ZmbM_Patrol\n'
        '23:00:07 | Player "A" (id=a=) has been disconnected\n')
    assert [d["type"] for d in docs] == ["connect", "chat", "suicide", "death", "killed_by_env", "disconnect"]
    assert docs[1]["text"] == "boa noite"
    assert docs[4]["cause"] == "infected"


def test_unknown_position_sentinel_is_dropped():
    # o jogo escreve o menor float quando não sabe onde o jogador está
    [doc] = parse('18:02:03 | Player "A" (id=a= pos=<-3.40282e+38, -3.40282e+38, -3.40282e+38>) has been disconnected\n')
    assert doc["type"] == "disconnect"
    assert "pos" not in doc and "alt" not in doc


def test_midnight_moves_to_the_next_day():
    docs = parse('23:59:00 | Player "A" (id=a=) is connected\n00:01:00 | Player "A" (id=a=) has been disconnected\n')
    assert docs[1]["ts"] == datetime(2026, 11, 9, 0, 1)
