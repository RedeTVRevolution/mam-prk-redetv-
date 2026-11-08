"""Executa os passos da fila com relógio e Firestore locais, sem chamar a nuvem."""

import ast
import re
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from api.tests.test_workflow import _definicao


class Mapa(dict[str, Any]):
    def __getattr__(self, nome: str) -> Any:
        try:
            return self[nome]
        except KeyError:
            raise AttributeError(nome) from None


def mapa(valor: Any) -> Any:
    if isinstance(valor, dict):
        return Mapa({k: mapa(v) for k, v in valor.items()})
    if isinstance(valor, list):
        return [mapa(v) for v in valor]
    return valor


def campo(valor: Any, caminho: str | list[str]) -> Any:
    for chave in [caminho] if isinstance(caminho, str) else caminho:
        valor = valor.get(chave) if isinstance(valor, dict) else None
    return valor


class Salto(Exception):
    pass


class Retorno(Exception):
    pass


class ErroDaChamada(Exception):
    def __init__(self, codigo: int, tags: list[str] | None = None):
        self.dados = mapa({"code": codigo, "tags": tags or ["HttpError"]})


class FilaLocal:
    """Interpreta só os comandos usados pela fila; APIs externas são os únicos dublês."""

    def __init__(self, vagas: int = 1):
        self.definicao = _definicao({"vagas_de_gpu": str(vagas)})
        self.agora = 1000.0
        self.documento: dict[str, Any] | None = None
        self.versao = 0
        self.jobs: dict[str, tuple[str, str]] = {}
        self.antes_patch: Callable[[], None] | None = None
        self.erro_antes: int | None = None
        self.erro_depois: int | None = None
        self.logs: list[Any] = []

    def job(
        self,
        nome: str,
        criado: str = "1970-01-01T00:00:01Z",
        estado: str = "analisando",
    ) -> None:
        self.jobs[nome] = (estado, criado)

    def executar(self, nome: str, dono: str = "execucao", **args: Any) -> Any:
        sub = self.definicao[nome]
        escopo = {
            k: v for p in sub["params"] if isinstance(p, dict) for k, v in p.items()
        }
        escopo.update(args)
        escopo.update(
            sys=SimpleNamespace(now=lambda: self.agora, get_env=lambda _: dono),
            time=SimpleNamespace(
                parse=lambda v: datetime.fromisoformat(v).timestamp(),
                format=lambda v: datetime.fromtimestamp(v, UTC).isoformat(),
            ),
            map=SimpleNamespace(get=campo),
            list=SimpleNamespace(concat=lambda a, b: a + [b]),
            default=lambda v, padrao: padrao if v is None else v,
            len=len,
            string=str,
            text=SimpleNamespace(
                match_regex=lambda texto, padrao: re.search(padrao, texto) is not None
            ),
        )
        try:
            self.passos(sub["steps"], escopo, dono)
        except Retorno as retorno:
            return retorno.args[0]
        return None

    def valor(self, valor: Any, escopo: dict[str, Any]) -> Any:
        if isinstance(valor, str) and valor.startswith("${"):
            expressao = re.sub(
                r"\b(null|true|false)\b",
                lambda m: {"null": "None", "true": "True", "false": "False"}[m[0]],
                valor[2:-1],
            )
            return mapa(deepcopy(eval(expressao, {"__builtins__": {}}, escopo)))
        if isinstance(valor, dict):
            return mapa({k: self.valor(v, escopo) for k, v in valor.items()})
        if isinstance(valor, list):
            return [self.valor(v, escopo) for v in valor]
        return valor

    def atribuir(self, alvo: str, valor: Any, escopo: dict[str, Any]) -> None:
        arvore = ast.parse(alvo, mode="eval").body
        if isinstance(arvore, ast.Name):
            escopo[alvo] = valor
        else:
            assert isinstance(arvore, ast.Attribute | ast.Subscript)
            recipiente = eval(
                compile(ast.Expression(arvore.value), "<alvo>", "eval"),
                {"__builtins__": {}},
                escopo,
            )
            chave = (
                arvore.attr
                if isinstance(arvore, ast.Attribute)
                else eval(
                    compile(ast.Expression(arvore.slice), "<chave>", "eval"),
                    {"__builtins__": {}},
                    escopo,
                )
            )
            recipiente[chave] = valor

    def passos(self, passos: list[Any], escopo: dict[str, Any], dono: str) -> None:
        nomes = [next(iter(p)) for p in passos]
        indice, limite = 0, 10000
        while indice < len(passos):
            limite -= 1
            assert limite > 0, "laço sem progresso no YAML"
            corpo = passos[indice][nomes[indice]]
            try:
                self.passo(corpo, escopo, dono)
            except Salto as salto:
                if salto.args[0] not in nomes:
                    raise
                indice = nomes.index(salto.args[0])
            else:
                indice += 1

    def passo(self, corpo: Any, escopo: dict[str, Any], dono: str) -> None:
        for atribuicao in corpo.get("assign", []):
            for alvo, valor in atribuicao.items():
                self.atribuir(alvo, self.valor(valor, escopo), escopo)
        if "try" in corpo:
            try:
                for tentativa in range(6):
                    try:
                        self.passo(corpo["try"], escopo, dono)
                        break
                    except ErroDaChamada as erro:
                        if (
                            corpo.get("retry") != "${http.default_retry}"
                            or tentativa == 5
                            or not (
                                erro.dados.code in [429, 502, 503, 504]
                                or set(erro.dados.tags)
                                & {
                                    "ConnectionError",
                                    "ConnectionFailedError",
                                    "TimeoutError",
                                }
                            )
                        ):
                            raise
                        self.agora += min(1.25**tentativa, 60)
            except ErroDaChamada as erro:
                escopo[corpo["except"]["as"]] = erro.dados
                self.passos(corpo["except"]["steps"], escopo, dono)
        if "steps" in corpo:
            self.passos(corpo["steps"], escopo, dono)
        for ramo in corpo.get("switch", []):
            if self.valor(ramo["condition"], escopo):
                self.passo(ramo, escopo, dono)
                break
        if "for" in corpo:
            laco = corpo["for"]
            for indice, entrada in enumerate(self.valor(laco["in"], escopo)):
                escopo[laco["value"]] = entrada
                if "index" in laco:
                    escopo[laco["index"]] = indice
                try:
                    self.passos(laco["steps"], escopo, dono)
                except Salto as salto:
                    if salto.args[0] != "continue":
                        raise
        if "call" in corpo:
            args = self.valor(corpo.get("args", {}), escopo)
            nome = corpo["call"]
            resultado = (
                self.executar(nome, dono, **args)
                if nome in self.definicao
                else self.chamar(nome, args)
            )
            if "result" in corpo:
                escopo[corpo["result"]] = mapa(resultado)
        if "raise" in corpo:
            falha = self.valor(corpo["raise"], escopo)
            if isinstance(falha, dict):
                raise ErroDaChamada(falha["code"], falha["tags"])
            raise ErroDaChamada(0, [str(falha)])
        if "return" in corpo:
            raise Retorno(self.valor(corpo["return"], escopo))
        if "next" in corpo:
            raise Salto(corpo["next"])

    def chamar(self, nome: str, args: dict[str, Any]) -> Any:
        if nome == "sys.sleep":
            self.agora += args["seconds"]
            return None
        if nome == "sys.log":
            self.logs.append(args)
            return None
        if nome.endswith("documents.get"):
            if args["name"].endswith("fila_gpu/vagas"):
                if self.documento is None:
                    raise ErroDaChamada(404)
                return deepcopy(self.documento)
            estado, criado = self.jobs.get(
                args["name"].rsplit("/", 1)[1], ("ausente", "")
            )
            if estado == "ausente":
                raise ErroDaChamada(404)
            return {
                "updateTime": "1",
                "fields": {
                    "estado": {"stringValue": estado},
                    "criado_em": {"timestampValue": criado},
                },
            }
        assert nome.endswith("documents.patch"), nome
        if "/jobs/" in args["name"]:
            job_id = args["name"].rsplit("/", 1)[1]
            self.jobs[job_id] = (
                args["body"]["fields"]["estado"]["stringValue"],
                self.jobs[job_id][1],
            )
            return None
        if self.antes_patch:
            chamada, self.antes_patch = self.antes_patch, None
            chamada()
        if self.erro_antes:
            codigo, self.erro_antes = self.erro_antes, None
            raise ErroDaChamada(codigo)
        esperado = args["currentDocument"]
        if esperado.get("exists") is False:
            if self.documento is not None:
                raise ErroDaChamada(409)
        elif (
            self.documento is None
            or esperado["updateTime"] != self.documento["updateTime"]
        ):
            # O Firestore responde FAILED_PRECONDITION, que o conector do Workflows
            # entrega como HTTP 400 (e não 412).
            raise ErroDaChamada(400)
        self.versao += 1
        self.documento = {**deepcopy(args["body"]), "updateTime": str(self.versao)}
        if self.erro_depois:
            codigo, self.erro_depois = self.erro_depois, None
            raise ErroDaChamada(codigo, ["TimeoutError"])
        return deepcopy(self.documento)

    def pedir(
        self,
        job: str,
        etapa: str = "transcricao",
        dono: str = "execucao",
        acao: str = "pedir",
    ) -> Any:
        return self.executar(
            "atualiza_fila_gpu",
            dono,
            job_id=job,
            etapa=etapa,
            timeout_gpu=300,
            acao=acao,
        )

    def itens(self, grupo: str) -> list[Any]:
        assert self.documento is not None
        return [
            v["mapValue"]["fields"]
            for v in self.documento["fields"][grupo]["arrayValue"]["values"]
        ]


def test_aquisicao_nao_deixa_o_mesmo_pedido_na_espera() -> None:
    fila = FilaLocal()
    fila.job("a")
    assert fila.pedir("a") == {"vaga": True, "posicao": 0, "posicao_inicial": 0}
    assert fila.itens("espera") == []
    assert len(fila.itens("ocupadas")) == 1


@pytest.mark.parametrize("ja_existe", [False, True])
def test_duas_execucoes_disputam_a_ultima_vaga_sem_perder_pedidos(
    ja_existe: bool,
) -> None:
    fila = FilaLocal()
    for job in ("a", "b", "antigo"):
        fila.job(job)
    if ja_existe:
        fila.pedir("antigo")
        fila.pedir("antigo", acao="liberar")
    fila.antes_patch = lambda: fila.pedir("a", dono="outra")
    assert fila.pedir("b")["vaga"] is False
    assert [p["job_id"]["stringValue"] for p in fila.itens("ocupadas")] == ["a"]
    assert [p["job_id"]["stringValue"] for p in fila.itens("espera")] == ["b"]


@pytest.mark.parametrize("depois", [False, True])
def test_gravacao_falha_antes_ou_depois_de_persistir_sem_duplicar_vaga(
    depois: bool,
) -> None:
    fila = FilaLocal()
    fila.job("a")
    if depois:
        fila.erro_depois = 504
    else:
        fila.erro_antes = 503
    assert fila.pedir("a")["vaga"] is True
    assert len(fila.itens("ocupadas")) == 1
    assert fila.itens("espera") == []
    fila.erro_depois = 504
    fila.pedir("a", acao="liberar")
    assert fila.itens("ocupadas") == []


def test_400_que_nao_passa_tem_teto_de_releituras() -> None:
    """Um 400 que não é de concorrência (pedido malformado) vira erro, não laço sem fim."""

    class SempreRecusa(FilaLocal):
        @property
        def erro_antes(self) -> int:
            return 400

        @erro_antes.setter
        def erro_antes(self, _: int | None) -> None:
            pass

    fila = SempreRecusa()
    fila.job("a")
    with pytest.raises(ErroDaChamada):
        fila.pedir("a")


def test_ordem_e_pelo_job_e_nao_pela_ordem_dos_pulsos() -> None:
    fila = FilaLocal()
    fila.job("ocupante")
    fila.job("b", "1970-01-01T00:00:03Z")
    fila.job("a", "1970-01-01T00:00:02Z")
    fila.pedir("ocupante")
    fila.pedir("b")
    fila.pedir("a")
    fila.pedir("ocupante", acao="liberar")
    assert fila.pedir("b") == {"vaga": False, "posicao": 1, "posicao_inicial": 0}
    assert fila.pedir("a") == {"vaga": True, "posicao": 0, "posicao_inicial": 0}


def test_desempata_por_job_id_e_depois_por_etapa() -> None:
    fila = FilaLocal()
    for job in ("ocupante", "b", "a"):
        fila.job(job)
    fila.pedir("ocupante")
    fila.pedir("b")
    fila.pedir("a", "transcricao")
    fila.pedir("a", "leitura_da_tela")
    fila.pedir("ocupante", acao="liberar")
    assert fila.pedir("b")["posicao"] == 2
    assert fila.pedir("a", "transcricao")["posicao"] == 1
    assert fila.pedir("a", "leitura_da_tela")["vaga"] is True


@pytest.mark.parametrize(
    "etapa,estado,mantem",
    [
        ("transcricao", "analisando", True),
        ("transcricao", "concluido", False),
        ("inventario_de_objetos", "concluido", True),
        ("inventario_de_objetos", "falhou", False),
        ("inventario_de_objetos", "cancelado", False),
        ("transcricao", "ausente", False),
    ],
)
def test_limpa_vagas_perdidas_preservando_florence_concluido(
    etapa: str, estado: str, mantem: bool
) -> None:
    fila = FilaLocal()
    fila.job("a")
    fila.job("b")
    fila.pedir("a", etapa)
    fila.job("a", estado=estado)
    assert fila.pedir("b")["vaga"] is not mantem


@pytest.mark.parametrize("etapa", ["transcricao", "inventario_de_objetos"])
def test_vaga_expira_pelo_timeout_e_pedido_abandonado_por_tres_esperas(
    etapa: str,
) -> None:
    fila = FilaLocal()
    for job in ("ocupante", "abandonado", "vivo"):
        fila.job(job)
    fila.pedir("ocupante", etapa)
    if etapa == "inventario_de_objetos":
        fila.job("ocupante", estado="concluido")
    fila.pedir("abandonado")
    fila.agora += 180
    fila.pedir("vivo")
    assert len(fila.itens("espera")) == 2
    fila.agora += 1
    fila.pedir("vivo")
    assert [p["job_id"]["stringValue"] for p in fila.itens("espera")] == ["vivo"]
    fila.agora += 120
    assert fila.pedir("vivo")["vaga"] is True
    assert fila.itens("espera") == []


def test_cancelamento_na_espera_limpa_o_pedido_antes_de_subir_o_erro() -> None:
    fila = FilaLocal()
    for job in ("ocupante", "cancelado", "seguinte"):
        fila.job(job)
    fila.pedir("ocupante")
    fila.pedir("cancelado")
    fila.job("cancelado", estado="cancelado")
    with pytest.raises(ErroDaChamada):
        fila.pedir("cancelado")
    assert fila.itens("espera") == []
    fila.pedir("ocupante", acao="liberar")
    assert fila.pedir("seguinte")["vaga"] is True


def test_liberacao_atrasada_nao_remove_a_vaga_de_outra_execucao() -> None:
    fila = FilaLocal()
    fila.job("a")
    fila.pedir("a", dono="antiga")
    fila.agora += 301
    assert fila.pedir("a", dono="nova")["vaga"] is True
    fila.pedir("a", dono="antiga", acao="liberar")
    assert fila.itens("ocupadas")[0]["dono"]["stringValue"] == "nova"


def test_duas_etapas_do_mesmo_video_ocupam_uma_vaga_cada() -> None:
    fila = FilaLocal(vagas=2)
    fila.job("a")
    fila.job("b")
    assert fila.pedir("a")["vaga"] is True
    assert fila.pedir("a", "leitura_da_tela")["vaga"] is True
    assert fila.pedir("b")["vaga"] is False
    fila.executar("atualiza_fila_gpu", job_id="a", acao="liberar")
    assert fila.itens("ocupadas") == []
    assert fila.pedir("b")["vaga"] is True


def test_o_log_recupera_a_posicao_se_a_resposta_da_gravacao_se_perdeu() -> None:
    fila = FilaLocal()
    fila.job("a")
    fila.erro_depois = 504
    fila.executar("espera_vaga_gpu", job_id="a", etapa="transcricao", timeout_gpu=300)
    assert fila.logs[-1]["json"] == {
        "evento": "vaga_de_gpu",
        "job_id": "a",
        "etapa": "transcricao",
        "posicao": 0,
        "espera_s": 2.0,
    }


def test_posicao_inicial_resiste_a_chegada_de_job_mais_antigo() -> None:
    fila = FilaLocal()
    for job in ("ocupante", "b", "a"):
        fila.job(job)
    fila.pedir("ocupante")
    fila.pedir("b")
    fila.pedir("a")
    pedido = fila.pedir("b")
    assert pedido["posicao"] == 1
    assert pedido["posicao_inicial"] == 0


def test_renovacao_preserva_a_vaga_durante_a_tentativa_seguinte() -> None:
    fila = FilaLocal()
    fila.job("a")
    fila.job("b")
    fila.pedir("a")
    fila.agora += 240
    fila.pedir("a", acao="renovar")
    fila.agora += 100
    assert fila.pedir("b")["vaga"] is False
    fila.agora += 201
    # Uma execução morta perde a vaga; uma tentativa velha não pode renová-la de volta.
    with pytest.raises(ErroDaChamada):
        fila.pedir("a", acao="renovar")
    assert fila.pedir("b")["vaga"] is True


def test_interrupcao_marca_o_job_antes_de_liberar_mesmo_com_fila_indisponivel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fila = FilaLocal()
    fila.job("a")
    fila.pedir("a")
    chamar = fila.chamar
    estados_ao_liberar = []
    avisos = []

    def chamar_com_503(nome: str, args: dict[str, Any]) -> Any:
        if nome.endswith("documents.get") and args["name"].endswith("fila_gpu/vagas"):
            estados_ao_liberar.append(fila.jobs["a"][0])
            raise ErroDaChamada(503)
        if nome.endswith("jobs.run"):
            avisos.append(args)
            return None
        return chamar(nome, args)

    monkeypatch.setattr(fila, "chamar", chamar_com_503)
    assert fila.executar("marca_interrompido", job_id="a") is None
    assert fila.jobs["a"][0] == "falhou"
    assert estados_ao_liberar == ["falhou"] * 6
    assert len(avisos) == 1
    assert any(log.get("data", {}).get("code") == 503 for log in fila.logs)

    monkeypatch.setattr(fila, "chamar", chamar)
    fila.job("b")
    assert fila.pedir("b")["vaga"] is True


@pytest.mark.parametrize("chamada", ["le_fila", "le_job", "grava_fila"])
def test_503_passageiro_na_liberacao_libera_a_vaga_do_florence(
    monkeypatch: pytest.MonkeyPatch, chamada: str
) -> None:
    fila = FilaLocal()
    fila.job("a", estado="concluido")
    chamar = fila.chamar
    terminou = False
    falhas = 0

    def chamar_com_503(nome: str, args: dict[str, Any]) -> Any:
        nonlocal terminou, falhas
        if nome.endswith("jobs.run"):
            terminou = True
            return None
        alvo = (
            "grava_fila"
            if nome.endswith("documents.patch")
            else "le_fila"
            if args.get("name", "").endswith("fila_gpu/vagas")
            else "le_job"
        )
        if terminou and falhas == 0 and alvo == chamada:
            falhas += 1
            raise ErroDaChamada(503)
        return chamar(nome, args)

    monkeypatch.setattr(fila, "chamar", chamar_com_503)
    assert (
        fila.executar(
            "roda_o_job_com_gpu",
            job_id="a",
            etapa="inventario_de_objetos",
            job_gpu="gpu",
            timeout_gpu=300,
        )
        == "gpu"
    )
    assert falhas == 1
    assert fila.itens("ocupadas") == []
    assert fila.itens("espera") == []
    assert not any(log.get("severity") == "ERROR" for log in fila.logs)


@pytest.mark.parametrize("metodo", ["get", "patch"])
@pytest.mark.parametrize(
    "erro_gpu,job_cpu,erro_cpu,resultado",
    [
        (None, "cpu", None, "gpu"),
        (400, "cpu", None, 400),
        (429, "cpu", None, "cpu"),
        (429, None, None, 429),
        (429, "cpu", 403, 403),
    ],
)
def test_fila_indisponivel_na_liberacao_preserva_resultado_ou_erro_da_etapa(
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
    erro_gpu: int | None,
    job_cpu: str | None,
    erro_cpu: int | None,
    resultado: str | int,
) -> None:
    fila = FilaLocal()
    fila.definicao = _definicao({"gpu_espera_total_s": "0"})
    fila.job("a")
    chamar = fila.chamar
    execucoes: list[str] = []

    def chamar_com_503_na_liberacao(nome: str, args: dict[str, Any]) -> Any:
        if (
            execucoes
            and nome.endswith("documents." + metodo)
            and args["name"].endswith("fila_gpu/vagas")
        ):
            raise ErroDaChamada(503)
        if nome.endswith("jobs.run"):
            job = args["name"].rsplit("/", 1)[1]
            execucoes.append(job)
            codigo = erro_gpu if job == "gpu" else erro_cpu
            if codigo:
                raise ErroDaChamada(codigo)
            return None
        return chamar(nome, args)

    monkeypatch.setattr(fila, "chamar", chamar_com_503_na_liberacao)
    args: dict[str, Any] = {
        "job_id": "a",
        "etapa": "transcricao",
        "job_gpu": "gpu",
        "timeout_gpu": 300,
        "job_cpu": job_cpu,
        "timeout_cpu": 300,
    }
    if isinstance(resultado, int):
        with pytest.raises(ErroDaChamada) as erro:
            fila.executar("roda_o_job_com_gpu", **args)
        assert erro.value.dados == {"code": resultado, "tags": ["HttpError"]}
    else:
        assert fila.executar("roda_o_job_com_gpu", **args) == resultado
    assert execucoes == (["gpu", "cpu"] if erro_gpu == 429 and job_cpu else ["gpu"])
    assert any(log.get("data", {}).get("code") == 503 for log in fila.logs)
