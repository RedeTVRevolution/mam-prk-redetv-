"""O diagnóstico dos planos de menos de 1 s (#545), em dados locais."""

import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from api.decupagem import Decupagem
from api.planos_curtos import diagnosticar, diagnosticar_pasta, tabela


def _jpeg(variante: int) -> bytes:
    """Um de três quadros bem diferentes: degradê crescente, decrescente ou listras."""
    imagem = Image.new("L", (64, 64))
    valor = [lambda x: x * 4, lambda x: 255 - x * 4, lambda x: 255 * (x // 4 % 2)][
        variante
    ]
    imagem.putdata([valor(x) for _ in range(64) for x in range(64)])
    saida = io.BytesIO()
    imagem.save(saida, "PNG")
    return saida.getvalue()


def _plano(id: str, inicio: int, fim: int, quadro: str) -> dict[str, Any]:
    return {
        "id": id,
        "inicio_ms": inicio,
        "fim_ms": fim,
        "ambiente": "estúdio",
        "plano_limpo": False,
        "quadro": f"quadros/{quadro}",
        "quadros": [f"quadros/{quadro}"],
    }


def _decupagem(planos: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "versao_esquema": "1.5",
        "video": {"sha256": "a" * 64, "duracao_ms": 10_000},
        "programa": {"resumo": "r", "blocos": []},
        "pautas": [],
        "pessoas": [],
        "planos": planos,
        "comerciais": [],
        "transcricao": [],
        "textos_na_tela": [],
    }


def _video(tmp_path: Path, planos: list[dict[str, Any]], cortes: list[int] | None) -> Path:
    pasta = tmp_path / "v1"
    (pasta / "quadros").mkdir(parents=True)
    (pasta / "decupagem.json").write_text(json.dumps(_decupagem(planos)))
    if cortes is not None:
        (pasta / "cortes_ms.json").write_text(json.dumps(cortes))
    for p in planos:
        if p["quadro"]:
            # a.jpg e b.jpg são o mesmo quadro; c.jpg e d.jpg são outros dois
            variante = {"a": 0, "b": 0, "c": 1, "d": 2}[p["quadro"][-5]]
            (pasta / p["quadro"]).write_bytes(_jpeg(variante))
    return pasta


def test_corte_falso_tem_quadro_igual_dos_dois_lados_e_o_real_quadros_diferentes(
    tmp_path: Path,
) -> None:
    planos = [
        _plano("p1", 0, 4_000, "a.jpg"),
        _plano("p2", 4_000, 4_300, "b.jpg"),  # flash: igual ao anterior e ao seguinte
        _plano("p3", 4_300, 8_000, "a.jpg"),
        _plano("p4", 8_000, 8_400, "c.jpg"),  # montagem rápida: muda de quadro
        _plano("p5", 8_400, 10_000, "d.jpg"),
    ]
    pasta = _video(tmp_path, planos, cortes=[4_000, 4_300, 8_000, 8_400])

    linhas = diagnosticar_pasta(pasta)

    assert [(l.plano, l.origem, l.veredito) for l in linhas] == [
        ("p2", "cortes", "provavelmente falso"),
        ("p4", "cortes", "provavelmente real"),
    ]
    assert linhas[0].distancia_na_entrada == 0 and linhas[0].distancia_na_saida == 0
    assert linhas[1].distancia_na_entrada and linhas[1].distancia_na_entrada > 20


def test_sem_cortes_os_planos_vem_do_modelo_e_sem_quadro_nao_ha_veredito(
    tmp_path: Path,
) -> None:
    planos = [_plano("p1", 0, 400, "a.jpg"), _plano("p2", 400, 10_000, "a.jpg")]
    planos[0]["quadro"], planos[0]["quadros"] = None, []
    pasta = _video(tmp_path, planos[1:], cortes=None)
    decupagem = Decupagem.model_validate(_decupagem(planos))

    [linha] = diagnosticar(decupagem, [], lambda c: (pasta / c).read_bytes())

    assert (linha.origem, linha.veredito) == ("modelo", "sem quadros")


def test_a_tabela_resume_por_origem_e_veredito(tmp_path: Path) -> None:
    pasta = _video(
        tmp_path,
        [_plano("p1", 0, 5_000, "a.jpg"), _plano("p2", 5_000, 5_300, "b.jpg")],
        cortes=[5_000],
    )

    texto = tabela(diagnosticar_pasta(pasta))

    assert "p2" in texto and "provavelmente falso" in texto
    assert "cortes: 1" in texto
