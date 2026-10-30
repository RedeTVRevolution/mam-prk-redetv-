import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.comparador import (
    TIPOS,
    TOLERANCIA_MS,
    Item,
    ResultadoDoClipe,
    main,
    normalizar,
    parear,
    passou,
    se_sobrepoem,
    sobreposicao_ms,
    tempo_ms,
)

tempos = st.integers(min_value=0, max_value=600_000)
tipos = st.sampled_from(TIPOS)
nomes = st.text(alphabet="abcdeáéÇçãO ", min_size=1, max_size=8)


@st.composite
def itens(draw: st.DrawFn, tipo: st.SearchStrategy[str] = tipos) -> Item:
    a, b = sorted((draw(tempos), draw(tempos)))
    return Item(draw(tipo), draw(nomes), a, b)  # type: ignore[arg-type]


@given(st.lists(itens(), max_size=6), st.lists(itens(), max_size=6))
def test_todo_item_do_gabarito_tem_par_ou_vai_para_nao_encontrados(
    g: list[Item], m: list[Item]
) -> None:
    pareados, sem_par = parear(g, m)
    assert len(pareados) + len(sem_par) == len(g)


@given(st.lists(itens(), max_size=6), st.lists(itens(), max_size=6))
def test_par_tem_mesmo_tipo_e_sobreposicao(g: list[Item], m: list[Item]) -> None:
    for p in parear(g, m)[0]:
        assert p.gabarito.tipo == p.modelo.tipo
        assert se_sobrepoem(p.gabarito, p.modelo)


@given(tempos, tempos, tempos, tipos)
def test_item_pontual_pareia_com_o_que_o_contem(
    t: int, a: int, b: int, tipo: str
) -> None:
    ini, fim = sorted((a, b))
    g = Item(tipo, "Ana", t, t)  # type: ignore[arg-type]
    m = Item(tipo, "ana", ini, fim)  # type: ignore[arg-type]
    assert bool(parear([g], [m])[0]) == (ini <= t <= fim)
    assert bool(parear([m], [g])[0]) == (ini <= t <= fim)


@given(tempos, st.integers(1, 10_000), st.integers(0, 10_000))
def test_intervalos_que_so_se_tocam_nao_pareiam(ini: int, dur: int, dur2: int) -> None:
    g = Item("pauta", "x", ini, ini + dur)
    m = Item("pauta", "x", ini + dur, ini + dur + dur2 + 1)
    assert parear([g], [m])[0] == []


@given(itens(st.sampled_from(["aparicao", "mencao", "comercial"])), nomes)
def test_identidade_diferente_nao_pareia(g: Item, outro: str) -> None:
    m = Item(g.tipo, outro, g.inicio_ms, g.fim_ms)
    pareados, _ = parear([g], [m])
    assert bool(pareados) == (normalizar(outro) == normalizar(g.identidade))


def test_identidade_ignora_maiusculas_e_acentos() -> None:
    g = Item("aparicao", "José da Conceição", 0, 5000)
    m = Item("aparicao", "JOSE DA  CONCEICAO", 0, 5000)
    assert len(parear([g], [m])[0]) == 1


@given(itens(st.just("pauta")), nomes)
def test_pauta_vale_so_pela_sobreposicao(g: Item, titulo: str) -> None:
    m = Item("pauta", titulo, g.inicio_ms, g.fim_ms + 1)
    assert len(parear([g], [m])[0]) == 1


@given(
    itens(st.just("pauta")), st.lists(itens(st.just("pauta")), min_size=1, max_size=5)
)
def test_o_par_tem_a_maior_sobreposicao(g: Item, m: list[Item]) -> None:
    pareados, _ = parear([g], m)
    if pareados:
        melhor = pareados[0].modelo
        assert sobreposicao_ms(g, melhor) == max(sobreposicao_ms(g, x) for x in m)


@given(tempos, tempos, st.integers(-5000, 5000), st.integers(-5000, 5000))
def test_tolerancia_de_2s_no_inicio_e_no_fim(a: int, b: int, di: int, df: int) -> None:
    ini, fim = min(a, b), max(a, b) + 10_000
    g = Item("pauta", "x", ini, fim)
    m = Item("pauta", "y", max(0, ini + di), fim + df)
    pareados, _ = parear([g], [m])
    p = pareados[0]
    assert p.dentro == (
        p.erro_inicio_ms <= TOLERANCIA_MS and p.erro_fim_ms <= TOLERANCIA_MS
    )
    assert p.erro_inicio_ms == abs(m.inicio_ms - ini)


@pytest.mark.parametrize(("desvio", "dentro"), [(2000, True), (2001, False)])
def test_limite_exato_da_tolerancia(desvio: int, dentro: bool) -> None:
    g = Item("pauta", "x", 10_000, 20_000)
    for m in (
        Item("pauta", "x", 10_000 + desvio, 20_000),
        Item("pauta", "x", 10_000, 20_000 + desvio),
    ):
        assert parear([g], [m])[0][0].dentro is dentro


def _res(pareados_dentro: int, fora: int, sem_par: int) -> ResultadoDoClipe:
    base = Item("pauta", "x", 0, 10_000)
    ok = [parear([base], [base])[0][0]] * pareados_dentro
    ruim = [parear([base], [Item("pauta", "x", 5000, 20_000)])[0][0]] * fora
    return ResultadoDoClipe("c", ok + ruim, [base] * sem_par)


@given(st.integers(0, 40), st.integers(0, 40), st.integers(0, 40))
def test_criterio_de_95_por_cento_ignora_nao_encontrados(
    ok: int, fora: int, sem: int
) -> None:
    esperado = ok + fora > 0 and ok * 100 >= 95 * (ok + fora)
    assert passou([_res(ok, fora, sem)]) == esperado


def test_soma_os_clipes_antes_de_calcular() -> None:
    assert passou([_res(10, 0, 0), _res(9, 1, 0)])  # 19/20
    assert not passou([_res(9, 1, 0), _res(9, 1, 0)])  # 18/20


def test_tempo_mmss() -> None:
    assert tempo_ms("01:05") == 65_000
    assert tempo_ms("10:00") == 600_000
    for ruim in ["1:5", "00:60", "abc", "-1:00"]:
        with pytest.raises(ValueError):
            tempo_ms(ruim)


SHA = "a" * 64


def _decupagem(
    pessoas: list[dict[str, object]], pautas: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "versao_esquema": "1.2",
        "video": {"sha256": SHA, "duracao_ms": 600_000},
        "programa": {"resumo": "r", "blocos": []},
        "pautas": pautas,
        "pessoas": pessoas,
        "planos": [],
        "comerciais": [],
        "transcricao": [],
    }


def _pasta(tmp_path: Path, fim_pauta_ms: int) -> tuple[Path, Path]:
    g, d = tmp_path / "gabarito", tmp_path / "decupagens"
    g.mkdir()
    d.mkdir()
    (g / "clipe1.csv").write_text(
        f"# sha256: {SHA}\ntipo,identidade,inicio,fim\n"
        "pauta,Chuva,00:10,00:20\naparicao,Ana,00:00,00:30\ncomercial,Marca,01:00,01:10\n",
        encoding="utf-8",
    )
    pessoa: dict[str, object] = {
        "id": "p1",
        "nome": "ANA",
        "na_imagem": [{"inicio_ms": 0, "fim_ms": 30_000, "evidencia": "rosto"}],
        "citada_na_fala": [],
        "citada_no_texto": [],
    }
    pauta = {
        "id": "t1",
        "titulo": "outro",
        "resumo": "r",
        "inicio_ms": 11_000,
        "fim_ms": fim_pauta_ms,
    }
    (d / "clipe1.json").write_text(json.dumps(_decupagem([pessoa], [pauta])))
    return g, d


def test_comando_passou(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    g, d = _pasta(tmp_path, 21_000)
    assert main([str(g), str(d)]) == 0
    saida = capsys.readouterr().out
    assert "PASSOU" in saida and "Marca" in saida  # não encontrado listado
    assert "1.000s / 1.000s" in saida


def test_comando_falhou(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    g, d = _pasta(tmp_path, 25_000)
    assert main([str(g), str(d)]) == 1
    saida = capsys.readouterr().out
    assert "FALHOU" in saida and "[FORA] pauta Chuva" in saida
    assert saida.index("piores casos") < saida.index("pauta Chuva: 5.000s")


def test_entrada_invalida_da_codigo_2(tmp_path: Path) -> None:
    g, d = _pasta(tmp_path, 21_000)
    (g / "clipe1.csv").write_text("tipo,identidade,inicio,fim\n")
    assert main([str(g), str(d)]) == 2
    assert main([]) == 2


def test_csv_com_bom_e_sha_em_maiusculas(tmp_path: Path) -> None:
    g, d = _pasta(tmp_path, 21_000)
    csv = g / "clipe1.csv"
    texto = csv.read_text(encoding="utf-8").replace(SHA, SHA.upper())
    csv.write_text("\ufeff" + texto, encoding="utf-8")
    assert main([str(g), str(d)]) == 0


def test_sha_repetido_da_codigo_2(tmp_path: Path) -> None:
    g, d = _pasta(tmp_path, 21_000)
    (d / "copia.json").write_bytes((d / "clipe1.json").read_bytes())
    assert main([str(g), str(d)]) == 2
    (d / "copia.json").unlink()
    (g / "copia.csv").write_bytes((g / "clipe1.csv").read_bytes())
    assert main([str(g), str(d)]) == 2
