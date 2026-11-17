"""A `PortaHttp` real do webhook (#705): POST no IP já validado, só com a biblioteca
padrão. O host da URL vai no SNI e no `Host`; não resolve o DNS de novo nem segue
redirecionamento."""

import http.client
import socket
import ssl
import string
import threading
import time
from urllib.parse import quote, urlsplit

# Tempo total do POST, somando as tentativas em cada IP: cabe no ack de 60 s do Pub/Sub,
# com o cofre e o Firestore.
PRAZO_DO_POST_S = 30.0
CONEXAO_POR_IP_S = 10.0


class _ConexaoNoIp(http.client.HTTPSConnection):
    """Conecta no `ip`; o host da URL fica no SNI, na checagem do certificado e no `Host`."""

    def __init__(
        self, host: str, porta: int, ip: str, contexto: ssl.SSLContext, fim: float
    ) -> None:
        super().__init__(host, porta, context=contexto)
        self._ip = ip
        self._contexto = contexto
        self._fim = fim

    def _restante(self) -> float:
        # Timeout zero ou negativo levantaria ValueError, e não OSError.
        return max(self._fim - time.monotonic(), 0.001)

    def connect(self) -> None:
        # Um IP que não responde não come o prazo dos outros; o handshake fica com o
        # que sobrou (no CPython, o timeout vale para o handshake inteiro).
        bruto = socket.create_connection(
            (self._ip, self.port), min(self._restante(), CONEXAO_POR_IP_S)
        )
        try:
            bruto.settimeout(self._restante())
            self.sock = self._contexto.wrap_socket(bruto, server_hostname=self.host)
        except BaseException:
            bruto.close()
            raise


def _derrubar(sock: socket.socket) -> None:
    # `shutdown`, e não `close`: só ele acorda um `recv` parado em outra thread.
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class HttpNoIpValidado:
    """A `PortaHttp` real, só com a biblioteca padrão."""

    def __init__(
        self, contexto: ssl.SSLContext | None = None, prazo_s: float = PRAZO_DO_POST_S
    ) -> None:
        self._contexto = contexto or ssl.create_default_context()
        self._prazo_s = prazo_s

    def enviar(
        self, url: str, ips: list[str], corpo: bytes, cabecalhos: dict[str, str]
    ) -> int:
        partes = urlsplit(url)
        caminho = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
        # A linha do pedido só aceita ASCII: codifica o resto e mantém os escapes.
        caminho = quote(caminho, safe=string.punctuation)
        fim = time.monotonic() + self._prazo_s
        erro: OSError = OSError("nenhum IP para conectar")
        # IPv4 primeiro: o Cloud Run pode não ter saída IPv6.
        for ip in sorted(ips, key=lambda ip: ":" in ip):
            if time.monotonic() >= fim:
                break
            conexao = _ConexaoNoIp(
                partes.hostname or "", partes.port or 443, ip, self._contexto, fim
            )
            try:
                conexao.connect()
            except OSError as e:
                # Só a conexão que falhou passa ao próximo IP; o POST enviado nunca repete.
                erro = e
                conexao.close()
                continue
            # O timeout do socket vale por operação: um destino que goteja bytes o
            # renova sempre. No fim do prazo, o vigia derruba a conexão.
            vigia = threading.Timer(fim - time.monotonic(), _derrubar, [conexao.sock])
            vigia.start()
            try:
                conexao.request("POST", caminho, body=corpo, headers=cabecalhos)
                return conexao.getresponse().status
            except http.client.HTTPException as e:
                raise OSError(f"resposta inválida do destino: {e!r}") from e
            finally:
                vigia.cancel()
                conexao.close()
        raise erro
