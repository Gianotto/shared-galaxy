# New measurements

*[Leia em português](findings.pt-BR.md)*

What was measured after `savegame-format.md` and `shared-galaxy-server.md` were
written, while building the tools and running them against real saves from game
1.0.4. Every item says where the evidence came from.

Two of these corrections change code for whoever implements the server. They
have been applied to the original documents; the rest is here because it did not
fit there.

The saves used: `ship17 sem visao` (the fog test, 3 ships) and `Beyond Space`
(9 ships), plus `New haven-1`.

---

## 1. A celestial body has two ids, and only one works for the room

**This is the most expensive correction in this document.** Every celestial body
has:

| Attribute | What it is | Scope |
|---|---|---|
| `id` | starmap object id, taken from `starmap/@objectIdCounter` | **local to the save** |
| `celeid` | celestial body id, derived from the seed | **the same across the whole room** |

And **`starmap/@pa` points at the `id`, not at the `celeid`.**

Measured in `ship17`: `@pa=226` matches `<l type="Asteroid" id="226" celeid="1689">`,
and there is no body with `celeid=226` anywhere in the save. In `Beyond Space`:
`@pa=231` matches `<l id="231" celeid="0">`. In both cases the body pointed at is
where the `<f isPlayer="true">` fleet actually is.

The design consequence, and it is a serious one: section 1.4 says that "a
coordinate and a celestial body id mean the same thing to every player in the
room". That holds for `celeid` and does **not** hold for `id`. The server has to
speak `celeid` when saying where a player is, and translate to the local `id`
when writing `@pa` into each player's save. Swapping the two puts the neighbour
in the wrong sector, and the error is silent.

`starmap/@sys`, that one is the `systemId` directly — checked in all three saves.

This also corrects a comment in `compare_galaxy.py` in the editor repository,
which records `sys` and `pa` as "internal counters — they do not match the number
of systems or of bodies". They do not match any count at all, because they are
not indices: they are references.

## 2. `<ship fog="true">` — missing from the recipe

Section 2.5 calls for `fg="0"` on every cell, `unex="1"` and `forceRoof="1"`.
There is a fourth attribute, on the `<ship>` root.

Measured across 12 ships from two saves:

| Owner | `fog` | `unex` | `forceRoof` |
|---|---|---|---|
| Player (2 ships) | `false` | absent | absent |
| NPC (9 ships) | `true` | `1` | `1` on most |

The only exception is one Merchant ship with `fog="false"`, probably already
boarded — which confirms the reading that the attribute marks "this ship has
already been explored".

It matters because the source ship for a portrait is always the owner's ship,
which is always `fog="false"`. Left uncorrected, the portrait is born different
from every authentic NPC in the save.

## 3. Tradable cargo does not live in the `<shipBank>`

The `<shipBank>` holds **credits** (`ca`) and pricing rules (`<markup>`,
`<discount>`). Cargo sits in stacks inside the storage `<inv>` nodes:

```xml
<inv>
  <s elementaryId="2053" inStorage="4" onTheWayIn="0" onTheWayOut="0"/>
</inv>
```

The attribute is `elementaryId`, not `elementId`. There are also `<cinv>`,
`<pinv>`, `<stored>` and `<items>`, not yet told apart.

This is exactly what E3 of the trade experiment will measure: which of the two
the game reads and writes in a transaction.

## 4. The `hostmap` is indexed by faction name

92 rows in `ship17`, each one a pair, and **with no id at all**:

```xml
<l s1="Player" s2="Civilian" stance="Friendly" relationship="74" patience="100"
   accessTrade="true" accessShip="false" accessVision="false"
   accessServices="true" accessHire="true" s1SusOfS2="false" s2SusOfS1="false"
   playerOwesSettlement="0" settlementArrivedTurn="0" awareOfCrew="false"/>
```

`s1` and `s2` are **names** ("Player", "Civilian", "Merchant", "Military"), not
the numeric faction ids. There are more permissions than section 1.8 lists:
`accessServices`, and the fields `stance`, `patience`, `s1SusOfS2`, `s2SusOfS1`,
`awareOfCrew`.

The state of `ship17` is precisely the design of section 2.5 item 8:
`accessTrade="true"` with `accessVision="false"` and `accessShip="false"`.

## 5. `id="-1"` means "no id"

Every `<e>` element inside a ship — the hundreds of pieces it is made of — comes
with `id="-1"`. It is not identity, it is a sentinel.

It cost a real defect: the first version of `save_diff.py` treated it as
identity, and two saves that differed in 6 attributes produced 366 differences,
358 of them phantom. Anyone writing anything that matches elements between two
saves needs to know this.

The general rule that came out of it holds too: an identity is only useful if it
is unique among siblings.

## 6. `hdsid` is a reference to the ship

In the `<ai>` of each crew member, right next to the already known `hsid`, there
is `hdsid`. In the two ships where it appears, the value is always the `sid` of
the ship itself (6 occurrences in one, 1 in the other).

Anyone copying a ship has to renumber `sid`, `homeSid`, `hsid` **and** `hdsid`.

## 7. The game recreates the objects inside cells on load

Measured in E1a: two load-and-save cycles of `Beyond Space`, **with the game
paused**, without a single order given, produce **11,434 differences**.

They are not simulation. They are reallocation: each ship's `idCnt` advances by
thousands of units per load (ship 2 went from 20,417 to 22,913), 676 `<l>` nodes
inside `<e>` disappear and 676 appear, and 625 change `id`. By attribute: `hf`
(3,676), `atm`/`atm2` (1,685), `x`/`y` (1,559), `rot`, `m`, `invw`, `fg`.

Outside the ships, only seven shapes change on their own, among them
`masterData/@idCounter`, `space/@idCnt` and `hostmap/map/l @relationship` — the
relationship between factions decays by itself, which confirms section 1.8 from
the measurement side.

**Consequence for the server:** no object id from inside a ship survives a
session cycle. Whatever the server stores about a ship's contents has to be
described by shape and content — which resource, how much, in what kind of
module — never by id. This applies to the reconciliation in section 2.7 and to
any future idea of tracking an object.

**Consequence for tooling:** a noise profile based on exact paths is useless,
because the learned paths do not exist on the next run. The 11,434 differences
reduce to **103 shapes** once the ids are taken out of the path, and then the
profile transfers. That is how `save_diff.py` does it.

## 8. A transaction is asynchronous: the cargo travels by shuttle

Measured in E2. The player bought 1 Hyperium for 386 credits from a Merchant
ship. The credits move immediately and match exactly on both sides
(`playerBank` −386, the seller's `shipBank` +386), and the seller's stock is
already debited (3 → 2).

**The cargo is not.** At the moment of the save it was in transit:

- the destination stack in the buyer's storage had `onTheWayIn="1"` and
  `inStorage` **unchanged**
- there was an `<i eid="172" mo="BeingMoved" dstId="...">` in the ship's `<items>`
- the shuttles (`<crafts>`) carried manifests `<o a="HOW_MUCH" e="RESOURCE"
  sid="DESTINATION_SHIP">`

The game does not teleport goods: a shuttle goes and fetches them. Game time
passes between closing the deal and the cargo reaching storage, and a save taken
in that gap — which is the normal case, because autosave does not wait — catches
the state split in half.

**And delivery has two stages, not one.** The shuttle drops the goods **in crates
on the ship's floor**. Only afterwards does a crew member, a robot or the player
carry them to storage — *and only if there is room*. With no room, the crate stays
on the floor.

It matches the structure: `<items>/<i>` has `x`, `y` and **`grndTime`** — ground
time. In the player's ship there were 7 crates sitting still, grouped at the same
coordinate, with `grndTime` near 480 and none of them with `mo="BeingMoved"`.
They were not travelling: they were dumped.

**Consequence for reconciliation (section 2.7):** summing `inStorage` is wrong,
and it is not a transient error that resolves itself. The server has to count
**three places** — `inStorage`, `onTheWayIn` and the crates in `<items>` —
because with storage full the goods can live on the floor for the rest of the
game. Anyone summing only the shelf will report as lost what is sitting three
metres from it.

The same applies to check-in: a session can end with goods bought, delivered and
never stored.

**Measured cleanly in E6.** The storefront sold 5 Chemicals. In the buyer's save:
**+1 in `inStorage` and +4 in crates in `<items>`**. All five are there, in two
places. Counting only the shelf is off by 80% on that transaction.

## 8b. Reconciliation is by net delta, and E4 falls out for free

The E6 session had several transactions — the panel allows up to four per
negotiation — and the save kept **only the final state**. No log, no order, no
receipt, no trace of how many there were or in what order.

That is exactly what phase 3 assumes and what E4 of the script was going to ask.
The server builds the portrait's `<shipBank>` and storages, so it knows the
initial state down to the number; the difference at check-in is the transaction,
with no need to reconstruct it step by step.

## 9. `<markers>` is not required for trading

Section 1.7 lists `<markers>` (docking points) as one of the three nodes NPC
ships usually have and the player's does not. After item 8 — cargo travels by
shuttle — the question became serious: with no docking point, does the shuttle
deliver?

It does. The `MFB STRONGHOLD`, the ship that sold the Hyperium in E2, **has no
`<markers>`**, and the transaction was executed and delivered. Measured across 9
ships:

| Ship | markers | shipBank |
|---|---|---|
| MFB STRONGHOLD (Merchant) | no | **yes** |
| CS DASHERS SCRAPPER (Civilian) | yes (8) | yes |
| ACS ZAHKUL (Android) | yes (6) | yes |
| CB DUDDE (Civilian) | yes (4) | yes |
| MAS MARGIN CALL (Military) | yes (4) | yes |
| CNHS MORNING STAR (Cultist) | yes (4) | no |

There is no correlation with `<shipBank>` in either direction: there are ships
with a bank and no markers, and ships with markers and no bank. What governs
trade is the bank.

The format, where it exists, is `<m m="8" x="11" y="11"/>` — a coordinate inside
the ship. Which is why cloning from a donor would not work: the points belong to
the hull that has them.

**For the portrait builder:** not copying `<markers>` is safe.

## 10. Fog comes from the source ship, and the `hostmap` does not close the interior

Two runs in the game, changing **one** variable — the ship used as the source for
the portrait. Same destination, same faction, same `hostmap` row, everything else
equal.

| Source | Written by the tool | After load | On screen |
|---|---|---|---|
| `HSS PERSEUS`, a **player** ship (`fg=191`, explored) | `fog=true unex=1 forceRoof=1`, 616 cells at `fg=0` | `fog=false`, `unex` and `forceRoof` **erased**, 616 cells back at `fg=191` | roof open, crew in plain sight |
| `CS DASHERS SCRAPPER`, an **authentic NPC** (`fg=0`, never explored) | `fog=true unex=1 forceRoof=1`, 1536 cells at `fg=0` | **identical** | `State: Normal (Unexplored)`, grey silhouette |

**Fog is forgeable when the source is already unexplored, and is not when the
source is explored.** The game has another source of truth and rebuilds from it —
restoring, in the player's case, exactly the original `fg=191` values.

**Where the source is not:** it is not `fog`, `unex`, `forceRoof`, nor the cells'
`fg`, because we wrote all four in both cases. It is not the `hostmap`:
`accessVision="false"` came through the load intact in both runs. It is not the
relationship between factions — in the same save, an authentic Civilian under
that same row stays hidden while the Slaver in `Enemies` at −82 is revealed. And
it is not any attribute of the `<ship>` root: the two portraits have exactly the
same set of attributes. The only structural differences are `gasWarnings` on one
side and `markers` on the other, neither of which looks like an exploration mark.

**The design consequence is serious, and it is not technical.** A neighbour's
portrait would be *their* ship — and a player's ship is, by definition, explored.
By the measured rule, it is born revealed and there is no way to hide it. Two
paths remain, and the choice is a design one:

1. **Accept the visual exposure.** The neighbour sees the portrait's layout and
   crew. The economic protection stays intact (only the consigned goods are
   there) and the war mechanic of item 11 protects against theft. Privacy is
   lost, and what is gained is the charm of really seeing the other player's
   ship.
2. **The portrait stops being their ship.** The server builds a storefront out of
   an NPC hull — which is born unexplored and therefore stays hidden — and
   transplants only what matters: the owner's name, the consigned stock and the
   bank. It solves fog for free, it is cheaper to assemble, and it makes the
   question of showing someone else's layout go away. The cost is that the room
   loses "that one is So-and-so's ship".

The first keeps the project's promise; the second keeps privacy. There is no way
to have both with what is known today.

## 11. The `hostmap` is per faction, not per neighbour — and that limits the room

A consequence of the war mechanic above, and it is not in the design document.

A neighbour's portrait gets a faction from the game's fixed set. In this save
there are ten sides: `Pirate`, `Slaver`, `Android`, `Civilian`, `Cultist`,
`Merchant`, `Military`, `HavenFoundation`, `FlamingSwords`, `NotSet`. The
relationship table is indexed by **pair of sides** (item 4), never by ship.

So:

- boarding a neighbour's portrait declares war on the **whole side** — on every
  authentic NPC of that side, and on **any other neighbour** who landed in the
  same faction
- the reverse path leaks too: a player who goes to war with the Civilians for
  ordinary in-game reasons ends up at war with the neighbour we represent as
  Civilian
- the permissions the server turns on at checkout (`accessTrade` and so on) apply
  to the whole side, not just to the portrait

Section 1.8 calls the table "the server's control panel over what one player can
do with another's portrait". That is true **at faction granularity**, and only
there.

**Practical room limit.** Section 1.3 concludes, from the id counters, that
"there is no practical limit on players per room". That still holds for the save.
But for **neighbours visible in the same sector** the limit is the number of
distinct factions — around nine — because past that two neighbours share a side
and stop being distinguishable through the `hostmap`. Neighbours in different
sectors do not compete for this.

Visual identity still comes from `sname` (section 1.10). What collides is
permission control and war propagation, not the name.

## 12. The trade panel has a cap per resource, not per stock

Three runs to get here, and the first three hypotheses died along the way.

| Consigned | Offered | Hull |
|---|---|---|
| 40 Chemicals | **40** | player ship |
| 30 Steel Plates | **26** | player ship |
| 30 Steel Plates, alone in a storage | **26** | another player ship |
| 10 Chemicals | **10** | NPC hull |
| 30 Steel Plates | **26** | NPC hull |

**It is a cap, not an offset.** A small quantity comes out whole; the Plates stop
at 26 across three different hulls, with and without another resource alongside.

**What has already been ruled out:**

- *storage capacity* — authentic storages hold 1,530, 514, 278 units
- *per-stack cap* — Plates reach 47 in a real stack, Infrablock 65
- *concentration in a single storage* — the same 26 with the resource alone
- *crew consumption* — no pending construction, and nothing vanished from the
  file: the save carried on with 30 and the `playerBank` untouched

**The explanation that remains, and it fits with item 8:** the cap is on
**transport**, not on stock. Cargo is delivered by shuttle, in crates, and the
panel offers what fits in one trip. Steel Plates are bulky and stop at 26;
Chemicals are compact and go past 40. Nothing disappears — the excess simply is
not for sale at that moment.

**How to confirm:** consign 100 Chemicals. If they stop at a number of their own
— and not at 26 — the cap is by resource volume and the explanation closes.

**For consignment:** the owner needs to know that consigning 100 of something
bulky does not expose 100. The server should compute and show what actually goes
on sale, instead of promising the full number.

## 13. Steam Cloud syncs the zip, not the save folder

Measured in the game's `remotecache.vdf` (app 979110): Steam tracks **one entry
per game**, and it is always `savegames/<Name>/cloudZipFile.zip`. The `save/`
folder, where `game` and the ships live, is **not** synced.

In other words: `save/` is the local state, and the zip is the cloud copy,
rebuilt by the game when it writes.

**Why this matters for the client.** An old `cloudZipFile.zip` sitting next to a
freshly checked-out save is the dangerous combination: if Steam decides to
restore — another machine, a sync conflict — it overwrites the session the server
lent out with an old game, and the player loses progress without understanding
why. The client now deletes the previous zip when it writes a checkout.

**A side effect the server can detect.** If it happens anyway, the returned save
comes back with a **lower** game day than the one lent out. The galaxy matches,
the player did nothing wrong, and the check in section 2.7 has here a signal with
a known cause — worth telling this case apart from cheating before flagging
anyone.

**What the game needs in order to list a save.** The `GameData$SaveGame` class has
`scanForSaves`, `gameFile`, `infoFile` and `metaFile`: it scans the folder looking
for files, it does not read an index. `cloud.xml` and `cloudZipFile.zip` appear
only in the sync path. A save written without them should show up normally — to
be confirmed on the first checkout.

## 14. The game has a native mod loader, and it already ships AspectJ

**Corrects section 2.9**, which says: "from the community, not from Bugbyte. There
is no official API and no hooks provided by the game."

`fi.bugbyte.spacehaven.steam.SpacehavenSteam` has a `tryToLaunchModLoader` method,
and the class's strings point at Steam Workshop items:

```
/workshop/content/979110/3703674043/spacehaven-modloader.exe
/workshop/content/979110/3715831202/spacehaven-modloader
```

In other words: **the game itself looks for and launches a mod loader**
distributed through the Workshop. It is not an outside hack; it is a path the
executable knows about.

And the contents of item 3703674043, already installed on this machine, include:

```
aspectj-1.9.19.jar
aspectjweaver-1.9.19.jar
spacehaven-modloader.exe
```

**AspectJ comes with it.** Section 2.9 estimates the cost of the mod as "the
player has to install AspectJ, edit `config.json` and have Java 17". The first
two go away: whoever subscribes to the mod loader on the Workshop already
receives the weaver, and the game calls it on its own.

That knocks down almost the whole friction argument that got the mod postponed.
The decision in 2.9 — "the mod is optional and does not block any phase" — was
taken over a cost that is not the real one.

**What stays true from 2.9:** the simulation is still local and non-deterministic,
and every game update can break pointcuts, because they point at method
signatures nobody promised to keep.

**Not verified:** how you register your own aspect with the loader, and whether it
accepts any weaving or only what the data mods use. The other installed item
(3731405861) is a pure data mod — `info.xml` plus `patches/*.xml` — so the data
path is confirmed and the code path is only inferred from the presence of the
weaver.

## 20. The ship name is free text the player can change, so it cannot be identity

Section 1.10 concludes that since a save holds no player identity — the player's
faction is 461 in every game in the world — **the ship name is what tells one
player from another on screen**. That is true of what the game shows, and it is
the wrong thing to build identity on: `sname` is free text, and the player can
rename the ship in-game whenever they like.

With strangers in a room that is an impersonation route. Rename your ship to a
neighbour's and, on the room map and later inside other people's games, you look
like them.

**Nothing breaks technically.** No id depends on the name, and the server re-reads
it on every check-in, so a rename simply propagates.

**What changed.** The room map led with the ship name and fell back to the
account. Now the account name leads and the ship follows in brackets — `Ana (HSS
YANNI)`. The account name is the server's; nobody can edit it into someone
else's.

**Open for phase 2.** The storefront a neighbour sees carries a name the server
chooses, so it is safe today. But if that name is ever derived from the player's
current `sname` rather than from their account, the same route opens inside the
game, where it matters far more than on a web page.

## 19. The galaxy is materialised lazily, and that broke the fingerprint

**A live defect, found by a hyperspace jump.** It would have refused the check-in
of the first player who explored.

A grafted save had 123 bodies before the jump and 137 after. System 1 gained
fourteen at once — three planets, five moons and six asteroid fields, each with
its own seed. The player never went to system 1; opening the star map was enough.

So a save does not contain the whole galaxy. Systems exist as entries and their
bodies are filled in as the player looks at or reaches them.

**Why that matters.** The fingerprint was built from bodies, terrain sectors and
clouds — so it measured **how much of the galaxy had been explored**, not which
galaxy it was. Two players in one room drift apart the moment either travels, and
the server compares digests on check-in with strict equality. The first explorer
would have been told their save was from another galaxy.

The original measurement that justified the digest is not wrong: two *freshly
created* games from one seed do match. It only never covered a played save.

**The fix: stars.** Every system has one, it exists from the first save, it is
the fixed centre the rest orbits, and it carries the generator's seed. The digest
now covers the map size and each system's star, and nothing else.

| save | old digest | new digest |
|---|---|---|
| fresh, age 1.29 | `c06bd078` | `b51f95ce` |
| played, age 2.79 | `c06bd078` | `b51f95ce` |
| grafted | `c06bd078` | `b51f95ce` |
| **after a jump** | **`c3fe4ae9`** | **`b51f95ce`** |
| another galaxy | `75117b0a` | `7bdd1c8d` |

**The editor has the same defect**, in its own use: `compare_galaxy.py` will call
a fresh save and a played save of one galaxy different. Worth fixing there too.

## 18. The galaxy is not a self-contained subtree

**Cost a crash, and it is the correction to item 17.** The first graft moved
`<starmap>` alone, on the assumption that a galaxy is one node. The save loaded
fine. The first hyperspace jump crashed:

```
java.lang.NullPointerException
  QuestExodusFleetMissions.addFindBeaconFromDere
  QuestExodusFleet.onEvent
  Questlines$QuestLineManager.openStarmapInHyperspace
  StarMapScreen$2.update
```

The quest line went looking for a beacon that existed in the galaxy that had
been replaced.

Measured afterwards, three places outside `<starmap>` hold ids from inside it:

| Node | Attributes pointing into the starmap |
|---|---|
| `<questLines>` | `atSystemId`, `atSectorId`, `decoId`, `createdShipStarmapId` |
| `<missions>` | `systemId`, `sectorId` |
| `<ships>` | `givenByShipId`, `systemId`, `sectorId`, on mission nodes |

They are the same family of local object id as `starmap/@pa` — item 1 again, in
a place nobody thought to look.

**The fix.** `<questLines>` comes from the galaxy donor, because a player
arriving in that galaxy should have the quest state that belongs to it. Missions
are dropped: an outstanding job in a galaxy you just left cannot be honoured,
and nobody would expect it to be.

**Why the first test missed it.** Item 17 was verified on an asteroid base, and
a base cannot travel — so the hyperspace path was never exercised. A test that
cannot reach the failing code is not evidence, and I read it as if it were.

## 17. A galaxy can be grafted into a save, and the game accepts it

**The biggest lever found so far for onboarding.** Measured 2026-07-31.

Replacing a save's `<starmap>` with another galaxy's, moving the player's fleet
to the new starting body and fixing `@sys`/`@pa`, produces a save the game opens
normally. Tested on the hardest case available: a 124-day, twenty-crew base
grafted into a galaxy from a different seed.

After loading and saving back, everything held — same galaxy digest, same
position, same age, 64 systems, exactly one player fleet. The player's ship,
crew, research and 1,379,043 credits were never touched, because the graft moves
the galaxy rather than the player.

Why that direction: the player's state is not one node — ship, crew, bank,
research and faction standing sit scattered across the save — while the galaxy
**is** one node.

**What it changes.** Today a player must create a game with the room's exact
seed *and* every scenario option right, or the fingerprint refuses them. With
this, they create a game however they like and the server hands back a save
already in the room's galaxy. Section 2.3 can stop being a gate.

**`sta="1"` marks an asteroid base.** The save used was one, and the game loaded
the asteroid as a ship — which is how a base is stored. The graft did not care,
but a base cannot travel, so such a player stays in the starting sector: a fixed
trading post rather than an explorer.

**The known seam.** The starting sector's `<space>` came from the player's
original body, and the game does not regenerate sectors on load (section 1.6).
That one sector keeps the asteroid field it was born with while the new galaxy
declares different `<stuff>` for that body. Everything travelled to afterwards is
generated from the shared galaxy. Not yet inspected up close.

## 16. Everyone in a room starts on the same rock

Section 1.4 records that the seed reproduces the starting point — x=75724,
y=235080. The consequence was never spelled out: **every player who creates a
game from the room's seed begins at the same celestial body.** Measured on a
fresh game against the room's seed: system 31, `celeid` 1689, every time.

Harmless for phase 0. Each player has their own save, and the shared start is
only a coincidence of geography.

**Phase 2 cannot be naive about it.** On day one of a 64-player room, all 64 are
neighbours in one sector, and the injection recipe would put every other
player's storefront into everyone's save:

- the faction limit binds at once — about nine usable sides, so from the tenth
  neighbour the `hostmap` cannot tell them apart (item 11)
- each storefront costs ~166 KB, so 63 of them add ~10 MB to every save
- "stability with many neighbours" is still untested; ten may already confuse
  the ship AI

So co-location needs a rule, and it belongs in phase 2 where the injection
happens. Some candidates, none tested:

- **cap per sector.** Inject the N nearest or most recently active, and say so.
- **mutual consent.** Only inject players who have each other listed, which
  turns crowding into a social act instead of a default.
- **let the start disperse.** The room could ask people to travel before
  enabling injection — the game already spreads players naturally, and the
  problem solves itself after the first few days.

The last is cheapest and fits the design: section 1.6 already concluded that
players must earn territory by flying, because the server cannot generate a
sector.

## 15. System names arrive all at once, not by exploration

Worth recording because the natural assumption is wrong, and I built a feature
on it before checking.

`savegame-format.md` notes that system names are empty in a freshly created save
and appear later — which is why the galaxy fingerprint ignores them. The obvious
reading is that the game names a system when a player gets close, so the set of
named systems would map the room's exploration.

Measured across three states of the same game:

| Save | Named |
|---|---|
| age 1.29, just created | **0 of 64** |
| the same save, checked out | **0 of 64** |
| age 2.79, after playing | **64 of 64** |

All sixty-four at once. Whatever triggers it happens wholesale, early, and not
per system — so "named" says nothing about where anyone has been.

The room map briefly drew named systems brighter to show collective
exploration. It was removed: on a real galaxy every dot lit up, and the legend
claimed something false.

**Still unknown:** what triggers the naming. Somewhere between creating the game
and playing a day and a half of it, and it is not the checkout — the save the
server handed back still had none.

## 15. Odds and ends

- **`balanced.bin`** exists in the save folder and is not documented. The
  documents mention `stats.bin` and `timeline.xml`; `timeline.xml` did not appear
  in any of the saves examined.
- **`info/@version` is `21`**, the save format version — not the game version. A
  save from 1.0.4 carries `<info version="21" date="3289920"
  realTimeDate="1785467969073"/>`. If the server is going to anchor a version per
  room, as the plan recommends, this is the number it has to work with.
- **`fg` only exists on some of the `<e>` elements.** In `ship17`, 392 out of 737
  in one ship, 1536 out of 3501 in another. Fog is per floor cell, not per
  element.
- **`playerBank`** has the same shape as `<shipBank>`: `<playerBank s="Player"
  ca="0" cr="0" slp="10064" blp="9856"/>`.
- **The same `sid` can appear twice** in a scan of a save's ships (`sid=1459` in
  `Beyond Space`, once with 0 crew and once with 6). Not investigated; probably
  the same ship listed both in the sector and in a file under `ships/`.
