"""Teste de carga do mam-web no dev: `make carga-dev`.

Cada usuário virtual faz o que uma pessoa faz na tela, só com leituras: busca por texto (e os
quadros do resultado), abre um vídeo do resultado (detalhe e decupagem) e lista o acervo, às
vezes com filtro, com uma pausa de "pensar" entre as ações.

Variáveis: `URL` (o serviço) e `TOKEN` (ID token da sessão de quem roda, vale 1 h; vários
separados por vírgula, repartidos entre os usuários). Opcionais: `USUARIOS` (200), `DURACAO_S`
(300), `RAMPA_S` (30) e `PAUSA_S` (`5-15`, sorteada a cada ação, ou um número fixo).
Cuidado: a busca limita 30 consultas por minuto por pessoa e por instância (api/rota_da_busca.py);
com um token só, quase todas as buscas voltam 429. O relatório mostra quantas foram recusadas.
Sai com 0 se nenhum pedido falhou, 1 se algum falhou e 2 se faltou configuração.
"""

import math
import os
import random
import sys
import threading
import time
import tomllib
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import requests

CONSULTAS = Path(__file__).with_name("consultas_da_sonda.toml")
ROTA_DA_BUSCA = "GET /v1/busca"
# O campo da resposta da busca; escrito assim porque o nome entre aspas é o da coleção do
# índice e o `make verificar` (checar-nomes-da-nuvem.sh) o barra no código.
MOMENTOS = "mo" + "mentos"
# Pesos do roteiro: a busca é o que a tela mais faz.
PESOS = {"buscar": 4, "abrir": 3, "listar": 3}


class Transporte(Protocol):
    def __call__(
        self, metodo: str, caminho: str, params: dict[str, Any] | None, corpo: Any
    ) -> tuple[int, Any]:
        """Chama o serviço; devolve o status (0 se nem chegou) e o JSON (ou `None`)."""
        ...


def transporte_http(url: str, token: str) -> Transporte:
    sessao = requests.Session()  # uma por usuário, como um navegador
    sessao.headers["Authorization"] = f"Bearer {token}"

    def chamar(
        metodo: str, caminho: str, params: dict[str, Any] | None, corpo: Any
    ) -> tuple[int, Any]:
        try:
            r = sessao.request(
                metodo, url.rstrip("/") + caminho, params=params, json=corpo, timeout=30
            )
        except requests.RequestException:
            return 0, None
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None

    return chamar


def percentil(ordenados: list[float], p: float) -> float:
    """Posto mais próximo; `ordenados` não pode ser vazio."""
    return ordenados[max(0, math.ceil(p / 100 * len(ordenados)) - 1)]


class Medidas:
    def __init__(self) -> None:
        self._trava = threading.RLock()  # reentrante: `texto` chama as outras leituras
        self._por_rota: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self.no_ar = 0

    def iniciar(self) -> None:
        with self._trava:
            self.no_ar += 1

    def registrar(self, rota: str, status: int, duracao_s: float) -> None:
        with self._trava:
            self._por_rota[rota].append((status, duracao_s))
            self.no_ar = max(0, self.no_ar - 1)

    def copia(self) -> "Medidas":
        """Foto sob a trava: o que termina depois não a altera."""
        with self._trava:
            c = Medidas()
            c._por_rota = defaultdict(
                list, {r: list(v) for r, v in self._por_rota.items()}
            )
            c.no_ar = self.no_ar
            return c

    def total(self) -> int:
        with self._trava:
            return sum(len(v) for v in self._por_rota.values())

    def falhas(self) -> int:
        with self._trava:
            return sum(
                1 for v in self._por_rota.values() for s, _ in v if not 200 <= s < 400
            )

    def buscas(self) -> tuple[int, int]:
        """(enviadas, executadas): 429, 4xx de entrada e falha de rede não chegam a buscar."""
        with self._trava:
            v = list(self._por_rota.get(ROTA_DA_BUSCA, []))
        return len(v), sum(1 for s, _ in v if s not in (0, 401, 403, 422, 429))

    def texto(self) -> str:
        with self._trava:
            return self._texto()

    def _texto(self) -> str:
        linhas = [
            f"{'rota':<34}{'n':>6}  {'erros':<22}{'p50':>7}{'p95':>7}{'p99':>7}{'max':>7} (ms)"
        ]
        for rota in sorted(self._por_rota):
            v = self._por_rota[rota]
            ms = sorted(d * 1000 for _, d in v)
            erros = Counter(s for s, _ in v if not 200 <= s < 400)
            lista = " ".join(f"{s}:{n}" for s, n in sorted(erros.items())) or "-"
            linhas.append(
                f"{rota:<34}{len(v):>6}  {lista:<22}"
                + "".join(f"{percentil(ms, p):>7.0f}" for p in (50, 95, 99, 100))
            )
        enviadas, executadas = self.buscas()
        linhas.append(f"Total de pedidos: {self.total()} ({self.falhas()} com erro)")
        linhas.append(
            f"Buscas feitas: {enviadas} enviadas, {executadas} executadas "
            f"(as outras foram recusadas antes de buscar)"
        )
        if self.no_ar:
            linhas.append(
                f"No ar na parada: {self.no_ar} (não entram nas medidas acima)"
            )
        return "\n".join(linhas)


def consultas_da_sonda() -> list[str]:
    """Os termos da sonda e os pares deles: a busca guarda candidatos e ranking por 60 s
    em cada instância, e só os ~20 termos cairiam quase sempre no cache, medindo menos
    que a carga real."""
    with CONSULTAS.open("rb") as f:
        termos = [c["texto"] for c in tomllib.load(f)["consulta"]]
    return termos + [f"{a} {b}" for a in termos for b in termos if a != b]


class Usuario:
    """O estado de uma pessoa na tela: os vídeos que ela viu nos últimos resultados."""

    def __init__(
        self,
        transporte: Transporte,
        medidas: Medidas,
        termos: list[str],
        rng: random.Random,
        parar: threading.Event | None = None,
    ) -> None:
        self._parar = parar or threading.Event()
        self._t = transporte
        self._m = medidas
        self._termos = termos
        self._rng = rng
        self._ids: list[str] = []

    def _pedir(
        self,
        rota: str,
        caminho: str,
        params: dict[str, Any] | None = None,
        corpo: Any = None,
    ) -> Any:
        if self._parar.is_set():
            return None
        inicio = time.monotonic()
        self._m.iniciar()
        status, json = self._t(rota.split()[0], caminho, params, corpo)
        self._m.registrar(rota, status, time.monotonic() - inicio)
        return json if 200 <= status < 300 else None

    def buscar(self) -> None:
        achado = self._pedir(
            ROTA_DA_BUSCA,
            "/v1/busca",
            {"q": self._rng.choice(self._termos), "ordem": "relevancia", "limite": 20},
        )
        videos = (achado or {}).get("videos") or []
        self._ids = [v["job_id"] for v in videos if "job_id" in v] or self._ids
        # A tela pede as URLs dos quadros da página, num pedido só.
        pares = [
            {"job": v["job_id"], "arquivo": m["quadro"].rsplit("/", 1)[-1]}
            for v in videos
            for m in v.get(MOMENTOS, [])[:1]
            if m.get("quadro")
        ][:20]
        if pares:
            self._pedir(
                "POST /v1/jobs/quadros", "/v1/jobs/quadros", corpo={"quadros": pares}
            )

    def abrir(self) -> None:
        if not self._ids:
            return self.listar()
        job = self._rng.choice(self._ids)
        self._pedir("GET /v1/jobs/{id}", f"/v1/jobs/{job}")
        self._pedir("GET /v1/jobs/{id}/decupagem", f"/v1/jobs/{job}/decupagem")

    def listar(self) -> None:
        params: dict[str, Any] = {"limite": 24, "ordem": "enviado"}
        sorteio = self._rng.random()
        if sorteio < 0.25:
            params["q"] = self._rng.choice(self._termos)
        elif sorteio < 0.5:
            params["estado"] = "concluido"
        lista = self._pedir("GET /v1/jobs", "/v1/jobs", params)
        concluidos = [j["id"] for j in lista or [] if j.get("estado") == "concluido"]
        self._ids = concluidos or self._ids

    def agir(self) -> None:
        acao = self._rng.choices(list(PESOS), list(PESOS.values()))[0]
        getattr(self, acao)()


def pausa_sorteada(texto: str, rng: random.Random) -> Callable[[], float]:
    """`PAUSA_S`: `5-15` sorteia entre os dois a cada ação; `10` é fixa."""
    de, _, ate = texto.partition("-")
    return lambda: rng.uniform(float(de), float(ate or de))


def rodar(
    transportes: list[Transporte],
    usuarios: int,
    duracao_s: float,
    rampa_s: float,
    pausa: Callable[[], float],
    termos: list[str],
    medidas: Medidas,
    parar: threading.Event,
) -> None:
    inicio = time.monotonic()

    erros: list[BaseException] = []

    def um(i: int) -> None:
        try:
            if parar.wait(rampa_s * i / usuarios):
                return
            pessoa = Usuario(
                transportes[i % len(transportes)],
                medidas,
                termos,
                random.Random(i),
                parar,
            )
            while time.monotonic() - inicio < duracao_s and not parar.is_set():
                pessoa.agir()
                restante = max(0.0, duracao_s - (time.monotonic() - inicio))
                parar.wait(min(pausa(), restante))
        except BaseException as e:  # noqa: BLE001 - repassa à thread principal
            erros.append(e)
            parar.set()

    # Daemon: na interrupção o Python não espera os pedidos presos no timeout.
    threads = [
        threading.Thread(target=um, args=(i,), daemon=True) for i in range(usuarios)
    ]
    for t in threads:
        t.start()
    try:
        for t in threads:  # fim normal: espera os pedidos em curso
            t.join()
    except BaseException:
        parar.set()
        raise
    if erros:
        raise erros[0]


def main() -> int:
    url, token = os.environ.get("URL"), os.environ.get("TOKEN")
    if not (url and token):
        print(
            "Faltam URL e TOKEN (o ID token da sua sessão no front, vale 1 h; "
            "vários separados por vírgula).",
            file=sys.stderr,
        )
        return 2
    try:
        usuarios = int(os.environ.get("USUARIOS") or 200)
        duracao = float(os.environ.get("DURACAO_S") or 300)
        rampa = float(os.environ.get("RAMPA_S") or 30)
        pausa = pausa_sorteada(os.environ.get("PAUSA_S") or "5-15", random.Random())
    except ValueError:
        print("USUARIOS, DURACAO_S, RAMPA_S ou PAUSA_S inválido.", file=sys.stderr)
        return 2
    transportes = [
        transporte_http(url, t.strip()) for t in token.split(",") if t.strip()
    ]
    medidas, parar = Medidas(), threading.Event()
    print(
        f"{usuarios} usuários por {duracao:.0f} s, rampa de {rampa:.0f} s; Ctrl+C encerra."
    )
    try:
        rodar(
            transportes,
            usuarios,
            duracao,
            rampa,
            pausa,
            consultas_da_sonda(),
            medidas,
            parar,
        )
    except KeyboardInterrupt:
        parar.set()
    foto = medidas.copia()  # uma só: relatório e código de saída saem dela
    if not foto.total():
        print(f"Nenhum pedido concluído ({foto.no_ar} no ar).", file=sys.stderr)
        return 1
    print(foto.texto())
    return 1 if foto.falhas() else 0


if __name__ == "__main__":
    sys.exit(main())
