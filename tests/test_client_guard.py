"""
Testes da trava mais importante do cliente.

Nunca escrever num save com o jogo aberto (seção 2.9). O erro é caro nos dois
sentidos, e por isso os dois estão cobertos: falso positivo trava o jogador de
brincadeira, falso negativo destrói a partida dele.

    python3 -m unittest tests.test_client_guard -v
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_spec = importlib.util.spec_from_file_location(
    "sgalaxy_client",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "tools", "sgalaxy.py"))
client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(client)


class GameDetectionNegativeTestCase(unittest.TestCase):
    """O que NÃO pode ser confundido com o jogo."""

    def setUp(self):
        # Os testes de "não deve detectar" pressupõem que o jogo não está
        # aberto. Se estiver — e estará, na máquina de quem desenvolve isto —
        # a detecção correta faria o teste falhar. Um teste que depende do
        # desktop de quem roda não é um teste; é uma armadilha.
        if client.game_is_running():
            self.skipTest("o Space Haven está aberto nesta máquina")

    def test_does_not_match_a_process_that_merely_mentions_the_path(self):
        """O defeito real: o Steam (e o próprio shell) mencionam o caminho da
        instalação, e a primeira versão lia isso como 'o jogo está aberto'."""
        proc = subprocess.Popen(
            ["sleep", "5"],
            # O nome do programa é `sleep`; a instalação só aparece no
            # ambiente, que é como um processo do Steam se pareceria.
            env={**os.environ,
                 "FAKE": "/steamapps/common/SpaceHaven/spacehaven"})
        self.addCleanup(proc.kill)
        self.assertIsNone(client.game_is_running(),
                          "casou com um processo que só menciona o caminho")

    def test_does_not_match_itself(self):
        """O processo que faz a pergunta não pode ser a resposta."""
        self.assertIsNone(client.game_is_running())


class GameDetectionPositiveTestCase(unittest.TestCase):
    """O que PRECISA ser detectado. Roda mesmo com o jogo real aberto."""

    def test_matches_the_real_executable_name(self):
        """E precisa mesmo pegar o jogo: falso negativo destrói partida.

        Este roda mesmo com o jogo de verdade aberto: um processo chamado
        `spacehaven` tem que ser detectado, venha de onde vier.
        """
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        # Copiar `sleep` não serve: o coreutils é binário multi-chamada e
        # morre ao ser invocado com outro nome, o que deixava o teste
        # dependendo de uma corrida.
        falso = os.path.join(tmp, "spacehaven")
        shutil.copy(sys.executable, falso)
        proc = subprocess.Popen([falso, "-c", "import time; time.sleep(30)"])
        self.addCleanup(proc.kill)
        import time
        for _ in range(50):
            if client.game_is_running():
                break
            time.sleep(0.1)
        self.assertEqual(client.game_is_running(), "spacehaven",
                         "não detectou o executável do jogo rodando")


class SaveResolutionTestCase(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_accepts_the_save_folder(self):
        pasta = os.path.join(self.tmp.name, "save")
        os.makedirs(pasta)
        open(os.path.join(pasta, "game"), "w").close()
        self.assertEqual(client.resolve_save(pasta), pasta)

    def test_accepts_the_folder_that_contains_it(self):
        """É como o jogador pensa: a partida chama 'Fronteira', não 'save'."""
        pasta = os.path.join(self.tmp.name, "Fronteira", "save")
        os.makedirs(pasta)
        open(os.path.join(pasta, "game"), "w").close()
        self.assertEqual(client.resolve_save(os.path.dirname(pasta)), pasta)

    def test_refuses_a_folder_without_a_game_file(self):
        vazio = os.path.join(self.tmp.name, "vazio")
        os.makedirs(vazio)
        with self.assertRaises(client.ClientError) as ctx:
            client.resolve_save(vazio)
        self.assertIn("game", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class MostAdvancedTestCase(unittest.TestCase):
    """Escolher o estado certo para devolver.

    Quem sai do jogo sem salvar na mão deixa o avanço no autosave, e a seção
    2.4 é explícita: o cliente precisa conseguir devolver o último autosave.
    Devolver o `save/` nesse caso apagaria horas de jogo.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _estado(self, nome: str, dia: float):
        pasta = os.path.join(self.tmp.name, nome)
        os.makedirs(pasta, exist_ok=True)
        open(os.path.join(pasta, "game"), "w").close()
        with open(os.path.join(pasta, "info"), "w") as fh:
            fh.write(f'<info version="21" date="{int(dia * 86400)}"/>')
        return pasta

    def test_prefers_the_autosave_when_it_is_ahead(self):
        self._estado("save", 10.0)
        self._estado("autosave1", 12.5)
        _p, qual, dia = client.most_advanced(self.tmp.name)
        self.assertEqual(qual, "autosave1")
        self.assertAlmostEqual(dia, 12.5, places=2)

    def test_prefers_the_manual_save_when_it_is_ahead(self):
        self._estado("save", 20.0)
        self._estado("autosave1", 12.5)
        _p, qual, _d = client.most_advanced(self.tmp.name)
        self.assertEqual(qual, "save")

    def test_compares_game_day_not_file_time(self):
        """Depois de uma queda o relógio do sistema não diz quanto se jogou."""
        antigo = self._estado("autosave1", 30.0)
        recente = self._estado("save", 5.0)
        os.utime(os.path.join(recente, "game"), None)   # save/ é o mais novo
        os.utime(os.path.join(antigo, "game"), (0, 0))  # autosave1 é o mais velho
        _p, qual, _d = client.most_advanced(self.tmp.name)
        self.assertEqual(qual, "autosave1",
                         "escolheu por data de arquivo em vez de dia de jogo")

    def test_refuses_a_folder_with_no_save_inside(self):
        with self.assertRaises(client.ClientError):
            client.most_advanced(self.tmp.name)
