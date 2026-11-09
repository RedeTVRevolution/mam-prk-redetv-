from pathlib import Path

import pytest

from api.agent_retrieval import CAMPOS_DE_TEXTO, ConfigDaBusca
from api.busca import Momento, VideoDoResultado
from api.sondar_busca import (
    ARQUIVO_DAS_CONSULTAS,
    CASOS,
    Caso,
    Trecho,
    esquema_sem_campos,
    ler_casos,
    pertinencia,
    primeiros_resultados,
    relatorio_do_aceite,
    veredito,
)


def _video(
    *motivos: str, job_id: str = "j", inicio_ms: int = 0, fim_ms: int | None = None
) -> VideoDoResultado:
    momentos = [
        Momento(
            tipo="plano",
            inicio_ms=inicio_ms,
            fim_ms=inicio_ms + 1 if fim_ms is None else fim_ms,
            motivo=m,
            destaques=[],
            quadro_url=None,
        )
        for m in motivos
    ]
    return VideoDoResultado(
        job_id=job_id,
        nome="clipe.mp4",
        programa=None,
        data_exibicao=None,
        duracao_s=None,
        n_momentos=len(momentos),
        momentos=momentos,
    )


CALCA = Caso("calça vinho", "calça vinho", 2, exatos=True)


def test_exatos_pede_os_certos_antes_dos_parecidos_em_cada_video() -> None:
    certo = [
        _video("Objeto: calça vinho", "Objeto: cropped vinho"),
        _video("Objeto: calça vinho"),
    ]
    assert veredito(CALCA, certo)
    assert not veredito(
        CALCA, [_video("Objeto: cropped vinho", "Objeto: calça vinho")] * 2
    )
    assert not veredito(CALCA, [_video("Objeto: calça vinho")])  # falta uma aparição


def test_existe_olha_o_primeiro_momento_e_o_teto() -> None:
    terno = Caso("terno", "terno", 2)
    assert veredito(terno, [_video("Objeto: terno preto", "Fala: oi")])
    assert not veredito(terno, [_video("Fala: oi", "Objeto: terno preto")])
    assert not veredito(terno, [_video("Objeto: terno preto", "a", "b")])


def test_ausente_pede_nenhum_video() -> None:
    assert veredito(Caso("xyzzy", None), [])
    assert not veredito(Caso("xyzzy", None), [_video("Fala: xyzzy")])


def test_a_sonda_tem_consultas_de_objetos_de_cena() -> None:
    termos = {c.termo for c in CASOS if c.consulta in CONSULTAS_DE_CENA}
    # O carro BYD e as motos do telão (#121); os livros, a revista e o microfone da FAMA.
    assert termos == {"byd", "moto", "livro", "revista", "microfone"}
    assert all(c.termo and c.teto for c in CASOS if c.consulta in CONSULTAS_DE_CENA)


CONSULTAS_DE_CENA = {
    "carro BYD",
    "motos no telão",
    "livros",
    "revista",
    "microfone da RedeTV!",
}


def test_o_arquivo_do_repositorio_traz_as_consultas_de_hoje() -> None:
    assert len(CASOS) >= 20
    assert CASOS[0] == Caso("terno", "terno", 3)
    assert next(c for c in CASOS if c.consulta == "calça vinho").exatos
    assert [c.consulta for c in CASOS if c.termo is None][:2] == [
        "bicicleta",
        "cachorro",
    ]


def _arquivo(tmp_path: Path, texto: str) -> Path:
    arquivo = tmp_path / "consultas.toml"
    arquivo.write_text(texto)
    return arquivo


def test_ler_casos_le_filtros_e_trechos_pertinentes(tmp_path: Path) -> None:
    arquivo = _arquivo(
        tmp_path,
        """
[[consulta]]
texto = "vestido"
programa = "fama"
desde = 2024-05-01
ate = 2024-05-31
pertinentes = [{ job = "abc", de_s = 10, ate_s = 25 }]
""",
    )
    [caso] = ler_casos(arquivo)
    assert caso.programa == "fama"
    assert (str(caso.desde), str(caso.ate)) == ("2024-05-01", "2024-05-31")
    assert caso.pertinentes == (Trecho(job="abc", de_s=10, ate_s=25),)


def test_ler_casos_recusa_campo_desconhecido_e_trecho_invertido(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="termmo"):
        ler_casos(_arquivo(tmp_path, '[[consulta]]\ntexto = "a"\ntermmo = "b"\n'))
    with pytest.raises(ValueError, match="de_s"):
        ler_casos(
            _arquivo(
                tmp_path,
                '[[consulta]]\ntexto = "a"\n'
                'pertinentes = [{ job = "j", de_s = 9, ate_s = 1 }]\n',
            )
        )


def test_a_consulta_sem_anotacao_nao_tem_pertinencia() -> None:
    assert pertinencia(Caso("xyzzy", None), [_video("Fala: xyzzy")]) is None


def test_pertinencia_pelo_termo_conta_so_os_5_primeiros() -> None:
    caso = Caso("terno", "terno", 30)
    videos = [
        _video("terno", "terno", "fala", "fala"),
        _video("terno", "terno", "terno"),
    ]
    # Os 5 primeiros: terno, terno, fala, fala, terno.
    assert pertinencia(caso, videos) == pytest.approx(3 / 5)
    assert len(primeiros_resultados(videos)) == 5


def test_pertinencia_por_job_e_tempo() -> None:
    caso = Caso("vestido", None, pertinentes=(Trecho("abc", 10, 25),))
    videos = [
        _video("a", job_id="abc12345", inicio_ms=12_000),  # dentro
        _video("b", job_id="abc12345", inicio_ms=30_000),  # fora do tempo
        _video("c", job_id="zzz", inicio_ms=12_000),  # outro vídeo
    ]
    assert pertinencia(caso, videos) == pytest.approx(1 / 3)


def test_com_menos_de_5_resultados_a_fracao_e_dos_que_vieram() -> None:
    caso = Caso("terno", "terno", 30)
    assert pertinencia(caso, [_video("terno", "fala")]) == 0.5
    assert pertinencia(caso, []) == 0.0


def _com(consulta: str, fracao: float | None) -> tuple[Caso, float | None]:
    return Caso(consulta, "x"), fracao


def test_aceite_passa_com_80_por_cento_no_total_e_lista_as_abaixo() -> None:
    r = relatorio_do_aceite([_com("a", 1.0), _com("b", 0.6), _com("c", 1.0)])
    assert r.total == pytest.approx(2.6 / 3)
    assert r.passou
    assert [c.consulta for c, _ in r.abaixo] == ["b"]


def test_aceite_nao_passa_abaixo_de_80_por_cento() -> None:
    r = relatorio_do_aceite([_com("a", 1.0), _com("b", 0.4), _com("c", 0.8)])
    assert not r.passou
    assert [c.consulta for c, _ in r.abaixo] == ["b"]


def test_consulta_sem_anotacao_fica_fora_da_conta() -> None:
    r = relatorio_do_aceite([_com("a", 1.0), _com("b", None)])
    assert r.total == 1.0
    assert r.passou
    assert r.abaixo == []


def test_sem_nenhuma_anotacao_nao_ha_aceite() -> None:
    r = relatorio_do_aceite([_com("a", None)])
    assert r.total is None
    assert not r.passou


def test_a_consulta_so_com_pertinentes_nao_tem_veredito() -> None:
    caso = Caso("vestido", None, pertinentes=(Trecho("abc", 10, 25),))
    assert veredito(caso, [_video("Objeto: vestido", job_id="abc")]) is None


def test_existe_sem_teto_nao_limita_os_momentos() -> None:
    assert veredito(Caso("terno", "terno"), [_video("terno", "a", "b", "c")])


def test_o_trecho_conta_o_momento_que_comeca_antes_e_entra_nele() -> None:
    caso = Caso("vestido", None, pertinentes=(Trecho("abc", 10, 25),))
    videos = [_video("a", job_id="abc", inicio_ms=8_000, fim_ms=15_000)]
    assert pertinencia(caso, videos) == 1.0


def test_ler_casos_poe_o_termo_em_minusculas(tmp_path: Path) -> None:
    [caso] = ler_casos(
        _arquivo(tmp_path, '[[consulta]]\ntexto = "carro"\ntermo = "BYD"\n')
    )
    assert caso.termo == "byd"
    assert pertinencia(caso, [_video("Objeto: carro BYD")]) == 1.0


def test_ler_casos_recusa_data_entre_aspas_e_exatos_sem_teto(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="desde"):
        ler_casos(
            _arquivo(tmp_path, '[[consulta]]\ntexto = "a"\ndesde = "2024-05-01"\n')
        )
    with pytest.raises(ValueError, match="exatos"):
        ler_casos(
            _arquivo(
                tmp_path, '[[consulta]]\ntexto = "a"\ntermo = "a"\nexatos = true\n'
            )
        )


def test_o_arquivo_do_repositorio_esta_no_lugar_combinado() -> None:
    assert ARQUIVO_DAS_CONSULTAS.is_file()
    assert ler_casos(ARQUIVO_DAS_CONSULTAS) == CASOS


def test_esquema_sem_campo_de_texto_falha_nomeando_o_campo() -> None:
    config = ConfigDaBusca("p", "r", "c", "d", 128, "ct")
    sem_campos = {"dataSchema": {"properties": {"texto": {"type": "string"}}}}
    com_campos = {
        "dataSchema": {"properties": {c: {"type": "string"} for c in CAMPOS_DE_TEXTO}}
    }
    erro = esquema_sem_campos(config, lambda m, c, b: sem_campos)
    assert erro is not None and all(repr(c) in erro for c in CAMPOS_DE_TEXTO)
    assert esquema_sem_campos(config, lambda m, c, b: com_campos) is None


def test_sonda_confere_tambem_o_esquema_da_colecao_de_texto() -> None:
    config = ConfigDaBusca("p", "r", "c", "d", 128, "ct")
    chamados: list[str] = []

    def transporte(metodo: str, caminho: str, corpo: object) -> dict[str, object]:
        chamados.append(caminho)
        return {
            "dataSchema": {
                "properties": {"texto_da_busca": {"type": "string"}}
                if caminho.endswith("/c")
                else {}
            }
        }

    erro = esquema_sem_campos(config, transporte)
    assert erro is not None and "ct" in erro and "texto_da_busca" in erro
    assert len(chamados) == 2
