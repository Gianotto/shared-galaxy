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
 * it just before launching and this aspect deletes it after reading. So the
 * game behaves exactly like a vanilla game every other time it starts — a mod
 * that hijacked every launch would be worse than the problem it solves.
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
     * Frames to let the menu finish coming up before taking it over.
     *
     * <p>The first {@code update} can run before the menu has been activated,
     * and the load path needs an activated menu. Waiting a few frames costs
     * nothing a person can perceive and removes a race that would show up as
     * an occasional crash on startup.
     */
    private static final int SETTLE_FRAMES = 10;

    private static int frames;
    private static boolean done;

    @After("execution(* fi.bugbyte.spacehaven.gui.menu.GameMenu.update(float))")
    public void afterMenuUpdate(JoinPoint joinPoint) {
        if (done) {
            return;
        }
        if (++frames < SETTLE_FRAMES) {
            return;
        }
        done = true;

        File marker = new File(MARKER);
        if (!marker.isFile()) {
            return;
        }
        String folder = read(marker);
        // Deleted whatever happens next. A marker left behind would reload the
        // same save on the next launch, silently, forever.
        marker.delete();
        if (folder == null || folder.length() == 0) {
            return;
        }
        try {
            open(joinPoint.getTarget(), folder);
            System.out.println("[shared-galaxy] opening save " + folder);
        } catch (Throwable failure) {
            // The player is at the menu and can load by hand. Taking the game
            // down because our shortcut failed would be a worse trade.
            System.err.println("[shared-galaxy] could not open " + folder
                               + ": " + failure);
        }
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
