"""
Testes da trava mais importante do cliente.

Nunca escrever num save com o jogo aberto (seção 2.9). O erro é caro nos dois
sentidos, e por isso os dois estão cobertos: falso positivo trava o jogador de
brincadeira, falso negativo destrói a partida dele.

    python3 -m unittest tests.test_client_guard -v
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
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

    def setUp(self):
        # Sem `pgrep` não há detecção, e o cliente avisa em vez de fingir que
        # conferiu. O teste faz o mesmo: declara-se pulado em vez de falhar
        # numa máquina que nunca poderia passar — é o caso do container de CI,
        # que não traz procps.
        import shutil
        if shutil.which("pgrep") is None:
            self.skipTest("sem `pgrep` nesta máquina")

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

    def test_compares_age_days_not_file_time(self):
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


class AutoLoadTestCase(unittest.TestCase):
    """O bilhete que abre o jogo já no save da sala.

    O mod só age se o cliente deixar o marcador, e o cliente só promete a
    abertura direta se o mod estiver de fato armado no `config.json`. Prometer
    sem conferir é pior que não prometer: a pessoa espera o jogo abrir sozinho,
    ele para no menu, e ela conclui que quebrou.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _config(self, **campos) -> None:
        with open(os.path.join(self.tmp.name, "config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(campos, fh)

    def test_a_vanilla_game_is_not_modded(self):
        self._config(classPath=["spacehaven.jar"], vmArgs=["-Xmx4G"])
        self.assertFalse(client.mod_is_installed(self.tmp.name))

    def test_both_halves_are_required(self):
        """O jar sem o agente não é tecido, e o agente sem o jar não faz nada."""
        self._config(classPath=["spacehaven.jar", "SharedGalaxy.jar"],
                     vmArgs=["-Xmx4G"])
        self.assertFalse(client.mod_is_installed(self.tmp.name),
                         "jar no classPath sem -javaagent não roda")
        self._config(classPath=["spacehaven.jar"],
                     vmArgs=["-Xmx4G", "-javaagent:./aspectjweaver-1.9.19.jar"])
        self.assertFalse(client.mod_is_installed(self.tmp.name),
                         "agente sem o nosso jar não carrega o aspecto")

    def test_a_modded_game_is_recognised(self):
        self._config(classPath=["spacehaven.jar", "SharedGalaxy.jar"],
                     vmArgs=["-Xmx4G", "-javaagent:./aspectjweaver-1.9.19.jar"])
        self.assertTrue(client.mod_is_installed(self.tmp.name))

    def test_a_missing_config_is_not_a_crash(self):
        """Instalação estranha não pode derrubar a sessão inteira."""
        self.assertFalse(client.mod_is_installed(self.tmp.name))

    def test_the_marker_names_the_folder_to_open(self):
        self.assertTrue(client.arm_autoload(self.tmp.name, "Sala-6359GV"))
        with open(os.path.join(self.tmp.name, client.AUTOLOAD_MARKER),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "Sala-6359GV")


class FirstAccessTestCase(unittest.TestCase):
    """Sem conta guardada para este servidor.

    A credencial é indexada por URL. Quem troca de porta — um túnel que subiu
    noutro número — continua com a conta, só que sob outra chave, e uma
    mensagem "sem conta" sozinha parece perda de dados.

    E a trava tem que vir ANTES de qualquer coisa cara: a primeira versão
    descobria a falta de conta só na hora de subir o save, depois de a pessoa
    já ter confirmado o envio.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cred = client.CREDENTIALS
        client.CREDENTIALS = os.path.join(self.tmp.name, "credentials.json")
        self.addCleanup(lambda: setattr(client, "CREDENTIALS", self._cred))

    def _guarda(self, **por_url) -> None:
        with open(client.CREDENTIALS, "w", encoding="utf-8") as fh:
            json.dump(por_url, fh)

    def test_no_account_anywhere_says_how_to_register(self):
        with self.assertRaises(client.ClientError) as erro:
            client.require_account()
        self.assertIn("register", str(erro.exception))

    def test_an_account_on_another_url_is_pointed_at(self):
        """O caso real: a conta existe, sob outro endereço."""
        self._guarda(**{"http://127.0.0.1:18714": {"token": "x", "playerId": 1}})
        with self.assertRaises(client.ClientError) as erro:
            client.require_account()
        mensagem = str(erro.exception)
        self.assertIn("http://127.0.0.1:18714", mensagem,
                      "não disse onde a conta está; parece perda de dados")
        self.assertIn("SGALAXY_URL", mensagem)

    def test_an_account_here_passes(self):
        self._guarda(**{client.base_url(): {"token": "x", "playerId": 1}})
        client.require_account()   # não levanta

    def test_membership_never_swallows_a_real_failure(self):
        """Servidor fora do ar não pode virar "você ainda não entrou".

        Essa confusão é o que levava a pessoa até confirmar o envio do save
        para só então falhar.
        """
        self._guarda(**{client.base_url(): {"token": "x", "playerId": 1}})
        real = client.json_request
        client.json_request = lambda *a, **k: (_ for _ in ()).throw(
            client.ClientError("could not reach the server"))
        self.addCleanup(lambda: setattr(client, "json_request", real))
        with self.assertRaises(client.ClientError):
            client.is_member("XXXXXX")


class NewShipTestCase(unittest.TestCase):
    """O primeiro acesso a uma sala cria a nave, não reaproveita uma.

    O enxerto preserva nave, tripulação, banco e pesquisa de propósito. Entrar
    com uma colônia de meio ano é, portanto, chegar com meio ano de vantagem —
    e numa sala onde todo mundo começa junto isso não é atalho, é injustiça.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jogo = os.path.join(self.tmp.name, "SpaceHaven")
        self.saves = os.path.join(self.jogo, "savegames")
        os.makedirs(self.saves)
        self.exe = os.path.join(self.jogo, "spacehaven")
        real = client.find_game
        client.find_game = lambda: self.exe
        self.addCleanup(lambda: setattr(client, "find_game", real))

    def _save(self, nome: str, idade_dias: float = 1.29) -> str:
        pasta = os.path.join(self.saves, nome, "save")
        os.makedirs(pasta)
        with open(os.path.join(pasta, "game"), "w", encoding="utf-8") as fh:
            fh.write("<game/>")
        with open(os.path.join(pasta, "info"), "w", encoding="utf-8") as fh:
            fh.write(f'<info version="21" date="{int(idade_dias * 86400)}"/>')
        return pasta

    def _abre_o_jogo(self, cria: str | list | None) -> list:
        """Substitui o lançamento do jogo por 'a pessoa criou tal partida'."""
        chamadas = []

        def falso(exe, marcador):
            chamadas.append(marcador)
            for nome in ([cria] if isinstance(cria, str) else (cria or [])):
                self._save(nome)

        real = client.launch_and_wait
        client.launch_and_wait = falso
        self.addCleanup(lambda: setattr(client, "launch_and_wait", real))
        return chamadas

    def test_the_game_is_opened_on_the_new_game_menu(self):
        chamadas = self._abre_o_jogo("Minha Nave")
        client.create_ship("XXXXXX", self.exe, sim=True)
        self.assertEqual(chamadas, [client.AUTOLOAD_NEW_GAME],
                         "não pediu ao mod para abrir o criador de partida")

    def test_the_new_game_is_found_by_difference(self):
        """Perguntar o nome erraria: quem escolhe é a pessoa, dentro do jogo."""
        self._save("partida antiga", 90.0)
        self._abre_o_jogo("A Que Eu Acabei De Criar")
        pasta = client.create_ship("XXXXXX", self.exe, sim=True)
        self.assertIsNotNone(pasta)
        self.assertIn("A Que Eu Acabei De Criar", pasta)

    def test_an_old_save_is_never_picked_up(self):
        """A partida velha estava lá antes e continua fora disto."""
        self._save("colônia de meio ano", 178.0)
        self._abre_o_jogo(None)
        self.assertIsNone(client.create_ship("XXXXXX", self.exe, sim=True),
                          "aproveitou um save que já existia")

    def test_creating_nothing_uploads_nothing(self):
        self._abre_o_jogo(None)
        self.assertIsNone(client.create_ship("XXXXXX", self.exe, sim=True))

    def test_creating_two_games_asks_which_one(self):
        """Escolher por nós qual das duas seria escolher errado metade das vezes."""
        self._abre_o_jogo(["Uma", "Outra"])
        self.assertIsNone(client.create_ship("XXXXXX", self.exe, sim=True))

    def test_saying_no_does_not_open_the_game(self):
        chamadas = self._abre_o_jogo("Qualquer")
        real_input = builtins.input
        builtins.input = lambda _p="": "n"
        self.addCleanup(lambda: setattr(builtins, "input", real_input))
        self.assertIsNone(client.create_ship("XXXXXX", self.exe, sim=False))
        self.assertEqual(chamadas, [], "abriu o jogo mesmo com a pessoa dizendo não")


class RecoveryTestCase(unittest.TestCase):
    """O código de recuperação, que é a única volta para uma conta.

    Não há e-mail e não há senha: o token é tudo. Por isso um código digitado
    errado não pode custar a conta que já estava guardada.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cred, self._dir = client.CREDENTIALS, client.CONFIG_DIR
        client.CONFIG_DIR = self.tmp.name
        client.CREDENTIALS = os.path.join(self.tmp.name, "credentials.json")
        self.addCleanup(lambda: setattr(client, "CREDENTIALS", self._cred))
        self.addCleanup(lambda: setattr(client, "CONFIG_DIR", self._dir))
        self.boa = {"token": "TOKEN-QUE-FUNCIONA", "playerId": 1, "name": "Eu"}
        with open(client.CREDENTIALS, "w", encoding="utf-8") as fh:
            json.dump({client.base_url(): self.boa}, fh)

    def _guardado(self) -> dict:
        with open(client.CREDENTIALS, encoding="utf-8") as fh:
            return json.load(fh)[client.base_url()]

    def _servidor(self, aceita: str | None):
        """Finge um servidor que só conhece um token."""
        def falso(method, path, body=None, headers=None, auth=True):
            enviado = (headers or {}).get("Authorization", "")
            if aceita is not None and enviado == f"Bearer {aceita}":
                return 200, json.dumps({"playerId": 7, "name": "Eu"}).encode(), {}
            raise client.ClientError("the server refused (401): unknown token")
        real = client.request
        client.request = falso
        self.addCleanup(lambda: setattr(client, "request", real))

    def test_a_wrong_code_does_not_cost_the_stored_account(self):
        """Gravar antes de conferir apagava a conta de quem errou o código."""
        self._servidor(aceita="OCODIGOCERTO")
        with self.assertRaises(client.ClientError):
            client.cmd_register(_Args(recover="CODIGO-ERRADO"))
        self.assertEqual(self._guardado(), self.boa,
                         "um código errado apagou a conta que estava guardada")

    def test_a_right_code_signs_in(self):
        self._servidor(aceita="OCODIGOCERTO")
        self.assertEqual(client.cmd_register(_Args(recover="OCOD-IGOC-ERTO")), 0)
        self.assertEqual(self._guardado()["token"], "OCODIGOCERTO")
        self.assertEqual(self._guardado()["playerId"], 7)

    def test_the_code_survives_dashes_spaces_and_case(self):
        """Ele é copiado de um papel; tem que voltar mesmo mal digitado."""
        self._servidor(aceita="OCODIGOCERTO")
        client.cmd_register(_Args(recover="  ocod-igoc-erto \n"))
        self.assertEqual(self._guardado()["token"], "OCODIGOCERTO")


class _Args:
    def __init__(self, **kw): self.__dict__.update(kw)
    def __getattr__(self, _): return None


class ConnectionFailureTestCase(unittest.TestCase):
    """Quando a conexão cai no meio de uma devolução.

    O cliente tem uma mensagem exatamente para isso: diz onde a partida está e
    como devolvê-la depois. Ela só aparece se o erro chegar como `ClientError`,
    e `RemoteDisconnected` não é `URLError` nem `HTTPError` — escapava cru, e o
    jogador via um traceback no lugar da instrução. Numa sala aberta a sessenta
    e quatro pessoas, isso acontece.
    """

    def _falha_com(self, erro: Exception):
        real = client.urllib.request.urlopen

        def falso(*_a, **_k):
            raise erro

        client.urllib.request.urlopen = falso
        self.addCleanup(
            lambda: setattr(client.urllib.request, "urlopen", real))

    def _pede(self):
        real_token = client.token
        client.token = lambda: "x"
        self.addCleanup(lambda: setattr(client, "token", real_token))
        return client.request("POST", "/api/v1/rooms/X/checkin", b"z")

    def test_a_dropped_connection_becomes_a_readable_error(self):
        import http.client
        self._falha_com(http.client.RemoteDisconnected(
            "Remote end closed connection without response"))
        with self.assertRaises(client.ClientError) as erro:
            self._pede()
        self.assertIn("broke", str(erro.exception))

    def test_a_reset_connection_becomes_a_readable_error(self):
        self._falha_com(ConnectionResetError("Connection reset by peer"))
        with self.assertRaises(client.ClientError):
            self._pede()

    def test_a_refused_connection_still_says_where(self):
        self._falha_com(client.urllib.error.URLError("Connection refused"))
        with self.assertRaises(client.ClientError) as erro:
            self._pede()
        self.assertIn(client.base_url(), str(erro.exception))


class WatcherTestCase(unittest.TestCase):
    """O vigia de autosaves durante a sessão.

    Ele só lê, e só depois que a pasta para de mudar: enquanto o jogo está
    aberto aqueles arquivos são dele. E ele conta o que fez nos dois lugares —
    no log do jogo, que é onde a pessoa está olhando, e no terminal, que é onde
    ela vai procurar se algo der errado.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sala = os.path.join(self.tmp.name, "Sala-XXXXXX")
        self.jogo = os.path.join(self.tmp.name, "jogo")
        os.makedirs(self.sala)
        os.makedirs(self.jogo)

    def _autosave(self, nome: str, dia: float) -> str:
        pasta = os.path.join(self.sala, nome)
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, "game"), "w", encoding="utf-8") as fh:
            fh.write("<game/>")
        with open(os.path.join(pasta, "info"), "w", encoding="utf-8") as fh:
            fh.write(f'<info version="21" date="{int(dia * 86400)}"/>')
        return pasta

    def test_only_autosaves_are_watched(self):
        """A pasta `save` é a manual; ela vai na devolução, não em checkpoint."""
        self._autosave("save", 5.0)
        self._autosave("autosave1", 5.2)
        enviados = []
        real = client._send_checkpoint
        client._send_checkpoint = lambda p, n, r, g: enviados.append(n)
        self.addCleanup(lambda: setattr(client, "_send_checkpoint", real))

        parar = threading.Event()
        client.WATCH_EVERY, client.SETTLE_SECONDS = 0.01, 0.01
        t = threading.Thread(target=client.watch_autosaves,
                             args=(self.sala, "XXXXXX", self.jogo, parar))
        t.start()
        time.sleep(0.3)
        parar.set()
        t.join(timeout=2)
        self.assertEqual(enviados, ["autosave1"],
                         f"mandou o que não devia: {enviados}")

    def test_the_same_autosave_is_not_sent_twice(self):
        """Sem isto, um autosave viraria uma versão nova a cada volta do laço."""
        self._autosave("autosave1", 5.2)
        enviados = []
        real = client._send_checkpoint
        client._send_checkpoint = lambda p, n, r, g: enviados.append(n)
        self.addCleanup(lambda: setattr(client, "_send_checkpoint", real))

        parar = threading.Event()
        client.WATCH_EVERY, client.SETTLE_SECONDS = 0.01, 0.01
        t = threading.Thread(target=client.watch_autosaves,
                             args=(self.sala, "XXXXXX", self.jogo, parar))
        t.start()
        time.sleep(0.4)
        parar.set()
        t.join(timeout=2)
        self.assertEqual(enviados, ["autosave1"],
                         f"mandou o mesmo autosave {len(enviados)} vezes")

    def test_a_folder_still_being_written_waits(self):
        """Ler no meio da gravação daria XML cortado. Espera a pasta assentar."""
        pasta = self._autosave("autosave1", 5.2)
        assinatura = client._folder_state(pasta)
        with open(os.path.join(pasta, "game"), "a", encoding="utf-8") as fh:
            fh.write("<mais/>")
        self.assertNotEqual(client._folder_state(pasta), assinatura,
                            "a assinatura não percebeu a pasta mudando")


class JoinWithoutASaveTestCase(unittest.TestCase):
    """`join` exigia `--save`, e a página do site manda rodar `join` antes de
    `play`. Quem chega pela primeira vez não tem save nenhum para apontar: a
    criação pelo New Game já estava escrita, presa dentro do `play`."""

    def test_save_is_optional(self):
        parser = client.build_parser()
        args = parser.parse_args(["join", "6359GV"])
        self.assertIsNone(args.save)

    def test_join_takes_the_flags_the_first_access_needs(self):
        args = client.build_parser().parse_args(
            ["join", "6359GV", "--game", "/tmp/x", "-y"])
        self.assertEqual(args.game, "/tmp/x")
        self.assertTrue(args.yes)

    def test_without_a_game_it_says_what_to_do(self):
        args = client.build_parser().parse_args(
            ["join", "6359GV", "--game", "/nao/existe"])
        with self.assertRaises(client.ClientError) as erro:
            client.cmd_join(args)
        self.assertIn("--save", str(erro.exception))
