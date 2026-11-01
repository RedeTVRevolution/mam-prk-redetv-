"""Comparação com as fotos de referência e o nome aplicado (#112, ADR 0005)."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from api.catalogo import CatalogoEmMemoria, Rosto
from api.comparacao import comparar
from api.gemini import ErroHttp
from api.referencias import SugestoesEmMemoria
from api.rostos_dos_palpites import FotoAusente
from api.tests.test_gemini import TransporteFalso
from api.tests.test_identificacao import decupagem, pessoa

AGORA = datetime(2026, 10, 31, tzinfo=UTC)
BARBA = "não identificado, homem de barba"


class FotosEmMemoria:
    def __init__(self) -> None:
        self.objetos: dict[str, bytes] = {}

    def ler(self, objeto: str) -> bytes:
        if objeto not in self.objetos:
            raise FotoAusente(objeto)
        return self.objetos[objeto]

    def gravar(self, objeto: str, conteudo: bytes) -> None:
        self.objetos[objeto] = conteudo

    def apagar(self, objeto: str) -> None:
        self.objetos.pop(objeto, None)


class Cenario:
    def __init__(self) -> None:
        self.catalogo = CatalogoEmMemoria()
        self.fotos = FotosEmMemoria()
        self.sugestoes = SugestoesEmMemoria()
        self.leao = self.com_fotos("Leão Lobo", "comentarista", ["Leãozinho"])
        self.nelson = self.com_fotos("Nelson Rubens", "apresentador", [])

    def com_fotos(self, nome: str, papel: str, apelidos: list[str]) -> str:
        p = self.catalogo.acrescentar(nome, papel, apelidos)
        rostos = []
        for i in range(3):
            objeto = f"referencias/{p.id}/{i}.jpg"
            self.fotos.objetos[objeto] = f"foto-{nome}-{i}".encode()
            rostos.append(
                Rosto(
                    origem="web",
                    referencia=objeto,
                    pagina_url=f"https://x/{i}",
                    obtida_em=AGORA - timedelta(days=1),
                )
            )
        self.catalogo.definir_rostos(p.id, rostos)
        return p.id


def palpite(
    id: str, nome: str, aparicoes: list[tuple[int, int]], **campos: Any
) -> dict[str, Any]:
    return pessoa(
        id, nome, aparicoes, estado_do_nome="palpite", fontes_do_nome=[], **campos
    )


def escolha(rotulo: str) -> str:
    return json.dumps({"rotulo": rotulo})


def confianca(valor: float) -> str:
    return json.dumps({"confianca": valor})


def quadros(instantes: Sequence[int]) -> list[bytes]:
    return [f"quadro-{i}".encode() for i in instantes]


def rodar(c: Cenario, d: Any, transporte: TransporteFalso, **kw: Any) -> Any:
    kw.setdefault("embaralhar", lambda lista: None)
    return comparar(
        d,
        transporte=transporte,
        quadros_em=quadros,
        fotos=c.fotos,
        catalogo=c.catalogo,
        job_id="job-1",
        agora=AGORA,
        validade=timedelta(days=180),
        dormir=lambda _: None,
        **kw,
    )


def rotulo_de(transporte: TransporteFalso, chamada: int, nome_das_fotos: str) -> str:
    """O rótulo que a chamada deu ao grupo de fotos de `nome_das_fotos`."""
    instrucao = transporte.chamadas[chamada].instrucao
    imagens = transporte.chamadas[chamada].imagens
    primeira = next(i for i, im in enumerate(imagens) if nome_das_fotos.encode() in im)
    linha = next(
        linha
        for linha in instrucao.splitlines()
        if f"imagens {primeira + 1} a " in linha
    )
    return linha.split(":")[0].removeprefix("- Grupo ").strip()


def test_escolha_as_cegas_e_tres_fotos_acima_do_limiar_confirmam_o_nome() -> None:
    c = Cenario()
    d = decupagem([pessoa("pes01", BARBA, [(10_000, 40_000)], fontes_do_nome=[])])
    transporte = TransporteFalso(
        escolha("A"), confianca(0.9), confianca(0.95), confianca(0.85)
    )

    r = rodar(c, d, transporte, limiar=0.8)

    [p] = r.decupagem.pessoas
    assert (p.nome, p.estado_do_nome, p.origem, p.fontes_do_nome) == (
        "Leão Lobo",
        "confirmado",
        "modelo_forte",
        ["referencia"],
    )
    assert p.catalogo_id == c.leao
    [v] = r.vereditos
    assert v.estado == "confirmado"
    # as fotos que confirmaram são as da pessoa do catálogo ligada à pessoa do vídeo
    assert v.fotos == tuple(c.catalogo.obter(c.leao).rostos)  # type: ignore[union-attr]
    assert v.confiancas == (0.9, 0.95, 0.85)
    # 1 escolha + 3 conferências, uma por foto
    assert len(transporte.chamadas) == 4


def test_o_modelo_nunca_recebe_nomes_e_o_codigo_traduz_o_rotulo() -> None:
    c = Cenario()
    d = decupagem([palpite("pes01", "Nelson Rubens", [(10_000, 40_000)])])
    transporte = TransporteFalso(escolha("B"), confianca(1), confianca(1), confianca(1))

    # sem embaralhar, A é o Leão e B o Nelson (ordem do catálogo)
    r = rodar(c, d, transporte)

    assert r.decupagem.pessoas[0].nome == "Nelson Rubens"
    for chamada in transporte.chamadas:
        texto = chamada.instrucao + chamada.texto
        for proibido in ("Leão", "Leãozinho", "Lobo", "Nelson", "Rubens"):
            assert proibido not in texto


def test_a_ordem_dos_rotulos_muda_entre_chamadas() -> None:
    c = Cenario()
    d = decupagem(
        [
            pessoa("pes01", BARBA, [(10_000, 40_000)], fontes_do_nome=[]),
            pessoa("pes02", "não identificado, mulher loira", [(50_000, 70_000)]),
        ]
    )
    transporte = TransporteFalso(escolha("nenhum"), escolha("nenhum"))
    giros = iter([False, True])

    rodar(
        c,
        d,
        transporte,
        embaralhar=lambda lista: lista.reverse() if next(giros) else None,
    )

    primeira = rotulo_de(transporte, 0, "Leão")
    segunda = rotulo_de(transporte, 1, "Leão")
    assert primeira != segunda


def test_uma_foto_abaixo_do_limiar_deixa_o_palpite_nao_confirmado() -> None:
    c = Cenario()
    d = decupagem([palpite("pes01", "Leão Lobo", [(10_000, 40_000)])])
    transporte = TransporteFalso(
        escolha("A"), confianca(0.9), confianca(0.5), confianca(0.9)
    )

    r = rodar(c, d, transporte, limiar=0.8)

    [p] = r.decupagem.pessoas
    assert (p.nome, p.estado_do_nome, p.fontes_do_nome) == ("Leão Lobo", "palpite", [])
    assert [v.estado for v in r.vereditos] == ["palpite_nao_confirmado"]


def test_palpite_cuja_escolha_apontou_outro_candidato_e_descartado() -> None:
    c = Cenario()
    # o homem de barba é "Nelson Rubens" pelo palpite; às cegas, é o Leão (A)
    d = decupagem([palpite("pes01", "Nelson Rubens", [(10_000, 40_000)])])
    transporte = TransporteFalso(
        escolha("A"), confianca(0.9), confianca(0.9), confianca(0.9)
    )

    r = rodar(c, d, transporte)

    [p] = r.decupagem.pessoas
    assert (p.nome, p.estado_do_nome) == ("Leão Lobo", "confirmado")
    [v] = r.vereditos
    assert (v.estado, v.palpite, v.nome) == ("confirmado", "Nelson Rubens", "Leão Lobo")
    assert v.palpite_descartado


def test_nenhum_descarta_o_palpite_e_a_pessoa_volta_a_sem_nome() -> None:
    c = Cenario()
    d = decupagem([palpite("pes01", "Nelson Rubens", [(10_000, 40_000)])])
    transporte = TransporteFalso(escolha("nenhum"))

    r = rodar(c, d, transporte)

    [p] = r.decupagem.pessoas
    assert p.nome.startswith("não identificado")
    assert (p.estado_do_nome, p.origem, p.catalogo_id) == (None, "modelo", None)
    [v] = r.vereditos
    assert (v.estado, v.palpite, v.palpite_descartado) == (
        "palpite_descartado",
        "Nelson Rubens",
        True,
    )


def test_palpite_ja_confirmado_para_outra_pessoa_e_descartado() -> None:
    c = Cenario()
    d = decupagem(
        [
            pessoa(
                "pes01",
                "Leão Lobo",
                [(10_000, 40_000)],
                estado_do_nome="confirmado",
                origem="modelo_forte",
                fontes_do_nome=["gc"],
            ),
            palpite("pes02", "Leão Lobo", [(100_000, 130_000)]),
        ]
    )
    transporte = TransporteFalso(escolha("A"), confianca(1), confianca(1), confianca(1))

    r = rodar(c, d, transporte)

    # só o Nelson sobra como opção: o Leão já é de outra pessoa e não vai ao modelo
    imagens = transporte.chamadas[0].imagens
    assert not any(b"Lobo" in im for im in imagens)
    segunda = r.decupagem.pessoas[1]
    assert segunda.nome == "Nelson Rubens"  # A era o Nelson
    assert r.vereditos[0].palpite_descartado


def test_palpite_sem_referencia_continua_palpite_sem_chamar_o_modelo() -> None:
    c = Cenario()
    for p in c.catalogo.todas():
        c.catalogo.definir_rostos(p.id, [])
    d = decupagem([palpite("pes01", "Fulano de Tal", [(10_000, 40_000)])])
    transporte = TransporteFalso()

    r = rodar(c, d, transporte)

    assert transporte.chamadas == []
    [v] = r.vereditos
    assert v.estado == "palpite_nao_confirmado"
    assert r.decupagem.pessoas[0].nome == "Fulano de Tal"


def test_limite_de_pessoas_deixa_o_resto_palpite_nao_confirmado() -> None:
    c = Cenario()
    d = decupagem(
        [
            palpite("pes01", "Leão Lobo", [(10_000, 40_000)]),
            palpite("pes02", "Nelson Rubens", [(50_000, 60_000)]),
        ]
    )
    transporte = TransporteFalso(escolha("nenhum"))

    r = rodar(c, d, transporte, limite_de_pessoas=1)

    assert len(transporte.chamadas) == 1
    assert [v.estado for v in r.vereditos] == [
        "palpite_descartado",
        "palpite_nao_confirmado",
    ]


def test_falha_do_modelo_nao_derruba_o_video() -> None:
    c = Cenario()
    d = decupagem([palpite("pes01", "Leão Lobo", [(10_000, 40_000)])])
    transporte = TransporteFalso(ErroHttp(400))

    r = rodar(c, d, transporte)

    assert r.decupagem.pessoas[0].estado_do_nome == "palpite"
    assert r.vereditos[0].estado == "palpite_nao_confirmado"


def test_cada_chamada_leva_o_rotulo_de_custo() -> None:
    c = Cenario()
    d = decupagem([pessoa("pes01", BARBA, [(10_000, 40_000)], fontes_do_nome=[])])
    transporte = TransporteFalso(escolha("A"), confianca(1), confianca(1), confianca(1))

    rodar(c, d, transporte)

    etapas = [ch.rotulos["etapa"] for ch in transporte.chamadas]
    assert etapas == ["comparacao_escolha"] + ["comparacao_conferencia"] * 3
    assert all(ch.rotulos["job_id"] == "job-1" for ch in transporte.chamadas)


def test_pessoa_da_revisora_e_confirmada_ficam_como_estao() -> None:
    c = Cenario()
    d = decupagem(
        [
            pessoa("pes01", "Alguém", [(10_000, 40_000)], origem="revisao"),
            pessoa(
                "pes02",
                "Leão Lobo",
                [(50_000, 60_000)],
                estado_do_nome="confirmado",
                origem="modelo_forte",
            ),
        ]
    )
    transporte = TransporteFalso()

    r = rodar(c, d, transporte)

    assert transporte.chamadas == [] and r.vereditos == []
    assert r.decupagem == d


def test_nome_confirmado_vira_sugestao_para_o_perfil_so_se_nao_esta_nele() -> None:
    c = Cenario()
    d = decupagem(
        [
            pessoa(
                "pes01",
                "Fulana da Silva",
                [(10_000, 40_000)],
                estado_do_nome="confirmado",
                origem="modelo_forte",
                fontes_do_nome=["gc"],
            ),
            palpite("pes02", "Beltrano", [(50_000, 60_000)]),
        ]
    )
    transporte = TransporteFalso(escolha("nenhum"))

    rodar(c, d, transporte, programa="TV Fama", sugestoes=c.sugestoes)

    assert c.sugestoes.do_programa("TV Fama") == ["Fulana da Silva"]


def test_foto_ausente_tira_o_candidato_das_opcoes() -> None:
    c = Cenario()
    c.fotos.objetos.pop(f"referencias/{c.leao}/0.jpg")
    d = decupagem([pessoa("pes01", BARBA, [(10_000, 40_000)], fontes_do_nome=[])])
    transporte = TransporteFalso(escolha("A"), confianca(1), confianca(1), confianca(1))

    r = rodar(c, d, transporte)

    assert r.decupagem.pessoas[0].nome == "Nelson Rubens"  # só ele ficou


def test_confianca_igual_ao_limiar_confirma() -> None:
    c = Cenario()
    d = decupagem([palpite("pes01", "Leão Lobo", [(10_000, 40_000)])])
    transporte = TransporteFalso(
        escolha("A"), confianca(0.8), confianca(0.8), confianca(0.8)
    )

    r = rodar(c, d, transporte, limiar=0.8)

    assert r.decupagem.pessoas[0].estado_do_nome == "confirmado"


def test_palpite_ja_confirmado_sem_outra_opcao_e_descartado_sem_chamar_o_modelo() -> (
    None
):
    c = Cenario()
    for p in c.catalogo.todas():
        if p.id != c.leao:
            c.catalogo.definir_rostos(p.id, [])
    d = decupagem(
        [
            pessoa(
                "pes01",
                "Leão Lobo",
                [(10_000, 40_000)],
                estado_do_nome="confirmado",
                origem="modelo_forte",
                fontes_do_nome=["gc"],
            ),
            palpite("pes02", "Leão Lobo", [(100_000, 130_000)]),
        ]
    )
    transporte = TransporteFalso()

    r = rodar(c, d, transporte)

    assert transporte.chamadas == []
    segunda = r.decupagem.pessoas[1]
    assert segunda.nome.startswith("não identificado")
    assert segunda.estado_do_nome is None
    [v] = r.vereditos
    assert (v.estado, v.palpite_descartado) == ("palpite_descartado", True)


def test_palpite_nao_confirmado_e_descartado_se_o_nome_se_confirma_depois() -> None:
    c = Cenario()
    # o palpite "Leão" tem mais tempo na imagem e vai primeiro, mas uma foto falha;
    # depois o homem de barba se confirma como o Leão
    d = decupagem(
        [
            palpite("pes01", "Leão Lobo", [(10_000, 90_000)]),
            pessoa("pes02", BARBA, [(100_000, 130_000)], fontes_do_nome=[]),
        ]
    )
    transporte = TransporteFalso(
        escolha("A"),
        confianca(0.9),
        confianca(0.5),
        confianca(0.9),
        escolha("A"),
        confianca(1),
        confianca(1),
        confianca(1),
    )

    r = rodar(c, d, transporte, limiar=0.8)

    primeira, segunda = r.decupagem.pessoas
    assert (segunda.nome, segunda.estado_do_nome) == ("Leão Lobo", "confirmado")
    assert primeira.nome.startswith("não identificado")
    assert [v.estado for v in r.vereditos] == ["palpite_descartado", "confirmado"]
    assert r.vereditos[0].palpite_descartado


def test_palpite_sem_referencia_substituido_por_outro_nome_fica_descartado() -> None:
    c = Cenario()
    d = decupagem([palpite("pes01", "Fulano de Tal", [(10_000, 40_000)])])
    transporte = TransporteFalso(escolha("A"), confianca(1), confianca(1), confianca(1))

    r = rodar(c, d, transporte)

    [v] = r.vereditos
    assert (v.estado, v.nome, v.palpite_descartado) == ("confirmado", "Leão Lobo", True)


def test_mais_de_26_candidatos_ganham_rotulos_de_duas_letras() -> None:
    c = Cenario()
    for i in range(30):
        c.com_fotos(f"Pessoa {i:02d}", "convidado", [])
    d = decupagem([pessoa("pes01", BARBA, [(10_000, 40_000)], fontes_do_nome=[])])
    transporte = TransporteFalso(
        escolha("AF"), confianca(1), confianca(1), confianca(1)
    )

    r = rodar(c, d, transporte)

    # 32 opções: A a Z, AA a AF; a 32ª é a última do catálogo
    assert "- Grupo AF:" in transporte.chamadas[0].instrucao
    assert r.decupagem.pessoas[0].nome == "Pessoa 29"
