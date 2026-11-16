"""Job da identificação (modelo forte, #112), com dublês em memória.

O ffmpeg é trocado por `quadros_falsos` e o Gemini, pelo `TransporteFalso`.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from api import identificacao_job
from api.catalogo import CatalogoEmMemoria
from api.correcoes import Ancora, Correcao
from api.decupagem import Comercial, Decupagem
from api.gemini import ErroHttp
from api.jobs import RepositorioEmMemoria
from api.juncao_de_pessoas import chave_da_pessoa
from api.modelo_do_job import Job
from api.tests.test_gemini import TransporteFalso
from api.tests.test_identificacao import decupagem, gc, pessoa, whisper

BASE = datetime(2026, 10, 31, tzinfo=UTC)
BARBA = "não identificado, homem de barba"


class DecupagensEmMemoria:
    def __init__(self, atual: Decupagem | None, com_copia: bool = True) -> None:
        self.atual = atual
        self.com_copia = com_copia
        self.gravada: Decupagem | None = None
        self.downloads = 0
        self.consultas = 0

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        return self.atual

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> bool:
        self.downloads += 1
        return self.com_copia

    def copia_limpa_existe(self, job_id: str) -> bool:
        self.consultas += 1
        return self.com_copia

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None:
        self.gravada = Decupagem.model_validate_json(conteudo)


class TranscricoesEmMemoria:
    def __init__(self, transcricao: Any = None) -> None:
        self.transcricao = transcricao or whisper(("oi", 1.0))

    def ler_transcricao(self, job_id: str) -> Any:
        return self.transcricao


def repositorio(estado: str = "concluido") -> RepositorioEmMemoria:
    r = RepositorioEmMemoria()
    r.salvar(
        Job(
            id="job-1",
            nome="a.mp4",
            tamanho_bytes=10,
            sha256="a" * 64,
            duracao_s=60.0,
            estado=estado,  # type: ignore[arg-type]
            criado_por="uid-1",
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )
    return r


@pytest.fixture(autouse=True)
def quadros_falsos(monkeypatch: pytest.MonkeyPatch) -> None:
    def falsos(video: Path, instantes: Sequence[int]) -> list[bytes]:
        return [f"quadro-{i}".encode() for i in instantes]

    monkeypatch.setattr(identificacao_job, "extrair_quadros", falsos)


def com_gc() -> Decupagem:
    return decupagem(
        [pessoa("pes01", BARBA, [(100_000, 110_000)], fontes_do_nome=[])],
        [gc("Leão Lobo", 101_000, 108_000)],
    )


def identificar(
    d: Decupagem | None,
    *respostas: str | Exception,
    estado: str = "concluido",
    com_copia: bool = True,
    tmp_path: Path,
    repo: RepositorioEmMemoria | None = None,
    correcoes: Any = None,
    transcricao: Any = None,
    tolerancia_ms: int = 2000,
) -> tuple[str, DecupagensEmMemoria]:
    decupagens = DecupagensEmMemoria(d, com_copia)
    resultado = identificacao_job.executar(
        "job-1",
        repo or repositorio(estado),
        decupagens,
        TransporteFalso(*respostas),
        TranscricoesEmMemoria(transcricao),
        CatalogoEmMemoria(),
        tmp_path,
        correcoes=correcoes,
        tolerancia_ms=tolerancia_ms,
    )
    return resultado, decupagens


def nome_do_modelo_forte() -> str:
    return json.dumps(
        {
            "resultado": "nome_com_prova",
            "nome": "Leão Lobo",
            "prova": "gc",
            "tempo_da_prova": "01:41",
        }
    )


def test_identificacao_regrava_a_decupagem_com_o_nome_confirmado(
    tmp_path: Path,
) -> None:
    resultado, decupagens = identificar(
        com_gc(), nome_do_modelo_forte(), tmp_path=tmp_path
    )

    assert resultado == "identificado"
    assert decupagens.gravada is not None
    assert decupagens.gravada.pessoas[0].nome == "Leão Lobo"


def test_identificacao_ignora_job_que_nao_esta_concluido(tmp_path: Path) -> None:
    resultado, decupagens = identificar(
        com_gc(), estado="analisando", tmp_path=tmp_path
    )

    assert resultado == "ignorado"
    assert decupagens.gravada is None


@pytest.mark.parametrize("sem", ["decupagem", "copia"])
def test_identificacao_sem_decupagem_ou_sem_copia_limpa_nao_muda_nada(
    sem: str, tmp_path: Path
) -> None:
    resultado, decupagens = identificar(
        None if sem == "decupagem" else com_gc(),
        com_copia=sem != "copia",
        tmp_path=tmp_path,
    )

    assert resultado == "sem_alteracao"
    assert decupagens.gravada is None


def test_falha_do_modelo_forte_nao_derruba_a_execucao_e_mantem_a_decupagem(
    tmp_path: Path,
) -> None:
    repo = repositorio()

    resultado, decupagens = identificar(
        com_gc(), ErroHttp(400), tmp_path=tmp_path, repo=repo
    )

    assert resultado == "incompleto"
    assert decupagens.gravada is not None
    assert decupagens.gravada.pessoas[0].nome == BARBA
    assert_etapa(repo, "identificacao", "falhou")


def assert_etapa(repo: RepositorioEmMemoria, nome: Any, resultado: str) -> None:
    job = repo.obter("job-1")
    assert job is not None
    assert job.estado == "concluido"
    assert job.etapa_atual is None
    etapa = job.etapas[nome]
    assert etapa.resultado == resultado
    assert etapa.fim is not None and etapa.fim >= etapa.inicio
    assert list(job.etapas) == [nome]


def test_identificacao_conclui_a_etapa_sem_mudar_o_estado_do_job(
    tmp_path: Path,
) -> None:
    repo = repositorio()

    identificar(com_gc(), nome_do_modelo_forte(), tmp_path=tmp_path, repo=repo)

    assert_etapa(repo, "identificacao", "concluida")


@pytest.mark.parametrize("sem", ["decupagem", "copia"])
def test_identificacao_sem_decupagem_ou_copia_deixa_a_etapa_falhou(
    sem: str, tmp_path: Path
) -> None:
    repo = repositorio()

    identificar(
        None if sem == "decupagem" else com_gc(),
        com_copia=sem != "copia",
        tmp_path=tmp_path,
        repo=repo,
    )

    assert_etapa(repo, "identificacao", "falhou")


def test_identificacao_de_job_que_nao_esta_concluido_nao_abre_etapa(
    tmp_path: Path,
) -> None:
    repo = repositorio("analisando")

    identificar(com_gc(), tmp_path=tmp_path, repo=repo)

    job = repo.obter("job-1")
    assert job is not None and job.etapas == {} and job.etapa_atual is None


def test_erro_inesperado_deixa_a_etapa_falhou_e_sobe(tmp_path: Path) -> None:
    repo = repositorio()

    class Quebrada(DecupagensEmMemoria):
        def ler_decupagem(self, job_id: str) -> Decupagem | None:
            raise RuntimeError("storage fora")

    with pytest.raises(RuntimeError):
        identificacao_job.executar(
            "job-1",
            repo,
            Quebrada(None),
            TransporteFalso(),
            TranscricoesEmMemoria(),
            CatalogoEmMemoria(),
            tmp_path,
        )

    assert_etapa(repo, "identificacao", "falhou")


DUAS_SEM_NOME = [
    pessoa(
        "pes01",
        "Não identificado, blusa vermelha",
        [(100_000, 110_000)],
        fontes_do_nome=[],
        janela=0,
    ),
    pessoa(
        "pes02",
        "Não identificado, blusa vermelha",
        [(400_000, 410_000)],
        fontes_do_nome=[],
        janela=1,
    ),
]


def test_a_juncao_roda_depois_do_modelo_forte_e_a_decupagem_sai_com_as_origens(
    tmp_path: Path,
) -> None:
    # O modelo forte não nomeia ninguém; a junção une as duas.
    nao_identificado = json.dumps(
        {
            "resultado": "nao_identificado",
            "nome": None,
            "prova": None,
            "tempo_da_prova": None,
        }
    )

    resultado, decupagens = identificar(
        decupagem(DUAS_SEM_NOME), nao_identificado, nao_identificado, tmp_path=tmp_path
    )

    assert resultado == "identificado"
    assert decupagens.gravada is not None
    [p] = decupagens.gravada.pessoas
    assert [o.id for o in p.origens] == ["pes01", "pes02"]


def test_a_separacao_de_uma_pessoa_na_tela_impede_a_juncao_no_reprocessamento(
    tmp_path: Path,
) -> None:
    nao_identificado = json.dumps(
        {
            "resultado": "nao_identificado",
            "nome": None,
            "prova": None,
            "tempo_da_prova": None,
        }
    )
    chaves = [chave_da_pessoa(p) for p in decupagem(DUAS_SEM_NOME).pessoas]

    class Separacoes:
        def listar(self, job_id: str) -> list[Correcao]:
            return [_separacao(chaves[0], chaves[1])]

    _, decupagens = identificar(
        decupagem(DUAS_SEM_NOME),
        nao_identificado,
        nao_identificado,
        tmp_path=tmp_path,
        correcoes=Separacoes(),
    )

    assert decupagens.gravada is not None
    assert [p.id for p in decupagens.gravada.pessoas] == ["pes01", "pes02"]


def test_pessoa_renomeada_na_tela_nao_entra_na_juncao_do_reprocessamento(
    tmp_path: Path,
) -> None:
    nao_identificado = json.dumps(
        {
            "resultado": "nao_identificado",
            "nome": None,
            "prova": None,
            "tempo_da_prova": None,
        }
    )
    chave = chave_da_pessoa(decupagem(DUAS_SEM_NOME).pessoas[1])
    renomeacao = _separacao(chave, chave).model_copy(
        update={
            "tipo": "pessoa.renomear",
            "item_id": "pes02",
            "depois": "Maria Souza",
            "antes": "",
            "ancora": Ancora(
                versao="v",
                tipo_do_item="pessoa",
                identidade=chave,
                inicio_ms=0,
                fim_ms=1,
            ),
        }
    )

    class Renomeacoes:
        def listar(self, job_id: str) -> list[Correcao]:
            return [renomeacao]

    _, decupagens = identificar(
        decupagem(DUAS_SEM_NOME),
        nao_identificado,
        nao_identificado,
        tmp_path=tmp_path,
        correcoes=Renomeacoes(),
    )

    assert decupagens.gravada is not None
    assert [p.id for p in decupagens.gravada.pessoas] == ["pes01", "pes02"]


def _separacao(separada: str, outra: str) -> Correcao:
    return Correcao(
        id="c1",
        job_id="job-1",
        autor_uid="u1",
        autor_email="a@b.c",
        criada_em=BASE,
        motivo="duas pessoas",
        tipo="pessoa.separar",
        item_id="pes01",
        antes=json.dumps([outra, separada]),
        depois=separada,
        ancora=Ancora(
            versao="v", tipo_do_item="pessoa", identidade="x", inicio_ms=0, fim_ms=1
        ),
    )


NOMEADA = decupagem([pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])])


@pytest.mark.parametrize(
    ("decupagem_lida", "com_copia", "resultado", "downloads", "gravada"),
    [
        (None, True, "sem_alteracao", 0, False),
        (com_gc(), True, "identificado", 1, True),
        (com_gc(), False, "sem_alteracao", 1, False),
        (NOMEADA, True, "identificado", 0, True),
        (NOMEADA, False, "sem_alteracao", 0, False),
    ],
)
def test_so_baixa_a_copia_limpa_quando_ha_pessoa_sem_nome(
    decupagem_lida: Decupagem | None,
    com_copia: bool,
    resultado: str,
    downloads: int,
    gravada: bool,
    tmp_path: Path,
) -> None:
    obtido, decupagens = identificar(
        decupagem_lida,
        nome_do_modelo_forte(),
        com_copia=com_copia,
        tmp_path=tmp_path,
    )

    assert obtido == resultado
    assert decupagens.downloads == downloads
    assert (decupagens.gravada is not None) == gravada
    if decupagem_lida is NOMEADA and com_copia:
        assert decupagens.consultas == 1


def test_lista_as_correcoes_uma_vez_so(tmp_path: Path) -> None:
    chamadas: list[str] = []

    class Contadas:
        def listar(self, job_id: str) -> list[Correcao]:
            chamadas.append(job_id)
            return []

    identificar(
        com_gc(), nome_do_modelo_forte(), tmp_path=tmp_path, correcoes=Contadas()
    )

    assert chamadas == ["job-1"]


def _com_comercial_de_marca(marca: str) -> Decupagem:
    d = com_gc()
    comercial = {
        "marca": marca,
        "tipo": "intervalo",
        "evidencias": ["logo"],
        "inicio_ms": 200_000,
        "fim_ms": 210_000,
    }
    return d.model_copy(update={"comerciais": [Comercial.model_validate(comercial)]})


def test_comercial_com_a_marca_do_nome_dado_pelo_modelo_forte_sai(
    tmp_path: Path,
) -> None:
    d = _com_comercial_de_marca("Leão Lobo")

    _, decupagens = identificar(d, nome_do_modelo_forte(), tmp_path=tmp_path)

    assert decupagens.gravada is not None
    assert decupagens.gravada.pessoas[0].nome == "Leão Lobo"
    assert decupagens.gravada.comerciais == []


def test_sem_nome_dado_pelo_modelo_forte_a_decupagem_volta_igual(
    tmp_path: Path,
) -> None:
    d = _com_comercial_de_marca("Leão Lobo")
    nao_identificado = json.dumps(
        {
            "resultado": "nao_identificado",
            "nome": None,
            "prova": None,
            "tempo_da_prova": None,
        }
    )

    _, decupagens = identificar(d, nao_identificado, tmp_path=tmp_path)

    assert decupagens.gravada == d


def test_a_tolerancia_da_fala_chega_a_identificacao(tmp_path: Path) -> None:
    # A fala vem 2,5 s depois de a pessoa sair da imagem: só 3000 ms provam o nome.
    d = decupagem([pessoa("pes01", BARBA, [(100_000, 110_000)], fontes_do_nome=[])])
    fala = whisper(("Leão", 112.5), ("Lobo", 113.0))

    _, padrao = identificar(
        d, nome_do_modelo_forte(), tmp_path=tmp_path, transcricao=fala
    )
    _, larga = identificar(
        d,
        nome_do_modelo_forte(),
        tmp_path=tmp_path,
        transcricao=fala,
        tolerancia_ms=3000,
    )

    assert padrao.gravada is not None and larga.gravada is not None
    assert padrao.gravada.pessoas[0].estado_do_nome == "palpite"
    assert larga.gravada.pessoas[0].estado_do_nome == "confirmado"
