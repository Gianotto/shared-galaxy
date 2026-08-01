package fi.bugbyte.spacehaven.gui.menu;

/**
 * Dublê com a mesma forma que o jogo tem, incluindo o que derrubou a primeira
 * versão do aspecto: os menus NÃO existem nos primeiros frames.
 *
 * Tem tudo que o aspecto alcança por reflexão, para que o caminho inteiro seja
 * exercitado — era essa lacuna que deixava o defeito passar até o jogo real.
 */
public class GameMenu {

    public enum MenuType { Options, Save, Load, NewGame, MainMenu }

    /** O jogo real leva bem mais que dez frames; a tela de disclaimer está no ar. */
    static final int MENUS_PRONTOS_EM = 200;

    public static String abriu = null;
    public static MenuType ultimoSetMenu = null;

    int frame = 0;

    public void update(float dt) { frame++; }

    public Object getCurrent() {
        return frame < MENUS_PRONTOS_EM ? null : "MainMenu";
    }

    /** É o que devolvia nulo e produzia "the game has no Load menu". */
    public Object getContent(MenuType type) {
        if (frame < MENUS_PRONTOS_EM) { return null; }
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
     * `esperado` é o nome da pasta que tinha que ser aberta, ou "-" para
     * "não podia abrir nada".
     */
    public static void main(String[] args) {
        String esperado = args.length > 0 ? args[0] : "-";
        int frames = args.length > 1 ? Integer.parseInt(args[1]) : 400;

        GameMenu menu = new GameMenu();
        for (int i = 0; i < frames; i++) { menu.update(0.016f); }

        boolean consumido = !new java.io.File("sharedgalaxy.autoload").isFile();
        System.out.println("  setMenu   -> " + ultimoSetMenu);
        System.out.println("  carregou  -> " + abriu);
        System.out.println("  consumido -> " + consumido);

        boolean ok;
        if ("-".equals(esperado)) {
            ok = abriu == null;
        } else if (NEW_GAME_ESPERADO.equals(esperado)) {
            ok = ultimoSetMenu == MenuType.NewGame && abriu == null;
        } else {
            ok = esperado.equals(abriu);
        }
        System.out.println(ok ? "  PASSOU" : "  FALHOU (esperava " + esperado + ")");
        if (!ok) { System.exit(1); }
    }

    static final String NEW_GAME_ESPERADO = "__new__";
}
