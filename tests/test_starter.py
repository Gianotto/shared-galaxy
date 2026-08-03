"""O save de partida que a sala entrega a quem chega.

Mover a frota de um jogador exige quatro coisas concordando, e fazer três delas
produz um save que abre e mente sobre onde a pessoa está. A primeira versão
disto fazia uma: reescrevia `x`/`y` da frota e a deixava pendurada no sistema
antigo, escolhendo um corpo de outro sistema que por acaso estava no mesmo
ponto do mapa.
"""

import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy import starter  # noqa: E402
from sgalaxy.savefile import SaveFile  # noqa: E402


def _save(tmp: str) -> SaveFile:
    """Um save com um sistema, quatro corpos e a frota do jogador num deles."""
    os.makedirs(tmp, exist_ok=True)
    jogo = ET.Element("game", {"seed": "0"})
    naves = ET.SubElement(jogo, "ships")
    nave = ET.SubElement(naves, "ship", {"sid": "39", "sname": "HSS DOADORA"})
    ET.SubElement(nave, "settings", {"of": "461", "owner": "Player"})
    tripulacao = ET.SubElement(ET.SubElement(nave, "characters"), "c",
                               {"entId": "1", "name": "Ana"})
    tripulacao.set("name", "Ana")
    starmap = ET.SubElement(jogo, "starmap",
                            {"w": "900000", "h": "400000", "sys": "1",
                             "pa": "10", "objectIdCounter": "500"})
    sistemas = ET.SubElement(starmap, "systems")
    sistema = ET.SubElement(sistemas, "l", {"systemId": "7"})
    corpos = ET.SubElement(sistema, "bodies")
    for ident, tipo, x, y in (("10", "Star", "1000", "1000"),
                              ("11", "AsteroidField", "1100", "1000"),
                              ("12", "AsteroidField", "1200", "1000"),
                              ("13", "Moon", "1300", "1000")):
        corpo = ET.SubElement(corpos, "l", {"id": ident, "celeid": ident,
                                            "type": tipo, "x": x, "y": y})
        ET.SubElement(corpo, "info")
    # A frota começa no Star, que é onde o doador a deixou.
    inicio = corpos.find("l")
    frotas = ET.SubElement(inicio, "fleets")
    ET.SubElement(frotas, "f", {"id": "0", "isPlayer": "true",
                                "x": "1000", "y": "1000"})

    with open(os.path.join(tmp, "game"), "wb") as fh:
        fh.write(ET.tostring(jogo))
    with open(os.path.join(tmp, "info"), "wb") as fh:
        fh.write(b'<info date="86400" version="21"/>')
    return SaveFile(tmp)


class PlacementTestCase(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.sf = _save(os.path.join(self.tmp, "save"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _frotas(self):
        starmap = self.sf.main.find("starmap")
        return [e for e in starmap.iter() if e.get("isPlayer") == "true"]

    def test_the_ship_gets_its_own_name(self):
        rel = starter.personalise(self.sf, "HSS PIONEIRA")
        self.assertEqual(rel["shipName"], "HSS PIONEIRA")
        self.assertEqual(starter.player_ship(self.sf).get("sname"),
                         "HSS PIONEIRA")

    def test_only_one_player_fleet_survives(self):
        """A cópia vai para o destino e a original tem que sair: com duas, o
        jogo escolhe uma e o servidor lê a outra."""
        starter.personalise(self.sf, "HSS PIONEIRA")
        self.assertEqual(len(self._frotas()), 1)

    def test_the_fleet_lands_on_a_body_not_on_the_star(self):
        """Corpo celeste inclui o sol. A primeira versão parou a nave de
        alguém em cima de uma estrela."""
        rel = starter.personalise(self.sf, "HSS PIONEIRA")
        starmap = self.sf.main.find("starmap")
        destino = next(c for c in starmap.iter("l")
                       if c.get("celeid") == rel["at"]["celeid"])
        self.assertEqual(destino.get("type"), "AsteroidField")

    def test_the_four_things_agree(self):
        """Frota pendurada no corpo, tag `f`, coordenadas DO CORPO, e
        `@sys`/`@pa` apontando para o mesmo lugar."""
        rel = starter.personalise(self.sf, "HSS PIONEIRA")
        starmap = self.sf.main.find("starmap")
        frota = self._frotas()[0]
        pais = {f: p for p in starmap.iter() for f in p}
        container = pais[frota]
        corpo = pais[container]

        self.assertEqual(frota.tag, "f")
        self.assertEqual(container.tag, "fleets")
        self.assertEqual((frota.get("x"), frota.get("y")),
                         (corpo.get("x"), corpo.get("y")))
        self.assertEqual(starmap.get("pa"), corpo.get("id"))
        self.assertEqual(starmap.get("sys"), "7")
        self.assertEqual(rel["at"]["system"], "7")

    def test_it_stays_in_the_same_system(self):
        """A sala existe para as pessoas se encontrarem. Espalhá-las pela
        galáxia faria a vitrine do vizinho não aparecer para ninguém."""
        rel = starter.personalise(self.sf, "HSS PIONEIRA")
        self.assertEqual(rel["at"]["system"], "7")

    def test_two_newcomers_do_not_stack(self):
        primeiro = starter.personalise(self.sf, "HSS UMA")
        outro = _save(os.path.join(self.tmp, "save2"))
        segundo = starter.personalise(
            outro, "HSS OUTRA",
            evitar={(primeiro["at"]["x"], primeiro["at"]["y"])})
        self.assertNotEqual((primeiro["at"]["x"], primeiro["at"]["y"]),
                            (segundo["at"]["x"], segundo["at"]["y"]))

    def test_a_full_system_says_so_instead_of_stacking(self):
        ocupado = {("1100", "1000"), ("1200", "1000"), ("1300", "1000")}
        rel = starter.personalise(self.sf, "HSS TARDIA", evitar=ocupado)
        self.assertFalse(rel["moved"])
        self.assertTrue(rel["warnings"])


if __name__ == "__main__":
    unittest.main()


class TemplateHealthTestCase(unittest.TestCase):
    """Um molde ruim entregue calado custou uma sessão: quem recebia a cópia
    via o casco fechado e não conseguia entrar na própria nave."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.sf = _save(os.path.join(self.tmp, "save"))
        nave = starter.player_ship(self.sf)
        teto = ET.SubElement(nave, "roof", {"hullPattern": "1", "sx": "56"})
        ET.SubElement(teto, "e", {"m": "-2", "x": "0", "y": "0",
                                  "col": "56b8fc"})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_healthy_save_has_no_problems(self):
        self.assertEqual(starter.problems(self.sf), [])

    def test_a_roof_without_hullpattern_is_refused(self):
        """Medido num molde real: os filhos do `<roof>` eram módulos e não
        chapas de casco, e os três atributos de teto faltavam."""
        starter.player_ship(self.sf).find("roof").attrib.pop("hullPattern")
        problemas = starter.problems(self.sf)
        self.assertTrue(problemas)
        self.assertIn("hullPattern", problemas[0])

    def test_a_ship_with_no_roof_is_refused(self):
        nave = starter.player_ship(self.sf)
        nave.remove(nave.find("roof"))
        self.assertTrue(starter.problems(self.sf))

    def test_a_save_without_a_player_ship_is_refused(self):
        naves = self.sf.main.find("ships")
        for nave in list(naves):
            naves.remove(nave)
        self.assertIn("no Player ship", starter.problems(self.sf)[0])

    def test_a_ship_without_crew_is_refused(self):
        nave = starter.player_ship(self.sf)
        nave.remove(nave.find("characters"))
        self.assertTrue(any("crew" in p for p in starter.problems(self.sf)))
