"""
Testes da contagem de carga.

É a base da reconciliação da fase 3, e o erro aqui não dá erro nenhum: dá
acusação. Um vizinho que vendeu cinco e recebeu por um; um jogador cobrado por
carga que está a três metros da prateleira.

O que estes testes protegem é a medida do item 8 do findings: mercadoria vive em
**três lugares**. No E6, uma venda de 5 Chemicals apareceu como +1 na prateleira
e +4 em caixas no chão. Quem somasse só a prateleira erraria 80% da transação.

E a terceira não é transitória. A nave-vaivém despeja em caixas no piso, e só
depois alguém carrega para o armazém — e só se houver espaço. Com armazém cheio,
a caixa fica lá pelo resto da partida.

    python3 -m unittest tests.test_inventory -v
"""

from __future__ import annotations

import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy import inventory  # noqa: E402

# A forma real, medida em `E6 vitrine`. As caixas não têm quantidade: cada
# `<i>` é uma unidade, e o recurso é `eid` — não `elementaryId`, que é como a
# prateleira o chama.
NAVE = """<ship sid="1" sname="Teste">
  <settings of="461" owner="Player"/>
  <inv>
    <s elementaryId="176" inStorage="87" onTheWayIn="0" onTheWayOut="0"/>
    <s elementaryId="930" inStorage="19" onTheWayIn="0" onTheWayOut="0"/>
  </inv>
  <items>
    <i eid="176" x="27.23" y="46.23" id="5293" moprio="5" grndTime="155"/>
    <i eid="176" x="26.77" y="46.23" id="5292" moprio="5" grndTime="157"/>
    <i eid="176" x="27.00" y="46.00" id="5291" grndTime="150"/>
    <i eid="176" x="27.50" y="46.50" id="5290" grndTime="151"/>
    <i eid="930" x="48.77" y="22.23" id="5296" grndTime="145"/>
  </items>
  <shipBank s="Player" ca="12000" cr="0"/>
</ship>"""


class CountTestCase(unittest.TestCase):

    def setUp(self):
        self.nave = ET.fromstring(NAVE)

    def test_the_shelf_alone_is_not_the_answer(self):
        self.assertEqual(inventory.on_shelves(self.nave),
                         {"176": 87, "930": 19})

    def test_crates_are_counted_one_per_element(self):
        """Não há atributo de quantidade; cada `<i>` é uma unidade."""
        self.assertEqual(inventory.in_crates(self.nave), {"176": 4, "930": 1})

    def test_the_total_is_the_three_places(self):
        """A medida do E6: 5 Chemicals viraram +1 prateleira e +4 caixas."""
        self.assertEqual(inventory.count(self.nave), {"176": 91, "930": 20})

    def test_goods_in_flight_belong_to_whoever_bought_them(self):
        """`onTheWayIn` é carga que uma vaivém foi buscar. Já é de quem comprou."""
        nave = ET.fromstring(NAVE.replace(
            '<s elementaryId="930" inStorage="19" onTheWayIn="0"',
            '<s elementaryId="930" inStorage="19" onTheWayIn="7"'))
        self.assertEqual(inventory.count(nave)["930"], 19 + 7 + 1)

    def test_goods_on_the_way_out_are_not_counted(self):
        """Contá-las seria contar duas vezes o que o outro lado já recebe."""
        nave = ET.fromstring(NAVE.replace(
            'onTheWayOut="0"/>\n    <s elementaryId="930"',
            'onTheWayOut="30"/>\n    <s elementaryId="930"'))
        self.assertEqual(inventory.count(nave)["176"], 91)

    def test_a_ship_with_no_crates_is_not_a_crash(self):
        nave = ET.fromstring(NAVE.replace(
            NAVE[NAVE.index("<items>"):NAVE.index("</items>") + 9], ""))
        self.assertEqual(inventory.in_crates(nave), {})
        self.assertEqual(inventory.count(nave), {"176": 87, "930": 19})

    def test_credits_come_from_the_bank(self):
        self.assertEqual(inventory.credits_of(self.nave), 12000)
        sem_banca = ET.fromstring("<ship sid='2'><inv/></ship>")
        self.assertEqual(inventory.credits_of(sem_banca), 0)


class DeltaTestCase(unittest.TestCase):
    """A reconciliação inteira: o servidor montou a vitrine, então conhece o
    estado inicial exato; o save que volta diz o final.

    O jogo não guarda recibo — nem quantas transações houve, nem em que ordem
    (findings item 8b). A diferença é tudo que há, e é tudo que é preciso.
    """

    def test_what_left_and_what_arrived(self):
        antes = {"176": 100, "930": 10}
        depois = {"176": 95, "930": 10, "2053": 3}
        self.assertEqual(inventory.delta(antes, depois),
                         {"176": -5, "2053": 3})

    def test_nothing_moved_is_an_empty_delta(self):
        self.assertEqual(inventory.delta({"176": 5}, {"176": 5}), {})

    def test_four_purchases_look_like_one(self):
        """E4 caiu de graça: o save só guarda o estado final, então o servidor
        não precisa reconstruir a ordem — e não conseguiria."""
        antes = {"176": 100}
        depois = {"176": 88}
        self.assertEqual(inventory.delta(antes, depois), {"176": -12})


if __name__ == "__main__":
    unittest.main()
