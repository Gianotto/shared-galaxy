# Anatomy of a Space Haven savegame

*[Leia em português](savegame-format.pt-BR.md)*

Notes gathered by measuring real saves from game 1.0.4, not by reading its code.
Every claim here was verified by loading the modified save into the game and
looking at the result on screen; where doubt remains, it is said so.

What motivated the survey was a specific question: can several players share one
galaxy, each running their own game, with a server stitching the parts together?
The answer turned out to be more interesting than the question.

## How a save is organised

```
save/
  game               the whole game and the sector you are in right now
  ships/shipNNNN     a ship that is in another sector, one file per ship
  info               version and date
  stats.bin, timeline.xml
```

The ship file's name is `ship` followed by its `sid`. They are loose XML
documents, with `<ship>` at the root, no header, ending in a line break.

The split matters: **`game/ships` are the ships of the loaded sector**, and
`ships/` are the ones that are far away. Moving a ship between the two is what
the game does when you travel.

## Identifiers

`masterData/@idCounter` is the save's global counter: every new entity —
character, ship, object — takes its `entId` from there. Reserving an id and
advancing the counter is what the editor does to create a crew member without
colliding with anything.

The ids **inside** a ship (`id`, `eid`) are local to it. Two ships living in the
same save share 448 ids without any conflict, which makes copying a whole ship a
cheap operation: only the `sid` and the crew's `entId` need renumbering.

Observed consumption of the global counter: 55 in a freshly created game, 4,539
on day 37, 62,174 on day 124. The ceiling of a 32-bit integer is four orders of
magnitude away.

`starmap/@objectIdCounter` is a separate counter, for fleets and star map
objects.

## The star map and the seed

`<starmap>` holds the galaxy's size (`w`, `h`) and the list of systems. Each
system has:

- `sn` and `smn`: long and short name, **in hexadecimal**
- `bodies/l`: star, planets, moons, asteroids, asteroid fields. Each body has
  its own seed, type, `celeid`, orbit radius (`ox`, `oy`) and what it orbits
  (`centerId`)
- `emptySectors/l`: the rest of the terrain — asteroid fields, debris, bases,
  mines
- `clouds`: nebulae

**The seed typed at creation reproduces the whole galaxy.** Two games created
with the same seed and the same options gave identical maps: same systems, same
bodies with the same seeds, same terrain sectors, same starting point. This is
the foundation of any shared-universe idea, because it means a coordinate means
the same thing to every player, and celestial body ids are common vocabulary.

**The seed does not reproduce the rest.** The starting crew comes out different
(other names, other attributes, other skills), the ship's name changes, and the
insides of the ships do not match: on the starting ship 338 out of 630 elements
coincide, and the abandoned ship in the starting sector has 414 elements in one
game and 407 in the other.

The save **does not store the seed** that was typed — the root's `seed`
attribute came out as `0` in every game examined, including completely different
galaxies. Anyone wanting to compare has to write the seed down elsewhere.

`tools/compare_galaxy.py` builds a fingerprint of the generated world and
compares saves. It deliberately ignores what changes while you play: the
position and orbital phase of the bodies, the temporary sectors (missions, ships
on the map, new home offers) and the system names, which in a freshly created
save are still empty and only show up later.

## Where the player is

Three things have to agree:

| Where | What |
|---|---|
| `<f isPlayer="true">` inside a celestial body's `<fleets>` | the fleet |
| `starmap/@pa` | the `id` of the body it is at — **not** the `celeid` |
| `starmap/@sys` | the system's `systemId` |

Changing all three relocates the player, and the game accepts it without
complaint. The destination body usually has no `<fleets>`; it has to be created,
between `<stuff>` and `<info>`.

A celestial body has **two** ids: `id`, local to the save and taken from
`starmap/@objectIdCounter`, and `celeid`, derived from the seed and therefore
the same in every save of the same galaxy. `@pa` points at the `id`. See
`findings.md`, item 1.

Two presentation details, in the body's `<info>`:

- `visited` and `isVisible` control the "Unvisited sector" label and whether the
  place shows on the map. In a new game the **starting sector itself** comes
  with both turned off, and the game turns them on at some point during play.
- `isst="1"` appears exactly once in the save, always on an asteroid: it is the
  player's origin. It and `pa` coincide in a new game and diverge once the
  person travels, so they are separate concepts.

## What a loaded sector is made of

| Node | Content | On changing sector |
|---|---|---|
| `<space>` | rock cells, ore fields, mining orders | stays |
| `<ships>` | ships present | the local ones stay, yours goes |
| `<spaceItems>` | loose items floating around | stays |
| `<crafts>` | small docked ships, linked by `homeSid` | go with you |

The `<space>` is built from the celestial body's `<stuff>`: the ores listed in
`<mining>/<toMine>` are exactly the ones the body declares.

**The game does not regenerate the sector on load.** Relocating the player
without touching the `<space>` takes the old scenery along; emptying the
`<space>` leaves the person in the void, and the `visited` flag does not change
that. A sector is only generated during a trip made inside the game. Emptying
can be done precisely; filling cannot — that would require writing an asteroid
field generator, and the format is known but the result would not look like what
the game draws.

## Who a ship belongs to

Found out the hard way, after testing four wrong hypotheses:

**`<ship>/<settings>` has `of` (faction id) and `owner` (side name).** That is
what rules. A ship copied from yours stays yours as long as those two say `461`
and `Player`, even if the crew belongs to another faction and even if an NPC
fleet is registered pointing at it.

Registering the ship in a star map fleet is also necessary — an `<f>` on the
celestial body, with `factionId`, `isPlayer="false"` and a `<createdShips><l>`
whose `createdShipId` is the ship's `sid` and `created="true"`.

With no declared owner the game improvises, and the improvisation depends on the
crew:

- `Player` crew: the game hands you the whole ship
- crew of another faction: the game treats the people as castaways, your shuttle
  goes to fetch them and the ship becomes a claimable derelict

NPC ships usually have three nodes that yours does not: `<asi>` (the AI — radio,
combat stance), `<shipBank>` (its own credits and pricing rules, this is what it
trades with) and `<markers>`. A ship without a `<shipBank>` has nothing to trade
with; there is precedent for this in the game.

## Who sees what

The inside of someone else's ship is **not** hidden by the ship's data. An
authentic NPC ship, transplanted from another save with all its fog (`fg="0"` on
every cell), `unex="1"` and `forceRoof="1"`, stayed open.

What rules is `hostmap/map/l`, the table of relations between factions, per
pair:

| Permission | What it governs |
|---|---|
| `accessTrade` | trading |
| `accessShip` | boarding the ship |
| `accessVision` | seeing inside it |
| `accessHire` | hiring the crew |

In a new game the player starts **Friendly** with Civilians, Traders and
Military, with relationship around 70, and the permissions all come turned on —
which is why you can see the inside of their ships on the very first day. Over
time the relationship decays to Neutral and the doors close. Turning
`accessVision` off closes the interior immediately.

Derelicts are a different mechanism: they are registered in the body's `<stuff>`
with `derelict="true"` and only reveal themselves on boarding, regardless of
faction.

## What the game gives away for free

A ship of another faction sitting in your sector offers **HAIL, TRADE and
MISSIONS** without anything needing to be built, and it even generates a mission
of its own. For the idea of trading between players this is significant: the
interface already exists, it is native, and it works without both players being
online — the ship sits there like an open shop.

What such a ship trades is **its** stock and credits, not the game's. Whoever
builds the portrait decides what gets put on show.

## Summary of what works and what does not

Works, verified in the game:

- reproducing the same galaxy across several saves from the seed
- moving the player to any celestial body, in any system
- unloading a sector completely, piece by piece
- inserting another player's ship as a legitimate NPC, with owner, fleet, trade
  and a closed interior
- creating a crew member, moving cargo, adjusting relations between factions

Does not work, from outside the game:

- generating the scenery of a new sector
- making anything appear in a game that is open: the game rewrites the save when
  it saves, so anything coming from outside only gets in between sessions
