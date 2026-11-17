"""A porta HTTP real do webhook contra um servidor TLS local, com uma CA de teste."""

import datetime
import http.server
import socket
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from api.webhook import HttpNoIpValidado

# Nome que não resolve: se o cliente resolvesse o host de novo, a conexão falharia.
HOST = "webhook.exemplo.invalid"


def _nome(texto: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, texto)])


def _certificados(pasta: Path) -> tuple[bytes, Path, Path]:
    agora = datetime.datetime.now(datetime.UTC)
    validade = (agora - datetime.timedelta(days=1), agora + datetime.timedelta(days=1))
    chave_ca = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_nome("CA de teste"))
        .issuer_name(_nome("CA de teste"))
        .public_key(chave_ca.public_key())
        .serial_number(1)
        .not_valid_before(validade[0])
        .not_valid_after(validade[1])
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(chave_ca, hashes.SHA256())
    )
    chave = ec.generate_private_key(ec.SECP256R1())
    folha = (
        x509.CertificateBuilder()
        .subject_name(_nome(HOST))
        .issuer_name(ca.subject)
        .public_key(chave.public_key())
        .serial_number(2)
        .not_valid_before(validade[0])
        .not_valid_after(validade[1])
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), False)
        .sign(chave_ca, hashes.SHA256())
    )
    cert, pem_chave = pasta / "cert.pem", pasta / "chave.pem"
    cert.write_bytes(folha.public_bytes(serialization.Encoding.PEM))
    pem_chave.write_bytes(
        chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca.public_bytes(serialization.Encoding.PEM), cert, pem_chave


class Servidor:
    def __init__(self, porta: int, ca: bytes) -> None:
        self.porta = porta
        self.ca = ca
        self.status = 200
        self.sni: list[str | None] = []
        self.pedidos: list[tuple[str, str, dict[str, str], bytes]] = []

    def cliente(self) -> HttpNoIpValidado:
        return HttpNoIpValidado(ssl.create_default_context(cadata=self.ca.decode()))


@pytest.fixture
def servidor(tmp_path: Path) -> Iterator[Servidor]:
    ca, cert, chave = _certificados(tmp_path)
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.load_cert_chain(cert, chave)

    class Tratador(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            corpo = self.rfile.read(int(self.headers["Content-Length"]))
            estado.pedidos.append(
                (self.command, self.path, dict(self.headers.items()), corpo)
            )
            self.send_response(estado.status)
            self.send_header("Location", "https://127.0.0.1/interno")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
    estado = Servidor(httpd.server_address[1], ca)
    contexto.sni_callback = lambda sock, nome, ctx: estado.sni.append(nome)
    httpd.socket = contexto.wrap_socket(httpd.socket, server_side=True)
    fio = threading.Thread(target=httpd.serve_forever, daemon=True)
    fio.start()
    yield estado
    httpd.shutdown()
    httpd.server_close()


def test_conecta_no_ip_com_o_host_da_url_no_sni_e_no_host(servidor: Servidor) -> None:
    url = f"https://{HOST}:{servidor.porta}/eventos?x=1"
    status = servidor.cliente().enviar(
        url, ["127.0.0.1"], b'{"a":1}', {"X-Webhook-Id": "9"}
    )
    assert status == 200
    assert servidor.sni == [HOST]
    metodo, caminho, cabecalhos, corpo = servidor.pedidos[0]
    assert (metodo, caminho, corpo) == ("POST", "/eventos?x=1", b'{"a":1}')
    assert cabecalhos["Host"] == f"{HOST}:{servidor.porta}"
    assert cabecalhos["X-Webhook-Id"] == "9"


def test_redirecionamento_volta_como_status(servidor: Servidor) -> None:
    servidor.status = 302
    url = f"https://{HOST}:{servidor.porta}/"
    assert servidor.cliente().enviar(url, ["127.0.0.1"], b"{}", {}) == 302
    assert len(servidor.pedidos) == 1


def test_certificado_de_outro_nome_e_recusado(servidor: Servidor) -> None:
    url = f"https://outro.exemplo.invalid:{servidor.porta}/"
    with pytest.raises(OSError):
        servidor.cliente().enviar(url, ["127.0.0.1"], b"{}", {})
    assert servidor.pedidos == []


def test_ip_que_nao_conecta_passa_ao_proximo(
    servidor: Servidor, monkeypatch: pytest.MonkeyPatch
) -> None:
    conectar = socket.create_connection
    tentados: list[str] = []

    def so_o_local(endereco: tuple[str, int], *args: object, **kw: object) -> object:
        tentados.append(endereco[0])
        if endereco[0] != "127.0.0.1":
            raise ConnectionRefusedError
        return conectar(endereco, *args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "create_connection", so_o_local)
    url = f"https://{HOST}:{servidor.porta}/"
    assert (
        servidor.cliente().enviar(url, ["203.0.113.9", "127.0.0.1"], b"{}", {}) == 200
    )
    assert tentados == ["203.0.113.9", "127.0.0.1"]


def test_nenhum_ip_conecta_levanta_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def recusa(*args: object, **kw: object) -> object:
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", recusa)
    with pytest.raises(OSError):
        HttpNoIpValidado().enviar(f"https://{HOST}/", ["203.0.113.9"], b"{}", {})
