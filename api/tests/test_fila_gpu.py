"""Executa os passos da fila com relógio e Firestore locais, sem chamar a nuvem."""

import ast
import re
from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from itertools import permutations
from pathlib import Path
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
    def __init__(self, codigo: int | None, tags: list[str] | None = None):
        # Erro de conexão chega sem `code`: o mapa não tem a chave.
        dados: dict[str, Any] = {"tags": tags or ["HttpError"]}
        if codigo is not None:
            dados["code"] = codigo
        self.dados = mapa(dados)


def numero(valor: Any) -> Any:
    if type(valor) not in (int, float):
        raise TypeError("operação exige números no Workflows")
    return valor


class ComparacoesNumericas(ast.NodeTransformer):
    def visit_Compare(self, no: ast.Compare) -> ast.Compare:
        self.generic_visit(no)
        if any(isinstance(op, ast.Lt | ast.LtE | ast.Gt | ast.GtE) for op in no.ops):
            operandos: list[ast.expr] = [
                ast.Call(
                    func=ast.Name(id="numero", ctx=ast.Load()),
                    args=[operando],
                    keywords=[],
                )
                for operando in [no.left, *no.comparators]
            ]
            no.left, no.comparators = operandos[0], operandos[1:]
        return no


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
        # Estado das execuções do Workflows por id; a que não está aqui está ativa.
        self.execucoes: dict[str, str] = {}

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
            int=lambda v: int(numero(v)),
            list=SimpleNamespace(concat=lambda a, b: a + [b]),
            math=SimpleNamespace(min=min),
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
            arvore = ast.parse(expressao, mode="eval")
            if any(isinstance(no, ast.Dict) for no in ast.walk(arvore)):
                raise SyntaxError("Workflows não aceita mapa literal em expressão")
            arvore = ComparacoesNumericas().visit(arvore)
            codigo = compile(ast.fix_missing_locations(arvore), "<expressao>", "eval")
            return mapa(
                deepcopy(eval(codigo, {"__builtins__": {}, "numero": numero}, escopo))
            )
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
            if isinstance(recipiente, dict) and not isinstance(chave, str):
                raise TypeError("chave de mapa exige string no Workflows")
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
                                erro.dados.get("code") in [429, 502, 503, 504]
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
                raise ErroDaChamada(falha.get("code"), falha["tags"])
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
        if nome.endswith("executions.get"):
            return {
                "state": self.execucoes.get(args["name"].rsplit("/", 1)[1], "ACTIVE")
            }
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


def test_patch_com_versao_vencida_recusa_sem_mudar_a_fila() -> None:
    fila = FilaLocal()
    fila.job("a")
    fila.pedir("a")
    antigo = deepcopy(fila.documento)
    assert antigo is not None
    fila.pedir("a", acao="renovar")
    atual = deepcopy(fila.documento)
    with pytest.raises(ErroDaChamada) as erro:
        fila.chamar(
            "googleapis.firestore.v1.projects.databases.documents.patch",
            {
                "name": "fila_gpu/vagas",
                "currentDocument": {"updateTime": antigo["updateTime"]},
                "body": antigo,
            },
        )
    assert erro.value.dados.code == 400  # FAILED_PRECONDITION
    assert fila.documento == atual


def test_24_pedidos_intercalados_convergem_apos_ler_versoes_vencidas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fila = FilaLocal(vagas=3)
    fila.job("ff")
    fila.pedir("ff")
    pedidos = [f"{i:032x}" for i in range(24)]
    for job in pedidos:
        fila.job(job)
    conflitos: Counter[str] = Counter()
    em_curso: list[str] = []
    chamar = fila.chamar

    def contar_conflitos(nome: str, args: dict[str, Any]) -> Any:
        try:
            return chamar(nome, args)
        except ErroDaChamada as erro:
            if erro.dados.code == 400:
                conflitos[em_curso[-1]] += 1
            raise

    def intercalar(indice: int) -> None:
        if indice == len(pedidos):
            # Vence a versão que todos os 24 já leram, antes de seus PATCHes.
            fila.pedir("ff", acao="renovar")
            return
        em_curso.append(pedidos[indice])
        fila.antes_patch = lambda: intercalar(indice + 1)
        fila.pedir(pedidos[indice], dono=pedidos[indice])
        em_curso.pop()

    monkeypatch.setattr(fila, "chamar", contar_conflitos)
    intercalar(0)
    assert conflitos == Counter({job: 1 for job in pedidos})
    assert len(fila.itens("ocupadas")) == 3
    itens = fila.itens("ocupadas") + fila.itens("espera")
    identidades = [
        (
            p["job_id"]["stringValue"],
            p["etapa"]["stringValue"],
            p["dono"]["stringValue"],
        )
        for p in itens
    ]
    assert len(identidades) == len(set(identidades)) == len(pedidos) + 1
    assert {p[0] for p in identidades} == {*pedidos, "ff"}


def test_releitura_le_cada_job_uma_vez_e_o_proximo_pulso_le_de_novo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fila = FilaLocal(vagas=2)
    for job in ("a", "b", "c"):
        fila.job(job)
    fila.pedir("a")
    fila.pedir("a", "leitura_da_tela")
    fila.pedir("b")
    fila.pedir("c")
    fila.job("c", estado="ausente")
    leituras: Counter[str] = Counter()
    chamar = fila.chamar

    def contar_jobs(nome: str, args: dict[str, Any]) -> Any:
        if nome.endswith("documents.get") and "/jobs/" in args["name"]:
            leituras[args["name"].rsplit("/", 1)[1]] += 1
        return chamar(nome, args)

    def vencer_a_versao() -> None:
        assert fila.documento is not None
        fila.versao += 1
        fila.documento["updateTime"] = str(fila.versao)
        fila.job("a", estado="cancelado")

    monkeypatch.setattr(fila, "chamar", contar_jobs)
    fila.antes_patch = vencer_a_versao
    assert fila.pedir("b")["vaga"] is False
    assert leituras == Counter({"a": 1, "b": 1, "c": 1})
    assert fila.pedir("b")["vaga"] is True
    assert leituras == Counter({"a": 2, "b": 2, "c": 1})


@pytest.mark.parametrize("agora", [1000.0, 1000.001, 1000.002, 1000.0035])
def test_espera_da_releitura_varia_com_os_milissegundos_do_relogio(
    monkeypatch: pytest.MonkeyPatch, agora: float
) -> None:
    fila = FilaLocal()
    fila.job("a")
    fila.agora = agora
    fila.erro_antes = 400
    esperas = []
    chamar = fila.chamar

    def contar_esperas(nome: str, args: dict[str, Any]) -> Any:
        if nome == "sys.sleep":
            esperas.append(args["seconds"])
        return chamar(nome, args)

    monkeypatch.setattr(fila, "chamar", contar_esperas)
    assert fila.pedir("a")["vaga"] is True
    assert esperas == [1 + int(agora * 1000) % 3]
    assert type(esperas[0]) is int


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


def test_desempata_pela_ordem_de_insercao() -> None:
    fila = FilaLocal()
    for job in ("ocupante", "b", "a"):
        fila.job(job)
    fila.pedir("ocupante")
    fila.pedir("b")
    fila.pedir("a", "transcricao")
    fila.pedir("a", "leitura_da_tela")
    fila.pedir("ocupante", acao="liberar")
    assert fila.pedir("a", "leitura_da_tela")["posicao"] == 2
    assert fila.pedir("a", "transcricao")["posicao"] == 1
    assert fila.pedir("b")["vaga"] is True


@pytest.mark.parametrize(
    "etapas",
    [("transcricao", "leitura_da_tela"), ("leitura_da_tela", "transcricao")],
)
def test_mesma_chegada_tem_posicoes_distintas_e_iguais_para_todos_os_leitores(
    etapas: tuple[str, str],
) -> None:
    fila = FilaLocal()
    fila.job("ocupante")
    fila.job("z", "1970-01-01T00:00:02Z")
    fila.job("a", "1970-01-01T00:00:03Z")
    fila.pedir("ocupante")
    pedidos = [("z", etapas[0]), ("z", etapas[1]), ("a", "transcricao")]
    assert [fila.pedir(*pedido)["posicao"] for pedido in pedidos] == [0, 1, 2]
    for ordem in permutations(range(3)):
        assert [fila.pedir(*pedidos[i])["posicao"] for i in ordem] == list(ordem)


@pytest.mark.parametrize("operador", ["<", "<=", ">", ">="])
def test_avaliador_recusa_comparacao_de_ordem_entre_strings(operador: str) -> None:
    fila = FilaLocal()
    with pytest.raises(TypeError, match="exige números"):
        fila.valor(f'${{"a" {operador} "b"}}', {})
    assert fila.valor(f"${{1 {operador} 2}}", {}) == (operador in ["<", "<="])
    assert fila.valor(f'${{false and "a" {operador} "b"}}', {}) is False


def test_avaliador_recusa_mapa_literal_e_chave_que_nao_e_string() -> None:
    fila = FilaLocal()
    with pytest.raises(SyntaxError, match="mapa literal"):
        fila.valor("${default(null, {})}", {"default": lambda v, padrao: padrao})
    with pytest.raises(TypeError, match="chave de mapa exige string"):
        fila.atribuir("cache[chave]", "job", {"cache": {}, "chave": 1})


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
        "espera_s": 4.0,
    }


def test_posicao_inicial_resiste_a_chegada_de_job_mais_antigo() -> None:
    fila = FilaLocal()
    for job in ("ocupante", "b", "a"):
        fila.job(job)
    fila.job("a", "1970-01-01T00:00:00Z")
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
    # A vaga de um Job `falhou` fica até o prazo ou até a execução acabar (#520): a
    # execução que marcou o Job terminou, e a vaga que a fila não liberou sai na limpeza.
    fila.execucoes["execucao"] = "FAILED"
    assert fila.pedir("b", dono="outra")["vaga"] is True


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


@pytest.mark.parametrize(
    "etapa", ["transcricao", "leitura_da_tela", "inventario_de_objetos"]
)
def test_cota_esgotada_falha_na_gpu_e_libera_a_vaga(
    monkeypatch: pytest.MonkeyPatch, etapa: str
) -> None:
    fila = FilaLocal()
    fila.definicao = _definicao({"gpu_espera_total_s": "0"})
    fila.job(
        "a", estado="concluido" if etapa == "inventario_de_objetos" else "analisando"
    )
    chamar = fila.chamar
    execucoes = []
    dispositivos = []

    def chamar_com_cota_esgotada(nome: str, args: dict[str, Any]) -> Any:
        if nome.endswith("jobs.run"):
            execucoes.append(args["name"])
            raise ErroDaChamada(429)
        if nome.endswith("documents.get") and "/jobs/" in args["name"]:
            documento = chamar(nome, args)
            documento["fields"]["etapas"] = {"mapValue": {"fields": {etapa: {}}}}
            return documento
        if nome.endswith("documents.patch") and "/jobs/" in args["name"]:
            dispositivos.append(
                args["body"]["fields"]["etapas"]["mapValue"]["fields"][etapa]
            )
            return None
        return chamar(nome, args)

    monkeypatch.setattr(fila, "chamar", chamar_com_cota_esgotada)
    with pytest.raises(ErroDaChamada) as erro:
        fila.executar(
            "roda_o_job_com_gpu",
            job_id="a",
            etapa=etapa,
            job_gpu="gpu",
            timeout_gpu=300,
        )
    assert erro.value.dados["code"] == 429
    assert len(execucoes) == 1 and execucoes[0].endswith("/gpu")
    assert dispositivos == [
        {
            "mapValue": {
                "fields": {
                    "dispositivo": {"stringValue": "gpu"},
                    "tentativas_gpu": {"integerValue": "1"},
                }
            }
        }
    ]
    assert fila.itens("ocupadas") == [] and fila.itens("espera") == []


@pytest.mark.parametrize("metodo", ["get", "patch"])
@pytest.mark.parametrize(
    "erro_gpu,resultado",
    [
        (None, "gpu"),
        (400, 400),
        (429, 429),
    ],
)
def test_fila_indisponivel_na_liberacao_preserva_resultado_ou_erro_da_etapa(
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
    erro_gpu: int | None,
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
            if erro_gpu:
                raise ErroDaChamada(erro_gpu)
            return None
        return chamar(nome, args)

    monkeypatch.setattr(fila, "chamar", chamar_com_503_na_liberacao)
    args: dict[str, Any] = {
        "job_id": "a",
        "etapa": "transcricao",
        "job_gpu": "gpu",
        "timeout_gpu": 300,
    }
    if isinstance(resultado, int):
        with pytest.raises(ErroDaChamada) as erro:
            fila.executar("roda_o_job_com_gpu", **args)
        assert erro.value.dados == {"code": resultado, "tags": ["HttpError"]}
    else:
        assert fila.executar("roda_o_job_com_gpu", **args) == resultado
    assert execucoes == ["gpu"]
    assert any(log.get("data", {}).get("code") == 503 for log in fila.logs)


def test_falha_de_uma_etapa_nao_libera_a_vaga_da_outra_que_ainda_roda() -> None:
    # A transcrição falhou e devolveu a vaga dela; o Job foi a `falhou`, mas a leitura da
    # tela segue na GPU: a vaga dela não pode sair da fila.
    fila = FilaLocal(vagas=2)
    for job in ("a", "b", "c"):
        fila.job(job)
    fila.pedir("a")
    fila.pedir("a", "leitura_da_tela")
    fila.pedir("a", acao="liberar", etapa="transcricao", dono="execucao")
    fila.job("a", estado="falhou")
    assert fila.pedir("b", dono="outra")["vaga"] is True
    assert fila.pedir("c", dono="outra")["vaga"] is False
    assert [p["etapa"]["stringValue"] for p in fila.itens("ocupadas")] == [
        "leitura_da_tela",
        "transcricao",
    ]


def test_vaga_de_execucao_do_workflows_que_nao_esta_mais_ativa_e_liberada() -> None:
    # Cancelar a execução no console não roda a limpeza: a fila confere a execução.
    fila = FilaLocal()
    fila.job("a")
    fila.job("b")
    fila.pedir("a", dono="cancelada")
    assert fila.pedir("b", dono="viva")["vaga"] is False
    fila.execucoes["cancelada"] = "CANCELLED"
    assert fila.pedir("b", dono="viva")["vaga"] is True
    assert [p["job_id"]["stringValue"] for p in fila.itens("ocupadas")] == ["b"]


def test_erro_do_firestore_sem_codigo_sobe_como_o_original() -> None:
    fila = FilaLocal()
    fila.job("a")
    fila.erro_antes = None
    chamar = fila.chamar

    def sem_codigo(nome: str, args: dict[str, Any]) -> Any:
        if nome.endswith("documents.get"):
            raise ErroDaChamada(None, ["ConnectionError"])
        return chamar(nome, args)

    fila.chamar = sem_codigo  # type: ignore[method-assign]
    with pytest.raises(ErroDaChamada) as erro:
        fila.pedir("a")
    assert erro.value.dados["tags"] == ["ConnectionError"]
    assert "code" not in erro.value.dados


def test_workflow_nao_le_code_direto_de_um_erro() -> None:
    texto = (
        Path(__file__).parents[2] / "infra/modulos/mam/validacao.workflow.yaml"
    ).read_text()
    assert re.findall(r"\b\w+\.code\b", texto) == []


def test_espera_apos_429_de_cota_mantem_a_vaga_e_tenta_de_novo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fila = FilaLocal()
    fila.definicao = _definicao(
        {
            "gpu_espera_total_s": "600",
            "gpu_espera_s": "10",
            "gpu_fator_da_espera": "2",
            "gpu_espera_maxima_s": "60",
        }
    )
    fila.job("a")
    chamar = fila.chamar
    execucoes: list[float] = []
    vagas_nas_tentativas: list[int] = []

    def com_cota_na_primeira(nome: str, args: dict[str, Any]) -> Any:
        if nome.endswith("jobs.run"):
            execucoes.append(fila.agora)
            vagas_nas_tentativas.append(len(fila.itens("ocupadas")))
            if len(execucoes) == 1:
                raise ErroDaChamada(429)
            return None
        return chamar(nome, args)

    monkeypatch.setattr(fila, "chamar", com_cota_na_primeira)
    resultado = fila.executar(
        "roda_o_job_com_gpu",
        job_id="a",
        etapa="transcricao",
        job_gpu="gpu",
        timeout_gpu=300,
    )
    assert resultado == "gpu"
    assert execucoes[1] - execucoes[0] == 10
    assert vagas_nas_tentativas == [1, 1]
    assert fila.itens("ocupadas") == []
    assert any(log.get("json", {}).get("evento") == "falta_de_gpu" for log in fila.logs)
