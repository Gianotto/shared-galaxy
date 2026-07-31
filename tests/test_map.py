"""
Tests for the room map drawing.

The map is the front door (section 2.11): someone sees the room alive and
decides whether to join, without installing anything. What it says has to be
true — an earlier version coloured systems as "explored" based on them having a
name, and the game names all of them at once, so the whole map lit up.

    python3 -m unittest tests.test_map -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.web.pages import starmap_svg  # noqa: E402

GALAXY = {
    "w": 1000, "h": 500,
    "systems": [
        {"systemId": "1", "name": "Alpha", "x": 100, "y": 100, "bodies": 3},
        {"systemId": "2", "name": "Beta", "x": 500, "y": 250, "bodies": 2},
        {"systemId": "3", "name": None, "x": 900, "y": 400, "bodies": 4},
    ],
}


def _player(system, ship="HSS TEST", playing=False, age=None):
    return {"at_system": system, "ship_name": ship, "display_name": "Ana",
            "playing": playing, "age_days": age}


class MapTestCase(unittest.TestCase):

    def test_empty_galaxy_says_so_instead_of_drawing_nothing(self):
        out = starmap_svg({"systems": []}, [], "en")
        self.assertNotIn("<svg", out)
        self.assertIn("first player", out)

    def test_visited_systems_are_bigger_and_brighter(self):
        visits = {"2": {"first_by": "Ana", "visits": 3}}
        out = starmap_svg(GALAXY, [], "en", visits)
        self.assertIn('r="3"', out, "o sistema visitado não foi destacado")
        self.assertIn("#a8c0f0", out)
        self.assertIn("first here: Ana", out, "não diz quem chegou primeiro")

    def test_a_name_alone_does_not_count_as_visited(self):
        """O erro que o item 15 registra: nomeado não é visitado."""
        out = starmap_svg(GALAXY, [], "en", visits={})
        self.assertNotIn('r="3"', out,
                         "destacou sistema sem visita registrada")
        self.assertNotIn("#a8c0f0", out)

    def test_every_system_gets_a_hover_target(self):
        """Ponto de 1,8px é quase impossível de acertar com o mouse."""
        out = starmap_svg(GALAXY, [], "en")
        self.assertEqual(out.count('fill="transparent"'), 3)

    def test_every_system_gets_a_box(self):
        out = starmap_svg(GALAXY, [], "en")
        self.assertEqual(out.count('class="tip"'), 3)

    def test_unnamed_system_says_so_in_the_box(self):
        out = starmap_svg(GALAXY, [], "en")
        self.assertIn(">system 3<", out)

    def test_an_untouched_system_says_nobody_has_been(self):
        out = starmap_svg(GALAXY, [], "en")
        self.assertIn("nobody has reached this yet", out)

    def test_player_marker_carries_ship_and_box_carries_system(self):
        out = starmap_svg(GALAXY, [_player("1")], "en")
        self.assertIn(">HSS TEST</text>", out, "a nave não aparece no mapa")
        self.assertIn(">Alpha</text>", out, "o sistema não aparece na caixa")

    def test_playing_uses_a_different_colour_and_a_mark(self):
        away = starmap_svg(GALAXY, [_player("1", playing=False)], "en")
        live = starmap_svg(GALAXY, [_player("1", playing=True)], "en")
        self.assertIn("var(--me)", away)
        self.assertIn("var(--on)", live)
        self.assertIn("●", live, "não marca quem está jogando agora")

    def test_ship_names_are_escaped(self):
        """O `sname` é texto livre do jogador, e a página é pública."""
        out = starmap_svg(GALAXY, [_player("1", "<script>x</script>")], "en")
        self.assertNotIn("<script>x</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_survives_a_galaxy_without_declared_size(self):
        galaxy = {"systems": GALAXY["systems"]}
        self.assertIn("<svg", starmap_svg(galaxy, [], "en"))

    def test_boxes_are_drawn_after_every_dot(self):
        """SVG não tem z-index: caixa desenhada antes fica atrás do vizinho."""
        out = starmap_svg(GALAXY, [], "en")
        primeira_caixa = out.index('class="tip"')
        ultimo_ponto = out.rindex('class="dot"')
        self.assertLess(ultimo_ponto, primeira_caixa,
                        "uma caixa seria coberta pelo ponto de outro sistema")


class CrowdedSystemTestCase(unittest.TestCase):
    """Todos nascem no mesmo corpo celeste (findings 16).

    Numa sala de 64, o dia um tem 64 jogadores num ponto só. O mapa é a
    vitrine — ilegível ali é caro.
    """

    def test_a_crowd_becomes_a_count_on_the_map(self):
        crowd = [_player("1", f"SHIP {i}") for i in range(20)]
        out = starmap_svg(GALAXY, crowd, "en")
        self.assertIn(">20 players</text>", out)
        self.assertNotIn(">SHIP 0, SHIP 1", out, "listou a multidão no mapa")

    def test_the_box_lists_the_oldest_and_counts_the_rest(self):
        """Numa multidão, o que interessa é quem está aqui há mais tempo."""
        crowd = [_player("1", f"SHIP {i}", age=i) for i in range(20)]
        out = starmap_svg(GALAXY, crowd, "en")
        self.assertIn("SHIP 19", out, "não mostrou a colônia mais antiga")
        self.assertIn("SHIP 15", out)
        self.assertNotIn("SHIP 0 ", out, "mostrou a mais nova em vez da antiga")
        self.assertIn("+15 ships on this system", out)

    def test_the_box_shows_age_next_to_each_ship(self):
        out = starmap_svg(GALAXY, [_player("1", "HSS OLD", age=42.4)], "en")
        self.assertIn("42d", out, "a idade não aparece na caixa")

    def test_a_single_player_keeps_their_name_on_the_map(self):
        out = starmap_svg(GALAXY, [_player("1", "HSS YANNI")], "en")
        self.assertIn(">HSS YANNI</text>", out)


if __name__ == "__main__":
    unittest.main()


class FingerprintStabilityTestCase(unittest.TestCase):
    """A impressão digital tem que sobreviver a jogar (findings 19).

    A galáxia é materializada preguiçosamente: um salto acrescentou 14 corpos a
    um sistema. Um digest que conte corpos mede exploração, não identidade — e o
    servidor recusaria a devolução do primeiro jogador que viajasse.
    """

    def _galaxy(self, extra_bodies=0):
        import xml.etree.ElementTree as ET
        corpos = ('<l celeid="575" type="Star" seed="99" x="8261" y="2132" '
                  'starType="A" starClass="V"/>')
        corpos += "".join(
            f'<l celeid="0" type="AsteroidField" seed="{i}" ox="1" oy="1" '
            f'centerId="1"/>' for i in range(extra_bodies))
        return (f'<game><masterData idCounter="1"/>'
                f'<starmap w="900000" h="400000">'
                f'<systems><l systemId="1" sn="" smn="">'
                f'<bodies>{corpos}</bodies>'
                f'<emptySectors/><clouds/></l></systems></starmap></game>\n')

    def test_materialising_bodies_does_not_change_the_digest(self):
        import os, sys, tempfile
        sys.path.insert(0, os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        from server.galaxy.fingerprint import digest_of
        with tempfile.TemporaryDirectory() as tmp:
            digests = []
            for n, extra in enumerate((0, 6, 14)):
                folder = os.path.join(tmp, f"s{n}")
                os.makedirs(folder)
                with open(os.path.join(folder, "game"), "w") as fh:
                    fh.write(self._galaxy(extra))
                digests.append(digest_of(folder))
            self.assertEqual(len(set(digests)), 1,
                             f"o digest mudou ao materializar corpos: {digests}")

    def test_a_different_star_is_a_different_galaxy(self):
        import os, sys, tempfile
        from server.galaxy.fingerprint import digest_of
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a"); os.makedirs(a)
            with open(os.path.join(a, "game"), "w") as fh:
                fh.write(self._galaxy())
            b = os.path.join(tmp, "b"); os.makedirs(b)
            with open(os.path.join(b, "game"), "w") as fh:
                fh.write(self._galaxy().replace('seed="99"', 'seed="1234"'))
            self.assertNotEqual(digest_of(a), digest_of(b),
                                "duas galáxias diferentes deram o mesmo digest")
