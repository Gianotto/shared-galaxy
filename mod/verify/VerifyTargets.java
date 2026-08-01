import java.lang.reflect.Constructor;
import java.lang.reflect.Method;

/**
 * Checks that everything the aspect reaches by reflection still exists.
 *
 * <p>Reflection has no compiler. A renamed method or a changed signature in a
 * game update produces no build error and no warning — it produces a mod that
 * installs, loads, and quietly fails at the one moment it is needed, with the
 * player already staring at the menu.
 *
 * <p>So this runs against the real {@code spacehaven.jar} and names every
 * target out loud. It is the closest thing to a compiler that reflection
 * allows, and it is what should run after every game update.
 *
 * <p>It does not launch the game and touches nothing.
 */
public final class VerifyTargets {

    private static int failures;

    public static void main(String[] args) throws Exception {
        Class<?> gameMenu = require("fi.bugbyte.spacehaven.gui.menu.GameMenu");
        Class<?> menuType = require(
            "fi.bugbyte.spacehaven.gui.menu.GameMenu$MenuType");
        Class<?> saveGame = require("fi.bugbyte.spacehaven.GameData$SaveGame");
        Class<?> loadMenu = require(
            "fi.bugbyte.spacehaven.gui.menu.GameMenu$LoadGameMenu");

        // The woven join point.
        method(gameMenu, "update", float.class);

        // The enum constants the aspect asks for by name.
        constant(menuType, "Load");
        constant(menuType, "NewGame");

        // How the aspect learns the menus are being built.
        method(gameMenu, "createContent", menuType);

        // Switching the menu is what activates it, and activation is what sets
        // the `onScreen` the load path dereferences.
        method(gameMenu, "setMenu", menuType);
        method(gameMenu, "getContent", menuType);

        // The last argument of load() comes from the game, never from a guess.
        constructor(saveGame, String.class);
        method(saveGame, "isSlaveWorldActive", boolean.class, int.class);

        // The method that does the actual work.
        method(loadMenu, "load", String.class, boolean.class, int.class,
               boolean.class);

        System.out.println();
        if (failures > 0) {
            System.out.println(failures + " target(s) missing — the mod would "
                               + "fail silently against this game version");
            System.exit(1);
        }
        System.out.println("all targets present");
    }

    private static Class<?> require(String name) {
        try {
            Class<?> found = Class.forName(name);
            System.out.println("ok    class  " + name);
            return found;
        } catch (Throwable missing) {
            System.out.println("FAIL  class  " + name);
            failures++;
            return null;
        }
    }

    private static void method(Class<?> owner, String name, Class<?>... args) {
        if (owner == null) {
            failures++;
            return;
        }
        try {
            Method found = owner.getDeclaredMethod(name, args);
            System.out.println("ok    method " + owner.getSimpleName() + "."
                               + name + describe(found.getParameterTypes()));
        } catch (Throwable missing) {
            System.out.println("FAIL  method " + owner.getName() + "." + name
                               + describe(args));
            failures++;
        }
    }

    private static void constructor(Class<?> owner, Class<?>... args) {
        if (owner == null) {
            failures++;
            return;
        }
        try {
            Constructor<?> found = owner.getDeclaredConstructor(args);
            System.out.println("ok    ctor   " + owner.getSimpleName()
                               + describe(found.getParameterTypes()));
        } catch (Throwable missing) {
            System.out.println("FAIL  ctor   " + owner.getName()
                               + describe(args));
            failures++;
        }
    }

    private static void constant(Class<?> enumType, String name) {
        if (enumType == null) {
            failures++;
            return;
        }
        try {
            enumType.getDeclaredField(name);
            System.out.println("ok    enum   " + enumType.getSimpleName() + "."
                               + name);
        } catch (Throwable missing) {
            System.out.println("FAIL  enum   " + enumType.getName() + "."
                               + name);
            failures++;
        }
    }

    private static String describe(Class<?>[] args) {
        StringBuilder out = new StringBuilder("(");
        for (int i = 0; i < args.length; i++) {
            if (i > 0) {
                out.append(", ");
            }
            out.append(args[i].getSimpleName());
        }
        return out.append(")").toString();
    }
}
