"""A lista do acervo no Firestore lê em lotes, com teto, e só os campos da lista (#480)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from api.jobs import FiltroDeJobs, Job
from api.nuvem import RepositorioFirestore

LIXEIRA = {
    "em": datetime(2026, 2, 1, tzinfo=UTC),
    "por_uid": "u",
    "por_email": "u@x.com",
    "motivo": "teste",
}


def _job(n: int, **campos: Any) -> Job:
    base = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=n)
    return Job(
        id=f"j{n:03}",
        nome="v.mp4",
        tamanho_bytes=1,
        estado="concluido",
        criado_por="u",
        criado_em=base,
        atualizado_em=base,
        **campos,
    )


class _Doc:
    def __init__(self, dados: dict[str, Any]) -> None:
        self.dados, self.id = dados, dados["id"]

    def to_dict(self) -> dict[str, Any]:
        return self.dados


class _Consulta:
    """Do mais recente ao mais antigo, como `order_by(criado_em, DESC)` com `start_after`."""

    def __init__(self, docs: list[_Doc], leituras: list[int], campos: list[list[str]]):
        self.docs, self.leituras, self.campos = docs, leituras, campos
        self.depois: _Doc | None = None
        self.maximo: int | None = None
        self.selecionados: list[str] | None = None

    def where(self, filter: Any) -> "_Consulta":
        assert filter.op_string == "array_contains"
        outra = _Consulta(
            [d for d in self.docs if filter.value in d.dados[filter.field_path]],
            self.leituras,
            self.campos,
        )
        return outra

    def order_by(self, *_a: Any, **_k: Any) -> "_Consulta":
        return self

    def start_after(self, doc: _Doc) -> "_Consulta":
        outra = self._copia()
        outra.depois = doc
        return outra

    def select(self, campos: list[str]) -> "_Consulta":
        outra = self._copia()
        outra.selecionados = campos
        return outra

    def limit(self, n: int) -> "_Consulta":
        outra = self._copia()
        outra.maximo = n
        return outra

    def _copia(self) -> "_Consulta":
        outra = _Consulta(self.docs, self.leituras, self.campos)
        outra.depois, outra.maximo = self.depois, self.maximo
        outra.selecionados = self.selecionados
        return outra

    def stream(self) -> list[_Doc]:
        docs = self.docs
        if self.depois is not None:
            ids = [d.id for d in docs]
            docs = docs[ids.index(self.depois.id) + 1 :]
        if self.maximo is not None:
            docs = docs[: self.maximo]
        if self.selecionados is not None:
            self.campos.append(self.selecionados)
            docs = [
                _Doc({k: v for k, v in d.dados.items() if k in self.selecionados})
                for d in docs
            ]
        self.leituras.append(len(docs))
        return docs


class _Colecao(_Consulta):
    def __init__(self, jobs: list[Job]) -> None:
        super().__init__(
            [
                _Doc(j.model_dump())
                for j in sorted(jobs, key=lambda j: j.id, reverse=True)
            ],
            [],
            [],
        )

    def document(self, id_: str) -> "_Referencia":
        return _Referencia(next(d for d in self.docs if d.id == id_))


class _Referencia:
    def __init__(self, doc: _Doc) -> None:
        self.doc = doc

    def get(self) -> Any:
        doc = self.doc
        return type(
            "Snap", (), {"exists": True, "id": doc.id, "to_dict": doc.to_dict}
        )()


class _Cliente:
    def __init__(self, colecao: _Colecao) -> None:
        self.colecao = colecao

    def collection(self, _nome: str) -> _Colecao:
        return self.colecao


def _repositorio(jobs: list[Job]) -> tuple[RepositorioFirestore, _Colecao]:
    colecao = _Colecao(jobs)
    repositorio = RepositorioFirestore(_Cliente(colecao))  # type: ignore[arg-type]
    # O cursor é lido como documento; a conversão é a do próprio fake.
    return repositorio, colecao


def _acervo(jobs: list[Job], **filtro: Any) -> tuple[list[str], list[str | None]]:
    repositorio, _ = _repositorio(jobs)
    ids: list[str] = []
    cursores: list[str | None] = []
    cursor = None
    while True:
        pagina = repositorio.consultar(FiltroDeJobs(cursor=cursor, **filtro))
        ids += [j.id for j in pagina.jobs]
        cursores.append(pagina.proximo_cursor)
        cursor = pagina.proximo_cursor
        if cursor is None:
            return ids, cursores


def test_paginar_nao_perde_nem_repete_com_a_lixeira_no_meio() -> None:
    jobs = [_job(n, lixeira=LIXEIRA) if n % 3 == 0 else _job(n) for n in range(30)]
    ids, _ = _acervo(jobs, limite=4)
    esperado = [
        j.id
        for j in sorted(jobs, key=lambda j: j.id, reverse=True)
        if j.lixeira is None
    ]
    assert ids == esperado


def test_palavra_rara_acha_so_quem_tem_depois_da_primeira() -> None:
    jobs = [_job(n, palavras=["a", "b"] if n % 7 == 0 else ["a"]) for n in range(30)]
    ids, _ = _acervo(jobs, limite=2, palavras=("a", "b"))
    assert ids == ["j028", "j021", "j014", "j007", "j000"]


def test_o_cursor_e_o_do_ultimo_examinado_e_nao_o_do_ultimo_aprovado() -> None:
    # j004 e j003 estão na lixeira: depois de j005 (aprovado), o extra só aparece em j002.
    jobs = [_job(n, lixeira=LIXEIRA if n in (3, 4) else None) for n in range(6)]
    repositorio, _ = _repositorio(jobs)

    pagina = repositorio.consultar(FiltroDeJobs(limite=1))

    assert [j.id for j in pagina.jobs] == ["j005"]
    assert pagina.proximo_cursor == "j003"


def test_o_teto_devolve_pagina_vazia_com_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.nuvem.TETO_DE_CANDIDATOS", 30)
    jobs = [_job(n, lixeira=LIXEIRA if n >= 10 else None) for n in range(100)]
    repositorio, colecao = _repositorio(jobs)

    pagina = repositorio.consultar(FiltroDeJobs(limite=5))

    assert pagina.jobs == []
    assert pagina.proximo_cursor == "j070"
    assert sum(colecao.leituras) == 30
    # Seguindo o cursor o acervo continua, sem pular ninguém.
    ids, _ = _acervo(jobs, limite=5)
    assert ids == [f"j{n:03}" for n in range(9, -1, -1)]


def test_o_teto_nao_corta_uma_pagina_que_enche_antes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.nuvem.TETO_DE_CANDIDATOS", 30)
    repositorio, _ = _repositorio([_job(n) for n in range(100)])

    pagina = repositorio.consultar(FiltroDeJobs(limite=5))

    assert [j.id for j in pagina.jobs] == ["j099", "j098", "j097", "j096", "j095"]
    assert pagina.proximo_cursor == "j095"


def test_sem_limite_a_leitura_e_completa_e_sem_teto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.nuvem.TETO_DE_CANDIDATOS", 3)
    jobs = [_job(n, lixeira=LIXEIRA if n % 2 else None) for n in range(40)]
    repositorio, _ = _repositorio(jobs)

    pagina = repositorio.consultar(FiltroDeJobs(na_lixeira=None))
    so_o_acervo = repositorio.consultar(FiltroDeJobs())

    assert len(pagina.jobs) == 40
    assert len(so_o_acervo.jobs) == 20
    assert pagina.proximo_cursor is None


def test_a_lista_do_acervo_pede_so_os_campos_da_lista() -> None:
    repositorio, colecao = _repositorio([_job(n, cortes_ms=[1, 2]) for n in range(3)])

    lista = repositorio.consultar(FiltroDeJobs(limite=2, so_os_da_lista=True))
    inteira = repositorio.consultar(FiltroDeJobs(limite=2))

    assert len(colecao.campos) == 1
    assert "cortes_ms" not in colecao.campos[0]
    assert {"id", "lixeira", "criado_em", "etapas", "criado_por_email"} <= set(
        colecao.campos[0]
    )
    assert lista.jobs[0].cortes_ms is None
    assert inteira.jobs[0].cortes_ms == [1, 2]


def test_os_campos_da_lista_cobrem_o_job_resumido_e_os_obrigatorios_do_job() -> None:
    # Um campo novo no `JobResumido` que não entre no `select()` chegaria vazio na lista.
    from api.jobs import JobResumido
    from api.nuvem import _CAMPOS_DA_LISTA

    do_resumo = set(JobResumido.model_fields) - {
        "enviado_por",
        "capa_url",
        "reprocessavel_ate",
    }
    obrigatorios = {n for n, c in Job.model_fields.items() if c.is_required()}

    assert do_resumo | obrigatorios | {"capa", "sistema", "criado_por_email"} <= (
        _CAMPOS_DA_LISTA
    )
