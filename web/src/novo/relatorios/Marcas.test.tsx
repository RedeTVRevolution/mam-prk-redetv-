import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, test, vi } from "vitest";
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from "../../auth/falso.ts";
import { filtrosDeMarcas } from "../../marcas.ts";
import App from "../App.tsx";

// Os casos de src/Marcas.test.tsx (interface atual) na interface nova, mais a paginação por
// cursor e as inserções que só vêm quando a marca abre.

const AMBEV = {
  marca: "Ambev",
  insercoes: 3,
  tempo_ms: 55_000,
  videos: 2,
  por_tipo: [
    { tipo: "merchan_apresentador", insercoes: 2, tempo_ms: 50_000, videos: 2 },
    { tipo: "sobreposicao_grafica", insercoes: 1, tempo_ms: 5_000, videos: 1 },
  ],
};
const NATURA = {
  marca: "Natura",
  insercoes: 1,
  tempo_ms: 5_000,
  videos: 1,
  por_tipo: [{ tipo: "intervalo", insercoes: 1, tempo_ms: 5_000, videos: 1 }],
};
const PRIMEIRA = {
  programa: null,
  desde: null,
  ate: null,
  tipo: null,
  // Os totais são do período todo: 3 marcas, de uma página de 2.
  total: { marcas: 3, insercoes: 4, tempo_ms: 60_000, videos: 2 },
  marcas: [AMBEV, NATURA],
};
const SEGUNDA = {
  ...PRIMEIRA,
  marcas: [{ ...NATURA, marca: "Vivo", por_tipo: [{ tipo: "testemunhal", insercoes: 1, tempo_ms: 5_000, videos: 1 }] }],
};

const INSERCOES = [
  { job_id: "v1", nome: "tv-fama-01.mp4", tipo: "merchan_apresentador", inicio_ms: 60_000, fim_ms: 90_000 },
  { job_id: "v2", nome: null, tipo: "sobreposicao_grafica", inicio_ms: 0, fim_ms: 5_000 },
];

const pedidos: URLSearchParams[] = [];
const pedidosDeInsercoes: URLSearchParams[] = [];
const comProxima = () => HttpResponse.json(PRIMEIRA, { headers: { "X-Proximo-Cursor": "pag2" } });
let resposta: (p: URLSearchParams) => Response = comProxima;

const servidor = setupServer(
  http.get("/v1/eu", () =>
    HttpResponse.json({ uid: "u1", email: "ana@redetv.com.br", permissoes: ["decupagem.ver"] }),
  ),
  http.get("/v1/jobs", () => HttpResponse.json([])),
  http.get("/v1/programas", () => HttpResponse.json(["TV Fama", "Leo Dias"])),
  http.get("/v1/relatorios/marcas", ({ request }) => {
    const p = new URL(request.url).searchParams;
    pedidos.push(p);
    if (p.get("formato") === "csv") {
      return new HttpResponse("marca,tipo\nAmbev,todos\n", { headers: { "Content-Type": "text/csv" } });
    }
    return resposta(p);
  }),
  http.get("/v1/relatorios/marcas/insercoes", ({ request }) => {
    const p = new URL(request.url).searchParams;
    pedidosDeInsercoes.push(p);
    if (p.get("cursor") === "mais") {
      return HttpResponse.json([{ job_id: "v9", nome: "extra.mp4", tipo: "intervalo", inicio_ms: 0, fim_ms: 1_000 }]);
    }
    if (p.get("marca") !== "Ambev") return HttpResponse.json([]);
    const tipo = p.get("tipo");
    const lista = INSERCOES.filter((i) => !tipo || i.tipo === tipo);
    return HttpResponse.json(lista, tipo ? {} : { headers: { "X-Proximo-Cursor": "mais" } });
  }),
);

beforeAll(() => servidor.listen({ onUnhandledFrame: "error" }));
// A tela é carregada sob demanda; sob carga, a primeira importação passava de 1 s e o primeiro teste falhava.
beforeAll(() => import("./Marcas.tsx"));
afterEach(() => {
  cleanup();
  history.replaceState(null, "", "/");
  servidor.resetHandlers();
  pedidos.length = 0;
  pedidosDeInsercoes.length = 0;
  resposta = comProxima;
});
afterAll(() => servidor.close());

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([{ email: "ana@redetv.com.br", senha: "senha-forte-1", totpCadastrado: true }]);
  await auth.entrar("ana@redetv.com.br", "senha-forte-1");
  await auth.confirmarTotp(CODIGO_TOTP_FALSO);
  history.replaceState(null, "", endereco);
  render(<App autenticador={auth} />);
}

const TABELA = "Inserções por marca";
const tabela = () => screen.findByRole("table", { name: TABELA });
const linhasDe = (t: HTMLElement) =>
  within(t)
    .getAllByRole("row")
    .slice(1)
    .map((l) => within(l).getAllByRole("cell").map((c) => c.textContent));

test("a tabela mostra inserções, tempo, vídeos e o detalhe por tipo, na ordem da API", async () => {
  await abrir("/relatorios/marcas");

  expect(linhasDe(await tabela())).toEqual([
    ["Ambev", "3", "55s", "2", "Merchan com apresentador: 2 (50s) · Sobreposição gráfica: 1 (5s)"],
    ["Natura", "1", "5s", "1", "Intervalo: 1 (5s)"],
  ]);
});

test("os cartões vêm do total do período, e os vídeos são os distintos", async () => {
  await abrir("/relatorios/marcas");
  await tabela();

  const cartoes = screen.getByRole("region", { name: "Resumo do período" });
  const valor = (rotulo: string) => within(cartoes).getByText(rotulo).nextElementSibling?.textContent;
  expect(valor("Marcas")).toBe("3");
  expect(valor("Inserções")).toBe("4");
  expect(valor("Tempo")).toBe("1min00s");
  expect(valor("Vídeos")).toBe("2");
});

test("os filtros, o tipo inclusive, vão à API e ao endereço", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/marcas?programa=TV+Fama&de=2026-10-01&ate=2026-10-31&tipo=intervalo");
  await tabela();

  expect(pedidos[0].get("programa")).toBe("TV Fama");
  expect(pedidos[0].get("desde")).toBe("2026-10-01");
  expect(pedidos[0].get("ate")).toBe("2026-10-31");
  expect(pedidos[0].get("tipo")).toBe("intervalo");
  expect(pedidos[0].get("limite")).toBe("50");

  fireEvent.change(screen.getByLabelText("Exibido até"), { target: { value: "2026-10-15" } });
  await waitFor(() => expect(pedidos.at(-1)?.get("ate")).toBe("2026-10-15"));
  expect(location.search).toContain("ate=2026-10-15");

  await usuario.selectOptions(screen.getByLabelText("Tipo de inserção"), "Testemunhal");
  await waitFor(() => expect(pedidos.at(-1)?.get("tipo")).toBe("testemunhal"));
  expect(location.search).toContain("tipo=testemunhal");
});

test("clicar numa marca pede as inserções dela só então: o vídeo, o tipo e o tempo", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/marcas");
  await tabela();
  expect(pedidosDeInsercoes).toHaveLength(0);

  await usuario.click(await screen.findByRole("button", { name: "Ambev" }));

  const lista = await screen.findByRole("table", { name: "Inserções de Ambev" });
  const link = within(lista).getByRole("link", { name: "tv-fama-01.mp4" });
  expect(link.getAttribute("href")).toBe("/video/v1?t=60");
  expect(within(lista).getByText("Merchan com apresentador")).toBeTruthy();
  expect(within(lista).getByText("30s")).toBeTruthy();
  // Sem nome, o vídeo aparece pelo id.
  expect(within(lista).getByRole("link", { name: "v2" })).toBeTruthy();
  expect(pedidosDeInsercoes[0].get("marca")).toBe("Ambev");
  expect(pedidosDeInsercoes[0].get("limite")).toBe("25");

  await usuario.click(screen.getByRole("button", { name: "Ambev" }));
  expect(screen.queryByRole("table", { name: "Inserções de Ambev" })).toBeNull();
});

test("a lista das inserções pede mais com o cursor e junta à lista", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/marcas");

  await usuario.click(await screen.findByRole("button", { name: "Ambev" }));
  await screen.findByRole("table", { name: "Inserções de Ambev" });
  await usuario.click(screen.getByRole("button", { name: "Ver mais inserções" }));

  const lista = screen.getByRole("table", { name: "Inserções de Ambev" });
  expect(await within(lista).findByRole("link", { name: "extra.mp4" })).toBeTruthy();
  expect(pedidosDeInsercoes.at(-1)?.get("cursor")).toBe("mais");
  expect(screen.queryByRole("button", { name: "Ver mais inserções" })).toBeNull();
});

test("Próxima pede a página seguinte com o cursor; Anterior volta, e a última não tem Próxima", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/marcas");
  await tabela();
  resposta = (p) => (p.get("cursor") === "pag2" ? HttpResponse.json(SEGUNDA) : comProxima());

  await usuario.click(screen.getByRole("button", { name: "Próxima" }));

  await screen.findByRole("button", { name: "Vivo" });
  expect(pedidos.at(-1)?.get("cursor")).toBe("pag2");
  expect(screen.getByText("Página 2")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Próxima" }) as HTMLButtonElement).disabled).toBe(true);

  await usuario.click(screen.getByRole("button", { name: "Anterior" }));
  expect(await screen.findByRole("button", { name: "Ambev" })).toBeTruthy();
  expect(screen.getByText("Página 1")).toBeTruthy();
});

test("cursor recusado (422) mostra a mensagem da API, e Anterior continua valendo", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/marcas");
  await tabela();
  resposta = (p) =>
    p.get("cursor") === "pag2" ? HttpResponse.json({ detail: "Cursor inválido" }, { status: 422 }) : comProxima();

  await usuario.click(screen.getByRole("button", { name: "Próxima" }));

  const alerta = await screen.findByRole("alert");
  expect(alerta.textContent).toContain("Cursor inválido");
  expect(alerta.textContent).toContain("http_422");
  await usuario.click(screen.getByRole("button", { name: "Anterior" }));
  expect(await tabela()).toBeTruthy();
});

test("Baixar CSV pede o formato csv com os mesmos filtros e entrega o arquivo", async () => {
  const usuario = userEvent.setup();
  const criar = vi.fn(() => "blob:csv");
  Object.assign(URL, { createObjectURL: criar, revokeObjectURL: vi.fn() });
  const clique = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  await abrir("/relatorios/marcas?programa=TV+Fama&tipo=intervalo");
  await tabela();

  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));

  await waitFor(() => expect(clique).toHaveBeenCalled());
  const csv = pedidos.find((p) => p.get("formato") === "csv");
  expect(csv?.get("programa")).toBe("TV Fama");
  expect(csv?.get("tipo")).toBe("intervalo");
  // O CSV vem inteiro: não leva limite nem cursor.
  expect(csv?.get("limite")).toBeNull();
  expect(csv?.get("cursor")).toBeNull();
  expect(criar).toHaveBeenCalled();
  clique.mockRestore();
});

test("sem inserção no filtro, a tela diz isso, não oferece o CSV e não há gráfico nem matriz", async () => {
  resposta = () => HttpResponse.json({ ...PRIMEIRA, total: { marcas: 0, insercoes: 0, tempo_ms: 0, videos: 0 }, marcas: [] });
  await abrir("/relatorios/marcas");

  expect(await screen.findByText("Nenhuma inserção de marca neste filtro.")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Baixar CSV" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole("img", { name: /^Marcas com mais tempo/ })).toBeNull();
  expect(screen.queryByRole("table", { name: "Tempo por marca e tipo de inserção" })).toBeNull();
});

test("erro da API mostra o alerta com o código e tenta de novo", async () => {
  const usuario = userEvent.setup();
  resposta = () => new HttpResponse(null, { status: 503 });
  await abrir("/relatorios/marcas");

  expect(await screen.findByText(/Código para o suporte: http_503/, {}, { timeout: 5000 })).toBeTruthy();

  resposta = comProxima;
  await usuario.click(screen.getByRole("button", { name: "Tentar de novo" }));

  expect(await tabela()).toBeTruthy();
}, 15_000);

test("o trilho leva ao relatório", async () => {
  const usuario = userEvent.setup();
  await abrir("/acervo");

  await usuario.click(await within(await screen.findByRole("navigation", { name: "Principal" })).findByRole("link", { name: "Marcas" }));

  expect(location.pathname).toBe("/relatorios/marcas");
  expect(await tabela()).toBeTruthy();
});

test("tipo desconhecido no endereço sai dos filtros", () => {
  expect(filtrosDeMarcas("tipo=outdoor&programa=X")).toEqual({ programa: "X", de: "", ate: "", tipo: "" });
  expect(filtrosDeMarcas("tipo=testemunhal").tipo).toBe("testemunhal");
  expect(filtrosDeMarcas("tipo=toString").tipo).toBe("");
});

test("o ranking vem acima da tabela; clicar na barra abre a linha da marca", async () => {
  await abrir("/relatorios/marcas");

  const ranking = await screen.findByRole("img", { name: /^Marcas com mais tempo/ });
  expect(await within(ranking).findByText("Ambev")).toBeTruthy();
  expect(within(ranking).getByText("55s")).toBeTruthy();
  // O ranking e a tabela vêm da mesma página: um pedido só.
  expect(pedidos.filter((p) => !p.get("cursor") && !p.get("formato"))).toHaveLength(1);

  const barras = ranking.querySelectorAll(".recharts-bar-rectangle");
  fireEvent.click(barras[0].firstElementChild ?? barras[0]);
  expect(await screen.findByRole("table", { name: "Inserções de Ambev" })).toBeTruthy();
});

test("a matriz tem uma coluna por tipo com inserção; clicar na célula abre a marca filtrada pelo tipo", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/marcas");

  const matriz = await screen.findByRole("table", { name: "Tempo por marca e tipo de inserção" });
  const colunas = within(matriz)
    .getAllByRole("columnheader")
    .map((c) => c.textContent);
  // Só os tipos com inserção no filtro, na ordem da lista de tipos.
  expect(colunas).toEqual(["Marca", "Intervalo", "Merchan com apresentador", "Sobreposição gráfica"]);

  await usuario.click(within(matriz).getByRole("button", { name: "Ambev, Sobreposição gráfica: 5s" }));

  const lista = await screen.findByRole("table", { name: "Inserções de Ambev" });
  expect(await within(lista).findByRole("link", { name: "v2" })).toBeTruthy();
  expect(within(lista).queryByRole("link", { name: "tv-fama-01.mp4" })).toBeNull();
  expect(screen.getByText("Só Sobreposição gráfica")).toBeTruthy();
  expect(pedidosDeInsercoes.at(-1)?.get("tipo")).toBe("sobreposicao_grafica");
});

test("a célula leva a cor do passo da escala e o texto legível sobre ela", async () => {
  await abrir("/relatorios/marcas");
  const matriz = await screen.findByRole("table", { name: "Tempo por marca e tipo de inserção" });

  // 50s é o maior da matriz (passo mais claro); 5s é um décimo dele (o mais escuro).
  expect(within(matriz).getByRole("button", { name: "Ambev, Merchan com apresentador: 50s" }).className).toContain("bg-seq-100 text-background");
  expect(within(matriz).getByRole("button", { name: "Ambev, Sobreposição gráfica: 5s" }).className).toContain("bg-seq-600 text-primary-foreground");
});

test("o ranking alterna com a tabela dos mesmos números", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/marcas");
  const secao = await screen.findByRole("region", { name: "Marcas com mais tempo" });

  await usuario.click(within(secao).getByRole("button", { name: "Tabela" }));

  expect(linhasDe(within(secao).getByRole("table", { name: "Marcas com mais tempo" }))).toEqual([
    ["Ambev", "55s"],
    ["Natura", "5s"],
  ]);
});
