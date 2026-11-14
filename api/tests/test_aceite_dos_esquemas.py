"""O aceite dos esquemas contra o Vertex (#617): a lógica, com transporte falso."""

from api.aceite_dos_esquemas import aceitar, codigo_de_saida
from api.decupagem import esquema_do_modelo
from api.gemini import Chamada, ErroHttp
from api.inventario import RespostaConvertida, RespostaVista, _esquema


class Transporte:
    def __init__(self, *respostas: str | Exception) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[Chamada] = []

    def gerar(self, chamada: Chamada) -> str:
        self.chamadas.append(chamada)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_manda_os_tres_esquemas_do_codigo_com_texto_so() -> None:
    t = Transporte("{}", "{}", "{}")

    resultados = aceitar(t)

    assert [c.esquema for c in t.chamadas] == [
        esquema_do_modelo(),
        _esquema(RespostaConvertida),
        _esquema(RespostaVista),
    ]
    assert all(c.video_uri == "" and not c.imagens for c in t.chamadas)
    assert [r.veredito for r in resultados] == ["aceito"] * 3
    assert codigo_de_saida(resultados) == 0


def test_400_e_erro_de_esquema_e_falha_mesmo_com_os_outros_passando() -> None:
    t = Transporte("{}", ErroHttp(400, "INVALID_ARGUMENT", "x"), "{}")

    resultados = aceitar(t)

    assert [r.veredito for r in resultados] == ["aceito", "recusado", "aceito"]
    assert "INVALID_ARGUMENT" in resultados[1].detalhe
    assert codigo_de_saida(resultados) == 1


def test_429_e_5xx_sao_passageiros_e_nao_derrubam_o_deploy() -> None:
    t = Transporte(ErroHttp(429), ErroHttp(503), "{}")

    resultados = aceitar(t)

    assert [r.veredito for r in resultados] == ["passageiro", "passageiro", "aceito"]
    assert codigo_de_saida(resultados) == 0


def test_outro_erro_nao_prova_nada_e_falha_com_codigo_proprio() -> None:
    resultados = aceitar(Transporte(ErroHttp(403), "{}", "{}"))

    assert resultados[0].veredito == "sem_prova"
    assert codigo_de_saida(resultados) == 2


def test_recusa_vale_mais_que_falta_de_prova() -> None:
    resultados = aceitar(Transporte(ErroHttp(403), ErroHttp(400), "{}"))

    assert codigo_de_saida(resultados) == 1
