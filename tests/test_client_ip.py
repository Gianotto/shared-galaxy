"""De onde o servidor tira o endereço de quem pediu.

Este é o teste que impede o limite por IP de fazer o oposto do que promete.
Medido nos logs do servidor: atrás do tunnel do Cloudflare, TODA requisição
chega como `172.22.0.1`, o gateway do Docker. Um limite por `client.host` não
daria uma conta por pessoa — daria uma conta para o servidor inteiro, e o
primeiro a se inscrever trancaria a porta para o resto do mundo.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.domain import addresses  # noqa: E402


class FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, headers=None, host="172.22.0.1"):
        self.headers = headers or {}
        self.client = FakeClient(host) if host else None


class ClientAddressTestCase(unittest.TestCase):

    def test_the_docker_gateway_is_not_the_person(self):
        """O caso que mata a funcionalidade inteira se passar despercebido."""
        pedido = FakeRequest({"cf-connecting-ip": "203.0.113.9"})
        self.assertEqual(addresses.client_ip(pedido), "203.0.113.9")

    def test_cloudflare_wins_over_forwarded_for(self):
        """`X-Forwarded-For` o cliente escreve; `CF-Connecting-IP` o Cloudflare
        sobrescreve. Entre os dois, o que não se forja."""
        pedido = FakeRequest({"cf-connecting-ip": "203.0.113.9",
                              "x-forwarded-for": "1.2.3.4"})
        self.assertEqual(addresses.client_ip(pedido), "203.0.113.9")

    def test_the_first_hop_of_forwarded_for_is_the_client(self):
        pedido = FakeRequest({"x-forwarded-for": "203.0.113.9, 10.0.0.1, 10.0.0.2"})
        self.assertEqual(addresses.client_ip(pedido), "203.0.113.9")

    def test_the_socket_is_the_last_resort(self):
        self.assertEqual(addresses.client_ip(FakeRequest()), "172.22.0.1")

    def test_no_client_at_all_is_not_a_crash(self):
        self.assertIsNone(addresses.client_ip(FakeRequest(host=None)))

    def test_an_empty_header_does_not_win(self):
        pedido = FakeRequest({"cf-connecting-ip": "  ",
                              "x-forwarded-for": "203.0.113.9"})
        self.assertEqual(addresses.client_ip(pedido), "203.0.113.9")


class FingerprintTestCase(unittest.TestCase):

    def test_without_a_pepper_nothing_is_stored(self):
        """Preferimos registrar aberto a guardar endereço de gente em claro."""
        self.assertIsNone(addresses.fingerprint("203.0.113.9", ""))

    def test_the_same_address_gives_the_same_fingerprint(self):
        a = addresses.fingerprint("203.0.113.9", "segredo")
        self.assertEqual(a, addresses.fingerprint("203.0.113.9", "segredo"))
        self.assertNotEqual(a, addresses.fingerprint("203.0.113.10", "segredo"))

    def test_the_address_is_not_recoverable_from_the_fingerprint(self):
        """Um sha256 puro de IPv4 se reverte por força bruta em segundos; é
        por isso que há um segredo no meio."""
        import hashlib
        impressao = addresses.fingerprint("203.0.113.9", "segredo")
        self.assertNotIn("203.0.113.9", impressao)
        self.assertNotEqual(
            impressao, hashlib.sha256(b"203.0.113.9").hexdigest())

    def test_a_different_pepper_gives_a_different_fingerprint(self):
        um = addresses.fingerprint("203.0.113.9", "um")
        self.assertNotEqual(um, addresses.fingerprint("203.0.113.9", "outro"))


if __name__ == "__main__":
    unittest.main()
