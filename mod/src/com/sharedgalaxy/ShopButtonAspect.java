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
            final String id = String.valueOf(
                element.getClass().getMethod("getId").invoke(element));
            addButton(panel, id, hook);
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

        // TIRA O NOSSO ANTIGO, nao pergunta se ja tem.
        //
        // A versao anterior perguntava "a caixa ja tem um botao nosso?" e
        // voltava calada quando sim. So que a caixa continua guardando a
        // referencia do botao da selecao passada mesmo depois de o painel ser
        // refeito — entao a resposta era sempre "sim", e a partir da segunda
        // selecao o botao nunca mais aparecia. Perguntar era o erro; remover e
        // idempotente e nao depende de a caixa estar limpa.
        Object caixa = read(selectionBox, "commandBox");
        int antes = caixa == null ? -1 : tamanho(read(caixa, "buttons"));
        int tirados = dropOurs(caixa);
        final Object button = Class.forName(BUTTONS, true, loader)
            .getMethod("getBaseCheckBox1").invoke(null);

        label(button, id);
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

        // NA CAIXA DE COMANDOS, junto de MOVE / DUPLICATE / DISMANTLE.
        //
        // A primeira versao chamou o `addButton` protegido do
        // `AbstractSelectedBoxItem`, que repassa para o `selectionBox` — outra
        // caixa. O botao existia e funcionava, mas aparecia no rodape, quase
        // fora da area do jogo, e o jogador quase nao o achou. O
        // ClaimAllDerelicts ja fazia o certo e eu li a receita pela metade:
        // selectionBox -> commandBox -> addButton.
        Object commandBox = caixa;
        if (commandBox == null) {
            throw new IllegalStateException("the panel has no commandBox");
        }
        // NA CAIXA DE COMANDOS, no comeco da fila.
        //
        // Medido nas duas direcoes, com o jogador olhando a tela: pelo
        // `addButton` do painel o controle vai para o rodape, quase fora da
        // area de jogo; pelo `commandBox` ele fica junto de MOVE / DUPLICATE /
        // DISMANTLE, que e onde alguem procuraria.
        //
        // O caminho do painel parecia o certo por ser o do jogo, e nao e: os
        // botoes do proprio painel chegam ao commandBox por outra rota.
        Class<?> stageButton = Class.forName(
            "fi.bugbyte.framework.screen.StageButton", true, loader);
        Object aceito;
        try {
            commandBox.getClass()
                .getMethod("addButtonAtIndex", stageButton, int.class)
                .invoke(commandBox, button, Integer.valueOf(0));
            aceito = Boolean.TRUE;
        } catch (NoSuchMethodException semIndice) {
            aceito = commandBox.getClass().getMethod("addButton", stageButton)
                .invoke(commandBox, button);
        }

        if (Boolean.FALSE.equals(aceito)) {
            trace(hook, id, "REFUSED, box " + antes + " -> "
                           + tamanho(read(commandBox, "buttons"))
                           + " || " + geometry(commandBox), panel);
        }
    }

    /**
     * Tira da caixa qualquer botao que seja nosso.
     *
     * Reconhecidos pelo que o proxy do clique responde a `toString`: o objeto
     * muda a cada selecao, a marca nao.
     */
    private static int dropOurs(Object commandBox) {
        Object lista = commandBox == null ? null : read(commandBox, "buttons");
        if (lista == null) {
            return 0;
        }
        int tirados = 0;
        try {
            java.lang.reflect.Method get = lista.getClass()
                .getMethod("get", int.class);
            java.lang.reflect.Method remove = commandBox.getClass()
                .getMethod("removeButton",
                    Class.forName("fi.bugbyte.framework.screen.StageButton",
                                  true, commandBox.getClass().getClassLoader()));
            for (int i = tamanho(lista) - 1; i >= 0; i--) {
                Object b = get.invoke(lista, Integer.valueOf(i));
                if (b == null) {
                    continue;
                }
                Object h = b.getClass().getMethod("getClickHandler").invoke(b);
                if (h != null && MARKER.equals(h.toString())) {
                    remove.invoke(commandBox, b);
                    tirados++;
                }
            }
        } catch (Throwable failure) {
            System.err.println("[shared-galaxy] could not clear the old shop "
                               + "button: " + failure);
        }
        return tirados;
    }

    /**
     * Onde cada botao da caixa foi parar, e ate onde a tela vai.
     *
     * O que decide se um botao existe mas nao se ve: `redoButtonPositions`
     * distribui somando larguras, e quem passar da borda fica invisivel.
     */
    private static String geometry(Object commandBox) {
        StringBuilder out = new StringBuilder();
        try {
            Object tela = Class.forName("com.badlogic.gdx.Gdx")
                .getField("graphics").get(null);
            out.append("screenW=")
               .append(tela.getClass().getMethod("getWidth").invoke(tela));
        } catch (Throwable unknown) {
            out.append("screenW=?");
        }
        Object lista = read(commandBox, "buttons");
        int total = tamanho(lista);
        try {
            java.lang.reflect.Method get = lista.getClass()
                .getMethod("get", int.class);
            for (int i = 0; i < total; i++) {
                Object b = get.invoke(lista, Integer.valueOf(i));
                Object h = b.getClass().getMethod("getClickHandler").invoke(b);
                boolean nosso = h != null && MARKER.equals(h.toString());
                out.append(nosso ? " [OURS " : " [")
                   .append(b.getClass().getMethod("getX").invoke(b))
                   .append(",w=")
                   .append(b.getClass().getMethod("getWidth").invoke(b))
                   .append("]");
            }
        } catch (Throwable unknown) {
            out.append(" (posicoes indisponiveis: ").append(unknown).append(")");
        }
        return out.toString();
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
