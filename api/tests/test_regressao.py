"""Conjunto de regressão (#253): formato, reserva estável, metas e exportação das correções."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api.comparador import TIPOS, Item, itens_do_modelo, ler_gabarito, parear
from api.correcoes import (
    Ancora,
    Correcao,
    Ocorrencia,
    RepositorioDeCorrecoesEmMemoria,
    TipoDoItem,
    versao_do_modelo,
)
from api.decupagem import Decupagem
from api.jobs import Job, RepositorioEmMemoria, ServicoIndisponivel
from api.regressao import (
    PERCENTUAL_RESERVADO,
    Caso,
    caso_do_gabarito,
    casos_das_correcoes,
    exportar,
    gravar_caso,
    ler_casos,
    ler_metas,
    main,
    para_ajuste,
    reservado_pelo_sorteio,
    reservados,
)
from api.tests.test_decupagem import decupagem_valida

SHA = "a" * 64
BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _c(id: str, minuto: int = 0, **campos: Any) -> Correcao:
    base: dict[str, Any] = {
        "id": id,
        "job_id": "j1",
        "autor_uid": "u",
        "autor_email": "u@x",
        "criada_em": BASE + timedelta(minutes=minuto),
        "motivo": "m",
        "tipo": "pessoa.renomear",
        "item_id": "p1",
        "antes": "Ana",
        "depois": "Ana Maria",
        "ancora": Ancora(
            versao="v",
            tipo_do_item="pessoa",
            identidade="ana",
            inicio_ms=1_000,
            fim_ms=5_000,
        ),
    }
    return Correcao(**{**base, **campos})


def test_reserva_e_estavel_e_so_depende_do_id() -> None:
    ids = [f"caso-{n}" for n in range(500)]
    primeira = [reservado_pelo_sorteio(i) for i in ids]
    assert primeira == [reservado_pelo_sorteio(i) for i in reversed(ids)][::-1]
    assert reservado_pelo_sorteio("caso-7") == reservado_pelo_sorteio("caso-7")
    proporcao = sum(primeira) / len(ids)
    assert abs(proporcao - PERCENTUAL_RESERVADO / 100) < 0.08


def test_reservados_e_ajuste_separam_sem_sobra() -> None:
    itens = [Item("pauta", "x", 0, 1_000)]
    casos = [caso_do_gabarito(f"{n:04x}" * 16, itens) for n in range(60)]
    assert {c.id for c in reservados(casos)}.isdisjoint(
        c.id for c in para_ajuste(casos)
    )
    assert len(reservados(casos)) + len(para_ajuste(casos)) == 60
    assert reservados(casos) and para_ajuste(casos)


def test_caso_com_reserva_fora_do_sorteio_e_recusado() -> None:
    caso = caso_do_gabarito(SHA, [Item("pauta", "x", 0, 1_000)])
    dados = caso.model_dump() | {"reservado": not caso.reservado}
    with pytest.raises(ValueError, match="sorteio"):
        Caso.model_validate(dados)


def test_caso_recusa_trecho_invertido_e_tipo_desconhecido() -> None:
    caso = caso_do_gabarito(SHA, [Item("pauta", "x", 0, 1_000)])
    with pytest.raises(ValueError):
        Caso.model_validate(caso.model_dump() | {"inicio_ms": 5_000, "fim_ms": 1})
    dados = caso.model_dump()
    dados["esperado"][0]["tipo"] = "cheiro"
    with pytest.raises(ValueError):
        Caso.model_validate(dados)


def test_caso_vai_e_volta_do_arquivo(tmp_path: Path) -> None:
    caso = caso_do_gabarito(SHA, [Item("aparicao", "Ana", 0, 2_000)], 0, 10_000)
    gravar_caso(tmp_path, caso)
    assert ler_casos(tmp_path) == [caso]
    assert caso.itens() == [Item("aparicao", "Ana", 0, 2_000)]


def test_ler_casos_diz_qual_arquivo_esta_ruim(tmp_path: Path) -> None:
    (tmp_path / "ruim.json").write_text("{}")
    with pytest.raises(ValueError, match="ruim.json"):
        ler_casos(tmp_path)


def test_formato_cobre_todas_as_categorias_da_decupagem() -> None:
    d = Decupagem.model_validate(
        decupagem_valida()
        | {
            "transcricao": [
                {"inicio_ms": 0, "fim_ms": 1_000, "locutor": "Ana", "texto": "oi"}
            ],
            "textos_na_tela": [
                {"inicio_ms": 0, "fim_ms": 1_000, "tipo": "gc", "texto": "ANA"}
            ],
        }
    )
    tipos = {i.tipo for i in itens_do_modelo(d)}
    assert {"plano", "fala", "texto_na_tela", "pauta", "comercial"} <= tipos
    assert {"aparicao", "mencao"} <= tipos
    gabarito = [Item("texto_na_tela", "ana", 0, 1_000), Item("plano", "x", 0, 4_000)]
    pareados, sem_par = parear(gabarito, itens_do_modelo(d))
    assert len(pareados) == 2 and not sem_par


def test_gabarito_csv_aceita_os_tipos_novos(tmp_path: Path) -> None:
    arq = tmp_path / "c.csv"
    arq.write_text(
        f"# sha256: {SHA}\ntipo,identidade,inicio,fim\nfala,Ana,00:01,00:02\n"
    )
    assert ler_gabarito(arq)[1] == [Item("fala", "Ana", 1_000, 2_000)]
    assert set(TIPOS) >= {"aparicao", "mencao", "pauta", "comercial"}


def test_metas_validas_e_invalidas(tmp_path: Path) -> None:
    arq = tmp_path / "metas.json"
    arq.write_text('{"aparicao": 0.95, "pauta": 1}')
    assert ler_metas(arq) == {"aparicao": 0.95, "pauta": 1.0}
    for ruim in ['{"a": 1.5}', '{"a": "x"}', '{"a": true}', "[]", '{"": 0.5}']:
        arq.write_text(ruim)
        with pytest.raises((ValueError, TypeError)):
            ler_metas(arq)


def test_o_arquivo_de_metas_do_repositorio_le() -> None:
    assert isinstance(ler_metas(), dict)


MODELO: dict[str, Any] = {
    "video": {"sha256": SHA},
    "versao_pipeline": "2026.11.1",
    "pessoas": [
        {
            "id": "p1",
            "nome": "Ana",
            "na_imagem": [
                {"inicio_ms": 1_000, "fim_ms": 2_000},
                {"inicio_ms": 4_000, "fim_ms": 5_000},
            ],
            "citada_na_fala": [{"inicio_ms": 20_000, "fim_ms": 21_000}],
        }
    ],
}


def _ancora(item: TipoDoItem, identidade: str = "x", fim_ms: int = 900) -> Ancora:
    return Ancora(
        versao="v",
        tipo_do_item=item,
        identidade=identidade,
        inicio_ms=0,
        fim_ms=fim_ms,
    )


def test_correcao_de_nome_vira_caso_com_job_trecho_e_versao() -> None:
    [caso] = casos_das_correcoes(MODELO, "v", [_c("c1")])
    assert caso.origem == "correcao"
    assert caso.job_id == "j1" and caso.versao_pipeline == "2026.11.1"
    assert caso.sha256 == SHA
    assert (caso.inicio_ms, caso.fim_ms) == (1_000, 5_000)
    # Uma aparição esperada por aparição da pessoa, com o nome novo.
    assert caso.itens() == [
        Item("aparicao", "Ana Maria", 1_000, 2_000),
        Item("aparicao", "Ana Maria", 4_000, 5_000),
    ]
    assert caso.correcao
    assert (caso.correcao.antes, caso.correcao.depois) == ("Ana", "Ana Maria")
    assert caso.reservado == reservado_pelo_sorteio(caso.id)


def test_correcao_de_tempos_usa_os_tempos_novos_e_cobre_os_dois() -> None:
    c = _c(
        "c2",
        tipo="item.tempos",
        antes="1000-5000",
        depois="2000-9000",
        ancora=Ancora(
            versao="v",
            tipo_do_item="pauta",
            identidade="chuva",
            inicio_ms=1_000,
            fim_ms=5_000,
        ),
    )
    [caso] = casos_das_correcoes(MODELO | {"versao_pipeline": None}, "v", [c])
    assert caso.itens() == [Item("pauta", "chuva", 2_000, 9_000)]
    assert (caso.inicio_ms, caso.fim_ms) == (1_000, 9_000)
    assert caso.versao_pipeline is None


def test_so_correcao_em_vigor_entra() -> None:
    correcoes = [
        _c("desfeita"),
        _c("d", 1, tipo="desfazer", desfaz="desfeita"),
        _c("pendente", exige_aprovacao=True),
        _c("recusada", exige_aprovacao=True),
        _c("aprovada", exige_aprovacao=True),
        _c("r", 2, tipo="recusar", recusa="recusada"),
        _c("a", 2, tipo="aprovar", aprova="aprovada"),
        _c("nao-e", tipo="pessoa.nao_e"),
    ]
    ids = {
        c.correcao.id for c in casos_das_correcoes(MODELO, "v", correcoes) if c.correcao
    }
    assert ids == {"aprovada"}


def test_correcao_de_outro_json_do_modelo_fica_de_fora() -> None:
    """Depois de um reprocessamento, o trecho e a versão que errou não são os deste JSON."""
    assert casos_das_correcoes(MODELO, "outra", [_c("c1")]) == []


def test_correcao_de_outras_categorias_mapeia_o_tipo_e_a_identidade() -> None:
    correcoes = [
        _c("m", tipo="comercial.marca", depois="Nova", ancora=_ancora("comercial")),
        _c(
            "ct",
            tipo="comercial.tipo",
            item_id="c9",
            depois="varejo",
            ancora=_ancora("comercial", "coca cola|merchandising"),
        ),
        _c(
            "t",
            tipo="texto_na_tela.texto",
            depois=json.dumps({"texto": "GC", "tipo": "gc"}),
            ancora=_ancora("texto_na_tela"),
        ),
        _c("f", tipo="fala.texto", depois="oi", ancora=_ancora("fala")),
        _c("p", tipo="plano.limpo", ancora=_ancora("plano")),
    ]
    por_id = {
        c.correcao.id: c.itens()
        for c in casos_das_correcoes(MODELO, "v", correcoes)
        if c.correcao
    }
    assert por_id == {
        "m": [Item("comercial", "Nova", 0, 900)],
        "ct": [Item("comercial", "coca cola", 0, 900)],
        "t": [Item("texto_na_tela", "GC", 0, 900)],
        "f": [Item("fala", "x", 0, 900)],
        "p": [Item("plano", "x", 0, 900)],
    }


def test_correcao_de_ocorrencia_mede_so_a_ocorrencia() -> None:
    ancora = _ancora("pessoa", "ana", 21_000)
    na_fala = Ocorrencia(lista="citada_na_fala", inicio_ms=20_000, fim_ms=21_000)
    na_imagem = Ocorrencia(lista="na_imagem", inicio_ms=4_000, fim_ms=5_000)
    correcoes = [
        _c(
            "men",
            tipo="pessoa.aparicao_para_mencao",
            ocorrencia=na_imagem,
            ancora=ancora,
        ),
        _c(
            "apa", tipo="pessoa.mencao_para_aparicao", ocorrencia=na_fala, ancora=ancora
        ),
        _c(
            "tem",
            tipo="item.tempos",
            depois="20500-22000",
            ocorrencia=na_fala,
            ancora=ancora,
        ),
        _c(
            "nova",
            tipo="pessoa.acrescentar_aparicao",
            depois=json.dumps(
                {"inicio_ms": 30_000, "fim_ms": 31_000, "evidencia": "rosto"}
            ),
            ancora=ancora,
        ),
    ]
    por_id = {
        c.correcao.id: c.itens()
        for c in casos_das_correcoes(MODELO, "v", correcoes)
        if c.correcao
    }
    assert por_id == {
        "men": [Item("mencao", "ana", 4_000, 5_000)],
        "apa": [Item("aparicao", "ana", 20_000, 21_000)],
        "tem": [Item("mencao", "ana", 20_500, 22_000)],
        "nova": [Item("aparicao", "ana", 30_000, 31_000)],
    }


def test_correcoes_do_mesmo_item_esperam_o_mesmo_nome() -> None:
    tempos = _c(
        "tem",
        1,
        tipo="item.tempos",
        depois="1500-2000",
        ocorrencia=Ocorrencia(lista="na_imagem", inicio_ms=1_000, fim_ms=2_000),
    )
    [_, caso] = casos_das_correcoes(MODELO, "v", [_c("ren"), tempos])
    assert caso.itens() == [Item("aparicao", "Ana Maria", 1_500, 2_000)]


def test_pessoa_sem_nome_nao_vira_caso() -> None:
    """O comparador não pareia "não identificado": o caso nunca mediria nada."""
    ancora = _ancora("pessoa", "nao identificado@1000-5000")
    c = _c("t", tipo="pessoa.fontes_do_nome", depois='["gc"]', ancora=ancora)
    assert casos_das_correcoes(MODELO, "v", [c]) == []
    renomeada = _c("r", ancora=ancora)
    [caso] = casos_das_correcoes(MODELO, "v", [renomeada])
    assert {i.identidade for i in caso.itens()} == {"Ana Maria"}


def test_correcao_com_tempos_ilegiveis_fica_de_fora() -> None:
    c = _c("c", tipo="item.tempos", depois="lixo", ancora=_ancora("pauta"))
    assert casos_das_correcoes(MODELO, "v", [c]) == []


class Decupagens:
    def __init__(self, dados: dict[str, dict[str, Any]]) -> None:
        self._dados = dados

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        if job_id not in self._dados:
            raise ServicoIndisponivel
        yield _bytes(self._dados[job_id])


def _job(id: str, estado: str = "concluido") -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        estado=estado,  # type: ignore[arg-type]
        criado_por="u1",
        criado_em=BASE,
        atualizado_em=BASE,
        etapas={},
    )


def _bytes(dados: dict[str, Any]) -> bytes:
    return json.dumps(dados).encode()


def test_exportar_grava_um_arquivo_por_caso_e_e_idempotente(tmp_path: Path) -> None:
    jobs = RepositorioEmMemoria()
    for j in ("j1", "j2", "j3", "j4", "j5"):
        jobs.salvar(_job(j, "falhou" if j == "j3" else "concluido"))
    dados = {
        "j1": MODELO,
        "j2": MODELO | {"versao_pipeline": None},
        "j5": MODELO | {"video": {"sha256": "NAO-E-SHA"}},
    }  # j4 sem decupagem legível; j3 não concluído; j5 com sha ruim
    correcoes = RepositorioDeCorrecoesEmMemoria()
    for job in ("j1", "j2", "j3", "j4", "j5"):
        versao = versao_do_modelo(_bytes(dados.get(job, MODELO)))
        ancora = _ancora("pessoa", "ana", 5_000).model_copy(update={"versao": versao})
        correcoes.acrescentar(_c(f"{job}-c", job_id=job, ancora=ancora))
    decupagens = Decupagens(dados)
    saida: list[str] = []
    gravados = exportar(jobs, decupagens, correcoes, tmp_path, saida.append)
    assert {c.job_id for c in gravados} == {"j1", "j2"}
    por_job = {c.job_id: c.versao_pipeline for c in gravados}
    assert por_job == {"j1": "2026.11.1", "j2": None}
    assert "2 casos gravados" in saida[0]
    antes = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    exportar(jobs, decupagens, correcoes, tmp_path, saida.append)
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == antes
    assert len(ler_casos(tmp_path)) == 2
    # Desfeita a correção, o caso dela sai da pasta.
    correcoes.acrescentar(_c("d", 5, job_id="j1", tipo="desfazer", desfaz="j1-c"))
    exportar(jobs, decupagens, correcoes, tmp_path, saida.append)
    assert [c.job_id for c in ler_casos(tmp_path)] == ["j2"]


def test_comando_sem_ambiente_sai_com_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], {}) == 2
    assert "erro:" in capsys.readouterr().err
