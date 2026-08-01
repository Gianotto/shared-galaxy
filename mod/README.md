# Shared Galaxy — the mod

Opens the game straight into your room's save.

It is the last step of the single command. Without it, `sgalaxy play` checks the
save out, launches the game, and then you still have to find the right folder in
the load menu among your own games — which is also the one step where somebody
picks the wrong save and returns a game the room never lent them.

**It is optional.** Everything works without it; you just load by hand.

## What it does, and what it does not

It watches for a file named `sharedgalaxy.autoload` in the game's folder,
holding a save folder name. The client writes it just before launching; the mod
reads it, deletes it, and opens that save.

The marker can also say `__new__`, and then the mod opens the **new game**
menu instead. That is the first time somebody joins a room: they have no ship
there yet, the room wants everyone to start together, so the client opens the
creator, waits, and uploads whatever was built.

It also reads a second file, `sharedgalaxy.log`, and puts each line into the
game's own log window — the one that says "Day 3.10 Autosaved". That is where
the room, the save version and the server appear, so nobody has to wonder
mid-session whether they are playing the room's save or a local game. The mod
does not know what a room or a server is: the client writes the text, this only
carries it in.

It also adds a **SET AS SHOP** button to the panel of any storage, so choosing
which storage your neighbours buy from happens where the storage is, instead of
by matching a number in a terminal against the "Capacity" line. The choice goes
to `sharedgalaxy.shop`, which the client sends on when the session is returned —
it cannot live in the savegame, because the game writes savegames from its own
objects and an attribute this mod invents would be gone at the next save.

Every other launch behaves exactly like an unmodded game. A mod that hijacked
every start would be worse than the problem it solves.

It changes nothing in any savegame, and reads nothing except that one file.

## Building

```
mod/build.sh --verify
```

Needs Docker and the game. No JDK, no AspectJ, no Maven — it runs everything in
containers. `--verify` additionally checks that every method the mod reaches by
reflection still exists in *your* `spacehaven.jar`.

The AspectJ jars come from the Mod Loader you already have subscribed. Nothing
is downloaded from anywhere else.

## Installing

```
python3 tools/install_mod.py --dry-run   # see what it would change
python3 tools/install_mod.py
python3 tools/install_mod.py --uninstall
```

On Windows you can also let the SpaceHaven Mod Loader install it, like any other
code mod. On Linux the Workshop loader is a Windows executable and cannot run,
which is why `install_mod.py` exists — see `docs/findings.md` item 25.

Either way, installation is only this:

1. `aspectjweaver-<version>.jar` beside the game
2. `-javaagent:./aspectjweaver-<version>.jar` appended to `vmArgs` in `config.json`
3. `SharedGalaxy.jar` appended to `classPath` in `config.json`

**This is the one place the project touches your game installation.** It keeps a
backup of `config.json`, `--uninstall` puts it back, and a Steam file
verification also undoes it.

## How it hooks in

An AspectJ aspect, woven at load time into `GameMenu.update(float)`. After a few
frames it switches the menu to `MenuType.Load` and calls the game's own
`LoadGameMenu.load(folder, false, 0, slave)` — the same method a click calls.

Driving the game's menu rather than reimplementing the load is deliberate: it
inherits the popup, the async loader and the callback, including whatever a
future version starts doing there.

`docs/findings.md` items 24b and 25 record what was measured to get here,
including the two mistakes that each cost a crash.

## Testing without the game

```
mod/build.sh --test
```

Runs the aspect under the real weaver against a stub that has the same shape as
the game, including the part that matters: **the menus do not exist for the
first frames.** Four scenarios — a menu that appears late, the new game path, no
marker at all, and a menu that never appears.

That last shape is what shipped broken once. The mod acted on a frame count, the
menus were not built yet, and it failed in the player's hands with "the game has
no Load menu". There was no way to exercise the reflection end to end without
launching the game, so the defect could only show up there. Now it cannot.

## After a game update

```
mod/build.sh --verify
```

The mod reaches the game by reflection, which has no compiler. A renamed method
produces no build error — just a mod that fails at the one moment it is needed.
`VerifyTargets` is the substitute for that missing compiler.
