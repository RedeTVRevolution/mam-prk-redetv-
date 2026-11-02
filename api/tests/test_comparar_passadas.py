"""Comparação do Job com a passada (#248), com decupagens montadas à mão."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api.comparador import TOLERANCIA_MS
from api.comparar_objetos import FaltaNoAmbiente, Preco
from api.comparar_passadas import (
    Custo,
    LadoDoResultado,
    PrecoUsado,
    Tempo,
    comparar,
    comparar_decupagens,
    custo_do_job,
    custo_por_hora,
    gravar,
    relatorio_em_json,
    relatorio_em_markdown,
    somar,
    tempo_do_job,
    tokens_do_job,
)
from api.decupagem import Decupagem
from api.jobs import Etapa, Job, RepositorioEmMemoria
from api.passadas import Custo as CustoDaPassada
from api.passadas import Etapa as EtapaDaPassada
from api.passadas import Passada, PassadasEmMemoria

SHA = "a" * 64
BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
FORA = TOLERANCIA_MS + 1000
LADO = LadoDoResultado(None, Tempo({}, 0.0))


def _pessoa(nome: str, ini: int, fim: int, mencao: bool = False) -> dict[str, Any]:
    return {
        "id": f"p-{nome}-{ini}",
        "nome": nome,
        "na_imagem": []
        if mencao
        else [{"inicio_ms": ini, "fim_ms": fim, "evidencia": "r"}],
        "citada_na_fala": [{"inicio_ms": ini, "fim_ms": fim}] if mencao else [],
        "citada_no_texto": [],
    }


def _pauta(titulo: str, ini: int, fim: int) -> dict[str, Any]:
    return {
        "id": f"t{ini}",
        "titulo": titulo,
        "resumo": "r",
        "inicio_ms": ini,
        "fim_ms": fim,
    }


def _comercial(
    marca: str, ini: int, fim: int, tipo: str = "intervalo"
) -> dict[str, Any]:
    return {
        "marca": marca,
        "tipo": tipo,
        "inicio_ms": ini,
        "fim_ms": fim,
        "evidencias": ["fala"],
    }


def _plano(ambiente: str, ini: int, fim: int, limpo: bool = True) -> dict[str, Any]:
    return {
        "id": f"pl{ini}",
        "ambiente": ambiente,
        "plano_limpo": limpo,
        "inicio_ms": ini,
        "fim_ms": fim,
    }


def _decupagem(**partes: list[dict[str, Any]]) -> Decupagem:
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.4",
            "video": {"sha256": SHA, "duracao_ms": 3_600_000},
            "programa": {"resumo": "r", "blocos": []},
            "pautas": partes.get("pautas", []),
            "pessoas": partes.get("pessoas", []),
            "planos": partes.get("planos", []),
            "comerciais": partes.get("comerciais", []),
            "transcricao": [],
        }
    )


# Em cada requisito: um item só do Job (A), um só da passada (B), um com nome trocado,
# um com o tempo fora da tolerância e um igual.
def _par() -> tuple[Decupagem, Decupagem]:
    a = _decupagem(
        pessoas=[
            _pessoa("Ana", 0, 10_000),  # igual
            _pessoa("Bia", 20_000, 30_000),  # tempo fora
            _pessoa("Caio", 40_000, 50_000),  # nome trocado
            _pessoa("Duda", 60_000, 70_000),  # só no Job
            _pessoa("não identificado, de blusa", 5_000, 6_000),  # não é famoso
            _pessoa("Ana", 100_000, 110_000, mencao=True),  # menção igual
            _pessoa("Bia", 120_000, 130_000, mencao=True),  # menção, tempo fora
            _pessoa("Caio", 140_000, 150_000, mencao=True),  # menção, nome trocado
            _pessoa("Duda", 160_000, 170_000, mencao=True),  # só no Job
        ],
        pautas=[
            _pauta("Chuva", 0, 10_000),
            _pauta("Trânsito", 20_000, 30_000),
            _pauta("Esporte", 40_000, 50_000),
            _pauta("Clima", 60_000, 70_000),
        ],
        comerciais=[
            _comercial("Marca A", 0, 10_000),
            _comercial("Marca B", 20_000, 30_000),
            _comercial("Marca C", 40_000, 50_000),
            _comercial("Marca D", 60_000, 70_000),
            _comercial("Marca E", 80_000, 90_000, tipo="testemunhal"),
        ],
        planos=[
            _plano("estúdio", 0, 10_000),
            _plano("rua", 20_000, 30_000),
            _plano("praia", 40_000, 50_000),
            _plano("aeroporto", 60_000, 70_000),
        ],
    )
    b = _decupagem(
        pessoas=[
            _pessoa("ANA", 0, 10_500),
            _pessoa("Bia", 20_000 + FORA, 30_000 + FORA),
            _pessoa("Caique", 40_000, 50_000),
            _pessoa("Eva", 200_000, 210_000),  # só na passada
            _pessoa("Ana", 100_000, 110_000, mencao=True),
            _pessoa("Bia", 120_000 + FORA, 130_000 + FORA, mencao=True),
            _pessoa("Caique", 140_000, 150_000, mencao=True),
            _pessoa("Eva", 220_000, 230_000, mencao=True),
        ],
        pautas=[
            _pauta("Chuva", 0, 10_000),
            _pauta("Trânsito", 20_000 + FORA, 30_000 + FORA),
            _pauta("Futebol", 40_000, 50_000),
            _pauta("Política", 300_000, 310_000),
        ],
        comerciais=[
            _comercial("Marca A", 0, 10_000),
            _comercial("Marca B", 20_000 + FORA, 30_000 + FORA),
            _comercial("Marca Z", 40_000, 50_000),
            _comercial("Marca Y", 300_000, 310_000),
            _comercial("Marca E", 80_000, 90_000, tipo="produto_em_cena"),
        ],
        planos=[
            _plano("estúdio", 0, 10_000),
            _plano("rua", 20_000 + FORA, 30_000 + FORA),
            _plano("jardim", 40_000, 50_000, limpo=False),
            _plano("garagem", 300_000, 310_000),
        ],
    )
    return a, b


def _comparar() -> Any:
    a, b = _par()
    return comparar_decupagens("j1", 3_600_000, a, b, LADO, LADO)


def _nomes(entradas: Any) -> set[str]:
    return {e.identidade for e in entradas}


def test_famosos() -> None:
    q = _comparar().requisitos["famosos"]
    assert (q.contagem_a, q.contagem_b) == (4, 4)  # o "não identificado" fica de fora
    assert q.iguais == 1  # Ana, com o fim 500 ms depois e o nome em outra caixa
    assert _nomes(q.so_em_a) == {"Duda"} and _nomes(q.so_em_b) == {"Eva"}
    por_motivo = {
        tuple(d.motivos): (d.a.identidade, d.b.identidade) for d in q.diferentes
    }
    assert por_motivo == {("tempo",): ("Bia", "Bia"), ("nome",): ("Caio", "Caique")}


def test_mencoes() -> None:
    q = _comparar().requisitos["mencoes"]
    assert (q.contagem_a, q.contagem_b, q.iguais) == (4, 4, 1)
    assert _nomes(q.so_em_a) == {"Duda"} and _nomes(q.so_em_b) == {"Eva"}
    assert sorted(d.motivos[0] for d in q.diferentes) == ["nome", "tempo"]


def test_pautas() -> None:
    q = _comparar().requisitos["pautas"]
    assert (q.contagem_a, q.contagem_b, q.iguais) == (4, 4, 1)
    assert _nomes(q.so_em_a) == {"Clima"} and _nomes(q.so_em_b) == {"Política"}
    por_motivo = {tuple(d.motivos): d.a.identidade for d in q.diferentes}
    assert por_motivo == {("tempo",): "Trânsito", ("nome",): "Esporte"}


def test_comerciais_com_marca_trocada_tipo_e_tempo() -> None:
    q = _comparar().requisitos["comerciais"]
    assert (q.contagem_a, q.contagem_b, q.iguais) == (5, 5, 1)
    assert _nomes(q.so_em_a) == {"Marca D"} and _nomes(q.so_em_b) == {"Marca Y"}
    por_motivo = {tuple(d.motivos): d for d in q.diferentes}
    assert set(por_motivo) == {("tempo",), ("nome",), ("tipo",)}
    tipo = por_motivo[("tipo",)]
    assert (tipo.a.detalhe, tipo.b.detalhe) == ("testemunhal", "produto_em_cena")
    assert (por_motivo[("nome",)].a.identidade, por_motivo[("nome",)].b.identidade) == (
        "Marca C",
        "Marca Z",
    )


def test_broll_limpos_e_descricoes() -> None:
    r = _comparar().requisitos
    limpos = r["broll_limpos"]
    assert (limpos.contagem_a, limpos.contagem_b) == (4, 3)
    assert _nomes(limpos.so_em_a) == {
        "praia",
        "aeroporto",
    }  # a praia virou plano não limpo
    assert _nomes(limpos.so_em_b) == {"garagem"}
    assert [d.motivos for d in limpos.diferentes] == [["tempo"]]
    assert limpos.iguais == 1
    descricoes = r["broll_descricoes"]
    assert (descricoes.contagem_a, descricoes.contagem_b, descricoes.iguais) == (
        4,
        4,
        1,
    )
    por_motivo = {tuple(d.motivos): d.a.identidade for d in descricoes.diferentes}
    assert por_motivo == {
        ("tempo",): "rua",
        ("descricao", "plano_limpo"): "praia",
    }
    assert _nomes(descricoes.so_em_a) == {"aeroporto"}


def test_timecode_dos_itens_pareados() -> None:
    t = _comparar().timecode
    # Pareados, com os de nome trocado: famosos 3, menções 3, pautas 3, comerciais 4,
    # planos 3 (os trechos que se cruzam).
    assert t.pares == 3 + 3 + 3 + 4 + 3
    assert t.fora_da_tolerancia == 5
    assert t.p95_ms == FORA
    assert t.media_ms is not None and t.media_ms > 0


def test_timecode_conferido_a_mao() -> None:
    a = _decupagem(pautas=[_pauta("X", 0, 10_000), _pauta("Y", 20_000, 30_000)])
    b = _decupagem(pautas=[_pauta("X", 1_000, 11_000), _pauta("Y", 20_000, 35_000)])
    t = comparar_decupagens("j", 3_600_000, a, b, LADO, LADO).timecode
    assert t.pares == 2
    assert t.fora_da_tolerancia == 1  # Y: 5 s no fim
    assert t.media_ms == (1000 + 1000 + 0 + 5000) / 4
    assert t.p95_ms == 5000


def test_duas_do_job_dentro_de_uma_da_passada_nao_derrubam() -> None:
    # O `parear` deixa as duas pautas do Job com a mesma da passada: só a primeira fica.
    a = _decupagem(
        pautas=[_pauta("X", 0, 10_000), _pauta("Y", 10_000, 20_000)],
        pessoas=[_pessoa("Ana", 0, 10_000), _pessoa("Ana", 5_000, 15_000)],
    )
    b = _decupagem(
        pautas=[_pauta("XY", 0, 20_000)], pessoas=[_pessoa("Ana", 0, 15_000)]
    )
    r = comparar_decupagens("j", 3_600_000, a, b, LADO, LADO)
    pautas = r.requisitos["pautas"]
    assert [(d.a.identidade, d.b.identidade) for d in pautas.diferentes] == [
        ("X", "XY")
    ]
    assert _nomes(pautas.so_em_a) == {"Y"} and not pautas.so_em_b
    famosos = r.requisitos["famosos"]
    assert len(famosos.diferentes) + famosos.iguais == 1
    assert len(famosos.so_em_a) == 1 and not famosos.so_em_b
    assert r.timecode.pares == 2


def test_sem_pares_o_timecode_fica_vazio() -> None:
    t = comparar_decupagens("j", 1, _decupagem(), _decupagem(), LADO, LADO).timecode
    assert (t.pares, t.media_ms, t.p95_ms, t.fora_da_tolerancia) == (0, None, None, 0)


def test_o_pareamento_e_o_do_comparador(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import comparador
    from api import comparar_passadas as modulo

    chamadas: list[int] = []
    original = comparador.parear

    def espia(g: Any, m: Any) -> Any:
        chamadas.append(1)
        return original(g, m)

    monkeypatch.setattr(modulo, "parear", espia)
    _comparar()
    assert chamadas


# --- custo e tempo ---------------------------------------------------------


def test_custo_por_hora_e_preco_na_configuracao() -> None:
    custo = custo_do_job((2_000_000, 500_000), "gemini-3.5-flash-lite", Preco(0.5, 2.0))
    assert custo == Custo(
        2_000_000, 500_000, 2.0, [PrecoUsado("gemini-3.5-flash-lite", 0.5, 2.0)]
    )
    assert custo_por_hora(custo, 1_800_000) == 4.0  # meia hora
    assert custo_por_hora(None, 1_800_000) is None
    assert custo_do_job(None, "m", Preco(1, 1)) is None


def test_tokens_do_job() -> None:
    assert tokens_do_job("j1=10:2, j2=3:4") == {"j1": (10, 2), "j2": (3, 4)}
    assert tokens_do_job("") == {}
    with pytest.raises(FaltaNoAmbiente):
        tokens_do_job("j1=dez")


def _job(job_id: str = "j1", duracao_s: float = 1800.0) -> Job:
    def etapa(ini: int, fim: int | None) -> Etapa:
        return Etapa(
            inicio=BASE + timedelta(seconds=ini),
            fim=BASE + timedelta(seconds=fim) if fim else None,
            resultado="concluida" if fim else None,
        )

    return Job(
        id=job_id,
        nome="a.mp4",
        tamanho_bytes=1,
        sha256=SHA,
        duracao_s=duracao_s,
        estado="concluido",
        criado_por="u",
        etapas={
            "transcricao": etapa(0, 60),
            "leitura_da_tela": etapa(0, 90),
            "analise": etapa(90, 150),
            "indexacao": etapa(150, None),
        },
        criado_em=BASE,
        atualizado_em=BASE,
    )


def test_tempo_do_job_por_etapa_e_total() -> None:
    t = tempo_do_job(_job())
    assert t.etapas == {"transcricao": 60.0, "leitura_da_tela": 90.0, "analise": 60.0}
    assert t.total_s == 150.0  # a transcrição e a leitura rodam juntas


def _passada(job_id: str, decupagem: Decupagem, modelo: str, dia: int) -> Passada:
    criada = BASE + timedelta(days=dia)
    return Passada(
        id=f"{criada:%Y%m%dT%H%M%S}-{modelo}",
        job_id=job_id,
        modelo=modelo,
        criada_em=criada,
        custo=CustoDaPassada(
            tokens_de_entrada=1_000_000,
            tokens_de_saida=100_000,
            preco_por_milhao_de_entrada=1.0,
            preco_por_milhao_de_saida=4.0,
            usd=1.4,
        ),
        etapas=[
            EtapaDaPassada(nome="janelas", segundos=30.0),
            EtapaDaPassada(nome="consolidacao", segundos=10.0),
        ],
        decupagem=decupagem,
    )


def _montar(
    job_ids: list[str],
) -> tuple[RepositorioEmMemoria, PassadasEmMemoria, dict[str, Decupagem]]:
    a, b = _par()
    repositorio, passadas, decupagens = RepositorioEmMemoria(), PassadasEmMemoria(), {}
    for j in job_ids:
        repositorio.salvar(_job(j))
        decupagens[j] = a
        passadas.gravar_passada(_passada(j, b, "modelo-velho", 0))
        passadas.gravar_passada(_passada(j, b, "modelo-novo", 1))
    return repositorio, passadas, decupagens


def _relatorio(
    job_ids: list[str], passada: str | None = None, modelo: str | None = None
) -> Any:
    repositorio, passadas, decupagens = _montar(job_ids)
    return comparar(
        job_ids,
        passada_id=passada,
        modelo=modelo,
        repositorio=repositorio,
        ler_decupagem=decupagens.get,
        passadas=passadas,
        custo_do_job_por_id=lambda _j: custo_do_job(
            (1_000_000, 100_000), "gemini-base", Preco(0.5, 2.0)
        ),
        tabela_de_precos_em="2026-10-30",
        agora=lambda: BASE,
    )


def test_um_job_usa_a_ultima_passada_e_traz_custo_e_tempo_dos_dois_lados() -> None:
    relatorio = _relatorio(["j1"])
    (feito,) = relatorio.jobs
    assert feito.modelo == "modelo-novo"
    r = feito.resultado
    assert r.a.custo.usd == 0.7 and r.b.custo.usd == 1.4
    assert custo_por_hora(r.a.custo, r.duracao_ms) == 1.4  # meia hora de vídeo
    assert custo_por_hora(r.b.custo, r.duracao_ms) == 2.8
    assert r.a.tempo.total_s == 150.0 and r.b.tempo.total_s == 40.0
    assert r.b.tempo.etapas == {"janelas": 30.0, "consolidacao": 10.0}


def test_passada_pelo_id_e_pelo_modelo() -> None:
    velho = _relatorio(["j1"], modelo="modelo-velho").jobs[0]
    assert velho.modelo == "modelo-velho"
    id_ = velho.passada_id
    assert _relatorio(["j1"], passada=id_).jobs[0].passada_id == id_
    with pytest.raises(ValueError, match="não há a passada"):
        _relatorio(["j1"], passada="nao-existe")
    with pytest.raises(ValueError, match="nenhuma passada de outro"):
        _relatorio(["j1"], modelo="outro")


def test_job_nao_concluido_ou_sem_decupagem() -> None:
    repositorio, passadas, decupagens = _montar(["j1"])
    base: dict[str, Any] = {
        "passada_id": None,
        "modelo": None,
        "passadas": passadas,
        "custo_do_job_por_id": lambda _j: None,
        "tabela_de_precos_em": "x",
    }
    with pytest.raises(ValueError, match="não está concluído"):
        comparar(["nao"], repositorio=repositorio, ler_decupagem=decupagens.get, **base)
    with pytest.raises(ValueError, match="não tem Decupagem"):
        comparar(["j1"], repositorio=repositorio, ler_decupagem=lambda _j: None, **base)


def test_varios_jobs_somam_por_requisito() -> None:
    relatorio = _relatorio(["j1", "j2"])
    um = _relatorio(["j1"]).total
    total = relatorio.total
    assert len(relatorio.jobs) == 2
    for nome, q in total.requisitos.items():
        base = um.requisitos[nome]
        assert q.contagem_a == 2 * base.contagem_a
        assert q.contagem_b == 2 * base.contagem_b
        assert q.iguais == 2 * base.iguais
        assert len(q.diferentes) == 2 * len(base.diferentes)
        assert len(q.so_em_a) == 2 * len(base.so_em_a)
        assert {e.job_id for e in q.so_em_a} <= {"j1", "j2"}
    assert total.duracao_ms == 2 * um.duracao_ms
    assert total.timecode.pares == 2 * um.timecode.pares
    assert total.timecode.fora_da_tolerancia == 2 * um.timecode.fora_da_tolerancia
    assert total.timecode.p95_ms == um.timecode.p95_ms
    assert total.a.custo is not None and total.a.custo.usd == 1.4
    assert total.b.tempo.total_s == 80.0
    assert total.b.tempo.etapas == {"janelas": 60.0, "consolidacao": 20.0}
    assert custo_por_hora(total.b.custo, total.duracao_ms) == 2.8


def test_soma_de_jobs_diferentes_junta_os_erros_e_divide_pela_duracao_total() -> None:
    # Média de p95 ou de custos por hora daria 2500 ms e US$ 2,50; a soma certa, não.
    exato = _decupagem(pautas=[_pauta("X", 0, 10_000)])
    atrasado = _decupagem(pautas=[_pauta("X", 0, 15_000)])

    def lado(usd: float) -> LadoDoResultado:
        return LadoDoResultado(Custo(1, 1, usd, []), Tempo({}, 1.0))

    r1 = comparar_decupagens("j1", 3_600_000, exato, exato, lado(1.0), lado(1.0))
    r2 = comparar_decupagens("j2", 1_800_000, exato, atrasado, lado(2.0), lado(2.0))
    total = somar([r1, r2])
    assert total.timecode.p95_ms == 5000
    assert total.timecode.media_ms == 1250
    assert (total.timecode.pares, total.timecode.fora_da_tolerancia) == (2, 1)
    assert custo_por_hora(total.b.custo, total.duracao_ms) == 2.0


def test_soma_sem_tokens_de_um_job_nao_inventa_custo() -> None:
    a = _comparar()
    com = LadoDoResultado(Custo(1, 1, 1.0, []), Tempo({}, 1.0))
    r1 = comparar_decupagens("j1", 1000, _par()[0], _par()[1], com, com)
    r2 = comparar_decupagens("j2", 1000, _par()[0], _par()[1], LADO, com)
    assert somar([r1, r2]).a.custo is None
    assert somar([r1, r1]).a.custo is not None
    assert a.a.custo is None


def test_relatorio_em_json_e_markdown(tmp_path: Path) -> None:
    relatorio = _relatorio(["j1", "j2"])
    corpo = json.loads(relatorio_em_json(relatorio))
    assert corpo["tabela_de_precos_em"] == "2026-10-30"
    assert [j["job_id"] for j in corpo["jobs"]] == ["j1", "j2"]
    total = corpo["total"]
    assert set(total["requisitos"]) == {
        "famosos",
        "mencoes",
        "pautas",
        "broll_limpos",
        "broll_descricoes",
        "comerciais",
    }
    assert total["b"]["custo_por_hora_usd"] == 2.8
    assert total["timecode"]["tolerancia_ms"] == TOLERANCIA_MS
    texto = relatorio_em_markdown(relatorio)
    assert "Total de 2 Jobs" in texto and "2026-10-30" in texto
    assert "Só no Job: Duda" in texto and "Diferença (nome)" in texto
    assert "US$ 2.8000 por hora" in texto
    md, js = gravar(relatorio, tmp_path / "saida")
    assert md.name.startswith("piloto-") and js.read_text(
        encoding="utf-8"
    ) == relatorio_em_json(relatorio)
    unico, _ = gravar(_relatorio(["j1"]), tmp_path / "saida")
    assert unico.name.startswith("j1-")


def test_job_sem_tokens_sai_n_d_no_markdown() -> None:
    repositorio, passadas, decupagens = _montar(["j1"])
    relatorio = comparar(
        ["j1"],
        passada_id=None,
        modelo=None,
        repositorio=repositorio,
        ler_decupagem=decupagens.get,
        passadas=passadas,
        custo_do_job_por_id=lambda _j: None,
        tabela_de_precos_em="2026-10-30",
    )
    assert "n/d (o Job não guarda os tokens)" in relatorio_em_markdown(relatorio)
    assert (
        json.loads(relatorio_em_json(relatorio))["total"]["a"]["custo_por_hora_usd"]
        is None
    )
