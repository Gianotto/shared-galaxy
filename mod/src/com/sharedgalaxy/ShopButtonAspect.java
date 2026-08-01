package com.sharedgalaxy;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.FileInputStream;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

import org.aspectj.lang.JoinPoint;
import org.aspectj.lang.annotation.After;
import org.aspectj.lang.annotation.Aspect;

/**
 * A button on the storage panel that makes that storage your shop.
 *
 * <p>Consignment is one storage on your own ship: what you move into it is what
 * your neighbours can buy. Choosing it in a terminal works and is what shipped
 * first, but the game never shows the storage's id — so the player was matching
 * a number against the "Capacity: 153 / 250" line. This puts the choice where
 * the storage is.
 *
 * <h2>Why the state lives in a file and not in the save</h2>
 *
 * <p>Because it cannot live in the save. The game writes savegames from its own
 * objects, so an attribute this mod invents is gone the next time the player
 * saves. The button therefore writes the chosen id to {@code sharedgalaxy.shop}
 * beside the game, and the client sends it on when the session is returned.
 *
 * <h2>The recipe</h2>
 *
 * <p>Every step of it is reflective, and every step was read out of the game or
 * out of a mod that already does this in production:
 *
 * <pre>
 *   MenuSystemItems$SingleWorldElementSelected.open(SelectionBox)  the hook
 *   field `element`                        what is selected
 *   WorldObject.features.stores != null    it is a storage
 *   WorldElement.getId()                   the id the save uses
 *   TextButtons2.getBase()                 a button
 *   ScalableIconTextButton.setText         its label
 *   Proxy of StageButton$clickHandler      the click
 *   selectionBox -> commandBox -> addButton  next to MOVE and DISMANTLE
 * </pre>
 *
 * <p>The panel is rebuilt every time it opens, so the button is added on every
 * open rather than kept — which is also what keeps its label honest when the
 * shop changes.
 *
 * <p>Nothing here can break a game. Every failure is caught and logged: the
 * worst case is a panel without our button, and the terminal command still
 * works.
 */
@Aspect
public class ShopButtonAspect {

    /** Where the chosen storage id is written, beside the game. */
    public static final String SHOP_FILE = "sharedgalaxy.shop";

    private static final String PANEL =
        "fi.bugbyte.spacehaven.gui.MenuSystemItems$SingleWorldElementSelected";
    private static final String BOX_ITEM =
        "fi.bugbyte.spacehaven.gui.MenuSystemItems$AbstractSelectedBoxItem";
    private static final String BUTTONS = "fi.bugbyte.gen.compiled.TextButtons2";
    private static final String CLICK =
        "fi.bugbyte.framework.screen.StageButton$clickHandler";

    @After("execution(* fi.bugbyte.spacehaven.gui.MenuSystemItems"
           + "$SingleWorldElementSelected.open(..))")
    public void afterPanelOpened(JoinPoint joinPoint) {
        Object panel = joinPoint.getTarget();
        try {
            Object element = read(panel, "element");
            if (element == null || !isStorage(element)) {
                return;
            }
            final String id = String.valueOf(
                element.getClass().getMethod("getId").invoke(element));
            addButton(panel, id);
        } catch (Throwable failure) {
            // A panel without our button is a small loss; a crash while
            // somebody clicks a crate is not.
            System.err.println("[shared-galaxy] could not add the shop button: "
                               + failure);
        }
    }

    /**
     * Is this a storage?
     *
     * <p>`features.stores` is what the game itself checks in
     * `isStorageWithStuff`. Producers, engines and sickbays carry inventories
     * too, of supplies being consumed — offering those would sell somebody the
     * fuel out of their engine.
     */
    private static boolean isStorage(Object element) {
        Object features = read(element, "features");
        return features != null && read(features, "stores") != null;
    }

    private static void addButton(final Object panel, final String id)
            throws Exception {
        ClassLoader loader = panel.getClass().getClassLoader();
        final Object button = Class.forName(BUTTONS, true, loader)
            .getMethod("getBase").invoke(null);

        label(button, id);

        Class<?> click = Class.forName(CLICK, true, loader);
        Object handler = Proxy.newProxyInstance(
            loader, new Class<?>[]{click}, new InvocationHandler() {
                public Object invoke(Object proxy, Method method, Object[] args) {
                    if ("clicked".equals(method.getName())) {
                        toggle(id);
                        try {
                            label(button, id);
                        } catch (Throwable ignored) {
                            // the label is cosmetic; the choice is already made
                        }
                        return null;
                    }
                    if ("toString".equals(method.getName())) {
                        return "sharedGalaxyShopButton";
                    }
                    if ("hashCode".equals(method.getName())) {
                        return Integer.valueOf(System.identityHashCode(proxy));
                    }
                    if ("equals".equals(method.getName())) {
                        return Boolean.valueOf(proxy == args[0]);
                    }
                    return null;
                }
            });
        button.getClass().getMethod("setClickHandler", click)
            .invoke(button, handler);

        // NA CAIXA DE COMANDOS, junto de MOVE / DUPLICATE / DISMANTLE.
        //
        // A primeira versao chamou o `addButton` protegido do
        // `AbstractSelectedBoxItem`, que repassa para o `selectionBox` — outra
        // caixa. O botao existia e funcionava, mas aparecia no rodape, quase
        // fora da area do jogo, e o jogador quase nao o achou. O
        // ClaimAllDerelicts ja fazia o certo e eu li a receita pela metade:
        // selectionBox -> commandBox -> addButton.
        Object selectionBox = read(panel, "selectionBox");
        if (selectionBox == null) {
            throw new IllegalStateException("the panel has no selectionBox");
        }
        Object commandBox = read(selectionBox, "commandBox");
        if (commandBox == null) {
            throw new IllegalStateException("the panel has no commandBox");
        }
        commandBox.getClass().getMethod("addButton",
                Class.forName("fi.bugbyte.framework.screen.StageButton",
                              true, loader))
            .invoke(commandBox, button);
    }

    private static void label(Object button, String id) throws Exception {
        String texto = id.equals(current()) ? "SHOP: ON" : "SET AS SHOP";
        button.getClass().getMethod("setText", String.class)
            .invoke(button, texto);
    }

    /** One shop at a time: choosing another moves it, choosing this one closes it. */
    private static void toggle(String id) {
        String agora = current();
        String novo = id.equals(agora) ? "" : id;
        write(novo);
        String recado = novo.isEmpty()
            ? "Shared Galaxy — shop closed; nothing of yours is for sale"
            : "Shared Galaxy — storage " + novo + " is your shop. It reaches "
              + "the server when you close the game";
        // Nos dois lugares. O log do jogo e onde a pessoa esta olhando; o
        // terminal e onde ela procura quando desconfia que nao funcionou.
        System.out.println("[shared-galaxy] " + recado);
        try {
            AutoLoadAspect.log(recado);
        } catch (Throwable failure) {
            // Engolir isto foi erro: uma falha silenciosa aqui parece que o
            // clique nao fez nada, e a pessoa clica de novo — desfazendo.
            System.err.println("[shared-galaxy] could not write to the game "
                               + "log: " + failure);
        }
    }

    static String current() {
        InputStream in = null;
        try {
            File file = new File(SHOP_FILE);
            if (!file.isFile()) {
                return "";
            }
            in = new FileInputStream(file);
            byte[] buffer = new byte[64];
            int n = in.read(buffer);
            return n <= 0 ? "" : new String(buffer, 0, n, "UTF-8").trim();
        } catch (Exception failure) {
            return "";
        } finally {
            close(in);
        }
    }

    private static void write(String id) {
        FileOutputStream out = null;
        try {
            out = new FileOutputStream(SHOP_FILE);
            out.write((id + "\n").getBytes("UTF-8"));
        } catch (Exception failure) {
            System.err.println("[shared-galaxy] could not write "
                               + SHOP_FILE + ": " + failure);
        } finally {
            close(out);
        }
    }

    private static void close(java.io.Closeable it) {
        if (it != null) {
            try {
                it.close();
            } catch (Exception ignored) {
                // nothing useful to do with a failed close
            }
        }
    }

    private static Object read(Object owner, String name) {
        for (Class<?> type = owner.getClass(); type != null;
                type = type.getSuperclass()) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                return field.get(owner);
            } catch (NoSuchFieldException keepLooking) {
                continue;
            } catch (Throwable failure) {
                return null;
            }
        }
        return null;
    }
}
