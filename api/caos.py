"""Roteiro de caos da API (E7, #274): um Job só por chave de idempotência, e cada sistema
vendo só os próprios Jobs.

O roteiro fala com a API por uma porta (`Api`), então o mesmo texto roda no teste local
(`api/tests/test_caos.py`, contra o app e os emuladores) e contra o dev (`make caos-dev`,
`api/caos_dev.py`, por HTTP com duas chaves de sistemas de teste).
"""

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

PARALELISMO = 12
CORPO = {"nome": "caos.mp4", "tamanho_bytes": 1000, "tipo": "video/mp4"}


class Api(Protocol):
    def requisitar(
        self,
        metodo: str,
        caminho: str,
        *,
        sistema: str,
        corpo: dict[str, Any] | None = None,
        chave: str | None = None,
    ) -> tuple[int, Any]:
        """Chama `/v1<caminho>` com a chave do sistema e, se vier, o `Idempotency-Key`.
        Devolve o status e o JSON (ou `None`)."""
        ...


@dataclass
class Verificacao:
    nome: str
    ok: bool
    detalhe: str = ""


@dataclass
class Relatorio:
    verificacoes: list[Verificacao] = field(default_factory=list)
    jobs_criados: list[str] = field(default_factory=list)

    def conferir(self, nome: str, ok: bool, detalhe: str = "") -> None:
        self.verificacoes.append(Verificacao(nome, ok, "" if ok else detalhe))

    @property
    def passou(self) -> bool:
        return all(v.ok for v in self.verificacoes)

    def texto(self) -> str:
        linhas = [
            f"{'ok    ' if v.ok else 'FALHOU'}  {v.nome}"
            + (f": {v.detalhe}" if v.detalhe else "")
            for v in self.verificacoes
        ]
        veredito = "passou" if self.passou else "FALHOU"
        return "\n".join([*linhas, "", f"Teste de caos: {veredito}"])


def em_paralelo(
    n: int, chamada: Callable[[], tuple[int, Any]]
) -> list[tuple[int, Any]]:
    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result() for f in [pool.submit(chamada) for _ in range(n)]]


def roteiro(
    api: Api, sistema_a: str, sistema_b: str, paralelismo: int = PARALELISMO
) -> Relatorio:
    """Roda o roteiro e cancela no fim os Jobs que criou. Cada rodada usa chaves novas."""
    relatorio = Relatorio()
    chave = f"caos-{uuid.uuid4()}"

    def criar(sistema: str, chave: str | None, corpo: dict[str, Any] = CORPO) -> Any:
        return api.requisitar(
            "POST", "/jobs", sistema=sistema, corpo=corpo, chave=chave
        )

    # 1. O mesmo envio repetido ao mesmo tempo, com a mesma chave: um Job só.
    respostas = em_paralelo(paralelismo, lambda: criar(sistema_a, chave))
    status = sorted(s for s, _ in respostas)
    ids = {c["id"] for s, c in respostas if s in (200, 202)}
    relatorio.conferir(
        "mesma chave em paralelo: uma criação (202) e o resto repetição (200)",
        status == [200] * (paralelismo - 1) + [202],
        f"status {status}",
    )
    relatorio.conferir(
        "mesma chave em paralelo: todas as respostas trazem o mesmo Job",
        len(ids) == 1,
        f"{len(ids)} Jobs: {sorted(ids)}",
    )
    job_a = next(iter(ids), "")
    relatorio.jobs_criados.append(job_a)

    # 2. A repetição tardia (o cliente que não viu a resposta) acha o mesmo Job.
    status_tardio, tardia = criar(sistema_a, chave)
    relatorio.conferir(
        "repetição tardia: 200 e o mesmo Job",
        status_tardio == 200 and tardia.get("id") == job_a,
        f"{status_tardio} {tardia}",
    )

    # 3. A mesma chave com outro corpo é erro, e não cria Job.
    status_outro, _ = criar(sistema_a, chave, {**CORPO, "tamanho_bytes": 2000})
    relatorio.conferir(
        "mesma chave com outro corpo: 409", status_outro == 409, str(status_outro)
    )

    # 4. O outro sistema com a mesma chave e o mesmo corpo tem o Job dele.
    status_b, criado_b = criar(sistema_b, chave)
    job_b = criado_b.get("id", "") if status_b == 202 else ""
    relatorio.jobs_criados.append(job_b)
    relatorio.conferir(
        "mesma chave em outro sistema: 202 e outro Job",
        status_b == 202 and job_b not in ("", job_a),
        f"{status_b} {criado_b}",
    )

    # 5. Cada sistema vê só os próprios Jobs.
    for dono, outro, meu, alheio in (
        (sistema_a, sistema_b, job_a, job_b),
        (sistema_b, sistema_a, job_b, job_a),
    ):
        lido, _ = api.requisitar("GET", f"/jobs/{meu}", sistema=dono)
        espiado, _ = api.requisitar("GET", f"/jobs/{alheio}", sistema=dono)
        _, lista = api.requisitar("GET", "/jobs", sistema=dono)
        ids_da_lista = {j["id"] for j in lista or []}
        relatorio.conferir(
            f"isolamento ({dono}): lê o próprio Job e recebe 404 no de {outro}",
            lido == 200 and espiado == 404,
            f"próprio {lido}, alheio {espiado}",
        )
        relatorio.conferir(
            f"isolamento ({dono}): a lista não traz Job de {outro}",
            alheio not in ids_da_lista and meu in ids_da_lista,
            f"lista {sorted(ids_da_lista)}",
        )
        cancelado, _ = api.requisitar("DELETE", f"/jobs/{alheio}", sistema=dono)
        relatorio.conferir(
            f"isolamento ({dono}): não cancela o Job de {outro}",
            cancelado == 404,
            str(cancelado),
        )

    # 6. Fecha: cancela os Jobs de teste; a repetição depois disso ainda devolve o mesmo Job.
    for dono, job in ((sistema_a, job_a), (sistema_b, job_b)):
        api.requisitar("DELETE", f"/jobs/{job}", sistema=dono)
    status_final, final = criar(sistema_a, chave)
    relatorio.conferir(
        "repetição depois do cancelamento: 200, o mesmo Job, sem novo upload",
        status_final == 200
        and final.get("id") == job_a
        and final.get("url_de_upload") is None,
        f"{status_final} {final}",
    )
    return relatorio
