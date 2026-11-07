"""Conferência da limpeza do Artifact Registry (#456): simula as regras KEEP e DELETE, só lendo.

`make conferir-limpeza-de-imagens` lista as versões dos repositórios `mam` e `mam-gpu`, as imagens
que o Cloud Run usa agora e aplica as regras do Terraform (output `limpeza_de_imagens`): mostra o
que seria apagado e o que fica. Sai com 1 se a limpeza apagaria uma versão em uso ou a da volta
(a tag `volta`, posta pelo scripts/deploy-dev.sh no build que o testar-jobs-gpu.sh restauraria).
Nada aqui escreve na nuvem: só `gcloud ... list/describe` e `terraform output`.
"""

import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).parents[1]


@dataclass(frozen=True)
class Regras:
    """As regras do Terraform: N últimas por imagem, cache e tags guardados, idade mínima."""

    manter_ultimas: int
    idade_minima_s: int
    pacotes_do_cache: tuple[str, ...]
    tags_protegidas: tuple[str, ...]
    tag_da_volta: str

    @classmethod
    def do_terraform(cls, saida: dict[str, Any]) -> "Regras":
        return cls(
            manter_ultimas=int(saida["manter_ultimas"]),
            idade_minima_s=int(saida["idade_minima_s"]),
            pacotes_do_cache=tuple(saida["pacotes_do_cache"]),
            tags_protegidas=tuple(saida["tags_protegidas"]),
            tag_da_volta=saida["tag_da_volta"],
        )


@dataclass(frozen=True)
class Versao:
    repositorio: str
    pacote: str  # o nome da imagem dentro do repositório, como `transcricao-gpu`
    digest: str
    criada_em: datetime
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Veredito:
    versao: Versao
    apagar: bool
    motivo: str
    em_uso: bool = False
    da_volta: bool = False

    @property
    def em_risco(self) -> bool:
        """A limpeza apagaria uma versão que o Cloud Run usa ou a da volta."""
        return self.apagar and (self.em_uso or self.da_volta)


@dataclass
class Simulacao:
    vereditos: list[Veredito] = field(default_factory=list)

    @property
    def em_risco(self) -> list[Veredito]:
        return [v for v in self.vereditos if v.em_risco]


def simular(
    versoes: Sequence[Versao],
    regras: Regras,
    agora: datetime,
    em_uso: set[tuple[str, str]] = frozenset(),  # type: ignore[assignment]
) -> Simulacao:
    """Aplica as regras como o Google: KEEP vence DELETE; o resto apaga com mais de N s.

    `em_uso` são pares (repositório, digest) lidos do Cloud Run. O registro não os conhece: se
    uma regra KEEP não os guarda, eles aparecem com `em_risco`.
    """
    ultimas: set[tuple[str, str, str]] = set()
    por_pacote: dict[tuple[str, str], list[Versao]] = {}
    for v in versoes:
        por_pacote.setdefault((v.repositorio, v.pacote), []).append(v)
    for (repositorio, pacote), grupo in por_pacote.items():
        recentes = sorted(grupo, key=lambda v: v.criada_em, reverse=True)
        ultimas |= {
            (repositorio, pacote, v.digest) for v in recentes[: regras.manter_ultimas]
        }

    vereditos = []
    for v in versoes:
        motivo = _guarda(v, regras, ultimas)
        apagar = motivo is None
        if apagar:
            idade = (agora - v.criada_em).total_seconds()
            if idade <= regras.idade_minima_s:
                apagar, motivo = False, "tem menos de 14 dias: a regra não alcança"
            else:
                motivo = "sem regra que a guarde e com mais de 14 dias"
        vereditos.append(
            Veredito(
                versao=v,
                apagar=apagar,
                motivo=motivo or "",
                em_uso=(v.repositorio, v.digest) in em_uso,
                da_volta=regras.tag_da_volta in v.tags,
            )
        )
    return Simulacao(vereditos)


def _guarda(
    v: Versao, regras: Regras, ultimas: set[tuple[str, str, str]]
) -> str | None:
    """O motivo da regra KEEP que guarda a versão, ou None se nenhuma a guarda."""
    if (v.repositorio, v.pacote, v.digest) in ultimas:
        return f"entre as {regras.manter_ultimas} mais recentes da imagem"
    if v.tags and any(v.pacote.startswith(p) for p in regras.pacotes_do_cache):
        return "cache das camadas com tag"
    for tag in v.tags:
        if any(tag.startswith(p) for p in regras.tags_protegidas):
            return f"tag protegida `{tag}`"
    return None


def relatorio(simulacao: Simulacao) -> str:
    linhas = []
    grupos: dict[tuple[str, str], list[Veredito]] = {}
    for v in simulacao.vereditos:
        grupos.setdefault((v.versao.repositorio, v.versao.pacote), []).append(v)
    for (repositorio, pacote), vereditos in sorted(grupos.items()):
        apagar = sum(v.apagar for v in vereditos)
        linhas.append(
            f"{repositorio}/{pacote}: {len(vereditos) - apagar} ficam, {apagar} seriam apagadas"
        )
        for v in sorted(vereditos, key=lambda v: v.versao.criada_em, reverse=True):
            marcas = [
                m
                for m, ligada in (("EM USO", v.em_uso), ("VOLTA", v.da_volta))
                if ligada
            ]
            marca = f" [{' '.join(marcas)}]" if marcas else ""
            tags = ",".join(v.versao.tags) or "-"
            acao = "APAGA" if v.apagar else "fica "
            linhas.append(
                f"  {acao} {v.versao.digest[:19]} {v.versao.criada_em:%Y-%m-%d} "
                f"tags={tags}{marca}  ({v.motivo})"
            )
    total = len(simulacao.vereditos)
    apagar = sum(v.apagar for v in simulacao.vereditos)
    linhas.append(f"Total: {total - apagar} ficam, {apagar} seriam apagadas.")
    for v in simulacao.em_risco:
        o_que = "EM USO" if v.em_uso else "DA VOLTA"
        linhas.append(
            f"ERRO: a limpeza apagaria uma versão {o_que}: {v.versao.repositorio}/"
            f"{v.versao.pacote}@{v.versao.digest}. Falta tag protegida: rode o deploy-dev."
        )
    return "\n".join(linhas)


# --- leitura (só `list`, `describe` e `terraform output`) -------------------------------------


def _data(texto: str) -> datetime:
    """`2026-10-29T12:00:00Z` ou com fração e deslocamento; sem fuso vale UTC."""
    t = datetime.fromisoformat(texto)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def versoes_do_gcloud(
    repositorio: str, itens: Sequence[dict[str, Any]]
) -> list[Versao]:
    """Converte o JSON de `gcloud artifacts docker images list --include-tags`."""
    versoes = []
    for item in itens:
        tags = item.get("tags") or ()
        if isinstance(tags, str):
            tags = [t for t in tags.split(",") if t]
        versoes.append(
            Versao(
                repositorio=repositorio,
                pacote=str(item["package"]).removeprefix(repositorio).strip("/"),
                digest=item["version"],
                criada_em=_data(item["createTime"]),
                tags=tuple(tags),
            )
        )
    return versoes


def em_uso_do_cloud_run(
    repositorios: Sequence[str], recursos: Sequence[dict[str, Any]]
) -> set[tuple[str, str]]:
    """Os pares (repositório, digest) das imagens dos serviços e Jobs, fixadas por digest."""
    achados: set[tuple[str, str]] = set()
    for recurso in recursos:
        template = recurso.get("spec", {}).get("template", {}).get("spec", {})
        # Serviço: spec.template.spec.containers; Job: spec.template.spec.template.spec.containers.
        conteineres = template.get("containers") or (
            template.get("template", {}).get("spec", {}).get("containers", [])
        )
        for c in conteineres:
            caminho, _, digest = c.get("image", "").partition("@")
            for r in repositorios:
                if digest and caminho.startswith(r + "/"):
                    achados.add((r, digest))
    return achados


def _json(comando: list[str]) -> object:
    return json.loads(
        subprocess.run(comando, check=True, capture_output=True, text=True).stdout
    )


def main(
    ler: Callable[[list[str]], object] = _json,
    agora: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    saida = ler(["terraform", f"-chdir={RAIZ / 'infra'}", "output", "-json"])
    assert isinstance(saida, dict)
    regras = Regras.do_terraform(saida["limpeza_de_imagens"]["value"])
    repositorios = [saida["repositorio"]["value"], saida["repositorio_gpu"]["value"]]
    versoes: list[Versao] = []
    recursos: list[dict[str, Any]] = []
    for repositorio in repositorios:
        itens = ler(
            ["gcloud", "artifacts", "docker", "images", "list", repositorio,
             "--include-tags", "--format=json"]
        )  # fmt: skip
        assert isinstance(itens, list)
        versoes += versoes_do_gcloud(repositorio, itens)
        # O host do repositório é `<região>-docker.pkg.dev`: o Cloud Run está nessa região.
        regiao = repositorio.split("-docker.pkg.dev")[0]
        for tipo in ("services", "jobs"):
            lidos = ler(
                ["gcloud", "run", tipo, "list", "--region", regiao, "--format=json"]
            )
            assert isinstance(lidos, list)
            recursos += lidos
    em_uso = em_uso_do_cloud_run(repositorios, recursos)
    simulacao = simular(versoes, regras, agora(), em_uso)
    print(relatorio(simulacao))
    return 1 if simulacao.em_risco else 0


if __name__ == "__main__":
    sys.exit(main())
