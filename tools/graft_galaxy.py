#!/usr/bin/env python3
"""
Replaces the galaxy inside a save with the room's, keeping everything else.

The onboarding problem this attacks: today a player must create a game with the
room's exact seed AND every scenario option right, or the fingerprint refuses
their save. With thirty people arriving from a Discord invite, that is dozens of
refusals over a checkbox nobody can see afterwards.

If the server can hand back a save that already sits in the room's galaxy, the
options stop being a fragile agreement between strangers and become a fact.

WHY THIS DIRECTION. The obvious design is the opposite: keep a canonical galaxy
on the server and transplant each new player's ship into it. That means moving
the player — ship, crew, bank, research, faction standing — and those live
scattered across the save, not in one node. Grafting the galaxy moves a single
subtree instead, and the player's own state is never touched.

WHAT MOVES

    <starmap>     the whole thing: systems, bodies, terrain sectors, clouds
    <questLines>  from the same donor, because it points INTO the starmap

WHAT IS CLEARED

    <missions>, and the mission nodes on ships — they name systems and sectors
    of the galaxy being replaced

WHAT IS PRESERVED FROM THE PLAYER'S SAVE

    everything else — ships, crew, `playerBank`, research, `hostmap`, and the
    already-generated starting sector in `<space>`

WHAT IS REBUILT

    the player's fleet `<f isPlayer="true">`, moved into the room's starting
    body, plus `starmap/@sys` and `starmap/@pa`. `@pa` takes the body's LOCAL
    `id`, never the `celeid` — they are different numbers and confusing them
    puts the player in the wrong sector, silently (findings item 1).

THE REFERENCES THAT COST A CRASH. The first version moved `<starmap>` alone, on
the assumption that the galaxy is a self-contained subtree. It is not. Loading
worked; the first hyperspace jump crashed with a NullPointerException inside
`QuestExodusFleetMissions.addFindBeaconFromDere` — the quest line had gone
looking for a beacon that existed in the old galaxy.

Measured afterwards, three places outside `<starmap>` hold ids from inside it:

    <questLines>  atSystemId, atSectorId, decoId, createdShipStarmapId
    <missions>    systemId, sectorId
    <ships>       givenByShipId, systemId, sectorId, on mission nodes

`<questLines>` is taken from the donor: the player is arriving in that galaxy,
so the fresh quest state that belongs to it is the correct one. Missions are
dropped, because an outstanding job in a galaxy you just left cannot be honoured
— and nobody would expect it to be.

THE KNOWN SEAM. The starting sector's `<space>` was generated from the player's
original body, and the game does not regenerate a sector on load (section 1.6).
So that one sector keeps the asteroid field it was born with, while the room's
starmap declares a possibly different `<stuff>` for that body. Everything
travelled to afterwards is generated from the shared galaxy and matches. It is
one sector's worth of cosmetic disagreement, and it is the price of not moving
the player.

Read-only on both inputs; `--out` is required.

    python3 tools/graft_galaxy.py --galaxy ROOM_SAVE --into PLAYER_SAVE \\
        --out RESULT [--start-celeid 1689]
"""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy.savefile import (  # noqa: E402
    SaveError,
    SaveFile,
    _insert_child,
    _remove_child,
)


def player_fleet(sf: SaveFile) -> tuple:
    """The player's fleet and the body holding it, or (None, None)."""
    starmap = sf.main.find("starmap")
    if starmap is None:
        return None, None
    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("celeid") is None:
                continue
            fleets = body.find("fleets")
            if fleets is None:
                continue
            for fleet in fleets.findall("f"):
                if fleet.get("isPlayer") == "true":
                    return fleet, body
    return None, None


def body_by_celeid(starmap: ET.Element, celeid: str) -> tuple:
    """The body with that `celeid`, and the system holding it."""
    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("celeid") == str(celeid):
                return body, system
    return None, None


def start_body(starmap: ET.Element) -> tuple:
    """Where a fresh game begins: the asteroid marked `isst="1"`.

    It appears exactly once in a save and is always an asteroid — the player's
    origin (section 1.5). Since the seed reproduces the starting point, this is
    the same body for everyone in a room (findings item 16), which is precisely
    what makes it the right place to graft someone in.

    The flag sits on the body's `<info>` CHILD, not on the body. Section 1.5
    does say "in the body's `<info>`" and I still read it as an attribute of the
    body — which found the `<info>` element itself, a thing with no `celeid` and
    no `id`, and produced a graft pointing nowhere.
    """
    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("celeid") is None:
                continue
            info = body.find("info")
            if info is not None and info.get("isst") == "1":
                return body, system
    return None, None


def graft(galaxy_sf: SaveFile, player_sf: SaveFile,
          start_celeid: str | None = None) -> dict:
    """Puts the room's galaxy into the player's save. Mutates `player_sf`."""
    source = galaxy_sf.main.find("starmap")
    if source is None:
        raise SaveError("the galaxy save has no <starmap>")
    target_root = player_sf.main
    current = target_root.find("starmap")
    if current is None:
        raise SaveError("the player save has no <starmap>")

    report: dict = {"warnings": []}

    fleet, old_body = player_fleet(player_sf)
    if fleet is None:
        raise SaveError(
            "no <f isPlayer=\"true\"> in the player save: without the fleet "
            "there is nothing to place in the new galaxy")
    report["fleetId"] = fleet.get("id")
    report["fromCeleid"] = old_body.get("celeid") if old_body is not None else None

    new_map = copy.deepcopy(source)
    new_map.tail = current.tail

    # The donor's own fleets come along with the subtree. Player fleets are
    # stripped — one save has exactly one player, and leaving the donor's would
    # make two.
    stripped = 0
    for fleets in list(new_map.iter("fleets")):
        for f in list(fleets.findall("f")):
            if f.get("isPlayer") == "true":
                _remove_child(fleets, f)
                stripped += 1
    report["strippedFleets"] = stripped

    if start_celeid:
        body, system = body_by_celeid(new_map, start_celeid)
        if body is None:
            raise SaveError(f"no body with celeid={start_celeid} in the galaxy")
    else:
        body, system = start_body(new_map)
        if body is None:
            raise SaveError(
                "no body marked isst=\"1\" in the galaxy, and no --start-celeid "
                "given: I do not know where to put the player")

    fleets = body.find("fleets")
    if fleets is None:
        # Section 1.5: the target body usually has no <fleets>; it goes between
        # <stuff> and <info>.
        fleets = ET.Element("fleets")
        info = body.find("info")
        index = list(body).index(info) if info is not None else len(list(body))
        _insert_child(body, fleets, index)
        report["createdFleets"] = True

    moved = copy.deepcopy(fleet)
    moved.tail = None
    # The fleet carries the coordinates it had in the old galaxy. They mean
    # nothing here — the body moved — so they take the new body's.
    for attr in ("x", "y"):
        if body.get(attr) is not None:
            moved.set(attr, body.get(attr))
    _insert_child(fleets, moved)

    # The three that have to agree (section 1.5). `@pa` is the body's LOCAL id,
    # not its celeid: confusing them is the silent error of findings item 1.
    new_map.set("sys", system.get("systemId"))
    if body.get("id") is not None:
        new_map.set("pa", body.get("id"))
    else:
        report["warnings"].append(
            "the destination body has no @id; left starmap/@pa untouched")

    index = list(target_root).index(current)
    _remove_child(target_root, current)
    _insert_child(target_root, new_map, index)

    report.update(_move_quests(galaxy_sf.main, target_root))

    player_sf.mark_dirty(target_root)
    player_sf.reindex()

    report.update({
        "systems": len(new_map.findall("systems/l")),
        "toCeleid": body.get("celeid"),
        "toBodyId": body.get("id"),
        "system": system.get("systemId"),
        "bodyType": body.get("type"),
    })
    return report


# Everything outside <starmap> that names something inside it. Found the hard
# way: the first graft crashed on the first hyperspace jump.
QUEST_NODE = "questLines"
MISSION_NODES = ("missions",)


def _move_quests(donor_root: ET.Element, target_root: ET.Element) -> dict:
    """Brings the donor's quest state over and drops the player's missions."""
    out: dict = {}

    donor_quests = donor_root.find(QUEST_NODE)
    current = target_root.find(QUEST_NODE)
    if donor_quests is not None and current is not None:
        fresh = copy.deepcopy(donor_quests)
        fresh.tail = current.tail
        index = list(target_root).index(current)
        _remove_child(target_root, current)
        _insert_child(target_root, fresh, index)
        out["questLines"] = "from the galaxy donor"
    elif current is not None:
        out["questLines"] = "left as they were: the donor has none"

    dropped = 0
    for tag in MISSION_NODES:
        node = target_root.find(tag)
        if node is None:
            continue
        for child in list(node):
            _remove_child(node, child)
            dropped += 1

    # Ships carry their own mission nodes, naming systems and sectors of the
    # galaxy that just went away.
    ships = target_root.find("ships")
    if ships is not None:
        for holder in list(ships.iter("missions")):
            for child in list(holder):
                _remove_child(holder, child)
                dropped += 1
    out["droppedMissions"] = dropped
    return out


def prepare_output(source_dir: str, out: str, keep_out_of: tuple) -> str:
    """Copies the player's save to `out`. Never writes over an input."""
    out = os.path.abspath(os.path.expanduser(out))
    if os.path.exists(out):
        raise SaveError(f"{out} already exists; choose a folder that does not")
    for forbidden in (*keep_out_of, source_dir):
        if out == forbidden or out.startswith(forbidden.rstrip("/") + "/"):
            raise SaveError(f"{out} is inside an input save; choose another")
    shutil.copytree(source_dir, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="graft a room's galaxy into a player's save")
    ap.add_argument("--galaxy", required=True,
                    help="save holding the room's galaxy (never modified)")
    ap.add_argument("--into", required=True,
                    help="the player's save (never modified)")
    ap.add_argument("--out", help="new folder for the result; required unless "
                                  "--dry-run")
    ap.add_argument("--start-celeid",
                    help="where to place the player; default is the body "
                         "marked isst=\"1\"")
    ap.add_argument("--dry-run", action="store_true",
                    help="describe what would happen and write nothing")
    args = ap.parse_args()

    if not args.dry_run and not args.out:
        print("error: --out is required unless --dry-run.", file=sys.stderr)
        return 1

    try:
        galaxy = SaveFile(args.galaxy)
        probe = SaveFile(args.into)
        if args.dry_run:
            player = probe
        else:
            out = prepare_output(probe.dir, args.out, (galaxy.dir,))
            player = SaveFile(out)

        report = graft(galaxy, player, args.start_celeid)

        print(f"galaxy: {report['systems']} systems from {args.galaxy}")
        print(f"player: fleet {report['fleetId']}, "
              f"celeid {report['fromCeleid']} -> {report['toCeleid']} "
              f"({report['bodyType']}, system {report['system']})")
        print(f"        starmap/@sys={report['system']} "
              f"@pa={report['toBodyId']}")
        if report["strippedFleets"]:
            print(f"        {report['strippedFleets']} donor player fleet(s) "
                  f"removed")
        if report.get("questLines"):
            print(f"quests: {report['questLines']}")
        if report.get("droppedMissions"):
            print(f"        {report['droppedMissions']} mission(s) dropped — "
                  f"they named places in the old galaxy")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")

        if args.dry_run:
            print("\ndry run: nothing was written.")
        else:
            written = player.save(backup=False)
            print(f"\nwritten to {os.path.dirname(written['path'])} "
                  f"({written['bytes']} bytes)")
    except SaveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
