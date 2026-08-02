"""A apuração de uma venda feita contra uma nave que o servidor inventou.

O que estes testes protegem é o momento em que o dinheiro muda de dono. Um
sinal trocado aqui paga a pessoa errada, e o jogo não tem como reclamar: para
ele a transação já terminou, certinha, contra um NPC.
"""

import unittest

from sgalaxy import settle


class ReconcileTestCase(unittest.TestCase):

    def test_what_left_the_shelf_is_what_was_sold(self):
        achado = settle.reconcile(
            {"stock": {"56": 100, "57": 20}, "credits": 5000},
            {"56": 60, "57": 20}, 5800)
        self.assertEqual(achado["sold"], {"56": 40})
        self.assertEqual(achado["credits"], 800)
        self.assertEqual(achado["inbound"], {})

    def test_a_resource_emptied_completely_still_counts(self):
        """Estoque zerado some do dicionário; ausência é venda, não engano."""
        achado = settle.reconcile(
            {"stock": {"56": 30}, "credits": 5000}, {}, 5450)
        self.assertEqual(achado["sold"], {"56": 30})
        self.assertEqual(achado["credits"], 450)

    def test_nothing_moved_settles_nothing(self):
        achado = settle.reconcile(
            {"stock": {"56": 30}, "credits": 5000}, {"56": 30}, 5000)
        self.assertEqual(achado["sold"], {})
        self.assertEqual(achado["credits"], 0)
        self.assertEqual(achado["notes"], [])

    def test_a_missing_storefront_settles_nothing(self):
        """Sem prateleira não há prova. A vitrine pode ter sido destruída, ou
        ter saído do setor, e inventar uma venda é pior que perdê-la."""
        achado = settle.reconcile(
            {"stock": {"56": 30}, "credits": 5000}, None, None)
        self.assertEqual(achado["sold"], {})
        self.assertEqual(achado["credits"], 0)
        self.assertTrue(achado["notes"])

    def test_selling_into_the_storefront_is_never_debited(self):
        """A banca da vitrine é um número que o servidor inventou, não o
        dinheiro do vizinho. Debitar alguém por uma compra que não fez, com
        dinheiro que nunca teve, é pior do que perder a transação."""
        achado = settle.reconcile(
            {"stock": {"56": 30}, "credits": 5000},
            {"56": 30, "99": 12}, 4100)
        self.assertEqual(achado["credits"], 0)
        self.assertEqual(achado["sold"], {})
        self.assertEqual(achado["inbound"], {"99": 12})
        self.assertTrue(any("sold INTO it" in n for n in achado["notes"]))

    def test_a_storefront_without_a_bank_gives_the_goods_back(self):
        """Sem preço não há venda. Deixar a mercadoria sair sem pagamento faria
        o vendedor perder carga de graça."""
        achado = settle.reconcile(
            {"stock": {"56": 30}, "credits": None}, {"56": 10}, None)
        self.assertEqual(achado["sold"], {})
        self.assertEqual(achado["credits"], 0)
        self.assertTrue(achado["notes"])

    def test_goods_gone_without_payment_still_count_as_sold(self):
        """Sumiram da prateleira de um jeito ou de outro. Cobrar do vendedor a
        carga E não pagar seria puni-lo duas vezes."""
        achado = settle.reconcile(
            {"stock": {"56": 30}, "credits": 5000}, {"56": 5}, 5000)
        self.assertEqual(achado["sold"], {"56": 25})
        self.assertEqual(achado["credits"], 0)
        self.assertTrue(achado["notes"])

    def test_both_directions_at_once(self):
        """Comprou aço e despejou lixo. Só a compra é liquidada."""
        achado = settle.reconcile(
            {"stock": {"56": 100}, "credits": 5000},
            {"56": 40, "77": 9}, 6200)
        self.assertEqual(achado["sold"], {"56": 60})
        self.assertEqual(achado["inbound"], {"77": 9})
        self.assertEqual(achado["credits"], 1200)


if __name__ == "__main__":
    unittest.main()
