package com.sharedgalaxy;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.lang.reflect.Method;

import org.aspectj.lang.JoinPoint;
import org.aspectj.lang.annotation.After;
import org.aspectj.lang.annotation.Aspect;

/**
 * Opens the game straight into the room's save.
 *
 * <p>Without this, a session goes: run the client, wait, then find the right
 * folder in the load menu among your own games and pick it. It works, and it is
 * the one step where somebody picks the wrong save and returns a game the room
 * never lent them.
 *
 * <h2>How it decides</h2>
 *
 * <p>It does nothing unless a file named {@code sharedgalaxy.autoload} sits in
 * the game's working directory, holding a save folder name. The client writes
 * it just before launching and this aspect drops it once it has acted. So the
 * game behaves exactly like a vanilla game every other time it starts — a mod
 * that hijacked every launch would be worse than the problem it solves.
 *
 * <h2>When it acts</h2>
 *
 * <p>When the menu it needs actually exists, which it polls for. Counting
 * frames instead was the first version, and it failed on a real launch with
 * "the game has no Load menu": {@code getContent} and the private
 * {@code getMenu} are the same lookup over a {@code content} array and neither
 * creates anything, and that array is filled long after the tenth frame, while
 * the disclaimer is still on screen.
 *
 * <h2>How it loads</h2>
 *
 * <p>By driving the game's own menu rather than reimplementing it. Measured in
 * {@code GameMenu$SaveGameSlot$LoadClickHandler}, clicking a save does:
 *
 * <pre>
 *   boolean slave = save.isSlaveWorldActive(autosave, slot);
 *   loadGameMenu.load(folderName, autosave, slot, slave);
 * </pre>
 *
 * <p>and {@code LoadGameMenu.load} then builds the {@code AsyncLoader}, opens
 * the loading popup and registers the callback. Calling that one method gets
 * all of it, including whatever the game starts doing there in a later version.
 *
 * <p>The menu is switched to {@code MenuType.Load} first. That is not cosmetic:
 * {@code load} reads the menu's {@code onScreen} field to open the popup, and
 * {@code onScreen} is only set when the menu is activated. Calling load on a
 * menu that was never shown throws a NullPointerException inside the game.
 *
 * <h2>Why reflection</h2>
 *
 * <p>{@code LoadGameMenu} and its superclass are package-private, so nothing
 * outside {@code fi.bugbyte.spacehaven.gui.menu} can name the type. Declaring
 * this class into the game's package would work on Java 8 and is exactly the
 * kind of trick that breaks quietly when the game is repackaged.
 *
 * <h2>Constraints</h2>
 *
 * <p>The game runs a bundled Java 8 JRE and its own classes are Java 7
 * bytecode, so this compiles to Java 8 and uses no API newer than that.
 */
@Aspect
public class AutoLoadAspect {

    /** Written by the client next to the game, read once, then deleted. */
    public static final String MARKER = "sharedgalaxy.autoload";

    /**
     * Marker contents that mean "open the new game menu" instead of a save.
     *
     * <p>Somebody joining a room for the first time has no ship in it yet, and
     * a room that lets a veteran arrive with a half-year-old colony is not a
     * shared start. So the first launch of a session goes to the creator, the
     * client uploads whatever was created, and the second launch opens the
     * result.
     */
    public static final String NEW_GAME = "__new__";

    /** Milliseconds to wait after the menu exists, before taking it over. */
    private static final long SETTLE_MILLIS = 250;

    /**
     * How long to keep waiting for a menu that never comes.
     *
     * <p>WALL CLOCK, not frames. The first version counted 3600 frames calling
     * it a minute; on a 144Hz machine that is twenty-five seconds, and it gave
     * up while the player was still reading the disclaimer.
     *
     * <p>Five minutes because the wait is not ours to bound: {@code
     * createContent} is only called from {@code Disclaimer} and {@code
     * MainMenu2}, so the Load menu does not exist until the person dismisses
     * the disclaimer. We are waiting on them, not on the machine.
     *
     * <p>Overridable so the test can shorten it.
     */
    private static final long GIVE_UP_MILLIS =
        Long.getLong("sharedgalaxy.giveup.ms", 300000L).longValue();

    /**
     * Frames between readiness checks.
     *
     * <p>Each check is a handful of reflective calls. At 144Hz, doing it every
     * frame is a few hundred a second for no gain.
     */
    private static final int CHECK_EVERY = 15;

    private static int frames;
    private static long deadline;
    private static long readyAt;
    private static boolean done;
    private static String wanted;
    private static boolean read;
    private static volatile boolean building;

    /**
     * The game just built a menu.
     *
     * <p>`createContent` is the switch that constructs a {@code MenuContent}
     * and puts it in the array `getContent` searches — it is the only thing
     * that does, and only `Disclaimer` and `MainMenu2` call it. Watching it is
     * how we learn the menus are being built rather than guessing at how long
     * that takes.
     */
    @After("execution(* fi.bugbyte.spacehaven.gui.menu.GameMenu.createContent(..))")
    public void afterCreateContent() {
        building = true;
    }

    @After("execution(* fi.bugbyte.spacehaven.gui.menu.GameMenu.update(float))")
    public void afterMenuUpdate(JoinPoint joinPoint) {
        if (done) {
            return;
        }
        if (!read) {
            read = true;
            deadline = System.currentTimeMillis() + GIVE_UP_MILLIS;
            File marker = new File(MARKER);
            wanted = marker.isFile() ? read(marker) : null;
            if (wanted == null || wanted.length() == 0) {
                done = true;      // vanilla launch; stop looking every frame
                return;
            }
        }
        if (++frames % CHECK_EVERY != 0 && readyAt == 0) {
            return;
        }

        Object gameMenu = joinPoint.getTarget();
        String menu = NEW_GAME.equals(wanted) ? "NewGame" : "Load";

        // WAIT FOR THE MENU TO EXIST, and wait in seconds rather than frames.
        //
        // Two failures in a row here, both from guessing instead of measuring.
        // First it fired on frame 10 and hit "the game has no Load menu":
        // `getContent` and the private `getMenu` are the same lookup over a
        // `content` array and neither creates anything. Then it waited 3600
        // frames calling that a minute, which on a 144Hz machine is
        // twenty-five seconds, and gave up mid-disclaimer.
        //
        // `content` is filled by `createContent`, called only from
        // `Disclaimer` and `MainMenu2`. So the Load menu exists once the person
        // has dismissed the disclaimer — the wait is on them.
        if (!ready(gameMenu, menu)) {
            // Enquanto o jogo ainda esta montando menu, ha o que esperar e o
            // prazo nao corre. O prazo existe so para nao deixar o bilhete
            // parado se a montagem nunca comecar.
            if (building) {
                deadline = System.currentTimeMillis() + GIVE_UP_MILLIS;
                building = false;
            }
            if (System.currentTimeMillis() > deadline) {
                done = true;
                consume();
                System.err.println("[shared-galaxy] the " + menu + " menu never "
                                   + "appeared; load your save from the menu");
            }
            return;
        }
        if (readyAt == 0) {
            readyAt = System.currentTimeMillis();
        }
        if (System.currentTimeMillis() - readyAt < SETTLE_MILLIS) {
            return;
        }

        done = true;
        String folder = wanted;
        consume();
        try {
            if (NEW_GAME.equals(folder)) {
                // First time in a room: no ship there yet, and the room wants
                // everybody to start together. Going straight to the creator is
                // what makes that fit in one command.
                newGame(gameMenu);
                System.out.println("[shared-galaxy] opening the new game menu");
            } else {
                open(gameMenu, folder);
                System.out.println("[shared-galaxy] opening save " + folder);
            }
        } catch (Throwable failure) {
            // The player is at the menu and can load by hand. Taking the game
            // down because our shortcut failed would be a worse trade.
            System.err.println("[shared-galaxy] could not open " + folder
                               + ": " + failure);
        }
    }

    /**
     * Is the menu we want built?
     *
     * <p>That is the whole condition, and asking anything else was the third
     * failure here. This also required {@code getCurrent() != null} as a
     * "menus are live" heuristic. It is not one: {@code getCurrent} returns the
     * submenu that is OPEN, and on the main screen none is — so it stayed null
     * until the player clicked Load, which is exactly when the mod finally
     * fired. {@code MainMenu2} creates the Load content while building its
     * buttons, so this is true from the main menu onwards.
     */
    @SuppressWarnings({"unchecked", "rawtypes"})
    private static boolean ready(Object gameMenu, String menu) {
        try {
            ClassLoader loader = gameMenu.getClass().getClassLoader();
            Class menuType = Class.forName(
                "fi.bugbyte.spacehaven.gui.menu.GameMenu$MenuType", true, loader);
            return gameMenu.getClass().getMethod("getContent", menuType)
                .invoke(gameMenu, Enum.valueOf(menuType, menu)) != null;
        } catch (Throwable notYet) {
            return false;
        }
    }

    /**
     * Drops the marker.
     *
     * <p>Only ever called when acting or giving up. The first version deleted
     * it up front, which meant the one failure it hit could not be retried —
     * the next launch had nothing left to read.
     */
    private static void consume() {
        new File(MARKER).delete();
    }

    private static String read(File marker) {
        InputStream in = null;
        try {
            in = new FileInputStream(marker);
            byte[] buffer = new byte[512];
            int n = in.read(buffer);
            if (n <= 0) {
                return null;
            }
            return new String(buffer, 0, n, "UTF-8").trim();
        } catch (Exception failure) {
            return null;
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (Exception ignored) {
                    // nothing useful to do with a failed close here
                }
            }
        }
    }

    /** Opens the new game creator, the same menu the main screen's button does. */
    @SuppressWarnings({"unchecked", "rawtypes"})
    private static void newGame(Object gameMenu) throws Exception {
        ClassLoader loader = gameMenu.getClass().getClassLoader();
        Class menuType = Class.forName(
            "fi.bugbyte.spacehaven.gui.menu.GameMenu$MenuType", true, loader);
        Method setMenu = gameMenu.getClass()
            .getDeclaredMethod("setMenu", menuType);
        setMenu.setAccessible(true);
        setMenu.invoke(gameMenu, Enum.valueOf(menuType, "NewGame"));
    }

    /** Drives the game's own load menu, exactly as a click would. */
    @SuppressWarnings({"unchecked", "rawtypes"})
    private static void open(Object gameMenu, String folder) throws Exception {
        ClassLoader loader = gameMenu.getClass().getClassLoader();
        Class menuType = Class.forName(
            "fi.bugbyte.spacehaven.gui.menu.GameMenu$MenuType", true, loader);
        Object load = Enum.valueOf(menuType, "Load");

        // Activating the menu is what sets the `onScreen` the load path needs.
        Method setMenu = gameMenu.getClass()
            .getDeclaredMethod("setMenu", menuType);
        setMenu.setAccessible(true);
        setMenu.invoke(gameMenu, load);

        Method getContent = gameMenu.getClass()
            .getMethod("getContent", menuType);
        Object loadMenu = getContent.invoke(gameMenu, load);
        if (loadMenu == null) {
            throw new IllegalStateException("the game has no Load menu");
        }

        // `isSlaveWorldActive` decides the last argument. The game asks it
        // before every load and we are in no position to guess it.
        Class saveGame = Class.forName(
            "fi.bugbyte.spacehaven.GameData$SaveGame", true, loader);
        Object save = saveGame.getConstructor(String.class).newInstance(folder);
        boolean slave = (Boolean) saveGame
            .getMethod("isSlaveWorldActive", boolean.class, int.class)
            .invoke(save, Boolean.FALSE, Integer.valueOf(0));

        Method loadIt = loadMenu.getClass().getMethod(
            "load", String.class, boolean.class, int.class, boolean.class);
        loadIt.setAccessible(true);
        loadIt.invoke(loadMenu, folder, Boolean.FALSE, Integer.valueOf(0),
                      Boolean.valueOf(slave));
    }
}
