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
