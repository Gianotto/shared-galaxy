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
    /**
     * A fabrica de toggles em estilo caixa de selecao — a mesma familia do
     * "ALLOW FOOD CONSUMPTION" do painel. Ser loja e uma CONFIGURACAO do
     * armazem, nao uma acao como MOVE ou DISMANTLE, e o controle tem que dizer
     * isso pela forma.
     */
    /** O armazem que esta selecionado agora, ou null. */
    private static volatile String selected;

    /** O nosso toggle enquanto o painel dele estiver aberto. */
    private static Object mine;

    /**
     * UM botao por armazem, reaproveitado.
     *
     * <p>E a diferenca entre este mod e um que funciona em producao. O
     * ClaimAllDerelicts guarda o botao num `WeakHashMap` por nave e adiciona
     * sempre o MESMO objeto — "Reutilizando boton existente" esta nas strings
     * dele. Eu criava um objeto novo a cada selecao e ainda removia o anterior,
     * que e justamente o que o jogo pode continuar rastreando: o novo entra
     * meio registrado, numa lista e nao noutra, e desenha as vezes.
     *
     * <p>Fraco por chave para nao segurar armazem que a pessoa desmontou.
     */
    private static final java.util.Map<String, Object> cache =
        new java.util.WeakHashMap<String, Object>();

    private static final String BUTTONS =
        "fi.bugbyte.gen.compiled.ToggleTextIconButtons1";
    private static final String CLICK =
        "fi.bugbyte.framework.screen.StageButton$clickHandler";

    /** O que o nosso proxy responde a `toString`, para reconhecer o botao. */
    static final String MARKER = "sharedGalaxyShopButton";

    /**
     * A troca de selecao, que e o que realmente acontece sempre.
     *
     * <p>O gancho era `SingleWorldElementSelected.open(..)`, e o botao ficava
     * intermitente. A instrumentacao respondeu: quando ele nao aparecia, NAO
     * havia linha nenhuma no terminal — o conselho nao rodava. `open()` nao e
     * chamado em toda reselecao; a `SelectionBox` reaproveita o painel.
     *
     * <p>`setSelectedItem` e `setNewSelectedItem` sao por onde toda troca
     * passa, e e de la que o painel chega como argumento.
     */
    @After("execution(* fi.bugbyte.spacehaven.gui.MenuSystem$SelectionBox"
           + ".setSelectedItem(..))"
           + " || execution(* fi.bugbyte.spacehaven.gui.MenuSystem$SelectionBox"
           + ".setNewSelectedItem(..))")
    public void afterSelectionChanged(JoinPoint joinPoint) {
        Object[] args = joinPoint.getArgs();
        if (args.length == 0 || args[0] == null) {
            return;
        }
        if (!args[0].getClass().getName().endsWith("SingleWorldElementSelected")) {
            return;
        }
        offerButton(args[0], joinPoint.getSignature().getName());
    }

    @After("execution(* fi.bugbyte.spacehaven.gui.MenuSystemItems"
           + "$SingleWorldElementSelected.open(..))")
    public void afterPanelOpened(JoinPoint joinPoint) {
        offerButton(joinPoint.getTarget(), "open");
    }

    /**
     * A caixa de comandos acabou de ser esvaziada; se um armazem esta
     * selecionado, o botao dele volta.
     *
     * <p>E o alvo que faltava. `clearCommandButtons` e do `MenuSystem`, roda
     * quando ele reconstroi a barra, e nao tem como saber de um botao que um
     * mod pos ali — some o nosso e fica o resto. Reagir a ele e reagir a causa,
     * em vez de tentar adivinhar o que havia de errado com o botao.
     *
     * <p>O mod publicado que faz isso em producao tece o `MenuSystem` por
     * exatamente esta razao, e eu nao tecia.
     */
    @After("execution(* fi.bugbyte.spacehaven.gui.MenuSystem"
           + ".clearCommandButtons(..))")
    public void afterCommandButtonsCleared(JoinPoint joinPoint) {
        try {
            Object menuSystem = joinPoint.getTarget();
            Object box = read(menuSystem, "selectionBox");
            Object item = box == null ? null : read(box, "selectedItem");
            if (item == null) {
                return;
            }
            if (!item.getClass().getName()
                    .endsWith("SingleWorldElementSelected")) {
                return;
            }
            offerButton(item, "afterClear");
        } catch (Throwable failure) {
            System.err.println("[shared-galaxy] could not restore the shop "
                               + "toggle: " + failure);
        }
    }

    private static void offerButton(Object panel, String hook) {
        try {
            if (panel == null) {
                trace(hook, "-", "no panel", null);
                return;
            }
            Object element = read(panel, "element");
            if (element == null) {
                trace(hook, "-", "panel has no element", panel);
                return;
            }
            if (!isStorage(element)) {
                return;     // nao e armazem: silencio aqui e correto
            }
            selected = String.valueOf(
                element.getClass().getMethod("getId").invoke(element));
            addButton(panel, selected, hook);
        } catch (Throwable failure) {
            // A panel without our button is a small loss; a crash while
            // somebody clicks a crate is not.
            System.err.println("[shared-galaxy] could not add the shop button: "
                               + failure);
        }
    }

    /**
     * O controle do armazem no OVERVIEW acabou de abrir: o toggle entra ali.
     *
     * <p>Aqui o registro e na TELA (`Screen.addButton`), nao numa caixa que o
     * `MenuSystem` administra e esvazia. Foi por isso que a barra de comandos
     * nunca parou de piscar: ela tem dono, e o dono nao tem contrato com mods.
     *
     * <p>E o lugar certo tambem pelo sentido: ser loja e uma configuracao do
     * armazem, vizinha do "allow food consumption", nao uma acao ao lado de
     * MOVE e DISMANTLE.
     */
    @After("execution(* fi.bugbyte.spacehaven.gui.WorldElementInfos"
           + "$StorageControl.open(..))")
    public void afterStorageControlOpened(JoinPoint joinPoint) {
        Object[] args = joinPoint.getArgs();
        String id = selected;
        // Falar tambem quando nao faz nada: um retorno mudo aqui produz
        // exatamente "o botao nem apareceu", que nao distingue gancho que nao
        // rodou de gancho que rodou sem dados.
        System.out.println("[shared-galaxy] storageControl.open args="
                           + args.length + " selected=" + id);
        if (args.length == 0 || args[0] == null || id == null) {
            return;
        }
        try {
            Object screen = args[0];
            ClassLoader loader = screen.getClass().getClassLoader();
            Object button = Class.forName(BUTTONS, true, loader)
                .getMethod("getBaseCheckBox1").invoke(null);
            label(button, id);
            hold(button, id);
            handler(button, id, loader);
            screen.getClass().getMethod("addButton",
                    Class.forName("fi.bugbyte.framework.screen.StageButton",
                                  true, loader))
                .invoke(screen, button);
            mine = button;
            System.out.println("[shared-galaxy] shop toggle added to the "
                               + "screen for storage " + id);
        } catch (Throwable failure) {
            System.err.println("[shared-galaxy] could not add the shop toggle: "
                               + failure);
        }
    }

    /**
     * Poe o toggle ao lado do de comida.
     *
     * <p>A posicao sai do proprio controle do jogo, nunca de coordenadas
     * inventadas: o `toggleEatingAllowed` acabou de ser colocado, e o nosso vai
     * ao lado dele. Se aquele nao existir — armazem so de corpos, por exemplo —
     * serve o botao de transferencia.
     */
    @After("execution(* fi.bugbyte.spacehaven.gui.WorldElementInfos"
           + "$StorageControl.setPos(..))")
    public void afterStorageControlMoved(JoinPoint joinPoint) {
        Object button = mine;
        if (button == null) {
            System.out.println("[shared-galaxy] storageControl.setPos, "
                               + "but no toggle of ours exists");
            return;
        }
        try {
            Object control = joinPoint.getTarget();
            Object vizinho = read(control, "toggleEatingAllowed");
            if (vizinho == null) {
                vizinho = read(control, "shipLevelTransfer");
            }
            if (vizinho == null) {
                return;
            }
            float x = ((Float) vizinho.getClass().getMethod("getX")
                .invoke(vizinho)).floatValue();
            float y = ((Float) vizinho.getClass().getMethod("getY")
                .invoke(vizinho)).floatValue();
            float w = ((Float) vizinho.getClass().getMethod("getWidth")
                .invoke(vizinho)).floatValue();
            button.getClass().getMethod("setPos", float.class, float.class)
                .invoke(button, Float.valueOf(x + w + 6f), Float.valueOf(y));
            System.out.println("[shared-galaxy] toggle placed at "
                               + (x + w + 6f) + "," + y + " (beside "
                               + vizinho.getClass().getSimpleName() + ")");
        } catch (Throwable failure) {
            System.err.println("[shared-galaxy] could not place the shop "
                               + "toggle: " + failure);
        }
    }

    /** O painel fechou: o toggle sai com ele. */
    @After("execution(* fi.bugbyte.spacehaven.gui.WorldElementInfos"
           + "$StorageControl.close(..))")
    public void afterStorageControlClosed(JoinPoint joinPoint) {
        Object button = mine;
        Object[] args = joinPoint.getArgs();
        mine = null;
        if (button == null || args.length == 0 || args[0] == null) {
            return;
        }
        try {
            Object screen = args[0];
            screen.getClass().getMethod("removeButton",
                    Class.forName("fi.bugbyte.framework.screen.StageButton",
                                  true, screen.getClass().getClassLoader()))
                .invoke(screen, button);
        } catch (Throwable failure) {
            System.err.println("[shared-galaxy] could not remove the shop "
                               + "toggle: " + failure);
        }
    }

    /** O clique, por proxy: a interface tem um metodo so. */
    private static void handler(final Object button, final String id,
                               ClassLoader loader) throws Exception {
        Class<?> click = Class.forName(CLICK, true, loader);
        Object proxy = Proxy.newProxyInstance(
            loader, new Class<?>[]{click}, new InvocationHandler() {
                public Object invoke(Object self, Method method, Object[] a) {
                    if ("clicked".equals(method.getName())) {
                        toggle(id);
                        hold(button, id);
                        return null;
                    }
                    if ("toString".equals(method.getName())) {
                        return MARKER;
                    }
                    if ("hashCode".equals(method.getName())) {
                        return Integer.valueOf(System.identityHashCode(self));
                    }
                    if ("equals".equals(method.getName())) {
                        return Boolean.valueOf(self == a[0]);
                    }
                    return null;
                }
            });
        button.getClass().getMethod("setClickHandler", click)
            .invoke(button, proxy);
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

    /** Uma linha por evento, com tudo que decide o comportamento. */
    private static void trace(String hook, String id, String o_que,
                              Object panel) {
        System.out.println("[shared-galaxy] " + hook + " storage=" + id
                           + " panel=" + (panel == null ? "null"
                               : Integer.toHexString(
                                   System.identityHashCode(panel)))
                           + " :: " + o_que);
    }

    private static void addButton(final Object panel, final String id,
                                  final String hook)
            throws Exception {
        ClassLoader loader = panel.getClass().getClassLoader();

        // CEDO DEMAIS NAO E ERRO.
        //
        // `setSelectedItem` roda antes de o painel ser preso a caixa, entao o
        // campo ainda esta vazio. Nao ha o que fazer nesse instante e nao ha o
        // que consertar: o `open(SelectionBox)` chega logo depois com a caixa
        // pronta, e e ele que poe o botao. Tratar isto como falha enchia o
        // terminal de excecoes numa sequencia que funciona.
        Object selectionBox = read(panel, "selectionBox");
        if (selectionBox == null) {
            return;     // cedo demais; o `open()` cobre logo depois
        }

        Object caixa = read(selectionBox, "commandBox");
        Object commandBox = caixa;

        Object reaproveitado = cache.get(id);
        final Object button;
        if (reaproveitado != null) {
            button = reaproveitado;
        } else {
            button = Class.forName(BUTTONS, true, loader)
                .getMethod("getBaseCheckBox1").invoke(null);
            label(button, id);
            handler(button, id, loader);
            cache.put(id, button);
        }
        hold(button, id);

        Class<?> click = Class.forName(CLICK, true, loader);
        Object handler = Proxy.newProxyInstance(
            loader, new Class<?>[]{click}, new InvocationHandler() {
                public Object invoke(Object proxy, Method method, Object[] args) {
                    if ("clicked".equals(method.getName())) {
                        toggle(id);
                        hold(button, id);
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

        // PELA API DO MENUSYSTEM, com o MESMO botao de sempre.
        //
        // Duas coisas que so o mod que funciona ensinou. A rota e publica —
        // `addCommandButtonAsFirst` — e nao escrever direto no `commandBox`,
        // que tem dono e um `clearCommandButtons()`. E o botao e reaproveitado:
        // criar um objeto novo a cada selecao, e remover o anterior, deixava o
        // jogo rastreando um e desenhando outro.
        if (commandBox == null) {
            throw new IllegalStateException("the panel has no commandBox");
        }
        Object menuSystem = read(selectionBox, "menuSystem");
        if (menuSystem == null) {
            throw new IllegalStateException("the box has no menuSystem");
        }
        Class<?> stageButton = Class.forName(
            "fi.bugbyte.framework.screen.StageButton", true, loader);
        menuSystem.getClass()
            .getMethod("addCommandButtonAsFirst", stageButton)
            .invoke(menuSystem, button);

        trace(hook, id, "box now " + tamanho(read(commandBox, "buttons"))
                       + (reaproveitado != null ? " (reused)" : " (new)"),
              panel);
    }

    private static int tamanho(Object lista) {
        try {
            return ((Integer) lista.getClass().getField("size").get(lista))
                .intValue();
        } catch (Throwable unknown) {
            return 0;
        }
    }

    /** Quantos botoes uma caixa carrega, ou -1 se nao der para saber. */
    private static int count(Object box) {
        if (box == null) {
            return -1;
        }
        Object lista = box.getClass().getName().endsWith("Array")
            ? box : read(box, "buttons");
        if (lista == null) {
            return -1;
        }
        try {
            return ((Integer) lista.getClass().getField("size").get(lista))
                .intValue();
        } catch (Throwable unknown) {
            return -1;
        }
    }


    private static void label(Object button, String id) throws Exception {
        // Um so texto. Quem diz ligado ou desligado e o proprio toggle, e
        // trocar o rotulo junto seria dizer duas vezes com palavras
        // diferentes.
        button.getClass().getMethod("setText", String.class)
            .invoke(button, "SHOP");
    }

    /** Deixa o toggle no estado que ele representa. */
    private static void hold(Object button, String id) {
        try {
            button.getClass().getMethod("setHoldDown", boolean.class)
                .invoke(button, Boolean.valueOf(id.equals(current())));
        } catch (Throwable semHold) {
            System.err.println("[shared-galaxy] could not set the toggle "
                               + "state: " + semHold);
        }
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
