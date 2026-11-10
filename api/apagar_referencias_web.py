"""`make apagar-referencias-web`: migração única da retirada das referências na web (#327).

Apaga o que a busca de fotos e a comparação de rostos deixaram (dado biométrico, LGPD
art. 11): as fotos do bucket de referências (`referencias/` e `palpites/`), os rostos
`origem=web` do catálogo, as sugestões de perfil que a comparação propunha (coleção
`sugestoes_de_perfil`), os objetos `<job>.comparacao.json` e
`<job>.nomes_a_buscar.json` e a fonte `referencia` das Decupagens gravadas (o nome que só
tinha essa prova volta a palpite). Imprime a contagem antes e depois; rodar de novo não
apaga nada a mais. Usa as credenciais da máquina; a regra é testada com dublês.
"""

import json
import logging
import os
import sys
from collections.abc import Iterable
from dataclasses import astuple, dataclass, fields
from typing import Any, Protocol

from google.cloud import firestore
from google.cloud.exceptions import NotFound
from google.cloud.storage import Client as ClienteStorage

from api.bancos import cliente_do_firestore
from api.catalogo import Catalogo
from api.nuvem import (
    CatalogoFirestore,
    ReferenciasStorage,
    RepositorioFirestore,
    _gravar_os_itens,
    objeto_da_decupagem,
)

log = logging.getLogger(__name__)

PREFIXOS_DAS_FOTOS = ("referencias/", "palpites/")
COLECAO_DOS_PERFIS_PROPOSTOS = "sugestoes_de_perfil"
FONTE_QUE_SAIU = "referencia"


class Fotos(Protocol):
    def contar_prefixo(self, prefixo: str) -> int: ...

    def apagar_prefixo(self, prefixo: str) -> None: ...


class PerfisPropostos(Protocol):
    def contar(self) -> int: ...

    def apagar_todos(self) -> None: ...


class Decupagens(Protocol):
    def ler(self, job_id: str) -> bytes | None: ...

    def gravar(self, job_id: str, conteudo: str) -> None: ...

    def contar_registros_da_comparacao(self, job_id: str) -> int:
        """Quantos de `<job>.comparacao.json` e `<job>.nomes_a_buscar.json` existem."""
        ...

    def apagar_registros_da_comparacao(self, job_id: str) -> None: ...


@dataclass(frozen=True)
class Contagem:
    fotos_de_referencia: int
    fotos_de_palpite: int
    rostos_da_web: int
    perfis_propostos: int
    decupagens_com_a_fonte_referencia: int
    registros_da_comparacao: int

    def __str__(self) -> str:
        return "\n".join(
            f"  {f.name.replace('_', ' ')}: {v}"
            for f, v in zip(fields(self), astuple(self), strict=True)
        )


def tirar_a_fonte_referencia(dados: dict[str, Any]) -> bool:
    """Tira `referencia` de `fontes_do_nome` na Decupagem lida, mudando `dados`; a pessoa
    que fica sem fonte e estava confirmada volta a palpite e perde o `catalogo_id` que a
    confirmação gravou (a da revisora fica como está). Diz se mudou alguma pessoa."""
    mudou = False
    for pessoa in dados.get("pessoas") or []:
        fontes = pessoa.get("fontes_do_nome") if isinstance(pessoa, dict) else None
        if not isinstance(fontes, list) or FONTE_QUE_SAIU not in fontes:
            continue
        pessoa["fontes_do_nome"] = [f for f in fontes if f != FONTE_QUE_SAIU]
        if (
            not pessoa["fontes_do_nome"]
            and pessoa.get("estado_do_nome") == "confirmado"
            and pessoa.get("origem") != "revisao"
        ):
            pessoa["estado_do_nome"] = "palpite"
            pessoa["catalogo_id"] = None
        mudou = True
    return mudou


def _lida(job_id: str, conteudo: bytes | None) -> dict[str, Any] | None:
    """A Decupagem gravada; a que não abre fica de fora, com aviso, sem parar a migração."""
    if conteudo is None:
        return None
    try:
        dados = json.loads(conteudo)
    except ValueError:
        log.warning("decupagem de %s não lida; fica como está", job_id)
        return None
    return dados if isinstance(dados, dict) else None


def _com_a_fonte(job_id: str, conteudo: bytes | None) -> bool:
    dados = _lida(job_id, conteudo)
    return dados is not None and tirar_a_fonte_referencia(dados)


def _pessoas_do_catalogo(catalogo: Catalogo) -> list[Any]:
    return [*catalogo.todas(), *catalogo.na_lixeira()]


def contar(
    *,
    fotos: Fotos,
    catalogo: Catalogo,
    perfis_propostos: PerfisPropostos,
    decupagens: Decupagens,
    job_ids: Iterable[str],
) -> Contagem:
    ids = list(job_ids)
    return Contagem(
        fotos_de_referencia=fotos.contar_prefixo(PREFIXOS_DAS_FOTOS[0]),
        fotos_de_palpite=fotos.contar_prefixo(PREFIXOS_DAS_FOTOS[1]),
        rostos_da_web=sum(
            1
            for p in _pessoas_do_catalogo(catalogo)
            for r in p.rostos
            if r.origem == "web"
        ),
        perfis_propostos=perfis_propostos.contar(),
        decupagens_com_a_fonte_referencia=sum(
            _com_a_fonte(i, decupagens.ler(i)) for i in ids
        ),
        registros_da_comparacao=sum(
            decupagens.contar_registros_da_comparacao(i) for i in ids
        ),
    )


def apagar(
    *,
    fotos: Fotos,
    catalogo: Catalogo,
    perfis_propostos: PerfisPropostos,
    decupagens: Decupagens,
    job_ids: Iterable[str],
) -> None:
    for prefixo in PREFIXOS_DAS_FOTOS:
        fotos.apagar_prefixo(prefixo)
    for pessoa in _pessoas_do_catalogo(catalogo):
        if any(r.origem == "web" for r in pessoa.rostos):
            catalogo.definir_rostos(
                pessoa.id, [r for r in pessoa.rostos if r.origem != "web"]
            )
    perfis_propostos.apagar_todos()
    for job_id in job_ids:
        dados = _lida(job_id, decupagens.ler(job_id))
        if dados is not None and tirar_a_fonte_referencia(dados):
            decupagens.gravar(job_id, json.dumps(dados, ensure_ascii=False))
        decupagens.apagar_registros_da_comparacao(job_id)


class PerfisPropostosFirestore:
    def __init__(self, cliente: firestore.Client) -> None:
        self._colecao = cliente.collection(COLECAO_DOS_PERFIS_PROPOSTOS)

    def contar(self) -> int:
        return sum(1 for _ in self._colecao.stream())

    def apagar_todos(self) -> None:
        for doc in self._colecao.stream():
            doc.reference.delete()


class DecupagensNoStorage:
    def __init__(self, cliente: ClienteStorage, bucket: str) -> None:
        self._cliente = cliente
        self._bucket = bucket

    @staticmethod
    def _registros(job_id: str) -> list[str]:
        return [f"{job_id}.comparacao.json", f"{job_id}.nomes_a_buscar.json"]

    def ler(self, job_id: str) -> bytes | None:
        blob = self._cliente.bucket(self._bucket).blob(objeto_da_decupagem(job_id))
        try:
            conteudo: bytes = blob.download_as_bytes()
            return conteudo
        except NotFound:
            return None

    def gravar(self, job_id: str, conteudo: str) -> None:
        self._cliente.bucket(self._bucket).blob(
            objeto_da_decupagem(job_id)
        ).upload_from_string(conteudo, content_type="application/json")
        _gravar_os_itens(self._cliente, self._bucket, job_id, conteudo)

    def contar_registros_da_comparacao(self, job_id: str) -> int:
        return sum(
            self._cliente.bucket(self._bucket).blob(o).exists()
            for o in self._registros(job_id)
        )

    def apagar_registros_da_comparacao(self, job_id: str) -> None:
        for objeto in self._registros(job_id):
            try:
                self._cliente.bucket(self._bucket).blob(objeto).delete()
            except NotFound:
                pass


if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID") or sys.exit("defina GCP_PROJECT_ID")
    cliente = cliente_do_firestore(projeto)
    storage = ClienteStorage(project=projeto)
    tudo: dict[str, Any] = {
        "fotos": ReferenciasStorage(storage, os.environ["BUCKET_REFERENCIAS"]),
        "catalogo": CatalogoFirestore(cliente),
        "perfis_propostos": PerfisPropostosFirestore(cliente),
        "decupagens": DecupagensNoStorage(storage, os.environ["BUCKET_DECUPAGENS"]),
        "job_ids": [j.id for j in RepositorioFirestore(cliente).listar()],
    }
    print(f"Antes:\n{contar(**tudo)}")
    apagar(**tudo)
    print(f"Depois:\n{contar(**tudo)}")
