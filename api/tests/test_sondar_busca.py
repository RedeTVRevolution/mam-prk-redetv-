from api.busca import Momento, VideoDoResultado
from api.sondar_busca import Caso, veredito


def _video(*motivos: str) -> VideoDoResultado:
    momentos = [
        Momento(inicio_ms=0, fim_ms=1, motivo=m, destaques=[], quadro_url=None)
        for m in motivos
    ]
    return VideoDoResultado(
        job_id="j",
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
