package com.sharedgalaxy;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.util.HashSet;
import java.util.Set;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;

/**
 * A neighbour's storefront does not phone you asking for cargo.
 *
 * <p>The game runs its own economy against any NPC ship in the sector: its crew
 * hails the player, names goods and a price, and the player accepts or refuses.
 * Against a real NPC that is the game. Against a storefront the server
 * assembled, it is the AI moving credits on behalf of a person who asked for
 * nothing — and both sides of that trade land in somebody's save.
 *
 * <h2>Why this is not a one-line switch</h2>
 *
 * <p>Because the game does not model a hail as coming from a ship. Every entry
 * point is keyed on a faction:
 *
 * <pre>
 *   Communication.npcHailsPlayer(FactionSide)
 *   Communication.updateCallPlayer(FactionSide, …)
 *   NpcHailingPlayer.side → FactionSide
 * </pre>
 *
 * <p>So silencing "our" ship is not something the game can express. Silencing
 * the faction would also silence the encounters the game itself created, for
 * everybody in the room, permanently.
 *
 * <p>What this does instead: suppress the call only when **every ship of that
 * faction currently in the sector is one of ours**. A real NPC of the same side
 * parked nearby keeps its voice, and the room loses no content the game meant
 * to give it.
 *
 * <p>Which ships are ours comes from the server, which assigned their ids when
 * it assembled them, and reaches the mod through {@code sharedgalaxy.ships}.
 * Guessing by name would be wrong the moment somebody names their ship after a
 * neighbour.
 *
 * <p>If the file is missing, nothing is suppressed. Being quiet is the risky
 * default here: a room where nobody can trade is worse than one where the AI
 * occasionally speaks out of turn.
 */
@Aspect
public class QuietNeighbourAspect {

    /** The storefront ship ids the server assembled, one per line. */
    public static final String SHIPS_FILE = "sharedgalaxy.ships";

    private static Set<String> ours;
    private static long readAt;

    /** Re-read at most this often: the file changes once per session. */
    private static final long REREAD_MILLIS = 30000;

    @Around("execution(* fi.bugbyte.spacehaven.ai.Communication.updateCallPlayer(..))"
            + " || execution(* fi.bugbyte.spacehaven.ai.Communication"
            + ".npcHailsPlayer(..))")
    public Object aroundCallingThePlayer(ProceedingJoinPoint call)
            throws Throwable {
        try {
            Object[] args = call.getArgs();
            if (args.length > 0 && args[0] != null
                    && onlyOurs(call.getTarget(), args[0])) {
                return null;    // nobody real is calling; say nothing
            }
        } catch (Throwable failure) {
            // Never let this decide a session. Letting the call through is the
            // game behaving as it always did.
            System.err.println("[shared-galaxy] could not check who is "
                               + "hailing: " + failure);
        }
        return call.proceed();
    }

    /**
     * Is every ship of this faction, here and now, one the server assembled?
     *
     * <p>False when there are none — an empty sector is not a reason to change
     * anything — and false the moment one real ship of that side is present.
     */
    private static boolean onlyOurs(Object communication, Object side)
            throws Exception {
        Set<String> nossos = storefronts();
        if (nossos.isEmpty()) {
            return false;
        }
        Object world = read(communication, "world");
        if (world == null) {
            return false;
        }
        Object ships = world.getClass().getMethod("getShips").invoke(world);
        if (ships == null) {
            return false;
        }
        int total = ((Integer) ships.getClass().getField("size").get(ships))
            .intValue();
        java.lang.reflect.Method get = ships.getClass()
            .getMethod("get", int.class);

        boolean achouAlguma = false;
        for (int i = 0; i < total; i++) {
            Object ship = get.invoke(ships, Integer.valueOf(i));
            if (ship == null) {
                continue;
            }
            Object lado = ship.getClass()
                .getMethod("getCurrentOwnerSide").invoke(ship);
            if (lado != side) {
                continue;
            }
            achouAlguma = true;
            Object id = read(ship, "shipId");
            if (id == null || !nossos.contains(String.valueOf(id))) {
                return false;   // a real one of this side is here; let it talk
            }
        }
        return achouAlguma;
    }

    static Set<String> storefronts() {
        long agora = System.currentTimeMillis();
        if (ours != null && agora - readAt < REREAD_MILLIS) {
            return ours;
        }
        readAt = agora;
        Set<String> lidos = new HashSet<String>();
        InputStream in = null;
        try {
            File file = new File(SHIPS_FILE);
            if (file.isFile()) {
                in = new FileInputStream(file);
                byte[] buffer = new byte[4096];
                int n = in.read(buffer);
                if (n > 0) {
                    String[] linhas =
                        new String(buffer, 0, n, "UTF-8").split("\\s+");
                    for (int i = 0; i < linhas.length; i++) {
                        String linha = linhas[i].trim();
                        if (linha.length() > 0) {
                            lidos.add(linha);
                        }
                    }
                }
            }
        } catch (Exception failure) {
            // An unreadable list means we know of no storefronts, and knowing
            // of none suppresses nothing.
            lidos.clear();
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (Exception ignored) {
                    // nothing useful to do with a failed close
                }
            }
        }
        ours = lidos;
        return ours;
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
