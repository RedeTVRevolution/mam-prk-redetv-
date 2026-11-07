"""A conferência da limpeza do Artifact Registry não deixa apagar o build em uso nem o da volta (#456)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from api import limpeza_de_imagens as limpeza
from api.limpeza_de_imagens import Regras, Simulacao, Veredito, Versao, simular

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
REPO = "us-east4-docker.pkg.dev/p/mam-gpu"
REGRAS = Regras(
    manter_ultimas=3,
    idade_minima_s=14 * 86400,
    pacotes_do_cache=("cache",),
    tags_protegidas=("em-uso", "volta"),
    tag_da_volta="volta",
)
# O `terraform output -json` com o que a conferência lê.
SAIDA_DO_TERRAFORM = {
    "limpeza_de_imagens": {
        "value": {
            "manter_ultimas": 3,
            "idade_minima_s": 14 * 86400,
            "pacotes_do_cache": ["cache"],
            "tags_protegidas": ["em-uso", "volta"],
            "tag_da_volta": "volta",
        }
    },
    "repositorio": {"value": "southamerica-east1-docker.pkg.dev/p/mam"},
    "repositorio_gpu": {"value": REPO},
}


def _versao(
    digest: str, dias: int, tags: Sequence[str] = (), pacote: str = "transcricao-gpu"
) -> Versao:
    return Versao(REPO, pacote, digest, AGORA - timedelta(days=dias), tuple(tags))


def _versoes(volta_tags: Sequence[str] = ("volta",)) -> list[Versao]:
    # A volta é velha (30 dias) e já saiu dos 3 últimos: só a tag a guarda.
    recentes = [_versao(f"sha256:novo{i}", i) for i in range(3)]
    return [
        *recentes,
        _versao("sha256:volta", 30, volta_tags),
        _versao("sha256:velha", 40),
    ]


def _veredito(simulacao: Simulacao, digest: str) -> Veredito:
    return next(v for v in simulacao.vereditos if v.versao.digest == digest)


def test_a_volta_velha_e_fora_dos_ultimos_fica_pela_tag() -> None:
    s = simular(_versoes(), REGRAS, AGORA)
    assert not _veredito(s, "sha256:volta").apagar
    assert _veredito(s, "sha256:volta").da_volta
    assert _veredito(s, "sha256:velha").apagar
    assert s.em_risco == []


def test_sem_a_tag_a_mesma_volta_seria_apagada_e_a_conferencia_acusa() -> None:
    s = simular(_versoes(volta_tags=()), REGRAS, AGORA, {(REPO, "sha256:volta")})
    assert _veredito(s, "sha256:volta").apagar
    assert [v.versao.digest for v in s.em_risco] == ["sha256:volta"]


def test_a_tag_da_volta_que_nenhuma_regra_guarda_e_acusada() -> None:
    regras = Regras(3, 14 * 86400, ("cache",), ("em-uso",), "volta")
    s = simular(_versoes(), regras, AGORA)
    assert [v.versao.digest for v in s.em_risco] == ["sha256:volta"]


def test_o_build_em_uso_velho_fica_pela_tag_em_uso() -> None:
    versoes = [*_versoes(), _versao("sha256:uso", 50, ["em-uso"])]
    s = simular(versoes, REGRAS, AGORA, {(REPO, "sha256:uso")})
    assert _veredito(s, "sha256:uso").em_uso
    assert not _veredito(s, "sha256:uso").apagar
    assert s.em_risco == []


def test_o_build_em_uso_sem_tag_e_fora_dos_ultimos_e_acusado() -> None:
    versoes = [*_versoes(), _versao("sha256:uso", 50)]
    s = simular(versoes, REGRAS, AGORA, {(REPO, "sha256:uso")})
    assert [v.versao.digest for v in s.em_risco] == ["sha256:uso"]


def test_versao_nova_nunca_e_apagada_e_o_cache_com_tag_fica() -> None:
    versoes = [
        *[_versao(f"sha256:n{i}", i + 1) for i in range(4)],  # a 4ª é a mais velha
        _versao("sha256:cache", 90, ["gpu"], pacote="cache"),
        *[_versao(f"sha256:c{i}", 10 + i, pacote="cache") for i in range(3)],
        _versao("sha256:cache-solto", 90, pacote="cache"),
    ]
    s = simular(versoes, REGRAS, AGORA)
    assert not any(
        v.apagar for v in s.vereditos if v.versao.pacote == "transcricao-gpu"
    )
    assert not _veredito(s, "sha256:cache").apagar
    assert _veredito(s, "sha256:cache-solto").apagar


def test_as_tres_mais_recentes_valem_por_imagem() -> None:
    outra = [_versao(f"sha256:o{i}", 20 + i, pacote="ocr-gpu") for i in range(5)]
    s = simular([*_versoes(), *outra], REGRAS, AGORA)
    apagadas = {v.versao.digest for v in s.vereditos if v.apagar}
    assert apagadas == {"sha256:velha", "sha256:o3", "sha256:o4"}


def test_le_o_json_do_gcloud_e_as_imagens_em_uso_do_cloud_run() -> None:
    itens = [
        {
            "package": f"{REPO}/transcricao-gpu",
            "version": "sha256:a",
            "createTime": "2026-10-29T10:00:00.123Z",
            "tags": "volta, em-uso",
        },
        {
            "package": f"{REPO}/cache",
            "version": "sha256:b",
            "createTime": "2026-10-30T10:00:00Z",
        },
    ]
    versoes = limpeza.versoes_do_gcloud(REPO, itens)
    assert versoes[0].pacote == "transcricao-gpu"
    assert versoes[0].tags == ("volta", "em-uso")
    assert versoes[1].tags == ()
    job = {
        "spec": {
            "template": {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {"image": f"{REPO}/transcricao-gpu@sha256:a"}
                            ]
                        }
                    }
                }
            }
        }
    }
    servico = {
        "spec": {
            "template": {"spec": {"containers": [{"image": f"{REPO}/web@sha256:c"}]}}
        }
    }
    de_fora = {
        "spec": {"template": {"spec": {"containers": [{"image": "outro/x@sha256:d"}]}}}
    }
    assert limpeza.em_uso_do_cloud_run([REPO], [job, servico, de_fora]) == {
        (REPO, "sha256:a"),
        (REPO, "sha256:c"),
    }


def test_main_sai_com_1_se_apagaria_versao_em_uso(
    capsys: pytest.CaptureFixture[str],
) -> None:

    def ler(comando: list[str]) -> object:
        if comando[0] == "terraform":
            return SAIDA_DO_TERRAFORM
        if comando[:3] == ["gcloud", "artifacts", "docker"]:
            if comando[5] != REPO:
                return []
            antigas = [
                {"package": f"{REPO}/ocr-gpu", "version": f"sha256:{i}",
                 "createTime": f"2026-10-{10 + i}T00:00:00Z"}
                for i in range(5)
            ]  # fmt: skip
            return antigas
        job = {"spec": {"template": {"spec": {"template": {"spec": {"containers": [
            {"image": f"{REPO}/ocr-gpu@sha256:0"}]}}}}}}  # fmt: skip
        return [job] if comando[2] == "jobs" and "us-east4" in comando else []

    codigo = limpeza.main(ler, lambda: AGORA)
    texto = capsys.readouterr().out
    assert codigo == 1
    assert "ERRO" in texto and "sha256:0" in texto


def test_main_sem_o_output_da_limpeza_sai_com_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert limpeza.main(lambda comando: {}, lambda: AGORA) == 2
    assert "limpeza_de_imagens" in capsys.readouterr().out


def test_main_sem_imagem_em_uso_no_cloud_run_sai_com_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Outra config do gcloud ativa lê o Cloud Run de outro projeto: nada em uso não é aprovação."""

    def ler(comando: list[str]) -> object:
        return SAIDA_DO_TERRAFORM if comando[0] == "terraform" else []

    assert limpeza.main(ler, lambda: AGORA) == 2
    assert "nenhum serviço nem Job" in capsys.readouterr().out


def test_o_motivo_diz_a_idade_das_regras() -> None:
    regras = Regras(3, 7 * 86400, ("cache",), ("em-uso", "volta"), "volta")
    s = simular(_versoes(), regras, AGORA)
    assert _veredito(s, "sha256:velha").motivo.endswith("mais de 7 dias")
