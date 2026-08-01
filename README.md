# Shared Galaxy

*[Leia em português](README.pt-BR.md)*

A server that lets several Space Haven players share one galaxy — each running
their own game, with **not a single line of the game's code changed**.

## How it can work at all

Space Haven has no headless mode, its simulation is not deterministic, and the
game owns the save file while it is open. So a live multiplayer server is out of
reach, and this project does not pretend otherwise.

What *is* reachable rests on facts measured by loading modified saves into game
1.0.4 and looking at the result:

- **The creation seed reproduces the galaxy.** Same seed and same options give
  the same systems, the same celestial bodies and the same starting point — but
  a different crew and a different ship. Same universe, different people. A
  coordinate means the same thing to everyone in a room, and no map has to be
  distributed.
- **A ship can be given an owner.** `<ship>/<settings>` with `of` and `owner`
  decides which faction a ship belongs to, so a shop can be placed in your
  sector as a legitimate NPC.
- **The game gives trading away for free.** A ship of another faction sitting in
  your sector offers HAIL, TRADE and MISSIONS with nothing built, and it works
  without the other player being online. **Measured end to end:** the seller's
  `<shipBank>` records the sale, and both sides balance to the credit. The
  trading interface between players does not have to be invented.

So: the server keeps each player's save, lends it out for a session, and gets it
back — placing the neighbours' shops between sessions. Everything happens with
the game closed.

The full design is in [docs/shared-galaxy-server.md](docs/shared-galaxy-server.md),
the measurements behind it in [docs/savegame-format.md](docs/savegame-format.md),
what was learned since in [docs/findings.md](docs/findings.md), and the
implementation order in [docs/plan.md](docs/plan.md).

Every document has a Portuguese version alongside it (`.pt-BR.md`); English is
the canonical one.

## What works today

**Phase 0 — custody.** The server holds each player's save, lends it for a
session with a deadline, and takes it back. There is no save scumming: one copy
exists and the server knows which. A full cycle has been run against a real
game — join, checkout, play, return — and the room map shows where everyone is.

**The trade experiment is answered.** A shop built by these tools was loaded in
the game, appeared closed (`Normal (Unexplored)`), traded, and reconciled: the
buyer paid 70 credits, the shop's bank gained exactly 70, and five Steel Plates
moved. Details in [docs/trade-experiment.md](docs/trade-experiment.md).

### The client

Two ways to run it, and they are the same program.

**A download**, from the [releases](../../releases) — one file, nothing to
install, Windows, Linux and macOS:

```
sgalaxy register "Your Name"
sgalaxy rooms
sgalaxy play ROOM              # checkout, launch, return — one command
sgalaxy install-mod            # opens the game straight into the room's save
```

**From this repository**, which is what the download is built from:

```bash
python3 tools/sgalaxy.py register "Your Name"
python3 tools/sgalaxy.py play ROOM
```

Standard library only — that is the point of it. A packaged binary is
convenient and it hides what it does; the source stays the honest path, reads
end to end in twenty minutes, and is what `client/build.sh` and the release
workflow package. Set `SGALAXY_URL` to point at a server other than the public
one.

`play` refuses to run while Space Haven is open: writing to a save with the game
running destroys the run, and that is the one thing the client can never get
wrong. It is also why the client launches the game itself rather than leaving it
to a web page — a browser can upload and download a save, but it cannot know the
game is closed.

### The tools

| | |
|---|---|
| `tools/sgalaxy.py` | the client: rooms, sessions, and the whole cycle |
| `tools/save_diff.py` | structural diff between two saves, with a learnable noise profile |
| `tools/save_snapshot.py` | copies a savegame into a labelled working folder |
| `tools/inject_npc_ship.py` | builds a neighbour's shop inside a save |
| `sgalaxy/savefile.py` | byte-identical savegame reading and writing (vendored) |

`save_snapshot.py` and `save_diff.py` never write to a savegame.
`inject_npc_ship.py` does, and requires an explicit output folder.

### The server

```bash
cp .env.example .env      # set POSTGRES_PASSWORD
docker compose up -d
```

Brings its own Postgres. Binds to localhost by default: a service that accepts
uploads from strangers should not become public because nobody read the compose
file.

## Tests

```bash
python3 -m unittest discover -s tests -t .          # tools and rules
DATABASE_URL=postgresql://... python3 -m unittest discover -s tests -t .   # and the server
```

They run against synthetic saves and a real Postgres — never a fake database,
because the guarantee that matters most here (one open lease per player, which
is what stops duplication by parallel session) is a unique index. Tests that
cannot run declare themselves skipped rather than passing quietly.

They prove the tools do what they claim. They prove nothing about the game:
every claim about Space Haven's behaviour comes from a real save, and
[docs/findings.md](docs/findings.md) says which.

## Trust

This project asks people to upload savegames to a server, and that is a real
thing to ask. Section 2.11 of the design deals with it deliberately:
self-hostable server, public builds from public source, a data policy written
before the code existed, and honesty about what cannot be prevented.

The game runs on the player's machine, on files they can edit. Nothing stops
someone from altering their own save, and the design does not pretend otherwise:
it is cooperative, and the server **checks** rather than guesses.

The published binary is the one place that asks for trust it cannot show. It is
built by [the release workflow](.github/workflows/release.yml) from the source
in this repository, on GitHub's runners, and anyone who prefers not to take that
on their word runs `tools/sgalaxy.py` directly — it needs nothing but Python.

## Disclaimer

**Space Haven** is a game by [Bugbyte Ltd.](https://bugbyte.fi/) This is an
independent, fan-made project: not official, not endorsed, no affiliation.

Nothing here changes the game — it reads and writes savegames, which players
have done by hand for years. See [NOTICE](NOTICE).

## License

MIT — see [LICENSE](LICENSE).
