import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, test, vi } from "vitest";
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from "../../auth/falso.ts";
import { duracaoLegivel, filtrosDoRelatorio } from "../../tempoDeTela.ts";
import App from "../App.tsx";

// Os casos de src/TempoDeTela.test.tsx (interface atual) na interface nova, mais a paginação por
// cursor e o detalhe que só vem quando a linha abre.

const video = (job_id: string, nome: string | null, tempo_de_tela_ms: number) => ({
  job_id,
  nome,
  tempo_de_tela_ms,
  aparicoes: 2,
  mencoes_na_fala: 1,
  mencoes_no_texto: 0,
});

const SABRINA = {
  pessoa_id: "c1",
  nome: "Sabrina Sato",
  tempo_de_tela_ms: 725_000,
  videos: 2,
  aparicoes: 4,
  mencoes_na_fala: 2,
  mencoes_no_texto: 1,
};
const LEO = {
  pessoa_id: "c2",
  nome: "Leo Dias",
  tempo_de_tela_ms: 45_000,
  videos: 1,
  aparicoes: 1,
  mencoes_na_fala: 0,
  mencoes_no_texto: 3,
};
const TOTAL = {
  pessoas: 3,
  tempo_de_tela_ms: 770_000 + 30_000,
  videos: 3,
  aparicoes: 6,
  mencoes_na_fala: 2,
  mencoes_no_texto: 4,
};
const PRIMEIRA = {
  programa: null,
  desde: null,
  ate: null,
  total: TOTAL,
  pessoas: [SABRINA, LEO],
};
const SEGUNDA = {
  ...PRIMEIRA,
  pessoas: [{ ...LEO, pessoa_id: "c3", nome: "Ticiane Pinheiro", tempo_de_tela_ms: 30_000 }],
};

const VIDEOS: Record<string, ReturnType<typeof video>[]> = {
  c1: [video("v1", "tv-fama-01.mp4", 600_000), video("v2", null, 125_000)],
  c2: [video("v1", "tv-fama-01.mp4", 45_000)],
};

const pedidos: URLSearchParams[] = [];
const pedidosDeVideos: URLSearchParams[] = [];
let resposta: (p: URLSearchParams) => Response = () => HttpResponse.json(PRIMEIRA, { headers: { "X-Proximo-Cursor": "pag2" } });

const servidor = setupServer(
  http.get("/v1/eu", () =>
    HttpResponse.json({ uid: "u1", email: "ana@redetv.com.br", permissoes: ["decupagem.ver"] }),
  ),
  http.get("/v1/jobs", () => HttpResponse.json([])),
  http.get("/v1/programas", () => HttpResponse.json(["TV Fama", "Leo Dias"])),
  http.get("/v1/relatorios/tempo-de-tela", ({ request }) => {
    const p = new URL(request.url).searchParams;
    pedidos.push(p);
    if (p.get("formato") === "csv") {
      return new HttpResponse("pessoa_id,nome\nc1,Sabrina Sato\n", { headers: { "Content-Type": "text/csv" } });
    }
    return resposta(p);
  }),
  http.get("/v1/relatorios/tempo-de-tela/videos", ({ request }) => {
    const p = new URL(request.url).searchParams;
    pedidosDeVideos.push(p);
    const todos = VIDEOS[p.get("pessoa_id") ?? ""] ?? [];
    // A segunda página existe para a Sabrina, para provar o "Ver mais".
    if (p.get("cursor") === "mais") return HttpResponse.json([video("v9", "extra.mp4", 1_000)]);
    return HttpResponse.json(todos, p.get("pessoa_id") === "c1" ? { headers: { "X-Proximo-Cursor": "mais" } } : {});
  }),
);

beforeAll(() => servidor.listen({ onUnhandledFrame: "error" }));
// A tela é carregada sob demanda; sob carga, a primeira importação passava de 1 s e o primeiro teste falhava.
beforeAll(() => import("./TempoDeTela.tsx"));
afterEach(() => {
  cleanup();
  history.replaceState(null, "", "/");
  servidor.resetHandlers();
  pedidos.length = 0;
  pedidosDeVideos.length = 0;
  resposta = () => HttpResponse.json(PRIMEIRA, { headers: { "X-Proximo-Cursor": "pag2" } });
});
afterAll(() => servidor.close());

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([{ email: "ana@redetv.com.br", senha: "senha-forte-1", totpCadastrado: true }]);
  await auth.entrar("ana@redetv.com.br", "senha-forte-1");
  await auth.confirmarTotp(CODIGO_TOTP_FALSO);
  history.replaceState(null, "", endereco);
  render(<App autenticador={auth} />);
}

const TABELA = "Tempo de tela por pessoa";
const tabela = () => screen.findByRole("table", { name: TABELA });
const linhasDe = (t: HTMLElement) =>
  within(t)
    .getAllByRole("row")
    .slice(1)
    .map((l) => within(l).getAllByRole("cell").map((c) => c.textContent));

test("a tabela mostra tempo, vídeos, aparições e menções, na ordem da API", async () => {
  await abrir("/relatorios/tempo-de-tela");

  expect(linhasDe(await tabela())).toEqual([
    ["Sabrina Sato", "12min05s", "2", "4", "2", "1"],
    ["Leo Dias", "45s", "1", "1", "0", "3"],
  ]);
});

test("os cartões trazem o total do período todo, não só o da página", async () => {
  await abrir("/relatorios/tempo-de-tela");
  await tabela();

  const cartoes = screen.getByRole("region", { name: "Resumo do período" });
  expect(within(cartoes).getByText("Pessoas").nextElementSibling?.textContent).toBe("3");
  expect(within(cartoes).getByText("Tempo de tela").nextElementSibling?.textContent).toBe("13min20s");
  expect(within(cartoes).getByText("Vídeos").nextElementSibling?.textContent).toBe("3");
});

test("os filtros vão à API e ao endereço; o endereço reproduz os filtros", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/tempo-de-tela?programa=TV+Fama&de=2026-10-01&ate=2026-10-31");
  await tabela();

  expect(pedidos[0].get("programa")).toBe("TV Fama");
  expect(pedidos[0].get("desde")).toBe("2026-10-01");
  expect(pedidos[0].get("ate")).toBe("2026-10-31");
  // O ranking vem de 50 em 50, não inteiro.
  expect(pedidos[0].get("limite")).toBe("50");

  fireEvent.change(screen.getByLabelText("Exibido até"), { target: { value: "2026-10-15" } });
  await waitFor(() => expect(pedidos.at(-1)?.get("ate")).toBe("2026-10-15"));
  expect(location.search).toContain("ate=2026-10-15");

  await usuario.selectOptions(screen.getByLabelText("Programa"), "Leo Dias");
  await waitFor(() => expect(pedidos.at(-1)?.get("programa")).toBe("Leo Dias"));
  expect(location.search).toContain("programa=Leo+Dias");
});

test("clicar numa pessoa pede os vídeos dela só então, e a lista mostra os tempos", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/tempo-de-tela");
  await tabela();
  expect(pedidosDeVideos).toHaveLength(0);

  await usuario.click(await screen.findByRole("button", { name: "Sabrina Sato" }));

  const videos = await screen.findByRole("table", { name: "Vídeos de Sabrina Sato" });
  expect(within(videos).getByRole("link", { name: "tv-fama-01.mp4" }).getAttribute("href")).toBe("/video/v1");
  expect(within(videos).getByText("10min00s")).toBeTruthy();
  // Sem nome, o vídeo aparece pelo id.
  expect(within(videos).getByRole("link", { name: "v2" })).toBeTruthy();
  expect(pedidosDeVideos[0].get("pessoa_id")).toBe("c1");
  expect(pedidosDeVideos[0].get("limite")).toBe("25");

  await usuario.click(screen.getByRole("button", { name: "Sabrina Sato" }));
  expect(screen.queryByRole("table", { name: "Vídeos de Sabrina Sato" })).toBeNull();
});

test("o detalhe pede mais vídeos com o cursor e junta à lista", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/tempo-de-tela");

  await usuario.click(await screen.findByRole("button", { name: "Sabrina Sato" }));
  await screen.findByRole("table", { name: "Vídeos de Sabrina Sato" });
  await usuario.click(screen.getByRole("button", { name: "Ver mais vídeos" }));

  const videos = screen.getByRole("table", { name: "Vídeos de Sabrina Sato" });
  expect(await within(videos).findByRole("link", { name: "extra.mp4" })).toBeTruthy();
  expect(pedidosDeVideos.at(-1)?.get("cursor")).toBe("mais");
  // Acabou: não há mais o que pedir.
  expect(screen.queryByRole("button", { name: "Ver mais vídeos" })).toBeNull();
});

test("Próxima pede a página seguinte com o cursor; Anterior volta, e a última não tem Próxima", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/tempo-de-tela");
  await tabela();
  expect((screen.getByRole("button", { name: "Anterior" }) as HTMLButtonElement).disabled).toBe(true);

  resposta = (p) =>
    p.get("cursor") === "pag2" ? HttpResponse.json(SEGUNDA) : HttpResponse.json(PRIMEIRA, { headers: { "X-Proximo-Cursor": "pag2" } });
  await usuario.click(screen.getByRole("button", { name: "Próxima" }));

  await screen.findByRole("button", { name: "Ticiane Pinheiro" });
  expect(pedidos.at(-1)?.get("cursor")).toBe("pag2");
  expect(screen.getByText("Página 2")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Próxima" }) as HTMLButtonElement).disabled).toBe(true);

  await usuario.click(screen.getByRole("button", { name: "Anterior" }));
  expect(await screen.findByRole("button", { name: "Sabrina Sato" })).toBeTruthy();
  expect(screen.getByText("Página 1")).toBeTruthy();
});

test("mudar o filtro volta à primeira página", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/tempo-de-tela");
  await tabela();
  resposta = (p) =>
    p.get("cursor") === "pag2" ? HttpResponse.json(SEGUNDA) : HttpResponse.json(PRIMEIRA, { headers: { "X-Proximo-Cursor": "pag2" } });
  await usuario.click(screen.getByRole("button", { name: "Próxima" }));
  await screen.findByText("Página 2");

  fireEvent.change(screen.getByLabelText("Exibido de"), { target: { value: "2026-10-01" } });

  await screen.findByText("Página 1");
  expect(pedidos.at(-1)?.get("cursor")).toBeNull();
});

test("cursor recusado (422) mostra a mensagem da API, e Anterior continua valendo", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/tempo-de-tela");
  await tabela();
  resposta = (p) =>
    p.get("cursor") === "pag2"
      ? HttpResponse.json({ detail: "Cursor inválido" }, { status: 422 })
      : HttpResponse.json(PRIMEIRA, { headers: { "X-Proximo-Cursor": "pag2" } });

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
  await abrir("/relatorios/tempo-de-tela?programa=TV+Fama");
  await tabela();

  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));

  await waitFor(() => expect(clique).toHaveBeenCalled());
  const csv = pedidos.find((p) => p.get("formato") === "csv");
  expect(csv?.get("programa")).toBe("TV Fama");
  // O CSV vem inteiro: não leva limite nem cursor.
  expect(csv?.get("limite")).toBeNull();
  expect(csv?.get("cursor")).toBeNull();
  expect(criar).toHaveBeenCalled();
  clique.mockRestore();
});

test("sem aparição nem menção no filtro, a tela diz isso e não oferece o CSV", async () => {
  resposta = () => HttpResponse.json({ ...PRIMEIRA, total: { ...TOTAL, pessoas: 0 }, pessoas: [] });
  await abrir("/relatorios/tempo-de-tela");

  expect(await screen.findByText("Nenhuma pessoa com aparição ou menção neste filtro.")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Baixar CSV" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole("img", { name: /^Pessoas com mais tempo de tela/ })).toBeNull();
});

test("erro da API mostra o alerta com o código e tenta de novo", async () => {
  const usuario = userEvent.setup();
  resposta = () => new HttpResponse(null, { status: 503 });
  await abrir("/relatorios/tempo-de-tela");

  expect(await screen.findByText(/Código para o suporte: http_503/, {}, { timeout: 5000 })).toBeTruthy();

  resposta = () => HttpResponse.json(PRIMEIRA);
  await usuario.click(screen.getByRole("button", { name: "Tentar de novo" }));

  expect(await tabela()).toBeTruthy();
});

test("o trilho leva ao relatório", async () => {
  const usuario = userEvent.setup();
  await abrir("/acervo");

  await usuario.click(await within(await screen.findByRole("navigation", { name: "Principal" })).findByRole("link", { name: "Tempo de tela" }));

  expect(location.pathname).toBe("/relatorios/tempo-de-tela");
  expect(await tabela()).toBeTruthy();
});

test("duração legível e filtros do endereço", () => {
  expect(duracaoLegivel(3_720_000)).toBe("1h02min");
  expect(duracaoLegivel(45_000)).toBe("45s");
  expect(filtrosDoRelatorio("de=ontem&ate=2026-10-31&programa=X")).toEqual({ programa: "X", de: "", ate: "2026-10-31" });
});

test("o gráfico mostra as pessoas e a divisão por tipo da primeira; clicar na barra abre a linha da tabela", async () => {
  await abrir("/relatorios/tempo-de-tela");

  const grafico = await screen.findByRole("img", { name: /^Pessoas com mais tempo de tela/ });
  expect(await within(grafico).findByText("Sabrina Sato")).toBeTruthy();
  expect(within(grafico).getByText("Leo Dias")).toBeTruthy();
  expect(within(grafico).getByText("12min05s")).toBeTruthy();
  // O ranking e a tabela vêm da mesma página: um pedido só.
  expect(pedidos.filter((p) => !p.get("cursor") && !p.get("formato"))).toHaveLength(1);

  const divisao = screen.getByRole("img", { name: "Divisão por tipo de Sabrina Sato" });
  expect(within(divisao).getByText("Menções na fala").nextElementSibling?.textContent).toBe("2");

  const barras = grafico.querySelectorAll(".recharts-bar-rectangle");
  fireEvent.click(barras[barras.length - 1].firstElementChild ?? barras[barras.length - 1]);
  expect(await screen.findByRole("table", { name: "Vídeos de Leo Dias" })).toBeTruthy();
  expect(screen.getByRole("img", { name: "Divisão por tipo de Leo Dias" })).toBeTruthy();
  // A barra da linha aberta fica em destaque; a outra continua na cor de série única.
  const cores = [...grafico.querySelectorAll(".recharts-bar-rectangle path")].map((p) => p.getAttribute("fill"));
  expect(cores).toEqual(["var(--color-primary)", "var(--color-link)"]);
});

test("o gráfico alterna com a tabela dos mesmos números", async () => {
  const usuario = userEvent.setup();
  await abrir("/relatorios/tempo-de-tela");
  const secao = await screen.findByRole("region", { name: "Pessoas com mais tempo de tela" });

  await usuario.click(within(secao).getByRole("button", { name: "Tabela" }));

  expect(linhasDe(within(secao).getByRole("table", { name: "Pessoas com mais tempo de tela" }))).toEqual([
    ["Sabrina Sato", "12min05s"],
    ["Leo Dias", "45s"],
  ]);
  expect(within(secao).queryByRole("img")).toBeNull();
});
