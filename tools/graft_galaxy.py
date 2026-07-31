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
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy.graft import graft  # noqa: E402
from sgalaxy.savefile import SaveError, SaveFile  # noqa: E402


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
