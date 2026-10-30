from api.espera import espera_com_jitter


def test_espera_dobra_a_cada_falha_e_para_no_teto() -> None:
    esperas = [espera_com_jitter(f, 5.0, 60.0, lambda teto: teto) for f in range(6)]

    assert esperas == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0]
