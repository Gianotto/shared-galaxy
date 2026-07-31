# Shared Galaxy

*[Leia em português](README.pt-BR.md)*

A server that lets several Space Haven players share one galaxy — each running
their own game, with **not a single line of the game's code changed**.

**Early stage.** No server exists yet. What is here is the design, the measured
facts it rests on, and the tools for the one experiment that has to be answered
before the interesting part can be built.

## How it can work at all

Space Haven has no headless mode, its simulation is not deterministic, and the
game owns the save file while it is open. So a live multiplayer server is out of
reach, and this project does not pretend otherwise.

What *is* reachable rests on three facts, each measured by loading modified
saves into game 1.0.4 and looking at the result:

- **The creation seed reproduces the galaxy.** Same seed and same options give
  the same systems, the same celestial bodies and the same starting point. A
  coordinate means the same thing to every player in a room, and no map has to
  be distributed.
- **A ship can be given an owner.** `<ship>/<settings>` with `of` and `owner`
  decides which faction a ship belongs to. Another player's ship can be dropped
  into your save as a legitimate NPC.
- **The game gives trading away for free.** A ship of another faction sitting in
  your sector offers HAIL, TRADE and MISSIONS with nothing built, and it works
  without the other player being online. The trading interface between players
  does not have to be invented.

So: the server keeps each player's save, lends it out for a session, and gets it
back — injecting the neighbours' ships between sessions. Everything happens with
the game closed.

The full design is in [docs/shared-galaxy-server.md](docs/shared-galaxy-server.md)
(Portuguese), and the measurements behind it in
[docs/savegame-format.md](docs/savegame-format.md).

## What is here now

Tools for the trade experiment — the assumption that decides whether trading
between players can be reconciled by a server at all:

| | |
|---|---|
| `tools/save_snapshot.py` | copies a savegame into a labelled working folder |
| `tools/save_diff.py` | structural diff between two saves, with a learnable noise profile |
| `tools/inject_npc_ship.py` | injects another player's ship as a legitimate NPC |
| `sgalaxy/savefile.py` | byte-identical savegame reading and writing (vendored) |

Python 3.10+, standard library only. Nothing to install.

```bash
python3 tools/save_snapshot.py path/to/save before
# play, trade, save
python3 tools/save_snapshot.py path/to/save after
python3 tools/save_diff.py "$(python3 tools/save_snapshot.py --path before)" \
                           "$(python3 tools/save_snapshot.py --path after)"
```

The protocol to follow is [docs/trade-experiment.md](docs/trade-experiment.md).
It needs a person playing: the simulation does not run without the client.

`tools/save_snapshot.py` and `tools/save_diff.py` never write to a savegame.
`tools/inject_npc_ship.py` does, and requires an explicit output folder — but it
has not yet been verified against a real save. **Use it on copies only.**

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

They run against synthetic saves and prove that the tools do what they claim —
that the diff finds what changed and does not invent changes where a naive
positional diff would. They prove nothing about the game itself. Every claim
about Space Haven's behaviour needs a real save.

## Trust

This project will eventually ask people to upload savegames to a server, and
that is a real thing to ask. The design document deals with it deliberately
(section 2.11): self-hostable server, public builds from public source, a data
policy written before the code exists, and honesty about what cannot be
prevented — the game runs on the player's machine, saves can be edited, and so
the design is cooperative and the server verifies rather than guesses.

## Disclaimer

**Space Haven** is a game by [Bugbyte Ltd.](https://bugbyte.fi/) This is an
independent, fan-made project: not official, not endorsed, no affiliation.

Nothing here changes the game. See [NOTICE](NOTICE).

## License

MIT — see [LICENSE](LICENSE).
