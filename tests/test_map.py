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


def _player(system, ship="HSS TEST", playing=False):
    return {"at_system": system, "ship_name": ship, "display_name": "Ana",
            "playing": playing}


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
        self.assertIn("first: Ana", out, "não diz quem chegou primeiro")

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

    def test_unnamed_system_still_has_a_tooltip(self):
        out = starmap_svg(GALAXY, [], "en")
        self.assertIn("<title>system 3</title>", out)

    def test_player_marker_carries_ship_and_system_name(self):
        out = starmap_svg(GALAXY, [_player("1")], "en")
        self.assertIn(">HSS TEST</text>", out)
        self.assertIn(">Alpha</text>", out, "o nome do sistema não apareceu")

    def test_playing_uses_a_different_colour(self):
        away = starmap_svg(GALAXY, [_player("1", playing=False)], "en")
        live = starmap_svg(GALAXY, [_player("1", playing=True)], "en")
        self.assertIn("var(--me)", away)
        self.assertIn("var(--on)", live)

    def test_two_players_in_one_system_are_listed_together(self):
        out = starmap_svg(GALAXY, [_player("2", "Alpha One"),
                                   _player("2", "Beta Two")], "en")
        self.assertIn("Alpha One, Beta Two", out)

    def test_ship_names_are_escaped(self):
        """O `sname` é texto livre do jogador, e a página é pública."""
        out = starmap_svg(GALAXY, [_player("1", "<script>x</script>")], "en")
        self.assertNotIn("<script>x</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_survives_a_galaxy_without_declared_size(self):
        galaxy = {"systems": GALAXY["systems"]}
        self.assertIn("<svg", starmap_svg(galaxy, [], "en"))


if __name__ == "__main__":
    unittest.main()


class CrowdedSystemTestCase(unittest.TestCase):
    """Todos nascem no mesmo corpo celeste (findings 16).

    Numa sala de 64, o dia um tem 64 nomes num ponto só. O mapa é a vitrine —
    ilegível ali é caro.
    """

    def test_a_crowd_is_summarised_not_listed(self):
        crowd = [_player("1", f"SHIP {i}") for i in range(20)]
        out = starmap_svg(GALAXY, crowd, "en")
        self.assertIn("SHIP 0, SHIP 1, SHIP 2 +17", out)
        self.assertNotIn("SHIP 9", out, "listou a multidão inteira")

    def test_a_small_group_is_listed_in_full(self):
        out = starmap_svg(GALAXY, [_player("1", "A"), _player("1", "B")], "en")
        self.assertIn(">A, B</text>", out)
        self.assertNotIn("+", out.split("</text>")[0])
