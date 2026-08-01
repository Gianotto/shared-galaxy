package fi.bugbyte.spacehaven.gui.menu;

/**
 * Dublê com a mesma forma que o jogo tem, incluindo as duas coisas que
 * derrubaram o aspecto em mãos de jogador.
 *
 * A PRIMEIRA: os menus não existem nos primeiros frames. `getContent` e o
 * `getMenu` privado são a mesma busca num array `content`, e nenhum dos dois
 * cria nada — quem cria é `createContent`, chamado só de `Disclaimer` e
 * `MainMenu2`. O menu de Load, portanto, só passa a existir depois que a pessoa
 * dispensa o disclaimer.
 *
 * A SEGUNDA: quanto tempo isso leva não se mede em frames. A versão que
 * esperava 3600 frames chamando aquilo de "um minuto" desistiu em 25 segundos
 * numa máquina de 144Hz, no meio do disclaimer.
 *
 * Por isso a prontidão aqui é por RELÓGIO, e o laço roda a 144Hz de propósito:
 * um prazo contado em frames volta a falhar neste dublê.
 */
public class GameMenu {

    public enum MenuType { Options, Save, Load, NewGame, MainMenu }

    /** Quantos milissegundos até os menus existirem — o disclaimer no ar. */
    static final long MENUS_EM_MS =
        Long.getLong("harness.menusAfterMs", 400L).longValue();

    /** 144Hz: ~7ms por frame. É o que expôs o prazo contado em frames. */
    static final long FRAME_MS = 7;

    public static String abriu = null;
    public static MenuType ultimoSetMenu = null;

    static long nascido = System.currentTimeMillis();

    boolean pronto() {
        return System.currentTimeMillis() - nascido >= MENUS_EM_MS;
    }

    public void update(float dt) { }

    /**
     * O jogo constroi cada menu por aqui, e e o unico lugar que preenche o
     * array que `getContent` busca. O dublê chama quando "o disclaimer sai",
     * que e quando o jogo real chama.
     */
    public Object createContent(MenuType type) { return null; }

    /**
     * O submenu ABERTO, e na tela principal não há nenhum.
     *
     * Sempre nulo aqui de propósito: o dublê devolvia "MainMenu" quando pronto,
     * e foi essa mentira que escondeu a terceira falha — o aspecto exigia
     * `getCurrent() != null` e por isso só agia quando a pessoa clicava em Load.
     */
    public Object getCurrent() { return null; }

    /** É o que devolvia nulo e produzia "the game has no Load menu". */
    public Object getContent(MenuType type) {
        if (!pronto()) {
            return null;
        }
        return type == MenuType.Load ? new LoadGameMenu() : new Object();
    }

    private void setMenu(MenuType type) { ultimoSetMenu = type; }

    static class LoadGameMenu {
        public void load(String folder, boolean autosave, int slot,
                         boolean slave) {
            abriu = folder;
        }
    }

    /**
     * Roda o aspecto contra este dublê e confere o resultado.
     *
     * <p>Argumentos: o que se espera que aconteça — o nome da pasta, `__new__`,
     * ou `-` para "não podia acontecer nada" — e por quantos milissegundos
     * rodar o laço.
     */
    public static void main(String[] args) {
        String esperado = args.length > 0 ? args[0] : "-";
        long duracao = args.length > 1 ? Long.parseLong(args[1]) : 3000L;

        GameMenu menu = new GameMenu();
        long limite = System.currentTimeMillis() + duracao;
        int frames = 0;
        boolean construiu = false;
        while (System.currentTimeMillis() < limite) {
            if (!construiu && menu.pronto()) {
                // O jogo constroi os menus quando o disclaimer sai.
                for (MenuType t : MenuType.values()) { menu.createContent(t); }
                construiu = true;
            }
            menu.update(1f / 144f);
            frames++;
            try {
                Thread.sleep(FRAME_MS);
            } catch (InterruptedException interrompido) {
                break;
            }
        }

        // Depois de "carregar", o jogo sai do estado de loading e a GUI passa
        // a rodar. É quando o log aceita linha.
        if ("-".equals(esperado) || abriu != null || ultimoSetMenu != null) {
            fi.bugbyte.spacehaven.SpaceHaven.isLoading = false;
            fi.bugbyte.spacehaven.gui.GUI gui = new fi.bugbyte.spacehaven.gui.GUI();
            for (int i = 0; i < 5; i++) { gui.update(1f / 144f); }
        }

        boolean consumido = !new java.io.File("sharedgalaxy.autoload").isFile();
        System.out.println("  frames    -> " + frames + " em " + duracao + "ms");
        System.out.println("  setMenu   -> " + ultimoSetMenu);
        System.out.println("  carregou  -> " + abriu);
        System.out.println("  consumido -> " + consumido);
        System.out.println("  no log    -> "
            + fi.bugbyte.spacehaven.gui.GameLog.linhas);

        // Se havia linhas para o log, elas tinham que chegar lá.
        boolean tinhaNotas = System.getProperty("harness.notes") != null;
        boolean logOk = !tinhaNotas
            || !fi.bugbyte.spacehaven.gui.GameLog.linhas.isEmpty();
        if (!logOk) {
            System.out.println("  FALHOU (nada chegou no log do jogo)");
            System.exit(1);
        }

        boolean ok;
        if ("-".equals(esperado)) {
            ok = abriu == null && ultimoSetMenu == null;
        } else if ("__new__".equals(esperado)) {
            ok = ultimoSetMenu == MenuType.NewGame && abriu == null;
        } else {
            ok = esperado.equals(abriu);
        }
        System.out.println(ok ? "  PASSOU" : "  FALHOU (esperava " + esperado + ")");
        if (!ok) {
            System.exit(1);
        }
    }
}
