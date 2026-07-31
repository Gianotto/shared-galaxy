# Shared Galaxy — server design

*[Leia em português](shared-galaxy-server.pt-BR.md)*

Design document for a server that lets several Space Haven players share one
galaxy, each running their own game, without a single line of the game's code
being changed.

Written to be read on its own, by whoever implements the server in a separate
repository. Everything stated here as fact was measured by loading modified
saves into game 1.0.4 and looking at the result; what is an assumption is marked
as such.

Origin project, where the tools for reading and writing saves already exist:
<https://github.com/Gianotto/Space-Haven-SaveGameEditor>

---

# Part 1 — What the game allows

## 1.1 What cannot be done, and why

Before the design, the three limits that shape it. None of them can be worked
around from outside the game.

**The simulation does not run without the client.** There is no headless mode.
The game's simulation classes (world, things, AI, star map) reference the
graphics library in 36% to 48% of cases and call the interface package directly
in 10% to 23%. There is no seam to cut. An authoritative server that simulates
the world is out of reach.

**The simulation is not deterministic.** Of the simulation classes that draw
random numbers, 312 create a generator with no seed. Two machines starting from
the same state diverge immediately, so lockstep — the standard multiplayer
technique for games of this genre — is not viable.

**The game owns the file while it is open.** It rewrites the save when it saves.
Anything the server wants to put inside someone's game has to arrive with the
game closed.

There is networking code in the jar (`fi.bugbyte.shared.matchmaking`, 21 classes
with a UDP socket), but **no Space Haven class references it** — it is a shared
library from Bugbyte's other games, dead weight along for the ride.

## 1.2 Anatomy of a save

```
save/
  game               the whole game and the sector the player is in right now
  ships/shipNNNN     a ship that is in another sector, one file per ship
  info               version and date
  stats.bin, timeline.xml
```

The ship file's name is `ship` + its `sid`. They are loose XML documents, root
`<ship>`, no XML header, ending in `</ship>` and a line break.

The central distinction: **`game/ships` are the ships of the loaded sector**;
`ships/` are the ones that are far away. Moving a ship between the two is what
the game does when the player travels.

Typical size: the `game` of a 124-day game is 4.5 MB; a freshly created save is
390 KB.

## 1.3 Identifiers

`masterData/@idCounter` is the save's global counter. Every new entity —
character, ship, object — takes its `entId` from there. **To create anything in
a save, reserve the current value and increment the counter.**

Ids **inside** a ship (`id`, `eid`) are local to it: two ships living in the
same save share 448 ids without conflict. Copying a whole ship requires
renumbering only the `sid` and the crew's `entId`.

`starmap/@objectIdCounter` is a separate counter, for fleets and star map
objects.

Observed consumption: 55 in a new save, 4,539 on day 37, 62,174 on day 124. The
ceiling of a 32-bit integer is four orders of magnitude away. **There is no
practical limit on players per room coming from here**, because each save has
its own counter and they never meet — all that is needed is renumbering whatever
is injected.

> The limit comes from elsewhere: **neighbours visible in the same sector**
> compete for factions. The `hostmap` is indexed by pair of sides, not by ship,
> and the game has about nine usable sides. Two neighbours on the same side stop
> being separately controllable, and a war declared on one hits the other. See
> `findings.md`, item 11.

## 1.4 The seed reproduces the galaxy

Verified with two games created with seed `1654267488` and the same options:

**Reproduces:** the systems (64), the celestial bodies (123) with their own
seed, type, orbit radius and what they orbit, the terrain sectors (99), the size
of the galaxy and **the starting point** (x=75724, y=235080).

**Does not reproduce:** the starting crew (other names, attributes and skills),
the name of the player's ship, and the insides of the ships — 338 out of 630
elements coincide on the starting ship, and the abandoned ship in the starting
sector has 414 elements in one game and 407 in the other.

This is the foundation of the project: **a coordinate and a celestial body id
mean the same thing to every player in the room**, without the server having to
distribute any map. And every player gets their own crew for free.

**The save does not store the seed that was typed** — the root's `seed`
attribute comes out as `0` in every game, including completely different
galaxies. The one that needs to know a room's seed is the server.

Tool ready for checking whether two galaxies are the same:
`tools/compare_galaxy.py` in the editor's repository.

## 1.5 Where the player is

Three things have to agree:

| Where | What |
|---|---|
| `<f isPlayer="true">` inside a celestial body's `<fleets>` | the fleet |
| `starmap/@pa` | the `id` of the body it is at — **not** the `celeid` |
| `starmap/@sys` | the system's `systemId` |

Changing all three relocates the player and the game accepts it. The destination
body generally has no `<fleets>`; it has to be created, between `<stuff>` and
`<info>`.

**A celestial body has two ids and confusing them puts the neighbour in the
wrong sector.** `id` is local to the save, taken from
`starmap/@objectIdCounter`; `celeid` comes from the seed and is the only one
that means the same thing to every player in the room. `@pa` points at the `id`.
Measured: `@pa=226` matches `<l id="226" celeid="1689">`, and there is no body
with `celeid=226` in the save. See `findings.md`, item 1.

In the body's `<info>`:

- `visited` and `isVisible` control the "Unvisited sector" label and whether it
  appears on the map. In a new game **the starting sector itself comes with both
  turned off** — that is factory behaviour, not a defect.
- `isst="1"` appears exactly once in the save, always on an asteroid: it is the
  player's origin. It coincides with `pa` in a new game and diverges once the
  person travels.

## 1.6 What a loaded sector is made of

| Root node | Content | On changing sector |
|---|---|---|
| `<space>` | rock cells, ore fields, mining orders | stays |
| `<ships>` | ships present | the local ones stay, the player's goes |
| `<spaceItems>` | loose items floating around | stays |
| `<crafts>` | small docked ships, linked by `homeSid` | go with the player |

The `<space>` is built from the celestial body's `<stuff>`: the ores in
`<mining>/<toMine>` are exactly the ones the body declares.

**The game does not regenerate the sector on load.** Relocating without touching
the `<space>` takes the old scenery along; emptying it leaves the player in the
void, and the `visited` flag does not change that. A sector is only generated
during a trip made inside the game.

**Design consequence:** the server does not place a new player anywhere. Everyone
is born at home and takes territory by flying — which makes for a better game,
besides being cheaper.

## 1.7 Who a ship belongs to

**`<ship>/<settings>` has `of` (faction id) and `owner` (side name). That is what
rules.** A copied ship stays the player's as long as those two say `461` and
`Player`, even with a crew from another faction and even with an NPC fleet
registered pointing at it.

Registering the ship in a star map fleet is also necessary: an `<f>` in the
celestial body's `<fleets>`, with `factionId`, `isPlayer="false"` and:

```xml
<createdShips>
  <l seed="..." createdShipId="SID" created="true" station="false"
     shipDamagedNoFTL="false" crew="N" cryoCrew="0" monsters="0" bigMonsters="0"
     hives="0" infesters="0" flybots="0" walkers="0" roboBase="0"
     derelict="false" addLoot="false" inHyper="false" sx="WIDTH" sy="HEIGHT"/>
</createdShips>
```

With no declared owner the game improvises, and the improvisation depends on the
crew:

- `Player` crew → the game hands the whole ship to the player
- crew of another faction → the game treats the people as castaways, the
  player's shuttle goes to fetch them and the ship becomes a claimable derelict

NPC ships usually have three nodes the player's does not:

- `<asi>` — the ship's AI: radio, hail cooldowns, combat stance
- `<shipBank>` — its own credits and pricing rules. **This is what it trades
  with.** Without this node the ship has no way to trade
- `<markers>` — docking points

Real `<shipBank>` example:

```xml
<shipBank s="Civilian" ca="12309" cr="0" slp="10066" blp="9891" spmd="2">
  <markup>
    <n element="2053" howMuch="1" consumeEvery="1"/>
  </markup>
  <discount/>
</shipBank>
```

## 1.8 Who sees what

The inside of someone else's ship is **not** hidden by the ship's data. An
authentic NPC ship, transplanted from another save with `fg="0"` on every cell,
`unex="1"` and `forceRoof="1"`, stayed open.

What rules is `hostmap/map/l`, the table of relations between factions, per
pair:

| Permission | What it governs |
|---|---|
| `accessTrade` | trading |
| `accessShip` | boarding the ship |
| `accessVision` | seeing inside it |
| `accessHire` | hiring the crew |

In a new game the player starts **Friendly** with Civilians, Traders and
Military, relationship around 70, and the permissions all come turned on — which
is why you can see the inside of their ships on the first day. Over time the
relationship decays to Neutral and the doors close.

**That table is the server's control panel** over what one player can do with
another's portrait.

> **Corrected on 2026-07-31 by E3 and E3b.** `accessVision="false"` does **not**
> close the interior: it survives the load intact and the ship stays visible.
> `accessTrade` **works**, and it is what holds up section 2.6.
>
> The fog has a different source of truth. Measured with a single variable: a
> portrait built from a never-explored NPC ship **stays hidden**; built from a
> player's ship, the game erases `unex`/`forceRoof` and restores the original
> `fg`. Since a neighbour's portrait would be their ship, and a player's ship is
> always explored, **the portrait is born revealed**.
>
> This forces a design decision — accept the visual exposure, or build the
> portrait on an NPC hull instead of the neighbour's ship. See `findings.md`,
> item 10.
>
> On theft, see 2.7: there is no lock, but boarding declares war.

Derelicts are a different mechanism: registered in the body's `<stuff>` with
`derelict="true"`, they only reveal themselves on boarding, regardless of
faction.

## 1.9 What the game gives away for free

A ship of another faction sitting in the player's sector offers **HAIL, TRADE
and MISSIONS** with nothing built, and it even generates a mission of its own.
Verified: you can trade without ever having had contact with the crew.

For the project this is decisive: **the trading interface between players does
not have to be invented.** It is native, and it works without both being online.

What such a ship trades is **its** stock and credits, not the game's. Whoever
builds the portrait decides what gets put on show.

## 1.10 There is no player identity in the save

Searched for and not found: `steam`, `account`, `userId`, `playerId`, SteamID64
prefix — zero occurrences. What exists is `settings/@f = 461` (the player's
faction, the same in every save in the world), the `id=0` fleet and the
`playerBank`.

The game has Steam integration in the jar, including authentication tickets, but
none of it reaches the savegame.

**Identity has to be the server's.** Advantages: it works for copies outside
Steam, it depends on no API, and inside the save itself "me" is always faction
461, with no ambiguity.

Since the game has a fixed set of factions, two neighbours can land on the same
one. **What distinguishes one player from another on screen is the ship's name**
(`sname`), which is free text.

---

# Part 2 — Server design

## 2.1 Principles

**The server owns the truth.** It keeps each player's save, lends it out for
each session and gets it back. The player has no canonical copy.

**Cooperative, not competitive.** Everyone runs the game on their own machine,
on files they can open. A design where you win by defeating the others invites
exactly the behaviour that cannot be policed. A design where you survive because
the neighbours supply you makes cheating pointless.

**Out continuously, in between sessions.** The autosave feeds the server while
you play; what comes back arrives at the next opening.

## 2.2 Identity and rooms

Account created on the server, token kept on the client. No Steam.

A **room** is:

| Field | Description |
|---|---|
| `id` | short identifier |
| `seed` | the creation seed, which defines the galaxy |
| `options` | the exact creation options (difficulty and the 21 scenario parameters) |
| `password` | optional |
| `roster` | players, each with their canonical save |
| `world` | shared state: who is where, consignments, events |

The listing shows the name, the number of players, and whether it has a
password. The client asks for the password only at the moment of joining.

For now: one server, one room, one seed. The structure is born per-room so that
it does not have to be redone.

**The creation options matter as much as the seed.** Two games with the same
seed and different options do not give the same galaxy. The room has to publish
the options and the client has to check them against the save it receives.

## 2.3 A new player joining

It is the only moment that requires the player, because of 1.6 — the server
cannot generate a starting colony.

1. the client shows the room's seed and the exact options
2. the player creates the game in the game itself, normally
3. the client uploads the freshly created save
4. the server checks that the galaxy matches the room's (fingerprint, see
   `tools/compare_galaxy.py`) and adopts the save as that player's canonical one

Once only. After that the server owns it.

If the fingerprint does not match, the save is refused with an explanation —
almost always it is a different creation option.

## 2.4 The session cycle

```
checkout  → the server assembles the player's save, with neighbours and pending
            deliveries already inside, and hands it to the client
play      → the client saves into a folder dedicated to the room and the player plays
heartbeat → the client watches the autosaves and sends the state to the server
return    → the client uploads the final save; the server reconciles and stores it
```

**Checkout deadline.** Whoever does not return goes back to the state they
picked up. This plugs the "I only return the session that went well" hole and
handles a stuck client.

**Crash recovery.** The game can close on its own. The client has to be able to
return the last autosave, and the server validates it the same way.

**The last heartbeat is what stands.** After the player disconnects, that is the
state the others see.

## 2.5 What the server injects at checkout

**The portrait is not the neighbour's ship. It is a shop window.**

The first version of this document said to copy their ship. E3b showed that this
does not work: a ship's fog only holds up if the source ship was never explored,
and a player's ship is always explored. The portrait would be born with the roof
open and the crew on show (`findings.md`, item 10).

So the server builds a shop, not a copy. For every neighbour in the room whose
fleet is at the same celestial body:

1. **an NPC hull taken from the destination save itself**, never explored, with
   a new `sid` from `masterData/@idCounter`. It comes from inside the player's
   own save, which also settles the rule in section 2.13: no game content is
   redistributed, because nothing leaves their installation
2. a new `entId` for each of the hull's crew members, from the same counter
3. `<ship>/<settings>` with the `of` and `owner` of the chosen faction
4. a `<shipBank>` containing **only what that player consigned**, with `ca`
   limiting how much it can buy
5. the storages emptied and filled only with the consigned goods, one resource
   per storage
6. **the fog is not touched.** The hull is born hidden already; writing to the
   fog is the thing that does not work
7. an `<f>` fleet on the celestial body, with `createdShipId` pointing at the
   `sid`
8. in the `hostmap`, that faction's permissions: `accessTrade` according to the
   relationship, `accessVision` and `accessShip` turned off

The ship's name (`sname`) carries the identity of the owning player.

**What is gained, beyond the fog.** The portrait no longer inherits the source
ship's build queue — in E3 the crew started building and consuming the consigned
stock. It stays small: a shop-window hull instead of 460 KB of someone else's
ship per neighbour. And nobody's ship layout travels.

**What is lost,** and it is real: the room no longer shows *So-and-so's ship*.
That comes back through the web map of section 2.11, where it costs nothing and
nobody has to trust anybody to see it.

Pending deliveries (closed purchases, gifts) go straight into the hold of the
player's ship, as stacks in a storage's `<inv>`.

## 2.6 Consignment and reconciliation

The legitimate fear is: "someone buys my entire stock and I open the game with
nothing."

The design that solves it: **market stall, not cargo hold.**

- the player consigns what they want to sell; **only that goes into the
  portrait**
- the rest of the stock does not exist in that copy, so nobody can buy it
- the `ca` credits limit how much that ship can buy
- at reconciliation the server deducts from the consignment and credits the
  seller
- the real hold is never exposed

Second lock: the per-faction permissions. A neighbour can trade without seeing
the hold; someone you are on bad terms with neither trades nor comes near.

## 2.7 Stance on cheating

The game runs on the player's machine, on files they can edit. There is no
solution to this, and the document does not pretend there is.

What can be done, and it is a lot:

- **the end of save scumming.** There is a single copy and the server knows
  which one it is. Reloading an old save is not accepted
- **the end of duplication via parallel session**
- **checking, not guessing.** The server assembled the file it handed over, so
  on return it compares the two and asks: how much time passed and how much
  would the modules produce in it? where did these credits come from? did this
  cargo fit in the ship that carried it? was this crew member on board at
  checkout? did this research have the points?

A discrepancy does not have to become an automatic punishment. It can become a
flag, and in a cooperative world that usually suffices.

**And the game helps more than this document assumed.** There is no lock against
boarding another faction's ship and taking what is inside — but doing that
**declares war** and tanks the reputation with that side. The deterrent is
native, and the evidence sits in the returned save's `hostmap`: `stance` turning
to `Enemies`, a drop in `relationship`, `awareOfCrew`. The server handed the
file over and gets it back, so it sees all of that. Robbing the neighbour is not
prevented; it is **recorded and expensive**. See `findings.md`, item 10.

## 2.8 The client's responsibilities

The client is the evolution of the savegame editor, which already reads and
writes a save byte by byte without disturbing anything that was not asked for.

- authenticate, list rooms, join
- manage one savegame folder per room
- **never write with the game open** — detect the process and refuse. It is the
  rule that keeps someone's game from being destroyed
- watch the autosaves and send heartbeats
- upload the final save on detecting that the game has closed
- show the room's map between sessions

## 2.9 How the client talks to the game

**A non-negotiable principle: the simulation is Bugbyte's and it is not
touched.** All this project does is read and write savegames — the same thing
players have been doing by hand for years. The server is a layer beside the
game, never inside it.

### The launcher is configurable

The `spacehaven` executable is not the game: it is an 86 KB native launcher that
reads `config.json`, creates a JVM and loads the main class.

```json
{
  "classPath": ["spacehaven.jar"],
  "mainClass": "fi.bugbyte.spacehaven.steam.SpacehavenSteam",
  "vmArgs": ["-Xmx4G"]
}
```

In the binary's strings you find
`Error: no 'mainClass' element found in config!` and the signature of
`URLClassLoader`. Classpath and main class are configurable through a text file,
and the game's classes are not obfuscated.

### There is a community mod template

<https://github.com/Spacehaven-modding-tools/SpaceHavenModTemplate> — **from the
community, not from Bugbyte.**

> **Corrected on 2026-07-31.** There is indeed a hook provided by the game:
> `SpacehavenSteam.tryToLaunchModLoader` looks for and launches a mod loader
> distributed through the Steam Workshop, and **that loader already ships
> `aspectjweaver` inside it**. That removes almost all the friction this document
> uses to defer the mod: whoever subscribes to the Workshop item gets AspectJ
> ready-made and the game calls it by itself. See `findings.md`, item 14.

It uses AspectJ with load-time weaving: you declare pointcuts that wrap the
game's methods, drop your jar in `mods/` and add the entry to the `classPath` in
`config.json`. It requires `aspectj-1.9.19` and `aspectjweaver` in the game's
folder, and Java 17+. `around` pointcuts wrap a method and decide whether the
original gets to run at all.

### What a mod would unlock

Wrapping the save and load routines gives **exact session boundaries**, instead
of watching autosave files and inferring. Going further, it allows manipulating
the game's live objects instead of editing a file, which would open the door to
placing a neighbour's ship in the sector without closing the game.

### What it does not change

The simulation stays local and non-deterministic. Two players watching each
other move live would require a networking layer of our own fighting the game's
premises.

And the cost is real: the player has to install AspectJ, edit `config.json` and
have Java 17. Every game update can break the pointcuts, because they point at
method signatures nobody promised to keep.

### The decision

**The client launches the game itself.** It runs the binary and waits for the
process to end. It touches neither code nor configuration, it is just process
management, and it settles the client's most important rule: since it is the one
that starts the game and waits for the end, it knows for certain when the game
is open and never writes over it.

**The mod is optional and blocks no phase.** A minimal mod, one that only wraps
saving and loading without touching game logic, improves the precision of the
session boundaries. Whoever installs it gets that; whoever does not carries on
with file watching. Making it a requirement would multiply the installation
friction before there is anything to enjoy — and the point of the first phases
is precisely to find out whether anyone wants this.

**Live injection waits until there are players.** It is the natural evolution
and it is now known to be possible.

## 2.10 Phases

| Phase | Delivers | What it proves |
|---|---|---|
| **0** | account, rooms, save upload and download | custody works, with no multiplayer at all |
| **1** | autosave heartbeat, web map of the room | the room stays alive between sessions |
| **2** | neighbour injection, no trading | you open the game and someone's ship is there |
| **3** | consignment and reconciliation | real trading between players |

Off the queue, blocking nothing: the **minimal mod** of 2.9, which gives exact
session boundaries to whoever wants to install it, and **live injection**, which
only makes sense once there are people playing.

Phase 0 is already a product on its own: save in the cloud, with history and no
save scumming. And it is the one that teaches the most, because it exposes early
what is genuinely tedious — an abandoned session, a stuck client, a game that
closes on its own.

Scope of the first cut: **trading only, plus the missions the game itself
generates.** Transferring crew and whole ships is possible (verified), but each
one brings its own game rules and can wait.

## 2.11 Trust and adoption

This project's real barrier is not technical. It is that the community — rightly
— does not install an unknown application, let alone one that uploads files to
some server. If that is not addressed deliberately, the rest does not matter.

### The sequence matters more than the argument

Each step asks for a little more trust than the last and delivers something
before asking for the next:

1. **The savegame editor**, which is useful on its own and sends nothing
   anywhere. It earns a base of people who already use it and already trust it.
2. **The room's map as a web page.** Nothing to install: the person sees the
   shared world alive and decides whether they want in. It can even allow taking
   part with no installation at all, with the person picking the save folder in
   the browser, click by click.
3. **The client**, which becomes a convenience instead of a front door — and
   arrives as *one more tab in a tool the person already has*, not as a new app.

The difference in conversion between "install this unknown app to play with
strangers" and "that editor you already use now connects to a room" is enormous.

### Verifiable instead of trusted

- **Running from source is the main option.** The editor is Python standard
  library; the client should keep that property for as long as possible.
- **Public build from public source.** The binary is assembled by GitHub Actions
  from the tag's commit, and the log is public. The checkable claim is: *this
  binary came out of this commit, and here is the record*. Link the run in the
  release notes.
- **Checksums on every release**, and a link to a public antivirus scan.
- **Code signing** costs money and can wait; it replaces nothing above.

### The server has to be self-hostable

It is the lever that most changes the conversation in a modding community. With
the server open and easy to stand up, nobody has to trust anybody: a group of
friends raises their own room. The author stops being a service you hand data to
and becomes the author of a tool. And it will happen anyway — there is always
someone who wants the private room.

### A data policy, written before it exists

The editor promises today that nothing leaves your computer. **The client breaks
that promise**, and pretending otherwise would be the worst possible mistake.
So, in plain language and where the person reads it before installing:

- what gets uploaded: the save file, in full
- where to
- who sees it: the server and, in portrait form, the other players in the room
- how long it is kept
- how to erase everything and leave

And inside the client:

- a **visible log** of everything that was sent and every file that was written
- a **dry-run mode**: show what would be changed without changing it
- never touch the game's installation. If the optional mod of 2.9 ever exists,
  it comes separately, with a warning, and never bundled

### Candour about what cannot be prevented

Saying openly that the game runs on the player's machine, that the save can be
edited, and that this is why the design is cooperative and the server checks
instead of guessing. A modding community respects that and distrusts the
opposite — anyone promising absolute security hasn't thought about it.

## 2.12 Assumptions not yet tested

Marked so that whoever implements does not take them as fact:

- **mutual injection.** We tested injecting one ship into one save. We did not
  test two players seeing each other at the same time, each in their own save
- ~~**reconcilable trading.**~~ **ANSWERED** on 2026-07-31, see
  `trade-experiment.md`. The seller's `<shipBank>` records the sale, and the
  credits match exactly on both sides. There is no transaction log: only final
  state, which is enough, because the server assembles the bank and knows where
  it started. **Reconciliation by net delta, and phase 3 stands as written.** One
  new caveat: cargo travels by shuttle and can be in flight at save time, and
  anyone adding up only `inStorage` will see goods disappear (`findings.md`,
  item 8)
- **stability with many neighbours.** We tested one injected ship. Ten might
  weigh, or confuse the AI
- **a game update.** If Bugbyte changes the format, everything here needs
  rechecking. `compare_galaxy.py` detects a change in generation; the rest is by
  hand
- **missions generated on an injected ship.** The game created one. We do not
  know whether it resolves properly, nor what happens if the ship disappears
  midway

## 2.13 Legal notice

Space Haven is a game by Bugbyte Ltd. This is an independent, fan-made project,
with no affiliation to them. Nothing here changes the game's code: everything is
reading and writing savegames, which players have been doing by hand for years.

What **cannot** be redistributed is game content. The origin editor extracts the
name table from the `spacehaven.jar` of the user's own installation, precisely
so as not to redistribute it. The server must follow the same rule.

If the project finds an audience, it is worth showing to Bugbyte — not as a
request for permission, which is not needed, but as a demonstration that the
demand exists.
