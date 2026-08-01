"""
Testes da loja: um armazém da nave do jogador, e só ele.

A regra que dá sentido a tudo aqui: **a loja é o único lugar que a pessoa nos
autorizou**. Ela move carga para lá com a interface do próprio jogo, e isso é o
consentimento. Tirar de qualquer outro armazém para cobrir uma venda seria mexer
no que ela guardou fora dali.

O que estes testes protegem:

- máquina não é depósito. Produtores, motores e enfermarias também têm `<inv>`,
  com insumos sendo consumidos. Oferecer isso à venda tiraria o combustível do
  motor de alguém
- vender só o que está na prateleira. O que está a caminho ainda não é dela; o
  que está saindo já deixou de ser
- não tirar mais do que existe, e não compensar em outro lugar
- o dinheiro vai para `game/playerBank`, não para o `<shipBank>` da nave

    python3 -m unittest tests.test_shop -v
"""

from __future__ import annotations

import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy import shop  # noqa: E402

# A forma medida em save real: o armazém é um <l> cujo <feat> pendura <inv>
# direto. O produtor tem <inv> também, mas dentro de um <prod>.
JOGO = """<game>
  <playerBank s="Player" ca="1000" cr="0"/>
  <ships>
    <ship sid="1" sname="Casa">
      <settings of="461" owner="Player"/>
      <e>
        <l id="435" x="28" y="20">
          <feat eatAllowed="1" cp="0">
            <inv>
              <s elementaryId="712" inStorage="25" onTheWayIn="0" onTheWayOut="0"/>
              <s elementaryId="176" inStorage="8" onTheWayIn="4" onTheWayOut="2"/>
              <rules/>
            </inv>
          </feat>
        </l>
      </e>
      <e>
        <l id="608" x="25" y="20">
          <feat eatAllowed="1" cp="0">
            <inv>
              <s elementaryId="712" inStorage="200" onTheWayIn="0" onTheWayOut="0"/>
            </inv>
          </feat>
        </l>
      </e>
      <e>
        <l id="900" x="10" y="10">
          <feat>
            <prod>
              <inv>
                <s elementaryId="2053" inStorage="40" onTheWayIn="0" onTheWayOut="0"/>
              </inv>
            </prod>
          </feat>
        </l>
      </e>
    </ship>
  </ships>
</game>"""


class ShopTestCase(unittest.TestCase):

    def setUp(self):
        self.jogo = ET.fromstring(JOGO)
        self.nave = self.jogo.find(".//ships/ship")

    def test_a_machine_is_not_a_warehouse(self):
        """O `<inv>` de um produtor são insumos sendo consumidos.

        Oferecê-los à venda tiraria o combustível do motor de alguém.
        """
        ids = {a["id"] for a in shop.storages(self.nave)}
        self.assertEqual(ids, {"435", "608"})
        self.assertNotIn("900", ids, "ofereceu o insumo de uma máquina")

    def test_the_fullest_comes_first(self):
        """É a ordem útil para alguém escolher qual armazém será a loja."""
        self.assertEqual([a["id"] for a in shop.storages(self.nave)],
                         ["608", "435"])

    def test_only_the_chosen_storage_is_on_sale(self):
        a_venda = shop.on_sale(self.nave, "435")
        self.assertEqual(a_venda, {"712": 25, "176": 8})
        self.assertNotIn(200, a_venda.values(), "vazou o outro armazém")

    def test_goods_in_flight_are_not_on_sale(self):
        """`onTheWayIn` ainda não chegou; `onTheWayOut` já foi vendido.

        Pôr qualquer um dos dois à venda é vender duas vezes a mesma caixa.
        """
        self.assertEqual(shop.on_sale(self.nave, "435")["176"], 8)

    def test_selling_takes_from_the_shop(self):
        saiu = shop.take(self.nave, "435", "712", 5)
        self.assertEqual(saiu, 5)
        self.assertEqual(shop.on_sale(self.nave, "435")["712"], 20)

    def test_it_never_takes_more_than_the_shop_has(self):
        """Entre montar a vitrine e reconciliar, a pessoa pode ter movido a
        carga. Sair menos que o pedido é resultado, não erro."""
        saiu = shop.take(self.nave, "435", "712", 999)
        self.assertEqual(saiu, 25)
        self.assertEqual(shop.on_sale(self.nave, "435").get("712", 0), 0)

    def test_it_never_covers_a_sale_from_another_storage(self):
        """A loja é o único lugar autorizado. O resto é dela."""
        shop.take(self.nave, "435", "712", 999)
        self.assertEqual(shop.on_sale(self.nave, "608")["712"], 200,
                         "tirou de um armazém que não é a loja")

    def test_a_dismantled_shop_is_not_a_crash(self):
        """Desmontar a loja entre sessões é escolha dela, não erro nosso."""
        self.assertEqual(shop.on_sale(self.nave, "12345"), {})
        self.assertEqual(shop.take(self.nave, "12345", "712", 5), 0)

    def test_the_money_reaches_the_player_not_the_ship(self):
        """`playerBank` é do jogo; `shipBank` é a caixa de uma NPC que negocia.

        Passar a nave aqui devolveria None em silêncio, e o vizinho entregaria
        carga sem receber nada.
        """
        self.assertEqual(shop.pay(self.jogo, 1930), 2930)
        self.assertEqual(self.jogo.find("playerBank").get("ca"), "2930")

    def test_paying_a_ship_by_mistake_is_visible(self):
        self.assertEqual(shop.pay(self.nave, 1930), 0,
                         "aceitou pagar numa árvore sem playerBank")


if __name__ == "__main__":
    unittest.main()
