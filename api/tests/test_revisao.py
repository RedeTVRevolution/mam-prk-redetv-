"""O tempo de revisão (#251): o cálculo dos pulsos, as rotas e o comando."""

from datetime import UTC, datetime, timedelta

from api.revisao import LIMITE_DE_INATIVIDADE_S, Medida, Pulso, aplicar

COMECO = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _pulso(segundos: float, evento: str = "atividade", uid: str = "u1") -> Pulso:
    return Pulso(
        job_id="j1",
        uid=uid,
        email=f"{uid}@redetv.com.br",
        quando=COMECO + timedelta(seconds=segundos),
        evento=evento,  # type: ignore[arg-type]
        duracao_s=3600.0,
    )


def _soma(*pulsos: Pulso, limite_s: float = LIMITE_DE_INATIVIDADE_S) -> Medida:
    medida: Medida | None = None
    for pulso in pulsos:
        medida = aplicar(medida, pulso, limite_s)
    assert medida is not None
    return medida


def test_pulsos_seguidos_somam() -> None:
    medida = _soma(_pulso(0, "inicio"), _pulso(60), _pulso(120), _pulso(180, "fim"))

    assert medida.ativo_s == 180
    assert medida.sessoes == 1
    assert medida.duracao_s == 3600.0


def test_intervalo_maior_que_o_limite_nao_conta_e_abre_outra_sessao() -> None:
    medida = _soma(_pulso(0, "inicio"), _pulso(60), _pulso(60 + 301), _pulso(60 + 361))

    assert medida.ativo_s == 60 + 60
    assert medida.sessoes == 2


def test_intervalo_no_limite_conta() -> None:
    assert _soma(_pulso(0, "inicio"), _pulso(300)).ativo_s == 300


def test_o_limite_vem_do_parametro() -> None:
    medida = _soma(_pulso(0, "inicio"), _pulso(120), limite_s=60)

    assert medida.ativo_s == 0
    assert medida.sessoes == 2


def test_duas_abas_da_mesma_pessoa_nao_contam_em_dobro() -> None:
    aba_a = [_pulso(0, "inicio"), _pulso(60), _pulso(120), _pulso(180)]
    aba_b = [_pulso(20), _pulso(80), _pulso(140), _pulso(200)]
    pulsos = sorted(aba_a + aba_b, key=lambda p: p.quando)

    medida = _soma(*pulsos)

    assert medida.ativo_s == 200
    assert medida.sessoes == 1


def test_pulso_atrasado_nao_volta_no_tempo() -> None:
    medida = _soma(_pulso(0, "inicio"), _pulso(120), _pulso(60))

    assert medida.ativo_s == 120
    assert medida.ultimo_pulso == COMECO + timedelta(seconds=120)


def test_atividade_sem_inicio_abre_a_sessao_sem_contar_tempo() -> None:
    medida = _soma(_pulso(500))

    assert medida.ativo_s == 0
    assert medida.sessoes == 1


def test_inicio_depois_de_uma_pausa_nao_conta_o_intervalo() -> None:
    medida = _soma(_pulso(0, "inicio"), _pulso(60), _pulso(200, "inicio"))

    assert medida.ativo_s == 60
    assert medida.sessoes == 1  # ainda dentro do limite: a mesma sessão


def test_pessoas_diferentes_nao_se_misturam() -> None:
    a = aplicar(None, _pulso(0, "inicio", "u1"), 300)
    b = aplicar(None, _pulso(0, "inicio", "u2"), 300)

    assert (a.uid, b.uid) == ("u1", "u2")


def test_a_duracao_do_video_acompanha_o_ultimo_pulso() -> None:
    medida = _soma(_pulso(0, "inicio"))
    novo = aplicar(medida, _pulso(60).model_copy(update={"duracao_s": None}), 300)

    assert novo.duracao_s == 3600.0


def test_sair_e_voltar_logo_abre_outra_sessao_sem_contar_o_intervalo() -> None:
    medida = _soma(
        _pulso(0, "inicio"),
        _pulso(60),
        _pulso(90, "fim"),
        _pulso(150, "inicio"),
        _pulso(210),
    )

    assert medida.ativo_s == 90 + 60
    assert medida.sessoes == 2


def test_outra_aba_abrindo_nao_abre_outra_sessao() -> None:
    assert _soma(_pulso(0, "inicio"), _pulso(60), _pulso(80, "inicio")).sessoes == 1
