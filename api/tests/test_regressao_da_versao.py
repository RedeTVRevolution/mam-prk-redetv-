"""Regressão de uma versão do pipeline (#254): transporte falso, sem nuvem."""

import json
from pathlib import Path

from api.comparador import Item
from api.regressao import (
    Caso,
    caso_do_gabarito,
    gravar_caso,
    reservado_pelo_sorteio,
)
from api.regressao_da_versao import (
    avaliar,
    custo_estimado,
    main,
    relatorio_em_json,
    relatorio_em_markdown,
    selecionar,
)

APROVADA = "2026.11.1"
NOVA = "2026.12.0"


def _sha(n: int) -> str:
    return f"{n:x}".ljust(64, "0")


def _caso(n: int, itens: list[Item], reservado: bool = False) -> Caso:
    """Um caso anotado do lado do sorteio pedido."""
    while reservado_pelo_sorteio(f"anotado-{_sha(n)[:12]}-0-60000") != reservado:
        n += 1000
    return caso_do_gabarito(_sha(n), itens, 0, 60_000)


class Falso:
    """Transporte: o que cada versão devolveu para cada caso."""

    def __init__(self, por_versao: dict[str, dict[str, list[Item]]]) -> None:
        self.por_versao = por_versao
        self.chamadas: list[tuple[str, str]] = []

    def itens(self, versao: str, caso: Caso) -> list[Item]:
        self.chamadas.append((versao, caso.id))
        return self.por_versao[versao][caso.id]


ANA = Item("aparicao", "Ana", 1_000, 5_000)
BIA = Item("aparicao", "Bia", 10_000, 15_000)
PAUTA = Item("pauta", "Economia", 20_000, 40_000)


def _tres_casos() -> tuple[list[Caso], Falso]:
    melhora = _caso(1, [ANA])
    piora = _caso(2, [BIA])
    igual = _caso(3, [PAUTA])
    aprovada = {
        melhora.id: [],
        piora.id: [BIA],
        igual.id: [PAUTA],
    }
    nova = {
        melhora.id: [ANA],
        piora.id: [Item("aparicao", "Bia", 30_000, 35_000)],
        igual.id: [PAUTA],
    }
    return [melhora, piora, igual], Falso({APROVADA: aprovada, NOVA: nova})


def test_caso_a_caso_melhorou_piorou_ou_ficou_igual() -> None:
    casos, transporte = _tres_casos()
    r = avaliar(transporte, casos, NOVA, APROVADA, {})
    veredito = {c.caso_id: c.requisitos for c in r.casos}
    assert veredito[casos[0].id]["famosos"].veredito == "melhorou"
    assert veredito[casos[1].id]["famosos"].veredito == "piorou"
    assert veredito[casos[2].id]["pautas"].veredito == "igual"
    famosos = r.requisitos["famosos"]
    assert (famosos.melhoraram, famosos.pioraram, famosos.iguais) == (1, 1, 0)
    assert (famosos.total, famosos.acertos_nova, famosos.acertos_aprovada) == (2, 1, 1)


def test_meta_nao_atingida_da_saida_diferente_de_zero(tmp_path: Path) -> None:
    casos, transporte = _tres_casos()
    pasta = tmp_path / "casos"
    for c in casos:
        gravar_caso(pasta, c)
    metas = tmp_path / "metas.json"
    metas.write_text(json.dumps({"famosos": 0.9, "pautas": 1.0}))
    r = avaliar(transporte, casos, NOVA, APROVADA, {"famosos": 0.9, "pautas": 1.0})
    assert r.requisitos["famosos"].atingida is False
    assert r.requisitos["pautas"].atingida is True
    assert r.passou is False
    saida = tmp_path / "saida"
    codigo = main(
        [NOVA, "", str(saida)],
        {"CASOS": str(pasta), "METAS": str(metas), "CONFIRMAR": "1"},
        transporte=transporte,
        versao_aprovada=APROVADA,
    )
    assert codigo == 1
    assert (saida / f"regressao-{NOVA}.md").exists()
    dados = json.loads((saida / f"regressao-{NOVA}.json").read_text())
    assert dados["passou"] is False


def _ambiente(tmp_path: Path, casos: list[Caso], metas: str) -> dict[str, str]:
    pasta = tmp_path / "casos"
    for c in casos:
        gravar_caso(pasta, c)
    arquivo = tmp_path / "metas.json"
    arquivo.write_text(metas)
    return {"CASOS": str(pasta), "METAS": str(arquivo), "CONFIRMAR": "1"}


def test_meta_atingida_sai_com_zero(tmp_path: Path) -> None:
    casos, transporte = _tres_casos()
    ambiente = _ambiente(tmp_path, casos[2:], '{"pautas": 1.0}')
    assert main([NOVA, "", str(tmp_path / "s")], ambiente, transporte, APROVADA) == 0


def test_meta_de_requisito_desconhecido_e_entrada_invalida(tmp_path: Path) -> None:
    casos, transporte = _tres_casos()
    ambiente = _ambiente(tmp_path, casos, '{"broll": 0.9}')
    assert main([NOVA, "", str(tmp_path / "s")], ambiente, transporte, APROVADA) == 2
    assert not (tmp_path / "s").exists()


def test_metas_fora_do_formato_sao_entrada_invalida(tmp_path: Path) -> None:
    casos, transporte = _tres_casos()
    ambiente = _ambiente(tmp_path, casos, "[]")
    assert main([NOVA, "", str(tmp_path / "s")], ambiente, transporte, APROVADA) == 2


def test_versao_igual_a_aprovada_e_entrada_invalida(tmp_path: Path) -> None:
    casos, transporte = _tres_casos()
    ambiente = _ambiente(tmp_path, casos, "{}")
    assert main([NOVA, "", str(tmp_path / "s")], ambiente, transporte, NOVA) == 2
    assert transporte.chamadas == []


def test_sem_decupagens_e_entrada_invalida(tmp_path: Path) -> None:
    casos, _ = _tres_casos()
    ambiente = _ambiente(tmp_path, casos, "{}")
    assert main([NOVA, "", str(tmp_path / "s")], ambiente, None, APROVADA) == 2


def test_reservados_so_entram_com_o_pedido() -> None:
    ajuste = _caso(1, [ANA])
    reservado = _caso(2, [BIA], reservado=True)
    assert [c.id for c in selecionar([ajuste, reservado], False)] == [ajuste.id]
    assert [c.id for c in selecionar([ajuste, reservado], True)] == [reservado.id]


def test_reservados_pelo_comando(tmp_path: Path) -> None:
    ajuste = _caso(1, [ANA])
    reservado = _caso(2, [BIA], reservado=True)
    pasta = tmp_path / "casos"
    for c in (ajuste, reservado):
        gravar_caso(pasta, c)
    metas = tmp_path / "metas.json"
    metas.write_text("{}")
    transporte = Falso(
        {
            APROVADA: {ajuste.id: [ANA], reservado.id: [BIA]},
            NOVA: {ajuste.id: [ANA], reservado.id: [BIA]},
        }
    )
    ambiente = {"CASOS": str(pasta), "METAS": str(metas), "CONFIRMAR": "1"}
    main([NOVA, "", str(tmp_path / "a")], ambiente, transporte, APROVADA)
    assert {i for _, i in transporte.chamadas} == {ajuste.id}
    transporte.chamadas.clear()
    main([NOVA, "1", str(tmp_path / "b")], ambiente, transporte, APROVADA)
    assert {i for _, i in transporte.chamadas} == {reservado.id}


def test_sem_confirmar_so_estima_o_custo(tmp_path: Path) -> None:
    casos, transporte = _tres_casos()
    pasta = tmp_path / "casos"
    for c in casos:
        gravar_caso(pasta, c)
    metas = tmp_path / "metas.json"
    metas.write_text("{}")
    ambiente = {
        "CASOS": str(pasta),
        "METAS": str(metas),
        "CUSTO_POR_HORA_USD": "0.28",
    }
    saidas: list[str] = []
    codigo = main(
        [NOVA, "", str(tmp_path / "s")],
        ambiente,
        transporte,
        APROVADA,
        escrever=saidas.append,
    )
    assert codigo == 0
    assert transporte.chamadas == []
    assert "CONFIRMAR=1" in "\n".join(saidas)
    # 3 trechos de 60 s: 0,05 h a US$ 0,28 por hora.
    assert custo_estimado(casos, 0.28) == 0.28 * 180 / 3600


def test_relatorios_dizem_o_que_mudou() -> None:
    casos, transporte = _tres_casos()
    r = avaliar(transporte, casos, NOVA, APROVADA, {"famosos": 0.9})
    md = relatorio_em_markdown(r)
    assert "melhorou" in md and "piorou" in md and "abaixo da meta" in md
    assert json.loads(relatorio_em_json(r))["requisitos"]["famosos"]["meta"] == 0.9
