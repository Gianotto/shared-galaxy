"""
Testes da descoberta compartilhada.

A regra que você decidiu: a sala junta os `visited`, e o `isVisible` não se
compartilha sozinho — vem junto onde houve visita. Quem chega novo herda as
viagens da sala, não o telescópio dela.

O que estes testes protegem, em ordem de estrago:

- **as naves dos outros não viajam junto.** Um corpo visitado carrega `<fleets>`,
  e copiar isso poria a nave de outra pessoa no setor de quem recebe. Vizinho
  visível é fase 2, com regra própria
- **o que já existe não é substituído.** O `<stuff>` local guarda o que a pessoa
  já minerou; sobrescrever devolveria minério que ela já tirou
- **id novo para corpo novo.** Reusar o id do doador colide com um corpo que já
  existe do outro lado, e id repetido carrega e quebra depois

    python3 -m unittest tests.test_discovery -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy import discovery  # noqa: E402
from sgalaxy.savefile import SaveFile  # noqa: E402
from tests import synthetic  # noqa: E402


class DiscoveryTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="disc-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.n = 0

    def _save(self, xml: str) -> SaveFile:
        self.n += 1
        return SaveFile(synthetic.write_save(
            os.path.join(self.tmp, f"s{self.n}"), xml))

    def _explorador(self) -> SaveFile:
        """Alguém que esteve no asteroide inicial."""
        xml = synthetic.build_game().replace(
            '<info visited="false" isVisible="false" isst="1"/>',
            '<info visited="true" isVisible="true" isst="1"/>')
        return self._save(xml)

    def _recem_chegado(self) -> SaveFile:
        """Alguém que nunca saiu de casa: nada visitado."""
        return self._save(synthetic.build_game())

    # -- o que sai de um save --------------------------------------------

    def test_only_visited_places_are_shared(self):
        achados = discovery.visited(self._explorador())
        self.assertEqual(len(achados), 1)
        chave = next(iter(achados))
        self.assertEqual(chave, ("6", "84119", "214759"),
                         "a chave tem que ser (systemId, x, y)")

    def test_a_save_that_went_nowhere_shares_nothing(self):
        self.assertEqual(discovery.visited(self._recem_chegado()), {})

    def test_other_peoples_ships_do_not_travel_with_the_place(self):
        """O estrago caro: a nave de outro jogador aparecendo no teu setor."""
        achados = discovery.visited(self._explorador())
        xml = next(iter(achados.values()))
        self.assertNotIn("<fleets", xml)
        self.assertNotIn("isPlayer", xml)
        self.assertIn("<stuff", xml, "o lugar em si tem que atravessar")

    # -- o que entra num save --------------------------------------------

    def test_a_missing_place_is_inserted(self):
        """É o caso normal: a galáxia se materializa conforme cada um chega,
        então o que um visitou nem existe no save de quem não foi."""
        sala = discovery.visited(self._explorador())
        # Um save sem aquele corpo nenhum.
        xml = synthetic.build_game()
        corte = xml.index('<l celeid="102"')
        fim = xml.index("</bodies>")
        chegando = self._save(xml[:corte] + xml[fim:])

        report = discovery.merge(chegando, sala)
        self.assertEqual(report["inserted"], 1)
        lugares = {discovery._lugar(s, b)
                   for s, b in discovery.bodies_of(chegando.main.find("starmap"))}
        self.assertIn(("6", "84119", "214759"), lugares)

    def test_an_inserted_place_arrives_charted(self):
        sala = discovery.visited(self._explorador())
        xml = synthetic.build_game()
        corte, fim = xml.index('<l celeid="102"'), xml.index("</bodies>")
        chegando = self._save(xml[:corte] + xml[fim:])
        discovery.merge(chegando, sala)

        corpo = [b for _s, b in discovery.bodies_of(chegando.main.find("starmap"))
                 if b.get("x") == "84119"][0]
        info = corpo.find("info")
        self.assertEqual(info.get("visited"), "true")
        self.assertEqual(info.get("isVisible"), "true",
                         "visited sem isVisible é combinação que o jogo não faz")

    def test_an_inserted_place_gets_a_fresh_id(self):
        """Reusar o id do doador colide com um corpo que já existe aqui."""
        sala = discovery.visited(self._explorador())
        xml = synthetic.build_game()
        corte, fim = xml.index('<l celeid="102"'), xml.index("</bodies>")
        chegando = self._save(xml[:corte] + xml[fim:])
        antes = chegando.main.find("starmap").get("objectIdCounter")

        discovery.merge(chegando, sala)
        starmap = chegando.main.find("starmap")
        corpo = [b for _s, b in discovery.bodies_of(starmap)
                 if b.get("x") == "84119"][0]
        self.assertEqual(corpo.get("id"), antes)
        self.assertEqual(starmap.get("objectIdCounter"), str(int(antes) + 1))

        ids = [b.get("id") for _s, b in discovery.bodies_of(starmap)
               if b.get("id") is not None]
        self.assertEqual(len(ids), len(set(ids)), "id repetido no starmap")

    def test_a_place_already_there_is_only_flagged(self):
        """Substituir apagaria o que a pessoa já minerou naquele asteroide."""
        sala = discovery.visited(self._explorador())
        chegando = self._recem_chegado()
        corpo = [b for _s, b in discovery.bodies_of(chegando.main.find("starmap"))
                 if b.get("x") == "84119"][0]
        corpo.find("stuff").set("marca-local", "não me apague")

        report = discovery.merge(chegando, sala)
        self.assertEqual((report["flagged"], report["inserted"]), (1, 0))
        self.assertEqual(corpo.find("stuff").get("marca-local"),
                         "não me apague")
        self.assertEqual(corpo.find("info").get("visited"), "true")

    def test_merging_twice_changes_nothing_the_second_time(self):
        """Todo checkout mescla de novo; a segunda vez não pode duplicar nada."""
        sala = discovery.visited(self._explorador())
        chegando = self._recem_chegado()
        discovery.merge(chegando, sala)
        antes = len(list(discovery.bodies_of(chegando.main.find("starmap"))))

        report = discovery.merge(chegando, sala)
        depois = len(list(discovery.bodies_of(chegando.main.find("starmap"))))
        self.assertEqual(antes, depois, "duplicou corpo na segunda mescla")
        self.assertEqual(report["flagged"], 0, "remarcou o que já estava marcado")

    def test_an_unknown_system_is_skipped_not_invented(self):
        sala = {("999", "1", "2"): '<l celeid="7" type="Planet" x="1" y="2"/>'}
        chegando = self._recem_chegado()
        report = discovery.merge(chegando, sala)
        self.assertEqual((report["inserted"], report["skipped"]), (0, 1))

    def test_the_save_still_round_trips(self):
        """Mesclar não pode estragar a serialização — o jogo lê estes bytes."""
        sala = discovery.visited(self._explorador())
        chegando = self._recem_chegado()
        discovery.merge(chegando, sala)
        chegando.save(backup=False)
        relido = SaveFile(chegando.dir)
        self.assertIsNotNone(relido.main.find("starmap"))
        corpo = [b for _s, b in discovery.bodies_of(relido.main.find("starmap"))
                 if b.get("x") == "84119"][0]
        self.assertEqual(corpo.find("info").get("visited"), "true")


if __name__ == "__main__":
    unittest.main()


class PlacementTestCase(unittest.TestCase):
    """Onde a vitrine de um vizinho é colocada.

    O injetor nasceu falando `celeid`, sob a ideia de que ele era "a língua da
    sala". O item 24 desmentiu: `celeid` nomeia o TIPO de lugar, e num sistema
    com dois campos de asteroide ele entrega um dos dois ao acaso. Pôr a
    vitrine de alguém no lugar errado é silencioso — o save carrega, e o vizinho
    simplesmente está onde não deveria.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="place-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _save(self) -> SaveFile:
        # Dois corpos com o MESMO celeid no mesmo sistema, como um save real
        # tem para campos de asteroide.
        xml = synthetic.build_game().replace(
            '<l celeid="101" type="Planet" seed="7731" x="83819" y="214459"',
            '<l celeid="0" type="AsteroidField" seed="7731" x="90000" y="90000"'
            '/><l celeid="0" type="AsteroidField" seed="7732" x="91000"'
            ' y="91000"/><l celeid="101" type="Planet" seed="7731"'
            ' x="83819" y="214459"')
        return SaveFile(synthetic.write_save(os.path.join(self.tmp, "s"), xml))

    def test_coordinates_name_exactly_one_place(self):
        from sgalaxy.storefront import locate_body
        corpo, _info = locate_body(self._save(), at=("91000", "91000"),
                                   system_id="6")
        self.assertEqual((corpo.get("x"), corpo.get("y")), ("91000", "91000"))
        self.assertEqual(corpo.get("seed"), "7732",
                         "pegou o outro campo de asteroide")

    def test_celeid_is_ambiguous_and_says_so(self):
        from sgalaxy.storefront import locate_body
        _corpo, info = locate_body(self._save(), celeid="0", system_id="6")
        self.assertTrue(any("celeid=0" in w for w in info["warnings"]),
                        "escolheu entre dois corpos sem avisar")

    def test_an_empty_coordinate_is_refused_not_guessed(self):
        from sgalaxy.savefile import SaveError
        from sgalaxy.storefront import locate_body
        with self.assertRaises(SaveError):
            locate_body(self._save(), at=("1", "2"), system_id="6")


class StorefrontTemplateTestCase(unittest.TestCase):
    """De que a vitrine de um vizinho é feita.

    A primeira versão a montava sobre um casco não explorado, que no jogo é a
    definição de destroço: névoa, `unex="1"` e ninguém a bordo. Ela apareceu ao
    jogador como "Derelict (Unexplored)" — e o problema não é o rótulo, é que
    destroço se reclama e se desmonta. A loja de outro jogador não pode ser
    desmontável.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vitrine-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _save(self, ships) -> SaveFile:
        return SaveFile(synthetic.write_save(
            os.path.join(self.tmp, "s"), synthetic.build_game(ships=ships)))

    def test_a_crewless_wreck_is_never_the_template(self):
        from sgalaxy import storefront
        sf = self._save([synthetic.default_player_ship(),
                         synthetic.unexplored_hull()])
        self.assertEqual(storefront.live_npc_ships(sf), [],
                         "escolheu um destroço como molde de vitrine")

    def test_a_live_npc_ship_is(self):
        from sgalaxy import storefront
        sf = self._save([synthetic.default_player_ship(),
                         synthetic.npc_trader_ship()])
        moldes = storefront.live_npc_ships(sf)
        self.assertEqual(len(moldes), 1)
        self.assertEqual(moldes[0].get("sname"), "Meridian")

    def test_the_players_own_ship_is_never_the_template(self):
        from sgalaxy import storefront
        sf = self._save([synthetic.default_player_ship()])
        self.assertEqual(storefront.live_npc_ships(sf), [])

    def test_the_crew_comes_along_and_is_renumbered(self):
        """Tripulação é o que separa nave viva de sucata, e entId repetido
        é o tipo de erro que carrega e quebra depois."""
        from sgalaxy import storefront
        sf = self._save([synthetic.default_player_ship(),
                         synthetic.npc_trader_ship()])
        molde = storefront.live_npc_ships(sf)[0]
        antes = {c.get("entId") for c in storefront.crew_members(molde)}

        rel = storefront.inject_ship(sf, molde, faction="Civilian",
                                     name="Meridian (Vizinha)", hull_mode=True,
                                     crew_side="Civilian",
                                     at=("84119", "214759"), system_id="6")
        nova = [s for _d, s in sf.ships()
                if s.get("sid") == rel["fleet"]["createdShipId"]][0]
        tripulacao = storefront.crew_members(nova)
        self.assertEqual(len(tripulacao), 2, "a vitrine ficou sem tripulação")
        depois = {c.get("entId") for c in tripulacao}
        self.assertFalse(antes & depois, "reusou entId da nave molde")

        todos = [c.get("entId") for _d, s in sf.ships()
                 for c in storefront.crew_members(s)]
        self.assertEqual(len(todos), len(set(todos)), "entId repetido no save")
