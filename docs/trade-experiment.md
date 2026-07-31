# Trade experiment

*[Leia em português](trade-experiment.pt-BR.md)*

The experiment that decides phase 3 of the project. It is in section 2.12 of the
design document as the most expensive assumption still untested:

> **reconcilable trade.** We saw TRADE appear and work. We did not measure how the
> transaction ends up recorded in the save, nor whether it can be reconstructed at
> check-in.

This document is the script for answering that. It needs you playing: the
simulation does not run without the client, so there is no way to automate it.

Until it is answered, phase 3 is speculation. Phases 0, 1 and 2 do not depend on
it and can move in parallel.

---

## Before you start

**Always work on a copy.** No tool in this repository writes into an input save,
but the game does. Make a game dedicated to the experiment and do not use a save
you care about.

Note down the game version. Everything here was surveyed on **1.0.4**; if yours is
different, say so in the result, because the answer may not hold.

Where the saves live:

| System | Path |
|---|---|
| Windows | `%APPDATA%\..\LocalLow\Bugbyte\Space Haven\savegames\` |
| Linux (native) | `~/.config/unity3d/Bugbyte/Space Haven/savegames/` |
| Linux (Steam via snap) | `~/snap/steam/common/.local/share/Steam/steamapps/common/SpaceHaven/savegames/` |
| Linux (Proton) | `.../steamapps/compatdata/979110/pfx/drive_c/users/steamuser/AppData/LocalLow/Bugbyte/Space Haven/savegames/` |

The tools accept the save folder, the folder containing it, or the `game` file
directly.

---

## Shortcut: the test saves already exist

The saves from the earlier research work as they are, and they save assembling two
experiments.

| Save | Good for | Why |
|---|---|---|
| `Beyond Space` | **E2** | 1,543 credits in the `playerBank` and five NPC ships with their own `<shipBank>` (`ca` from 785 to 6,901). You can buy. |
| `ship17 sem visao` | **E3** | it is already the assembled scenario: `CS DASHERS SCRAPPER` (sid=55) is a complete Civilian NPC, with `<asi>`, `<markers>` and `<shipBank ca="12309">`, and the `hostmap` is exactly the design in section 2.5 — `accessTrade="true"` with `accessVision="false"` and `accessShip="false"`. |

**Careful with `ship17`: the `playerBank` is at `ca="0"`.** With no credits you
cannot buy, so the experiment there starts by **selling**. That is not a problem —
selling answers the same question and tests one extra thing, which is whether the
game respects the ship's `ca` as a ceiling on what it can pay. If you want to buy
as well, give the player credits first through the savegame editor.

Work on a copy of both, not on them.

## E1 — The noise floor

**Without this, no later experiment is interpretable.** A save written twice
already differs in thousands of points: clocks, crew position, orbital phase,
counters. If you do not measure that floor first, the purchase of ten ore will be
buried in the middle of it.

There are **two** measurements, and the difference between them is information in
itself.

### E1a — the pure floor

How much changes in a save cycle, with nothing happening in the game.

1. Open the game, load the game, save **immediately**, exit to the menu.
2. `python3 tools/save_snapshot.py PATH/TO/SAVE E1a-1`
3. Load again, save immediately again, exit.
4. `python3 tools/save_snapshot.py PATH/TO/SAVE E1a-2`

```bash
python3 tools/save_diff.py \
    "$(python3 tools/save_snapshot.py --path E1a-1)" \
    "$(python3 tools/save_snapshot.py --path E1a-2)" \
    --learn-noise experiments/noise-puro.json
```

### E1b — the realistic floor

E2 will not be a pure cycle: negotiating takes game time, the crew walks around,
the modules produce. The noise E2 will carry is this one, and it is bigger.

Same thing, but **let the game run roughly as long as a negotiation takes** — a
minute on the clock, without giving any order — before saving.

```bash
python3 tools/save_diff.py \
    "$(python3 tools/save_snapshot.py --path E1b-1)" \
    "$(python3 tools/save_snapshot.py --path E1b-2)" \
    --learn-noise experiments/noise.json
```

The `noise.json` from E1b is the one the other experiments use. The
`noise-puro.json` stays as a reference: the difference between the two is exactly
what "time passing" costs, and it is the number the check in section 2.7 will have
to tolerate.

**What to note down:** how many raw changes appeared and in which areas. That
number is interesting in itself — it says how much the save moves on its own,
which is what the check in section 2.7 will have to tolerate.

**Careful:** if `--learn-noise` says it recorded zero signatures, the game did not
save between one snapshot and the other. Check with `--list`: two snapshots with
the same digest are identical.

**Refine the profile.** A single pass of E1 learns little. Repeat it two or three
times, with different intervals of game time between saves, always accumulating
into a new profile, and use the largest. Too little noise leaves junk in the
answer; too much noise hides the answer.

---

## E2 — Trade with a native NPC

The question: **does the transaction get recorded as an event, or only as final
state?**

It needs a ship from another faction parked in your sector. It offers HAIL, TRADE
and MISSIONS with nothing built (section 1.9).

1. Save with the ship already in the sector, before any contact. Snapshot
   `E2-antes`.
2. In the game, make **one purchase only, of one item only, in a round quantity**.
   Note down: what you bought, how much, for how many credits, and from which ship.
3. Save. Snapshot `E2-depois`.
4. Compare:

   ```bash
   python3 tools/save_diff.py \
       "$(python3 tools/save_snapshot.py --path E2-antes)" \
       "$(python3 tools/save_snapshot.py --path E2-depois)" \
       --noise experiments/noise-puro.json --noise experiments/noise.json \
       --focus economy --verbose
   ```

   And **again without `--noise`**, to check that the filter did not eat part of
   the transaction. It is the two outputs together that answer.

**What to answer:**

- did the credits leave the `playerBank`? does the amount match what you paid?
- did the cargo show up in an `<inv>` on your ship?
- **did the selling ship's `<shipBank>` change?** This is the most important of the
  five questions. If it records the sale, the server can reconcile by comparing
  against the bank it built itself.
- is there any history, log or receipt node anywhere? Run it once without
  `--focus` to sweep the whole save and look for anything that resembles a
  transaction record.

---

## E3 — Trade with an injected ship

Now with the `<shipBank>` **we** built, with known stock and known credits. It is
the project's real configuration.

```bash
python3 tools/inject_npc_ship.py --help
```

1. Inject a ship into a copy of the save, with known stock and known `ca`.
2. Snapshot `E3-antes`. Open the game and confirm the ship is there and offers
   TRADE.
3. Buy from it. Save. Snapshot `E3-depois`. Compare as in E2.

**What to answer:**

- does the injected ship's stock go down, and does that **persist** in the save?
- does the game respect `ca` as a limit on what it can buy from you?
- is the behaviour the same as the native NPC in E2, or is the injected ship
  treated differently?

---

## E4 — Several transactions

The question: **can you tell three purchases from one big purchase?** That is what
decides whether reconciliation is per transaction or by net delta.

In a single session, without saving in between: buy 10 of A, buy 10 of A again,
buy 5 of B, sell 20 of C. Note down the order. Save, snapshot, compare.

If the save only keeps the final state, the answer is that reconciliation is by
net delta — which is **enough**, because the server built the initial state and
knows exactly where it started from.

---

## E5 — Provenance

The question that is not in the design document and turned up while writing this
script: **with two neighbours in the same sector, can you tell what came from
whom?**

If the save only records "the player gained 10 ore", and there were two ships
selling ore, the server does not know who to credit. That breaks reconciliation
with more than one neighbour, which is the normal case for a room.

Inject **two** ships in the same sector, each with a resource the player does not
own and that the other one does not have either — marker resources. Buy from both.
Compare.

If provenance is not inferable from the save, consignment has to carry the marker:
each neighbour exposes a disjoint set of resources, or reconciliation becomes an
approximation and the design has to admit it.

---

## E6 — The storefront

It was not in the original script. It turned up when E3b showed that fog cannot be
forged on a player ship, and the project decided the portrait becomes a shop built
on an NPC hull (section 2.5).

You assemble it with `--hull`, which picks an unexplored hull from the save itself:

```bash
python3 tools/inject_npc_ship.py --into SAVE --out OUTPUT \
    --hull --name "LOJA DO FULANO" --faction Civilian \
    --credits 500 --stock 1922:30,176:10
```

**What to answer:**

- does the storefront appear with `State: Normal (Unexplored)`, roof closed?
- does it offer TRADE?
- **how much of each resource does the panel offer?** This is the design that goes
  after the mystery in item 12 of `findings.md`. Consigning 30 of one and 10 of
  the other:
  - 30 becomes 26 **and** 10 becomes 10 → the loss has a cap, it is not an offset
  - 30 becomes 26 **and** 10 becomes 6 → it is a constant −4
  - both full → the problem was the previous hull, not the mechanic

### Result (2026-07-31)

**The storefront works.** `State: Normal (Unexplored)`, roof closed, silhouette
with no interior — the hull's fog came through the load, as E3b predicted. It
offers TRADE, MISSIONS and SERVICE, with its own captain coming from the hull.

**And item 12 came out:** Chemicals **10 of 10**, Plates **26 of 30**. It is a cap
per resource, not an offset. See `findings.md`, item 12.

**The fog came through the complete cycle** — load, play, negotiate and save — with
`fog=true`, `unex=1`, `forceRoof=1` and the 518 cells at `fg=0` intact. It was not
just the load: the game rewrote the storefront preserving everything.

**The storefront's bank reconciles just like a native ship's:**

| | before | after | delta |
|---|---|---|---|
| `playerBank` | 1,157 | 397 | **−760** |
| storefront's `shipBank` | 500 | 1,260 | **+760** |

**And the goods closed item 8 in practice.** The storefront lost 5 Chemicals. The
buyer gained **1 in storage and 4 in crates on the floor**. They add up to the 5,
but anyone counting only `inStorage` would see +1 and conclude that 4 had gone
missing — and would report as lost what was sitting three metres from the shelf.

**As a bonus, E4.** The session had several transactions — the panel counts up to
four — and the save kept only the final state. No log, no order, no receipt: **net
delta**, as phase 3 assumes. E4 in the script is answered for free.

---

## E7 — Grafting the room's galaxy into a player's save

Not in the original protocol. It comes from a design question: today a player
has to create a game with the room's exact seed **and** every scenario option
right, or the fingerprint refuses their save. With thirty people arriving from a
Discord invite, that is dozens of refusals over a checkbox nobody can see
afterwards.

The idea was to keep a canonical galaxy on the server and transplant each new
player's ship into it. Building it turned the direction around: the player's
state is not one node — ship, crew, bank, research and faction standing sit
scattered across the save — while the galaxy **is** one node. So the tool grafts
`<starmap>` into the player's save instead of moving the player into a galaxy.

```bash
python3 tools/graft_galaxy.py --galaxy ROOM_SAVE --into PLAYER_SAVE --out RESULT
```

**Built and verified structurally** on the hardest case available: a 124-day
colony grafted into a galaxy from a different seed.

| | galaxy digest | ship | age | at |
|---|---|---|---|---|
| the room's galaxy | `c06bd078ea891448` | HSS YANNI | 1.29 | system 31, celeid 1689 |
| the player | `91b922a90ccc3680` | MAELSTROM HARBOR | 124.47 | system 1, celeid 0 |
| **grafted** | **`c06bd078ea891448`** | **MAELSTROM HARBOR** | **124.47** | **system 31, celeid 1689** |

Exactly one player fleet, 64 systems, `@sys`/`@pa` agreeing, and the player's
`playerBank` of 1,379,043 credits untouched. Both inputs byte-identical
afterwards.

**Answered: the game loads it.** Measured 2026-07-31 — the grafted save opened
at day 124.11 with the whole 124-day base, its twenty crew and its bank intact,
sitting in the room's galaxy. After the game saved it back, everything held:
same digest `c06bd078ea891448`, same position (system 31, `celeid` 1689), same
age, 64 systems, exactly one player fleet.

**So the onboarding story changes.** Create a game with any seed and any
options; the server hands back a save already in the room's galaxy. The
fingerprint stops being a gate and becomes a check.

**One caveat the test surfaced.** The save used was an asteroid base, not a
mobile ship — `sta="1"` on the `<ship>` root is what marks it. The game loaded
the asteroid as a ship, which is how a base is stored, and the graft did not
care. But a base cannot travel, so that player would sit in the starting sector
forever: a permanent trading post rather than an explorer. That is a role, not a
bug, but a room should know which it is getting.

**Still worth checking:** the same graft with an ordinary mobile ship, and what
the starting sector looks like up close. Its `<space>` came from the player's
original body and the game does not regenerate sectors on load (section 1.6), so
it keeps the asteroid field it was born with while the new galaxy declares
different `<stuff>` for that body.

---

## What each result implies

| E2/E3 result | Implication |
|---|---|
| The `<shipBank>` persists the sale | **Reconciliation by net delta. Phase 3 ships as it stands in the design document.** The server built the bank, knows the initial state, and the difference is the transaction. |
| The `<shipBank>` does not persist | The sale is not reconstructible from the ship's side. All that is left is inferring from the `playerBank` and from the cargo — E5 becomes mandatory and each neighbour has to expose disjoint marker resources. |
| Not even usable final state | Phase 3 changes in nature. Native trade becomes flavour, not economy, and the real exchange happens through consignment outside the game: the neighbour asks over the web, the server delivers into the hold at the next checkout. Less elegant, and it depends on none of this. |

---

## Results

*To be filled in as the experiments run. Record what you measured, not what you
concluded — the conclusion changes, the measurement stays.*

### E1a — pure floor (measured 2026-07-31, save `Beyond Space`)

Two load-and-save cycles, **with the game paused**, without any order.

- **11,434 raw changes**, which become **103 signatures** by shape
- 11,432 of them carry an id in the path
- the game **recreates the objects inside cells on load**: each ship's `idCnt`
  advances by thousands (ship 2 went from 20,417 to 22,913), 676 `<l>` nodes
  disappear and 676 appear, 625 change `id`
- areas: `game/ships/ship/e/l` dominates; by attribute, `hf` (3,676), `atm`/`atm2`
  (1,685), `x`/`y` (1,559), then `id`, `rot`, `m`, `invw`, `fg`
- outside the ships, only seven shapes change on their own, among them
  `masterData/@idCounter`, `space/@idCnt` and `hostmap/map/l @relationship` — the
  relationship between factions decays by itself, as section 1.8 says

**Paused does not mean still.** Nobody was simulating; the game was reallocating on
load. That is what makes any object identity inside `<e>` useless between one
session and the next — including for the server.

**Careful using this profile.** Seven of the 103 signatures touch the economy,
among them `feat/prod/inv/s @inStorage` (the buffer of a machine in production)
and whole `<inv>` nodes appearing and disappearing. That means **the profile can
silence part of a real transaction.** In E2, run the diff **twice, with and without
`--noise`**, and compare.

### E1b — realistic floor (measured 2026-07-31, same save)

Two cycles with about a minute of game time running, without any order.

- **23,863 raw changes**, which become **323 shapes** — double the pure cycle
- **228 shapes** appear only when the game is running; 8 appear only in the pure
  cycle
- what time brings: crew inventory (weapon, armour), nutrition
  (`props/Food/stored` with carbs, fat, protein, toxins, vitamins), buffers of
  machines in production (`feat/prod/cinv`), items in transit (`items/i @dstId`,
  `@grndTime`), and movement targets (`targetX`, `targetY`)

**Use the two profiles together**, because neither sees everything:

```bash
--noise experiments/noise-puro.json --noise experiments/noise.json
```

### The filter is safe for the E2 question

Checked against both profiles: the four signals the answer depends on **come
through clean**, none of them is noise.

| Signal | State |
|---|---|
| `playerBank @ca` | comes through |
| `shipBank @ca` | comes through |
| storage stack `@inStorage` | comes through |
| storage stack `@elementaryId` | comes through |

**There is only one risk left:** `feat/inv|added` is noise, meaning a whole `<inv>`
being born in a storage gets silenced. So **buy a resource the ship already has in
stock** — that way the change is a quantity on an existing stack, which comes
through, instead of a new node, which does not.

### E2 — trade with a native NPC (measured 2026-07-31, save `Beyond Space`)

Bought: **1 Hyperium (elem 172) for 386 credits**, from the `MFB STRONGHOLD`
(sid=4336, Merchant).

**The answer is yes, and it is clean. The `<shipBank>` records the sale.**

| | before | after | delta |
|---|---|---|---|
| `playerBank @ca` | 1543 | 1157 | **−386** |
| `shipBank @ca` of sid=4336 | 6901 | 7287 | **+386** |

The two sides match to the credit. So do the goods: the seller went from 3 to 2
Hyperium, and the player gained 1.

**There is no transaction record anywhere.** No log, receipt or history — only the
final state on both sides. Since the server is the one that builds the portrait's
`<shipBank>`, it knows the exact initial state, and the difference is the
transaction. **Reconciliation by net delta, and phase 3 ships as it stands in the
design document.**

**But the goods were in flight.** At the moment of the save the Hyperium **had not
arrived**: the player's destination stack had `onTheWayIn="1"` and `inStorage`
unchanged, and there was an `<i eid="172">` in the ship's `<items>`, with
`mo="BeingMoved"` and `dstId`. The seller's stock had already been debited.

This is a reconciliation rule, not a curiosity: **anyone summing only `inStorage`
sees the cargo vanish.** The server has to count three places — `inStorage`,
`onTheWayIn`, and the items in flight — or it will accuse the player of losing
goods the game itself is still delivering.

The noise filter behaved: 19,651 raw changes became 46 with both profiles, and 113
without them. The four signals that mattered survived, as predicted. The remaining
noise was wreck salvage happening in parallel (Hull Scrap going to the shuttles)
and machines consuming Energium and ore.

### E3 — trade with an injected ship

### E4 — several transactions

### E5 — provenance

### Conclusion
