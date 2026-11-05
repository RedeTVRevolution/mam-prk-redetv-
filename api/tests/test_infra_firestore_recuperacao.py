"""Recuperação do Firestore: PITR ligado e backups diário e semanal (#355)."""

import re
from pathlib import Path

MODULO = Path(__file__).resolve().parents[2] / "infra" / "modulos" / "mam"
TF = "\n".join(p.read_text() for p in sorted(MODULO.glob("*.tf")))
SETE_DIAS = 7 * 24 * 3600
CATORZE_SEMANAS = 14 * 7 * 24 * 3600


def _bloco(cabecalho: str) -> str:
    inicio = re.search(rf"^{re.escape(cabecalho)}", TF, re.MULTILINE)
    assert inicio
    return TF[inicio.start() : TF.index("\n}\n", inicio.start())]


def _agenda(nome: str) -> str:
    return _bloco(f'resource "google_firestore_backup_schedule" "{nome}"')


def _retencao(bloco: str) -> int:
    achado = re.search(r'^\s*retention\s*=\s*"(\d+)s"', bloco, re.MULTILINE)
    assert achado
    return int(achado.group(1))


def test_o_banco_liga_a_recuperacao_a_um_ponto_no_tempo() -> None:
    banco = _bloco('resource "google_firestore_database" "mam"')
    assert (
        'point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"' in banco
    )


def test_o_banco_continua_protegido_contra_exclusao() -> None:
    banco = _bloco('resource "google_firestore_database" "mam"')
    assert re.search(
        r'^\s*delete_protection_state\s*=\s*"DELETE_PROTECTION_ENABLED"',
        banco,
        re.MULTILINE,
    )


def test_a_agenda_diaria_guarda_sete_dias() -> None:
    bloco = _agenda("diaria")
    assert "daily_recurrence" in bloco
    assert "weekly_recurrence" not in bloco
    assert _retencao(bloco) == SETE_DIAS


def test_a_agenda_semanal_guarda_catorze_semanas() -> None:
    bloco = _agenda("semanal")
    assert "weekly_recurrence" in bloco
    assert "daily_recurrence" not in bloco
    assert _retencao(bloco) == CATORZE_SEMANAS
    assert re.search(r'day\s*=\s*"SUNDAY"', bloco)


def test_so_ha_duas_agendas_o_maximo_do_firestore() -> None:
    agendas = re.findall(
        r'^resource "google_firestore_backup_schedule"', TF, re.MULTILINE
    )
    assert len(agendas) == 2


def test_as_agendas_sao_do_banco_do_modulo() -> None:
    for nome in ("diaria", "semanal"):
        assert re.search(
            r"database\s*= google_firestore_database\.mam\.name", _agenda(nome)
        )
