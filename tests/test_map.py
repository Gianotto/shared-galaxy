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

from server.web import pages  # noqa: E402
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

    def test_the_marker_names_the_account_not_the_ship(self):
        """`sname` é texto livre e mutável: não pode carregar identidade.

        Sem isso, quem renomeasse a nave para o nome do vizinho viraria o
        vizinho neste mapa.
        """
        out = starmap_svg(GALAXY, [_player("1", "HSS TEST")], "en")
        self.assertIn(">Ana</text>", out, "o mapa não nomeia a conta")
        self.assertIn("Ana (HSS TEST)", out, "a nave sumiu da caixa")

    def test_the_box_carries_the_system_name(self):
        out = starmap_svg(GALAXY, [_player("1")], "en")
        self.assertIn(">Alpha</text>", out, "o sistema não aparece na caixa")

    def test_renaming_a_ship_cannot_impersonate_a_neighbour(self):
        vizinho = _player("1", "HSS REAL")
        vizinho["display_name"] = "Bruno"
        impostor = _player("1", "Bruno")
        out = starmap_svg(GALAXY, [vizinho, impostor], "en")
        self.assertIn("Bruno (HSS REAL)", out)
        self.assertIn("Ana (Bruno)", out,
                      "o impostor apareceu como se fosse o vizinho")

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
        self.assertNotIn(">Ana, Ana", out, "listou a multidão no mapa")

    def test_the_box_lists_the_oldest_and_counts_the_rest(self):
        """Numa multidão, o que interessa é quem está aqui há mais tempo."""
        crowd = []
        for i in range(20):
            p = _player("1", f"SHIP {i}", age=i)
            p["display_name"] = f"P{i}"
            crowd.append(p)
        out = starmap_svg(GALAXY, crowd, "en")
        self.assertIn("P19 (SHIP 19)", out, "não mostrou a colônia mais antiga")
        self.assertIn("P15 (SHIP 15)", out)
        self.assertNotIn("P0 (SHIP 0)", out,
                         "mostrou a mais nova em vez da antiga")
        self.assertIn("+15 ships on this system", out)

    def test_the_box_shows_age_next_to_each_ship(self):
        out = starmap_svg(GALAXY, [_player("1", "HSS OLD", age=42.4)], "en")
        self.assertIn("42d", out, "a idade não aparece na caixa")

    def test_a_single_player_keeps_their_name_on_the_map(self):
        out = starmap_svg(GALAXY, [_player("1", "HSS YANNI")], "en")
        self.assertIn(">Ana</text>", out)


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


class OrientationTestCase(unittest.TestCase):
    """O mapa não pode sair espelhado.

    Medido contra o mapa estelar do jogo, no save de um jogador: `Strange
    Kallisti Border` (y=232444) aparece ACIMA de `Magic Garuda Territory`
    (y=150263). No jogo, Y maior é mais alto; em SVG, Y maior é mais baixo.

    Um mapa espelhado é pior que nenhum — parece confiável e manda a pessoa
    para o lado errado.
    """

    def _svg(self) -> str:
        galaxia = {"w": 900000, "h": 400000, "systems": [
            {"systemId": "1", "name": "alto", "x": 100000, "y": 232444,
             "bodies": 1, "sectors": 0, "clouds": 0},
            {"systemId": "2", "name": "baixo", "x": 100000, "y": 150263,
             "bodies": 1, "sectors": 0, "clouds": 0},
        ]}
        return starmap_svg(galaxia, [], "en")

    def test_a_bigger_game_y_draws_higher(self):
        svg = self._svg()
        import re
        # Só os pontos: cada sistema também tem um círculo invisível maior,
        # que é o alvo do hover.
        cys = [float(v) for v in
               re.findall(r'class="dot"[^>]*cy="([\d.]+)"', svg)]
        self.assertEqual(len(cys), 2, f"esperava dois pontos, veio {len(cys)}")
        alto, baixo = cys[0], cys[1]
        self.assertLess(alto, baixo,
                        "o sistema de Y maior no jogo tem que ficar mais alto "
                        "no SVG (cy menor)")


class RosterColumnsTestCase(unittest.TestCase):
    """A tabela "quem está onde" fala a língua do jogador.

    `at_system` é id interno e `at_body` é nome de tipo: nenhum dos dois
    aparece na tela de quem joga. O que ele vê no mapa estelar é o NOME do
    sistema, e é isso que a tabela mostra.
    """

    GALAXIA = {"w": 900000, "h": 400000, "systems": [
        {"systemId": "1", "name": "Taros Ivanova Cluster", "x": 1, "y": 2,
         "bodies": 1, "sectors": 0, "clouds": 0},
        {"systemId": "31", "name": "", "x": 3, "y": 4,
         "bodies": 1, "sectors": 0, "clouds": 0}]}

    def _pagina(self, at_system):
        from server.web.pages import room_page
        roster = [{"player_id": 1, "display_name": "Alguém",
                   "ship_name": "HSS X", "at_system": at_system,
                   "at_x": "1", "at_y": "2", "at_body": "AsteroidField",
                   "age_days": 3.0, "playing": False, "joined_at": None,
                   "last_seen_at": None, "canonical_at": None}]
        sala = {"id": "X", "name": "Sala", "max_players": 64, "lease_hours": 12,
                "galaxy_digest": "d", "seed": "1", "password_hash": None,
                "listed": True, "retention_n": 20, "save_version": "21",
                "options": {}}
        return room_page(sala, roster, self.GALAXIA, "en")

    def test_it_shows_the_system_name(self):
        self.assertIn("Taros Ivanova Cluster", self._pagina("1"))

    def test_it_does_not_show_the_body_type(self):
        """`AsteroidField` é vocabulário nosso, não do jogo."""
        self.assertNotIn("AsteroidField", self._pagina("1"))

    def test_an_unnamed_system_reads_as_one(self):
        """O mesmo recuo do mapa, para as duas telas falarem igual."""
        self.assertIn("system 31", self._pagina("31"))

    def test_nowhere_is_a_dash(self):
        self.assertIn("—", self._pagina(None))


class JoinPageTestCase(unittest.TestCase):
    """A página que leva de "vi a sala" a "estou jogando".

    Quem chega por um convite no Discord não tem como adivinhar que existe um
    cliente, onde ele está, nem que entrar é uma coisa que se faz uma vez só.
    """

    SALA = {"id": "6359GV", "name": "Sala", "max_players": 64,
            "password_hash": None, "max_join_age_days": 5}

    def test_the_command_carries_the_room_id(self):
        """Um comando que não cola é o mesmo que não existir."""
        html = pages.join_page(self.SALA, "en", 3, False)
        self.assertIn("join 6359GV", html)

    def test_every_platform_gets_its_own_file_name(self):
        html = pages.join_page(self.SALA, "en", 3, False)
        for arquivo in ("sgalaxy-linux-x86_64", "sgalaxy-windows-x86_64.exe",
                        "sgalaxy-macos-arm64"):
            self.assertIn(arquivo, html)

    def test_a_locked_room_says_so_before_the_download(self):
        html = pages.join_page(dict(self.SALA, password_hash="x"), "en", 3, False)
        self.assertIn("password", html.lower())

    def test_a_full_room_says_so(self):
        html = pages.join_page(self.SALA, "en", 64, True)
        self.assertIn("full", html.lower())

    def test_the_fresh_start_rule_is_stated_before_anybody_downloads(self):
        """Chegar com uma colônia madura e ser recusado depois de instalar
        tudo é a pior ordem possível de descobrir a regra."""
        html = pages.join_page(self.SALA, "en", 3, False)
        self.assertIn("than 5 in-game days", html)

    def test_the_age_rule_reads_like_days_not_like_a_spreadsheet(self):
        """`numeric` vira "5.00" e ninguém conta dias assim."""
        from decimal import Decimal
        html = pages.join_page(dict(self.SALA, max_join_age_days=Decimal("5.00")),
                               "en", 3, False)
        self.assertIn("than 5 in-game days", html)
        self.assertNotIn("5.00", html)

    def test_both_languages_render(self):
        for lang in ("en", "pt"):
            self.assertIn("6359GV", pages.join_page(self.SALA, lang, 3, False))

    def test_the_room_page_offers_the_way_in(self):
        completa = dict(self.SALA, seed="123", lease_hours=12, retention_n=20)
        html = pages.room_page(completa, [], {}, "en")
        self.assertIn("/room/6359GV/join", html)

    def test_the_recovery_code_page_names_the_binary_not_the_repo(self):
        """Quem chega pelo Discord tem um binário, não um checkout do
        projeto: `python3 tools/sgalaxy.py` não existe na máquina dele."""
        html = pages.registered_page("Eu", "ABCD-1234", "en")
        self.assertIn("./sgalaxy register", html)
        self.assertNotIn("tools/sgalaxy.py", html)


class InviteFormTestCase(unittest.TestCase):
    """O modo convite é a resposta ao registro aberto, e ele tem de funcionar
    pelo site também: a API e o cliente já aceitavam `invite`, e o formulário
    apenas recusava, sem oferecer onde digitar."""

    def test_no_invite_field_when_the_server_does_not_ask(self):
        self.assertNotIn('name="invite"', pages.register_form("en"))

    def test_the_field_appears_when_the_server_asks(self):
        html = pages.register_form("en", needs_invite=True)
        self.assertIn('name="invite"', html)
        self.assertIn("invite", html.lower())

    def test_the_form_survives_an_error_without_losing_the_field(self):
        """Errar o convite não pode devolver um formulário sem o campo."""
        html = pages.register_form("en", "That invite is not valid.",
                                   needs_invite=True)
        self.assertIn('name="invite"', html)
        self.assertIn("not valid", html)

    def test_both_languages(self):
        for lang in ("en", "pt"):
            self.assertIn('name="invite"',
                          pages.register_form(lang, needs_invite=True))
