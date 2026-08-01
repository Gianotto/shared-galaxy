# Implementation plan

*[Leia em português](plan.pt-BR.md)*

Working document. It complements `shared-galaxy-server.md`, which is the design,
and `savegame-format.md`, which is the survey. What is here is the order, the
decisions taken and what each stage has to deliver for the next one to start.

English is canonical; the Portuguese version alongside it may lag by a
step. This plan changes often — treat a stale translation as the older
document, not as a second opinion.

---

## Decisions taken

| Subject | Decision | Consequence |
|---|---|---|
| Scope of this repo | server + web map of the room | the client is a new tab in `space_haven_editor`, not a new app (2.11, step 3) |
| Stack | Python, FastAPI, Postgres | outside the editor's stdlib discipline; accepted because the server does not run on the player's machine |
| Save persistence | compressed files on a volume, addressed by sha256; Postgres only for metadata | trivial backup, self-hosting without drama, no large objects |
| Identity | opaque token issued by the server, no e-mail and no password | zero personal data; losing the token loses the player, so the client forces a recovery code |
| Public | room open and listable from early on | quota, upload limit and rate limit go into phase 0, not later |
| History | last N versions per player, N per room, default 20 | predictable storage; the check in 2.7 has limited reach and that is accepted |
| Checkout term | 12 hours, configurable per room | covers a long session plus a night's sleep |
| Deploy | `docker compose up`, and nothing else | the same path for the public room and for anyone self-hosting |
| Language | code, API and routes in English; documentation bilingual | same as the editor |
| First job | trade experiment (2.12) | decides phase 3 before any server code |

---

## Stage A — The trade experiment

The document says that measuring how a TRADE transaction ends up recorded in the
save is the next experiment to run, and that it decides phase 3. It is cheap, it
needs no server at all, and if the result is bad it changes the design before
there is any code.

It lives in `tools/` in **this** repository. The first version of this plan sent
it to `space_haven_editor/tools/`, next to `compare_galaxy.py`, on the grounds
that both are save analysis. I changed it: the result of the experiment is a
document belonging to this project, the injector becomes the phase 2 portrait
builder — that is, it becomes server code — and the editor has a promise of its
own to keep ("nothing leaves your computer") that does not sit well with hosting
tooling for a project that uploads files. The price is vendoring `savefile.py`,
recorded in `sgalaxy/VENDOR.md`.

### A.1 — Instrumentation (I write it)

**`tools/save_snapshot.py`** — copies a save folder into a working directory with
a label and a timestamp. Trivial, but it is what makes the rest repeatable.

**`tools/save_diff.py`** — the central piece. Structural diff between two
snapshots, by XML path, reporting created elements, removed elements and changed
attributes. It needs a known-noise list to be readable: orbital phase of bodies,
timers, `idCounter`, crew position. Without that, the diff of a transaction comes
drowned in thousands of lines.

**`tools/inject_npc_ship.py`** — assembles the neighbour ship in a save, following
the recipe in 2.5: new `sid` and `entId` from `masterData/@idCounter`,
`settings/@of` and `@owner` from the faction, `<asi>` copied from an NPC,
`<shipBank>` with controlled stock, `fg="0"`/`unex`/`forceRoof`, `<f>` fleet on
the celestial body, permissions in the `hostmap`. It is an experiment now and it
becomes the phase 2 portrait builder later — worth writing with that double life
in mind from the start.

### A.2 — Script (you play)

In order, because each one depends on the previous:

**E1 — noise floor.** Load a save, do nothing, save. What changes anyway? Without
that measurement, no later diff is interpretable. It feeds the noise list for
`save_diff.py`.

**E2 — trade with a native NPC.** One purchase only, of one item only, with a ship
the game itself put there. Snapshot before and after. The question: *does the
transaction get recorded as an event, or only as final state?*

**E3 — trade with an injected ship.** Same thing, with the `<shipBank>` we built,
known stock and known `ca`. The questions: does the injected ship's stock go down
and does that persist? do the credits arrive in the `playerBank`? does the game
respect `ca` as a purchase limit?

**E4 — several transactions.** Three purchases and one sale in the same session.
Can you tell three purchases from one big purchase? That decides whether
reconciliation is per transaction or by net delta.

**E5 — provenance.** Two injected ships in the same sector, each with a marker
resource the player does not own. Looking at the cargo at the end, can you say
who it came from? If you cannot, reconciliation with several neighbours becomes
ambiguous and the design needs a marker per consignment.

### A.3 — What each result implies

- **Only final state, but the `<shipBank>` persists:** reconciliation by net
  delta. The server built the `<shipBank>`, so it knows the exact initial state
  and the difference is the transaction. **Phase 3 ships as it stands in the
  document.**
- **The `<shipBank>` does not persist** (the game regenerates the ship's bank on
  load): the sale is not reconstructible from the ship's side. All that is left is
  inferring from the `playerBank` and from the cargo, which only works with marker
  resources — E5 becomes mandatory and consignment becomes single-item per
  neighbour.
- **Not even usable final state:** phase 3 changes in nature. Native trade becomes
  flavour, not economy, and the real exchange happens through consignment outside
  the game (the neighbour asks, the server delivers into the hold at the next
  checkout). Less elegant, but it works and it depends on none of this.

**Stage A deliverable:** a `trade-experiment.md` document with the protocol, the
measured diffs and the implication chosen. It is what unblocks phase 3 and what
changes (or confirms) section 2.12.

---

## Stage B — Phase 0, custody

Starts in parallel with stage A as soon as E1 and E2 are measured: nothing in
phase 0 depends on the trade result.

### B.1 — Repository skeleton

```
Shared-Galaxy/
  server/
    api/            FastAPI routes
    domain/         room, player, lease, save version
    storage/        blobs on a volume, addressed by sha256
    galaxy/         fingerprint, vendored from the editor
    web/            map pages (Jinja2, no frontend build)
  migrations/
  compose.yml
  tests/
```

`git init`, licence and NOTICE the same as the editor's, the legal notice from
2.13 in the README from the first commit.

### B.2 — Galaxy fingerprint

The server needs the logic in `tools/compare_galaxy.py` to check the incoming save
(2.3). It lives in the editor and I am not going to create a package dependency
between the two repositories now. **Vendor** it into
`server/galaxy/fingerprint.py`, with a test that runs the same function from both
sides over the same saves and requires an identical result. If they ever diverge,
the test says so.

### B.3 — Data model

- `player` — token hash, nickname, creation
- `room` — short id, seed, creation options, password hash (optional),
  `lease_hours`, `retention_n`, owner
- `membership` — room, player, current canonical version
- `save_version` — room, player, sha256, size, game day, type
  (`canonical` or `checkpoint`), creation
- `lease` — room, player, issued at, expires at, version delivered, state

Pruning: when a new version is written, delete anything beyond `retention_n`,
never the current canonical one and never the one lent out.

### B.4 — API

**Done on 2026-07-31.** Seven routes, plus `/me` and `/health`. Exercised by 25
integration tests against a real Postgres — never against a test double, because
the guarantee that matters most at this phase is a unique index in the database.
The whole cycle was run over HTTP with a real 340 KB savegame: token, room, join
with galaxy check, checkout with a term, second checkout refused, check-in and
room state.

Four defects that only showed up by testing against a real database:

- the lease's `delivered_id` blocked retention pruning with `ON DELETE RESTRICT`.
  It became nullable with `SET NULL`: a closed lease is history, and blocking
  pruning is worse than losing the reference to an already reconciled session
- the synthetic fixture changed `starmap/@pa` to simulate "another galaxy", and it
  did not work — `pa` is a reference, not a generation parameter, and it is left
  out of the fingerprint on purpose
- the blob volume was not cleaned between tests, and a "junk costs no disk" test
  was counting blobs from previous tests
- presence (ship name and position) was not read from the save, so the room map
  would have been born empty


All under `/api/v1`, with the token in the header.

| Route | What it does |
|---|---|
| `POST /players` | issues a new token, returns a recovery code |
| `GET /rooms` | public listing: name, players, has password |
| `POST /rooms` | creates a room with a seed and options |
| `POST /rooms/{id}/join` | uploads the initial save; checks the fingerprint; adopts it as canonical |
| `POST /rooms/{id}/checkout` | opens a 12h lease and delivers the assembled save |
| `POST /rooms/{id}/checkin` | receives the final save, validates it, stores it, closes the lease |
| `GET /rooms/{id}/state` | room state as JSON, for the client |

A refused `join` explains why — almost always a different creation option (2.3).

### B.5 — Open room, therefore

- upload size limit (32 MB covers a 124-day save with room to spare)
- quota on rooms created per token, and on players per room
- rate limit on `checkout` and `checkin`
- the fingerprint check happens **before** writing a blob, so junk costs no disk
- `POST /players` with a cost (light proof-of-work or captcha) only if abuse shows
  up; do not anticipate

### B.6 — Web map

Server-rendered pages in the same FastAPI, no frontend build: room listing, room
page with who is where, and the history of check-outs and check-ins. It is the
shop window for step 2 of 2.11 — someone sees a living world and decides whether
they want in, without installing anything.

### B.7 — Lease and crashes

- 12h term; once expired, the state goes back to what it was at checkout
- a `checkin` outside a valid lease is refused with an explanation
- returning an autosave after a game crash is the normal path, not an exception

**Stage B deliverable:** saves in the cloud, with history and without save
scumming. A product on its own, as the document says, and the stage that teaches
the most — abandoned session, stuck client, game that closes by itself.

---

## Stage C — The client

Parallel track, in the editor's repository, as a new tab. It does not block B: you
can exercise the API with `curl` and with the browser itself.

- authenticate, list rooms, join
- a dedicated savegame folder per room
- **launch the game itself and wait for the process to end** — that is what
  guarantees never writing with the game open (2.9)
- a visible log of everything uploaded and every file written (2.11)
- dry-run mode: show what would be changed without changing it
- force the player to save the token's recovery code

---

## Stage D — Phases 1 to 3

**Phase 1 — heartbeat. Built.** The client watches the room folder while the
game runs and posts each autosave to `POST /rooms/{id}/checkpoint`. The server
stores it as `kind='checkpoint'` and moves the player on the map. It does not
touch the canonical and does not close the lease: what is delivered is still
decided by `checkin`, which is what keeps one session at a time intact.

The plan said "reduced state, full save only at check-in — sending 4.5 MB on
every autosave is waste". Measured, a save in this room is 150 KB compressed,
not 4.5 MB, and a whole autosave buys crash protection that a summary cannot.
So it sends the save. If a room ever grows saves where that stops being true,
the reduced state is still the fallback.

The client never writes during a session and only reads a folder that has
stopped changing — the game owns those files while it is open. And the mod puts
a line in the game's own log window on each send, so the player can see their
progress leaving the machine instead of hoping it did.

**Phase 2 — neighbour injection, without trade. Built.** The `inject_npc_ship.py` from
stage A becomes the portrait builder on the server, and assembly moves into
`checkout`. It proves the moment that sells the project: you open the game and
someone's shop is there.

The portrait is a **storefront built on an NPC hull from the destination save
itself** (`--hull`), not a copy of the neighbour's ship. Decided after E3b: fog
only holds if the source ship was never explored, and a player ship is always
explored. See `findings.md` item 10 and section 2.5 of the design. As a bonus the
hull comes from the player's own installation, which keeps the rule in section
2.13, and the portrait fits in 166 KB instead of 460.

**Everyone starts together, and the room says what that means.** A room
carries `maxJoinAgeDays` — the oldest colony it accepts at the moment of
joining, five days by default, `null` for a room that wants veterans to bring
what they have. It applies only at `join`; once you are in, you play as long as
you like.

The rule exists because of what the graft does well. It preserves ship, crew,
bank and research on purpose, so joining with a half-year-old colony means
arriving with half a year of advantage. The client closes the same gap from the
other side: a first join opens the game on NEW GAME, the player builds their
starting ship, and that is what gets uploaded. A fresh game is not day zero —
measured across saves made minutes apart, the game starts a colony at about day
1.3.

**Move the shop button to the storage's own toggle row.** It sits in the
command box today, next to MOVE / DUPLICATE / DISMANTLE — which are actions.
Being your shop is a *setting*, and the panel already has a row for those: the
green square and the fork that turn food consumption on and off. The player
suggested it twice and pointed at the transfer icon as the one to use.

It may also end the bug. The button still vanishes intermittently from the
command box, and measurement has ruled out insertion (always accepted),
lifecycle (the box is already clean) and position (all four buttons sit well
inside the screen). Whatever is left is specific to that container, and the
toggle row is a different one.

What is known about how to build it: the food toggle is a
`ScalableToggleIconButton`, `WorldObject$ObjectFeatures` is where `eatAllowed`
lives, and `SingleWorldElementSelected.makeFacilityAudioOnButton` is the game
building exactly this kind of control — a working recipe to read rather than
invent.

**A storefront lands on top of somebody's ship.** Reported from a real
session: the neighbour's shop appeared almost on top of the player's own ship.
The server places it at the neighbour's `(x, y)` — which is the celestial
body's position, not a free spot in the sector — so two members parked at the
same rock arrive stacked.

The game itself has the concept we are missing: a hyperspace jump opens a
sector grid and lets the player position their ship, showing where other ships,
bases, derelicts and asteroids already are. The placement to copy is that one.

It belongs with the in-game work rather than with the server: the sector is
generated on arrival, so the free-space question is only answerable where the
game is running.

**Send a copy on a manual save too, not only on autosaves.** The watcher
deliberately ignores the `save/` folder today, on the grounds that the manual
save is what the return sends. That reasoning holds for *the return* and not
for the copy: somebody who presses save has just decided this moment is worth
keeping, which is exactly when a copy is worth having.

It changes nothing about custody — a checkpoint never becomes the canonical —
and it costs one upload per deliberate save. `tests/test_client_guard.py` has a
test asserting `save/` is *not* watched; its reasoning has to change with it,
not just its assertion.

**Let a neighbour fade from the sector after a while away.** A storefront
appears for every member in the same system and nothing takes it out again, so
somebody who joined once and never came back sits there for good — and a room
open to sixty-four people from a Discord invite collects those quickly. A sector
of ghosts is not a living room.

The rule: a storefront only appears while its owner has played recently, on a
`neighbour_ttl_hours` per room, **24 hours** by default, `null` to never fade.
The clock is `membership.last_seen_at`, which is touched on join, on every
checkpoint and on check-in — by playing, not by logging in.

It does half the work of the item below, and the room page should show when
each member was last seen, because an invisible rule with a visible effect is
how someone concludes the thing is broken.

**Let the room owner remove a player's ship.** A room open to sixty-four people
from a Discord invite will eventually hold somebody who joined once and never
came back, or somebody who has to go. Today nothing can remove them, and the map
keeps drawing a ship that is not playing. It needs care the rest of phase 2 does
not: it deletes somebody's save, so it wants a confirmation that names the
player, and it should be recorded in the room's history rather than done
silently.

**Let the player name their own ship, from the client or the web.** The name is
what a neighbour reads on the storefront, so it is the one piece of self-
presentation the room offers — and today it is a random draw the game made at
creation. Whatever interface phase 2 grows, this belongs in it.

Two constraints it has to respect, both from `findings.md` item 20. The name
cannot become identity: the storefront must keep carrying the account as well,
or renaming turns into impersonation the moment the room has strangers. And the
server has to be the one that writes it into the portrait — reading the player's
current `sname` from their save would hand the same route back, inside the game
where it costs more.

**Shared discovery. Built.** What one player uncovers becomes visible to the others,
including people who join later. It is the co-op the room is missing: today
everyone explores the same galaxy alone, and the only thing the room shares is
where people are standing.

`findings.md` item 23 measured what "uncovered" is made of, and it is two
things. There are the `visited` and `isVisible` flags on each body's `<info>`,
and there is whether the body or empty sector is in the `<starmap>` at all —
item 19 established the galaxy materialises lazily, on arrival. A fresh save
carried 123 bodies for 64 systems; one played 178 days carried 233 for 77. So
sharing discovery is a **union of both**: merge in the subtrees other members
have materialised, and OR the flags. Mechanically it is the graft from item 17,
merged instead of wholesale, and it belongs in the same `checkout` assembly step
as the neighbour portraits.

It is only possible because the fingerprint counts stars. The digest that
counted bodies would refuse the very divergence this feature creates.

**The rule, decided and shipped:** share `visited`. Do not share `isVisible`
on its own — it comes along only where a visit came with it.

How it ended up working. The room keeps a `room_body` row per place, holding the
body's own XML with `<fleets>` stripped, keyed by `(systemId, x, y)`. Places are
harvested from every save that arrives — join, checkpoint and check-in, so a
discovery reaches the others *during* a session rather than at the end of it —
and merged into every save that leaves at checkout.

Two things it deliberately does not do. It never replaces a body the receiver
already has, only sets the flags: the local `<stuff>` holds what that person
already mined, and overwriting would hand back ore they had taken. And
`<fleets>` never travels, so nobody's ship appears in anybody else's sector —
that is phase 2, with a recipe of its own.

Measured before building: a visited body is 600 to 3300 bytes of XML, and the
fifteen in a 178-day save came to 18 KB. An inserted body takes a fresh id from
the receiver's `objectIdCounter`; reusing the donor's would collide with a body
that already exists on the other side.

So the room pools the places somebody actually went to, and those arrive
properly charted. What a member merely glimpsed from a distance, and never
entered, stays theirs. A newcomer inherits the room's travels, not its
telescope.

`findings.md` item 23 measured that `visited` is always a subset of
`isVisible` — the game never marks a place visited without also marking it
visible. So setting a shared `visited` obliges setting `isVisible` on that same
body, to avoid handing the game a combination it never produces itself. That is
not a second decision; it is the first one being applied correctly.

Bodies are matched between players by `(systemId, x, y)`. Not `celeid`, which
names a kind of place rather than a place, and not the local `id`, which is
allocated from a global counter as people explore and therefore collides
between two players who explored different systems. Both measured in item 24.

One consequence to watch, not a decision: **saves converge upward.** Everyone
ends up carrying the union, so the room's saves grow toward the most-travelled
member's. Worth measuring against the 32 MB upload ceiling before a room of 64
people finds it for us.

**What phase 2 delivered, and the seam it exposed.** A storefront now appears
in the sector of every member in the same system, capped at three, assembled at
checkout and stripped at check-in. Confirmed in a real game: `HSS YANNI
(Vizinha)`, Civilians, Relationship 74 [Friendly] — and its crew opened a
conversation asking for resources.

That conversation is the seam. The storefront is a **Civilian** ship, and the
relationship table is indexed by pair of sides, never by ship (item 11). So
giving those resources moves the player's standing with the entire Civilian
faction, and the neighbour it is named after receives nothing at all. The game
will happily run an economy against a ship the server invented; what it cannot
do is route the result to a person.

That is precisely the hole reconciliation has to fill, and it is worth stating
plainly before anyone in a room hands cargo to a shopfront believing a neighbour
is on the other side of it.

**Consignment is one storage on your own ship.** Decided after looking at
three ways to mark what is for sale.

The player points at one storage and that is the shop. From then on they manage
it with the game's own interface: what they move in is for sale, what they take
out is not. No catalogue, no new screen, and dragging cargo is a mechanic they
already know.

The other two lost for different reasons. Reusing the storage `<rules>` would
give them a meaning the game does not — they are autotransfer rules, so anybody
using "Bring here" to tidy their ship would be putting cargo up for sale without
knowing. A new button on the storage panel would be clearer and costs interface
written blind, in a game only the player can see.

It also matches the game's own model: an NPC bank has `offerList` and
`holdBackItems` — it offers the cargo it has, minus what it holds back. For the
game, having is offering. A dedicated storage is exactly "what I have to sell",
kept apart from "what I have".

**Phase 3 — consignment and reconciliation.** Depends on the result of stage A.
Market stall, not cargo hold: only the consigned goods go into the portrait, `ca`
limits how much the ship buys, and reconciliation debits the consignment and
credits the seller.

Out of the queue, blocking nothing: the minimal mod from 2.9 and live injection.

---

## Risks this plan accepts

- **Losing the token loses the player.** The price of not keeping personal data.
  Mitigated only by the client insisting on the recovery code.
- **An open room with no accounts invites throwaway players.** Creating a token is
  free; if it becomes a problem, the answer is a cost at creation, not
  registration.
- **A history of N versions limits the audit in 2.7.** An old divergence may
  already have left the window by the time someone looks.
- **Vendoring the fingerprint creates two copies of the same logic.** The
  cross-test is what stops silent drift.
- **A game update puts everything up for re-verification.** Worth anchoring the
  game version per room from phase 0, so the server refuses a save from a
  different version instead of accepting it and corrupting it.
