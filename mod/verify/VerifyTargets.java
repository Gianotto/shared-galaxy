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

        // Telling the player which room and version they are in, using the
        // game's own log window.
        Class<?> gui = require("fi.bugbyte.spacehaven.gui.GUI");
        Class<?> gameLog = require("fi.bugbyte.spacehaven.gui.GameLog");
        Class<?> logType = require(
            "fi.bugbyte.spacehaven.gui.GameLog$LogType");
        method(gui, "update", float.class);
        method(gameLog, "addLog", String.class, logType, Object.class);
        constant(logType, "Normal");
        field(require("fi.bugbyte.spacehaven.SpaceHaven"), "isLoading");

        // O botão que faz de um armazém a sua loja.
        Class<?> panel = require(
            "fi.bugbyte.spacehaven.gui.MenuSystemItems$SingleWorldElementSelected");
        Class<?> stageButton = require(
            "fi.bugbyte.framework.screen.StageButton");
        Class<?> clickHandler = require(
            "fi.bugbyte.framework.screen.StageButton$clickHandler");
        Class<?> buttons = require("fi.bugbyte.gen.compiled.TextButtons2");
        Class<?> worldObject = require(
            "fi.bugbyte.spacehaven.world.elements.WorldObject");
        Class<?> features = require(
            "fi.bugbyte.spacehaven.world.elements.WorldObject$ObjectFeatures");

        field(panel, "element", false);
        field(require("fi.bugbyte.spacehaven.gui.MenuSystem$SelectionBox"),
              "commandBox", false);
        method(require("fi.bugbyte.spacehaven.gui.MenuSystem$SelectionCommandBox"),
               "addButton", stageButton);
        method(buttons, "getBase");
        method(stageButton, "setClickHandler", clickHandler);
        method(require("fi.bugbyte.framework.screen.ScalableIconTextButton"),
               "setText", String.class);
        method(require("fi.bugbyte.spacehaven.world.elements.WorldElement"),
               "getId");
        field(worldObject, "features");
        field(features, "stores");

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
            // Sem inicializar. Classes de GUI compilada, como TextButtons2,
            // sobem a biblioteca de assets no <clinit> e falham fora do jogo —
            // e "nao consegui inicializar" nao e "nao existe".
            Class<?> found = Class.forName(name, false,
                                           VerifyTargets.class.getClassLoader());
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

    private static void field(Class<?> owner, String name) {
        field(owner, name, true);
    }

    /** `publico` falso procura tambem campos que so a reflexao alcanca. */
    private static void field(Class<?> owner, String name, boolean publico) {
        if (owner == null) {
            failures++;
            return;
        }
        try {
            if (publico) {
                owner.getField(name);
            } else {
                owner.getDeclaredField(name);
            }
            System.out.println("ok    field  " + owner.getSimpleName() + "."
                               + name);
        } catch (Throwable missing) {
            System.out.println("FAIL  field  " + owner.getName() + "." + name);
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
