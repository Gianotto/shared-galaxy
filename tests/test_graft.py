"""
Testes do enxerto de galáxia.

O enxerto é a operação que reescreve o jogo de alguém: troca a galáxia inteira e
mantém nave, tripulação e banco. Errar aqui não dá erro — dá um save que carrega
e quebra depois, que foi exatamente o que aconteceu no primeiro salto de
hiperespaço (findings item 18).

O que estes testes protegem:

- achar a frota do jogador onde quer que ela esteja. Parada num corpo celeste
  ela é `bodies/l/fleets/f`; parada em espaço aberto é `emptySectors/l/fleet/l`,
  com outra tag. Os dois são estado normal de jogo, e a versão que só procurava
  o primeiro recusava quem salvasse em trânsito (findings item 22)
- não deixar duas frotas de jogador no mesmo save
- preservar o que é do jogador

    python3 -m unittest tests.test_graft -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy.graft import graft, player_fleet, player_fleets  # noqa: E402
from sgalaxy.savefile import SaveError, SaveFile  # noqa: E402
from tests import synthetic  # noqa: E402

# A frota do jogador num corpo celeste: container <fleets>, filhos <f>.
NO_CORPO = synthetic.FLEETS_TEMPLATE.format(npc_fleet="")

# A mesma frota em espaço aberto. Medido em "New haven-1": container <fleet>,
# filhos <l>, pendurado num <emptySectors>. Mesma versão de formato (21).
EM_ESPACO_ABERTO = """<fleet>\
<l id="0" isPlayer="true" factionId="461" x="75353" y="186703">\
<createdShips/>\
</l>\
</fleet>"""


def _save(tmp: str, nome: str, xml: str) -> SaveFile:
    return SaveFile(synthetic.write_save(os.path.join(tmp, nome), xml))


class GraftTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="graft-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)

    def _doador(self) -> SaveFile:
        """A galáxia da sala. Tem 500000 de largura e uma frota própria."""
        return _save(self.tmp, "doador", synthetic.build_game(galaxy_w=500000))

    def _jogador(self, fleets_xml: str) -> SaveFile:
        """Quem chega: outra galáxia, e a frota onde `fleets_xml` puser."""
        xml = synthetic.build_game(galaxy_w=777000, player_credits=9999)
        return _save(self.tmp, f"jogador{abs(hash(fleets_xml))}",
                     xml.replace(NO_CORPO, fleets_xml))

    # -- achar a frota ----------------------------------------------------

    def test_finds_the_fleet_parked_at_a_body(self):
        fleet, holder = player_fleet(self._jogador(NO_CORPO))
        self.assertIsNotNone(fleet)
        self.assertEqual(fleet.get("id"), "0")
        self.assertEqual(holder.get("celeid"), "102")

    def test_finds_the_fleet_sitting_in_open_space(self):
        """Salvar em trânsito é jogo normal, e recusava todo mundo antes."""
        fleet, _holder = player_fleet(self._jogador(EM_ESPACO_ABERTO))
        self.assertIsNotNone(fleet,
                             "não achou a frota em <fleet>/<l>; quem salvar "
                             "fora de um corpo celeste não consegue entrar")
        self.assertEqual(fleet.get("id"), "0")

    def test_a_save_with_no_player_fleet_is_refused_clearly(self):
        jogador = self._jogador("<fleets/>")
        with self.assertRaises(SaveError) as erro:
            graft(self._doador(), jogador)
        self.assertIn("isPlayer", str(erro.exception))

    # -- o enxerto --------------------------------------------------------

    def _graft(self, fleets_xml: str) -> tuple:
        jogador = self._jogador(fleets_xml)
        report = graft(self._doador(), jogador)
        return jogador, report

    def test_the_galaxy_is_replaced(self):
        jogador, _ = self._graft(NO_CORPO)
        self.assertEqual(jogador.main.find("starmap").get("w"), "500000",
                         "ficou com a galáxia antiga")

    def test_the_player_keeps_what_is_theirs(self):
        """Nave, tripulação e banco não são da galáxia e não podem sumir."""
        jogador, _ = self._graft(NO_CORPO)
        self.assertEqual(jogador.main.find("playerBank").get("ca"), "9999")
        naves = jogador.main.findall(".//ships/ship")
        self.assertEqual([n.get("sname") for n in naves], ["Homestead"])
        self.assertEqual(len(naves[0].findall(".//characters/c")), 2)

    def test_exactly_one_player_fleet_survives(self):
        """Duas frotas de jogador no mesmo save é o doador vazando junto."""
        for rotulo, fleets_xml in (("no corpo", NO_CORPO),
                                   ("em espaço aberto", EM_ESPACO_ABERTO)):
            with self.subTest(rotulo):
                jogador, report = self._graft(fleets_xml)
                achadas = list(player_fleets(jogador.main.find("starmap")))
                self.assertEqual(len(achadas), 1,
                                 f"{len(achadas)} frotas de jogador no save")
                self.assertEqual(report["strippedFleets"], 1)

    def test_the_moved_fleet_matches_its_new_siblings(self):
        """Vinda de <fleet>/<l>, a frota entra em <fleets> e tem que virar <f>.

        O jogo lê a tag. Uma <l> pendurada num <fleets> é um save que carrega
        e não mostra a nave.
        """
        jogador, _ = self._graft(EM_ESPACO_ABERTO)
        fleet, container, _ = next(iter(
            player_fleets(jogador.main.find("starmap"))))
        self.assertEqual(container.tag, "fleets")
        self.assertEqual(fleet.tag, "f")

    def test_the_fleet_lands_on_the_start_body(self):
        """E as três referências da seção 1.5 passam a concordar."""
        jogador, _ = self._graft(EM_ESPACO_ABERTO)
        starmap = jogador.main.find("starmap")
        _fleet, _container, corpo = next(iter(player_fleets(starmap)))
        self.assertEqual(corpo.find("info").get("isst"), "1")
        self.assertEqual(starmap.get("pa"), corpo.get("id") or starmap.get("pa"))

    def test_stale_coordinates_do_not_survive(self):
        """As coordenadas eram da galáxia antiga; ali não há mais nada."""
        jogador, _ = self._graft(EM_ESPACO_ABERTO)
        fleet, _c, corpo = next(iter(
            player_fleets(jogador.main.find("starmap"))))
        for eixo in ("x", "y"):
            if corpo.get(eixo) is not None:
                self.assertEqual(fleet.get(eixo), corpo.get(eixo))
        self.assertNotEqual(fleet.get("x"), "75353")


if __name__ == "__main__":
    unittest.main()
