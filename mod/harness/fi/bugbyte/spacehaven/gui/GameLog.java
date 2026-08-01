package fi.bugbyte.spacehaven.gui;

import java.util.ArrayList;
import java.util.List;

/**
 * A janela de log do jogo, a mesma que diz "Day 3.10 Autosaved".
 *
 * Repete a defesa do original: enquanto `isLoading` estiver ligado, engole a
 * linha. É por isso que o aspecto espera esse sinal em vez de um atraso.
 */
public class GameLog {

    public enum LogType { Debug, Error, Normal, Bad, Good }

    public static final List<String> linhas = new ArrayList<String>();

    public static Object addLog(String texto, LogType tipo, Object alvo) {
        if (fi.bugbyte.spacehaven.SpaceHaven.isLoading) {
            return null;
        }
        linhas.add(texto);
        return null;
    }
}
