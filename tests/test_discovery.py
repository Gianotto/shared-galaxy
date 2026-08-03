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

    def test_the_sellers_shuttle_does_not_travel_with_the_storefront(self):
        """Medido num save real: a vitrine era a única nave do setor com um
        `<c>` em `<crafts>`, com coordenadas de voo próprias. É a lancha de
        outra pessoa voando na partida de um terceiro, e ela fica órfã se a
        nave-mãe sair do setor antes do checkin."""
        from sgalaxy import storefront
        sf = self._save([synthetic.default_player_ship(),
                         synthetic.npc_trader_ship()])
        molde = storefront.live_npc_ships(sf)[0]
        crafts = molde.find("crafts")
        if crafts is None:
            crafts = ET.SubElement(molde, "crafts")
        ET.SubElement(crafts, "c", {"id": "1702", "cid": "20",
                                    "x": "207.1", "y": "291.1"})
        self.assertEqual(len(molde.findall("crafts/c")), 1,
                         "o molde deveria ter o shuttle, senão o teste é vazio")

        rel = storefront.inject_ship(sf, molde, faction="Civilian",
                                     name="Meridian (Vizinha)", hull_mode=True,
                                     crew_side="Civilian",
                                     at=("84119", "214759"), system_id="6")
        self.assertEqual(rel["crafts"]["removed"], 1)
        nova = [s for _d, s in sf.ships()
                if s.get("sid") == rel["fleet"]["createdShipId"]][0]
        self.assertEqual(nova.findall("crafts/c"), [],
                         "a vitrine levou o shuttle do vendedor junto")
        self.assertEqual(len(molde.findall("crafts/c")), 1,
                         "estragou o molde: a cópia é que devia perder a lancha")

    def test_a_neighbours_ship_arrives_with_its_fog_untouched(self):
        """Escrever névoa por cima de um casco explorado desenha uma nave pela
        metade.

        Medido no save entregue ao Gianotto: a nave do Fernando chegava com 989
        células marcadas como não vistas, mais `unex`, `forceRoof` e `fog`, tudo
        por cima de um casco que o dono tinha explorado inteiro. O jogo não
        aceita nem recusa: casco preto, um cômodo aceso com tripulante dentro, e
        uma chapa faltando. Foi relatado como "faltando um HULL".
        """
        from sgalaxy import storefront
        sf = self._save([synthetic.default_player_ship(),
                         synthetic.npc_trader_ship()])
        # O molde é a nave de OUTRO jogador: casco explorado, sem `unex`.
        molde = storefront.live_npc_ships(sf)[0]
        elementos = ET.SubElement(molde, "elements")
        for eid in ("9101", "9102", "9103"):
            ET.SubElement(elementos, "e", {"eid": eid, "fg": "1"})
        molde.attrib.pop("unex", None)
        molde.set("fog", "false")

        rel = storefront.inject_ship(sf, molde, faction="Civilian",
                                     name="HSS FERNANDO (Fernando)",
                                     hull_mode=False, crew_side="Civilian",
                                     at=("84119", "214759"), system_id="6")
        nova = [s for _d, s in sf.ships()
                if s.get("sid") == rel["fleet"]["createdShipId"]][0]

        self.assertFalse(rel["fog"]["written"])
        self.assertEqual(
            [e.get("fg") for e in nova.iter("e") if e.get("fg") is not None],
            ["1", "1", "1"], "apagou a névoa de um casco já explorado")
        for atributo in ("unex", "forceRoof"):
            self.assertIsNone(nova.get(atributo),
                              f"marcou {atributo} numa nave que foi explorada")
        self.assertNotEqual(nova.get("fog"), "true")

    def test_an_npc_hull_still_arrives_hidden(self):
        """O outro lado da mesma regra: um casco de NPC já nasce escondido, e
        continua escondido porque ninguém escreve nele."""
        from sgalaxy import storefront
        sf = self._save([synthetic.default_player_ship(),
                         synthetic.npc_trader_ship()])
        molde = storefront.live_npc_ships(sf)[0]
        elementos = ET.SubElement(molde, "elements")
        ET.SubElement(elementos, "e", {"eid": "9201", "fg": "0"})
        molde.set("unex", "1")
        molde.set("fog", "true")

        rel = storefront.inject_ship(sf, molde, faction="Civilian",
                                     name="Meridian (Vizinha)", hull_mode=True,
                                     crew_side="Civilian",
                                     at=("84119", "214759"), system_id="6")
        nova = [s for _d, s in sf.ships()
                if s.get("sid") == rel["fleet"]["createdShipId"]][0]
        self.assertEqual(nova.get("unex"), "1")
        self.assertEqual([e.get("fg") for e in nova.iter("e")
                          if e.get("fg") is not None], ["0"])

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


class StorefrontLeakTestCase(unittest.TestCase):
    """O jogo move naves para arquivo próprio quando a pessoa sai do setor, e
    a vitrine ia junto. Medido num save de verdade: três cópias de
    `HSS YANNI (Vizinha)` em `ship1157`, `ship1383` e `ship2463`, de uma conta
    já apagada. Ficariam ali para sempre."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "save")
        os.makedirs(os.path.join(self.dir, "ships"))
        jogo = ET.Element("game", {"seed": "0"})
        ET.SubElement(jogo, "ships")
        ET.SubElement(jogo, "starmap", {"w": "1", "h": "1"})
        with open(os.path.join(self.dir, "game"), "wb") as fh:
            fh.write(ET.tostring(jogo))
        with open(os.path.join(self.dir, "info"), "wb") as fh:
            fh.write(b'<info date="86400" version="21"/>')
        # Uma vitrine que o jogo ja mudou para arquivo proprio.
        nave = ET.Element("ship", {"sid": "1157", "sname": "HSS YANNI (Vizinha)",
                                   "ox": "-9984", "oy": "5216"})
        with open(os.path.join(self.dir, "ships", "ship1157"), "wb") as fh:
            fh.write(ET.tostring(nave))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_storefront_in_its_own_file_is_removed(self):
        from sgalaxy import storefront
        from sgalaxy.savefile import SaveFile
        sf = SaveFile(self.dir)
        rel = storefront.remove_storefronts(sf, ["1157"])
        self.assertEqual(rel["ships"], 1)
        self.assertEqual(rel["missing"], [])
        sf.save(backup=False)
        self.assertFalse(os.path.isfile(
            os.path.join(self.dir, "ships", "ship1157")))

    def test_the_players_own_ship_is_never_removed(self):
        """Um `sid` sai do contador do save de destino, então o mesmo número
        pode ser uma nave legítima noutro save, e um molde copiado carrega os
        números do original."""
        from sgalaxy import storefront
        from sgalaxy.savefile import SaveFile
        import xml.etree.ElementTree as ET2
        casa = ET2.Element("ship", {"sid": "1157", "sname": "HSS MINHA"})
        ET2.SubElement(casa, "settings", {"of": "461", "owner": "Player"})
        with open(os.path.join(self.dir, "ships", "ship1157"), "wb") as fh:
            fh.write(ET2.tostring(casa))
        sf = SaveFile(self.dir)
        rel = storefront.remove_storefronts(sf, ["1157"])
        self.assertEqual(rel["ships"], 0)
        self.assertEqual(rel["kept"], ["1157"])
        sf.save(backup=False)
        self.assertTrue(os.path.isfile(
            os.path.join(self.dir, "ships", "ship1157")))

    def test_nothing_is_deleted_before_the_save_is_written(self):
        """Apagar na hora deixaria o save inconsistente se quem chama
        desistir de gravar."""
        from sgalaxy import storefront
        from sgalaxy.savefile import SaveFile
        storefront.remove_storefronts(SaveFile(self.dir), ["1157"])
        self.assertTrue(os.path.isfile(
            os.path.join(self.dir, "ships", "ship1157")))


class SectorSlotTestCase(unittest.TestCase):
    """A cópia trazia o `ox` da nave original, então reaparecia na coordenada
    que o dono ocupava no setor dele. Relatado duas vezes por quem jogou."""

    def _save_com(self, offsets):
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp,
                                                            ignore_errors=True))
        d = os.path.join(tmp, "save")
        os.makedirs(d)
        jogo = ET.Element("game", {"seed": "0"})
        naves = ET.SubElement(jogo, "ships")
        for i, ox in enumerate(offsets):
            ET.SubElement(naves, "ship", {"sid": str(100 + i), "ox": str(ox),
                                          "oy": "5216"})
        ET.SubElement(jogo, "starmap", {"w": "1", "h": "1"})
        with open(os.path.join(d, "game"), "wb") as fh:
            fh.write(ET.tostring(jogo))
        with open(os.path.join(d, "info"), "wb") as fh:
            fh.write(b'<info date="86400" version="21"/>')
        from sgalaxy.savefile import SaveFile
        return SaveFile(d)

    def test_it_keeps_clear_of_the_ships_already_there(self):
        from sgalaxy import storefront
        vaga, _altura = storefront.sector_slot(self._save_com([-4992, 4992]))
        self.assertIsNotNone(vaga)
        for usado in (-4992, 4992):
            self.assertGreaterEqual(abs(vaga - usado), storefront.FOLGA_SETOR)

    def test_it_stays_near_the_ships_that_are_there(self):
        """Uma vaga a quinze mil unidades da nave mais próxima está fora do
        que a pessoa enxerga. Medido num setor real: as naves estavam em 0,
        7488 e 10144, e a versão anterior escolheu -7488."""
        from sgalaxy import storefront
        vaga, _altura = storefront.sector_slot(self._save_com([0, 7488, 10144]))
        perto = min(abs(vaga - usado) for usado in (0, 7488, 10144))
        self.assertLessEqual(perto, storefront.FOLGA_SETOR * 2)
        self.assertGreater(vaga, 0)

    def test_the_height_follows_the_neighbourhood(self):
        """Uma nave na altura errada está tão fora da vista quanto uma na
        coluna errada."""
        from sgalaxy import storefront
        _vaga, altura = storefront.sector_slot(self._save_com([0, 7488]))
        self.assertEqual(altura, 5216)

    def test_an_empty_sector_takes_the_middle(self):
        from sgalaxy import storefront
        self.assertEqual(storefront.sector_slot(self._save_com([])), (0, None))

    def test_a_dense_sector_places_just_outside_it(self):
        """Um setor lotado não impede a vitrine: ela encosta na borda do
        aglomerado, que é onde ainda dá para ver."""
        from sgalaxy import storefront
        cheio = list(range(-7488, 7489, storefront.PASSO_SETOR))
        vaga, _altura = storefront.sector_slot(self._save_com(cheio))
        self.assertIsNotNone(vaga)
        for usado in cheio:
            self.assertGreaterEqual(abs(vaga - usado), storefront.FOLGA_SETOR)
        self.assertLessEqual(abs(vaga) - 7488, storefront.FOLGA_SETOR * 2)


class StorefrontSectorTestCase(unittest.TestCase):
    """O `<ships>` do `game` é a lista do setor onde a pessoa está, e não um
    índice da galáxia. Uma nave posta ali é desenhada ali, mesmo com a frota
    apontando para outro corpo: foi assim que a vitrine de um vizinho apareceu
    no setor de outro jogador enquanto o vizinho estava a dois corpos dali."""

    def _save(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp,
                                                            ignore_errors=True))
        d = os.path.join(tmp, "save")
        os.makedirs(d)
        jogo = ET.Element("game", {"seed": "0"})
        ET.SubElement(jogo, "masterData", {"idCounter": "5000"})
        ET.SubElement(jogo, "ships")
        starmap = ET.SubElement(jogo, "starmap",
                                {"w": "1", "h": "1", "objectIdCounter": "500"})
        sistemas = ET.SubElement(starmap, "systems")
        sistema = ET.SubElement(sistemas, "l", {"systemId": "31"})
        corpos = ET.SubElement(sistema, "bodies")
        for ident, x, y in (("10", "100", "100"), ("11", "900", "900")):
            corpo = ET.SubElement(corpos, "l", {"id": ident, "celeid": ident,
                                                "type": "AsteroidField",
                                                "x": x, "y": y})
            ET.SubElement(corpo, "info")
        aqui = corpos.find("l")
        ET.SubElement(ET.SubElement(aqui, "fleets"), "f",
                      {"id": "0", "isPlayer": "true", "x": "100", "y": "100"})
        with open(os.path.join(d, "game"), "wb") as fh:
            fh.write(ET.tostring(jogo))
        with open(os.path.join(d, "info"), "wb") as fh:
            fh.write(b'<info date="86400" version="21"/>')
        from sgalaxy.savefile import SaveFile
        return SaveFile(d)

    def _molde(self):
        nave = ET.Element("ship", {"sid": "77", "sname": "CS MOLDE",
                                   "ox": "0", "oy": "5216"})
        ET.SubElement(nave, "settings", {"of": "1694", "owner": "Civilian"})
        ET.SubElement(ET.SubElement(nave, "characters"), "c",
                      {"entId": "9", "name": "Alguem"})
        ET.SubElement(nave, "roof", {"hullPattern": "1"})
        return nave

    def test_a_neighbour_at_another_body_is_not_in_this_sector(self):
        from sgalaxy import storefront
        sf = self._save()
        rel = storefront.inject_ship(sf, self._molde(), faction="Civilian",
                                     name="CS VIZINHA", at=("900", "900"),
                                     system_id="31")
        sid = rel["fleet"]["createdShipId"]
        onde = [d for d, n in sf.ships() if n.get("sid") == sid]
        self.assertEqual(onde, [f"ship{sid}"])
        self.assertEqual(rel["stowed"], f"ship{sid}")

    def test_a_neighbour_on_the_same_body_stays_in_the_sector(self):
        """Estando no mesmo corpo, a nave TEM de ser desenhada aqui: é a
        vizinha com quem dá para comerciar sem viajar."""
        from sgalaxy import storefront
        sf = self._save()
        rel = storefront.inject_ship(sf, self._molde(), faction="Civilian",
                                     name="CS VIZINHA", at=("100", "100"),
                                     system_id="31")
        sid = rel["fleet"]["createdShipId"]
        onde = [d for d, n in sf.ships() if n.get("sid") == sid]
        self.assertEqual(onde, ["game"])
        self.assertIsNone(rel.get("stowed"))

    def test_a_player_in_an_empty_sector_is_still_located(self):
        """Quem está numa hyperlane tem a frota num setor vazio, e não sob um
        corpo celeste. `find_player_fleet` devolvia None ali, a verificação de
        "mesmo corpo?" não decidia nada, e a vitrine ia para o setor carregado."""
        from sgalaxy import storefront
        sf = self._save()
        starmap = sf.main.find("starmap")
        # Tira a frota do corpo e põe num setor vazio, como o jogo faz.
        for corpo in starmap.iter("l"):
            frotas = corpo.find("fleets")
            if frotas is not None:
                corpo.remove(frotas)
                break
        sistema = starmap.find("systems/l")
        vazios = ET.SubElement(sistema, "emptySectors")
        setor = ET.SubElement(vazios, "l", {"id": "99", "x": "500", "y": "500"})
        ET.SubElement(ET.SubElement(setor, "fleets"), "f",
                      {"id": "0", "isPlayer": "true", "x": "500", "y": "500"})
        self.assertEqual(storefront.where_the_player_is(sf), ("500", "500"))

    def test_not_knowing_where_the_player_is_still_stows(self):
        """Não saber não autoriza desenhar a nave de um vizinho aqui."""
        from sgalaxy import storefront
        sf = self._save()
        starmap = sf.main.find("starmap")
        for f in list(starmap.iter("f")):
            if f.get("isPlayer") == "true":
                for pai in starmap.iter():
                    if f in list(pai):
                        pai.remove(f)
        self.assertEqual(storefront.where_the_player_is(sf), (None, None))
        rel = storefront.inject_ship(sf, self._molde(), faction="Civilian",
                                     name="CS VIZINHA", at=("100", "100"),
                                     system_id="31")
        self.assertIsNotNone(rel["stowed"])


class ShelfIsOnlyWhatWasConsignedTestCase(unittest.TestCase):
    """O jogo vende o que está no chão junto com o que está na prateleira.
    Medido: uma venda de 544 créditos com a prateleira vazia, apurada como
    crédito sem mercadoria. A pessoa foi paga por carga que nunca ofereceu, e
    a carga não saiu do save dela porque nunca esteve à venda."""

    def _nave_com_caixas(self):
        nave = ET.Element("ship", {"sid": "77", "sname": "CS MOLDE",
                                   "ox": "0", "oy": "5216"})
        ET.SubElement(nave, "settings", {"of": "1694", "owner": "Civilian"})
        ET.SubElement(ET.SubElement(nave, "characters"), "c", {"entId": "9"})
        ET.SubElement(nave, "roof", {"hullPattern": "1"})
        feat = ET.SubElement(ET.SubElement(nave, "l"), "feat")
        ET.SubElement(ET.SubElement(feat, "inv"), "s",
                      {"elementaryId": "56", "inStorage": "30"})
        itens = ET.SubElement(nave, "items")
        for i in range(4):
            ET.SubElement(itens, "i", {"eid": "176", "id": str(500 + i)})
        return nave

    def test_crates_are_emptied_with_the_shelves(self):
        from sgalaxy import storefront
        nave = self._nave_com_caixas()
        rel = storefront.set_stock(nave, [("2475", "17")], clear=True)
        self.assertEqual(rel.get("cratesCleared"), 4)
        self.assertEqual(nave.findall("items/i"), [])

    def test_reading_back_counts_crates_too(self):
        """Ler só a prateleira faz uma venda de caixa virar crédito sem
        mercadoria."""
        from sgalaxy import storefront
        nave = self._nave_com_caixas()
        lido = storefront.read_stock(nave)
        self.assertEqual(lido.get("176"), 4)
        self.assertEqual(lido.get("56"), 30)

    def test_keeping_the_cargo_keeps_the_crates(self):
        from sgalaxy import storefront
        nave = self._nave_com_caixas()
        storefront.set_stock(nave, [], clear=False)
        self.assertEqual(len(nave.findall("items/i")), 4)

    def test_it_sits_near_the_player_not_the_middle(self):
        """Medido num setor com naves em -4992, -2336 e 1248: não cabia folga
        entre elas, havia duas vagas igualmente distantes do centro, e o
        desempate pegou -8736, a quase dez mil da nave da pessoa. Uma vitrine
        existe para ser alcançada."""
        from sgalaxy import storefront
        from sgalaxy.savefile import SaveFile
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp,
                                                            ignore_errors=True))
        d = os.path.join(tmp, "save")
        os.makedirs(d)
        jogo = ET.Element("game", {"seed": "0"})
        naves = ET.SubElement(jogo, "ships")
        for ox, dono in ((1248, "Player"), (-2336, "Civilian"),
                         (-4992, "Civilian")):
            nave = ET.SubElement(naves, "ship",
                                 {"sid": str(abs(ox)), "ox": str(ox),
                                  "oy": "2096"})
            ET.SubElement(nave, "settings", {"owner": dono})
        ET.SubElement(jogo, "starmap", {"w": "1", "h": "1"})
        with open(os.path.join(d, "game"), "wb") as fh:
            fh.write(ET.tostring(jogo))
        with open(os.path.join(d, "info"), "wb") as fh:
            fh.write(b'<info date="86400" version="21"/>')
        vaga, altura = storefront.sector_slot(SaveFile(d))
        self.assertLess(abs(vaga - 1248), abs(vaga - (-4992)),
                        f"ficou do lado errado: {vaga}")
        self.assertLessEqual(abs(vaga - 1248), storefront.FOLGA_SETOR + 1248)
        self.assertEqual(altura, 2096)
