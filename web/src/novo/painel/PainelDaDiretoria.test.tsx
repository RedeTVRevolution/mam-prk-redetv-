import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, test, vi } from "vitest";
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from "../../auth/falso.ts";
import catalogo from "../../catalogo.fixture.json";
import App from "../App.tsx";
import { NOTA_DO_DIA } from "./formato.ts";

// Os mesmos casos de src/PainelDaDiretoria.test.tsx (interface antiga), na interface nova; as
// tabelas ficam atrás do "Tabela" de cada seção, e o gráfico vem primeiro.

const RELATORIO = {
  desde: null,
  ate: null,
  usuario: null,
  total: { acessos: 7, usuarios_ativos: 2 },
  por_dia: [
    { dia: "2026-11-02", acessos: 3, usuarios_ativos: 2 },
    { dia: "2026-11-03", acessos: 4, usuarios_ativos: 1 },
  ],
  por_semana: [{ inicio: "2026-11-02", usuarios_ativos: 2 }],
  por_mes: [{ inicio: "2026-11-01", usuarios_ativos: 2 }],
  por_usuario: [
    {
      uid: "u1",
      email: "ana@redetv.com.br",
      acessos: 5,
      dias_ativos: 2,
      ultimo_acesso: "2026-11-03T15:00:00Z",
    },
    { uid: "u2", email: null, acessos: 2, dias_ativos: 1, ultimo_acesso: null },
  ],
};

const VIDEOS = {
  desde: null,
  ate: null,
  programa: null,
  usuario: null,
  total: {
    enviados: 5,
    concluidos: 3,
    falhos: 1,
    horas_concluidas: 3.5,
    tempo_medio_s: 120,
  },
  por_dia: [
    {
      dia: "2026-11-02",
      enviados: 5,
      concluidos: 3,
      falhos: 1,
      horas_concluidas: 3.5,
      tempo_medio_s: 120,
    },
  ],
  por_programa: [
    {
      programa: "TV Fama",
      enviados: 5,
      concluidos: 3,
      falhos: 1,
      horas_concluidas: 3.5,
      tempo_medio_s: null,
    },
    {
      programa: null,
      enviados: 0,
      concluidos: 0,
      falhos: 0,
      horas_concluidas: 0,
      tempo_medio_s: null,
    },
  ],
  por_usuario: [
    {
      quem_tipo: "usuario",
      quem_id: "u1",
      email: "ana@redetv.com.br",
      enviados: 2,
      concluidos: 2,
      falhos: 0,
      horas_concluidas: 1,
      tempo_medio_s: 60,
    },
    {
      quem_tipo: "sistema",
      quem_id: "ingestao",
      email: null,
      enviados: 3,
      concluidos: 1,
      falhos: 1,
      horas_concluidas: 2.5,
      tempo_medio_s: null,
    },
  ],
};

const BUSCAS = {
  desde: null,
  ate: null,
  programa: null,
  usuario: null,
  total: { buscas: 9, usuarios_que_buscam: 2, sem_resultado: 4 },
  por_dia: [
    { dia: "2026-11-03", buscas: 9, usuarios_que_buscam: 2, sem_resultado: 4 },
  ],
  por_usuario: [
    {
      quem_tipo: "usuario",
      quem_id: "u1",
      email: "ana@redetv.com.br",
      buscas: 9,
      sem_resultado: 4,
    },
  ],
};

const REVISAO = {
  desde: null,
  ate: null,
  programa: null,
  usuario: null,
  correcoes: {
    total: 6,
    por_dia: [{ dia: "2026-11-02", correcoes: 6 }],
    por_tipo: [
      { tipo: "texto", correcoes: 4 },
      { tipo: null, correcoes: 2 },
    ],
    por_usuario: [
      {
        quem_tipo: "usuario",
        quem_id: "u1",
        email: "ana@redetv.com.br",
        correcoes: 6,
      },
    ],
  },
  taxa_de_correcao: {
    por_tipo: [{ tipo: "texto", correcoes: 4, itens: 32, taxa: 0.125 }],
    por_programa: [{ programa: null, correcoes: 4, itens: 32, taxa: null }],
  },
  tempo_de_revisao: {
    total: {
      minutos: 30,
      videos: 2,
      horas_de_video: 1.5,
      minutos_por_hora_de_video: 20,
    },
    por_pessoa: [
      {
        uid: "u1",
        email: "ana@redetv.com.br",
        minutos: 30,
        videos: 2,
        horas_de_video: 1.5,
        minutos_por_hora_de_video: 20,
      },
    ],
    por_programa: [
      {
        programa: "TV Fama",
        minutos: 30,
        videos: 2,
        horas_de_video: 1.5,
        minutos_por_hora_de_video: null,
      },
    ],
  },
};

const API = {
  desde: null,
  ate: null,
  usuario: null,
  total: {
    chamadas: 10,
    erros_do_cliente: 2,
    erros_do_servidor: 1,
    sistemas: 1,
    videos_enviados: 3,
  },
  por_dia: [
    {
      dia: "2026-11-03",
      chamadas: 10,
      erros_do_cliente: 2,
      erros_do_servidor: 1,
      videos_enviados: 3,
    },
  ],
  por_sistema: [
    {
      quem_tipo: "sistema",
      quem_id: "ingestao",
      chamadas: 10,
      erros_do_cliente: 2,
      erros_do_servidor: 1,
      videos_enviados: 3,
    },
  ],
  por_rota: [
    {
      metodo: "POST",
      rota: "/v1/jobs",
      chamadas: 10,
      erros_do_cliente: 2,
      erros_do_servidor: 1,
    },
  ],
};

const CUSTO = {
  desde: null,
  ate: null,
  programa: null,
  usuario: null,
  moeda: "BRL",
  faturamento_ate: "2026-11-04",
  total: {
    custo: 150,
    custo_dos_jobs: 100,
    custo_sem_dono: 50,
    videos: 2,
    horas_de_video: 4,
    custo_por_hora: 25,
  },
  por_mes: [
    {
      mes: "2026-11",
      custo: 150,
      custo_dos_jobs: 100,
      custo_sem_dono: 50,
      videos: 2,
      horas_de_video: 4,
      custo_por_hora: 25,
    },
  ],
  por_quem: [
    {
      quem_tipo: "usuario",
      quem_id: "u1",
      email: "ana@redetv.com.br",
      custo: 100,
      videos: 2,
      horas_de_video: 4,
      custo_por_hora: 25,
    },
  ],
  por_etapa: [{ etapa: "analise", custo: 100 }],
  sem_dono_por_servico: [{ servico: "Cloud Run", custo: 50 }],
};

const FILA = {
  esperando_gpu: { quantidade: 3, idade_do_mais_antigo_s: 90 },
  por_estado: [
    { estado: "aguardando_upload", quantidade: 0, idade_do_mais_antigo_s: 0 },
    { estado: "validando", quantidade: 1, idade_do_mais_antigo_s: 30 },
    { estado: "analisando", quantidade: 2, idade_do_mais_antigo_s: 120 },
  ],
};

const pedidos: URLSearchParams[] = [];
let permissoes = ["decupagem.ver", "painel.ver"];
let resposta: () => Response = () => HttpResponse.json(RELATORIO);

/** Um relatório do painel: guarda os parâmetros e responde o CSV quando pedido. */
const relatorio = (aba: string, corpo: () => Response) =>
  http.get(`/v1/painel/${aba}`, ({ request }) => {
    const p = new URL(request.url).searchParams;
    pedidos.push(p);
    if (p.get("formato") === "csv")
      return new HttpResponse("coluna\n", {
        headers: { "Content-Type": "text/csv" },
      });
    return corpo();
  });

const servidor = setupServer(
  http.get("/v1/eu", () =>
    HttpResponse.json({ uid: "u1", email: "ana@redetv.com.br", permissoes }),
  ),
  http.get("/v1/painel/filtros", () =>
    HttpResponse.json({
      programas: ["TV Fama"],
      usuarios: [{ uid: "u1", email: "ana@redetv.com.br" }],
      sistemas: ["ingestao"],
    }),
  ),
  http.get("/v1/painel/fila", () => HttpResponse.json(FILA)),
  http.get("/v1/correcoes/catalogo", () => HttpResponse.json(catalogo)),
  relatorio("acessos", () => resposta()),
  relatorio("videos", () => HttpResponse.json(VIDEOS)),
  relatorio("buscas", () => HttpResponse.json(BUSCAS)),
  relatorio("revisao", () => HttpResponse.json(REVISAO)),
  relatorio("api", () => HttpResponse.json(API)),
  relatorio("custo", () => HttpResponse.json(CUSTO)),
);

beforeAll(() => servidor.listen({ onUnhandledFrame: "error" }));
// A tela é carregada sob demanda; sob carga, a primeira importação passava de 1 s e o primeiro teste falhava.
beforeAll(() => import("./PainelDaDiretoria.tsx"));
afterEach(() => {
  cleanup();
  history.replaceState(null, "", "/");
  servidor.resetHandlers();
  pedidos.length = 0;
  permissoes = ["decupagem.ver", "painel.ver"];
  resposta = () => HttpResponse.json(RELATORIO);
});
afterAll(() => servidor.close());

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([
    {
      email: "ana@redetv.com.br",
      senha: "senha-forte-1",
      totpCadastrado: true,
    },
  ]);
  await auth.entrar("ana@redetv.com.br", "senha-forte-1");
  await auth.confirmarTotp(CODIGO_TOTP_FALSO);
  history.replaceState(null, "", endereco);
  render(<App autenticador={auth} />);
}

/** A tabela da seção `nome`, trocando do gráfico para a tabela quando a seção tem os dois. */
async function tabela(nome: string) {
  const regiao = await screen.findByRole("region", { name: nome });
  const botao = within(regiao).queryByRole("button", { name: "Tabela" });
  if (botao) fireEvent.click(botao);
  return within(regiao).getByRole("table", { name: nome });
}

const linhasDe = (t: HTMLElement) =>
  within(t)
    .getAllByRole("row")
    .slice(1)
    .map((l) =>
      within(l)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    );

function simularDownload() {
  const criar = vi.fn(() => "blob:csv");
  Object.assign(URL, { createObjectURL: criar, revokeObjectURL: vi.fn() });
  const clique = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  return { criar, clique };
}

test("a aba Acessos mostra o total, os dias e os usuários", async () => {
  await abrir("/painel/acessos");

  expect(
    await screen.findByRole("img", {
      name: /Logins por dia: 02\/11, 3; 03\/11, 4/,
    }),
  ).toBeTruthy();
  expect(linhasDe(await tabela("Acessos por dia"))).toEqual([
    ["02/11/2026", "3", "2"],
    ["03/11/2026", "4", "1"],
  ]);
  const linhas = linhasDe(await tabela("Acessos por usuário"));
  expect(linhas[0].slice(0, 3)).toEqual(["ana@redetv.com.br", "5", "2"]);
  // Sem e-mail, aparece o uid.
  expect(linhas[1][0]).toBe("u2");
  expect(screen.getByText("Logins no período").nextSibling?.textContent).toBe(
    "7",
  );
  expect(linhasDe(await tabela("Usuários ativos por semana"))).toEqual([
    ["02/11/2026", "2"],
  ]);
  expect(linhasDe(await tabela("Usuários ativos por mês"))).toEqual([
    ["11/2026", "2"],
  ]);
});

test("a nota do painel diz que os números se atualizam a cada hora", async () => {
  expect(NOTA_DO_DIA).toContain("a cada hora");
  expect(NOTA_DO_DIA).not.toContain("10 minutos");
  await abrir("/painel/acessos");
  expect(await screen.findByText(/os números se atualizam a cada hora/)).toBeTruthy();
});

test("os filtros vão à API e ao endereço, e o programa nunca vai em acessos", async () => {
  await abrir(
    "/painel/acessos?programa=TV+Fama&usuario=u1&de=2026-10-01&ate=2026-10-31",
  );

  await tabela("Acessos por dia");

  expect(pedidos[0].get("usuario")).toBe("u1");
  expect(pedidos[0].get("desde")).toBe("2026-10-01");
  expect(pedidos[0].get("ate")).toBe("2026-10-31");
  expect(pedidos[0].has("programa")).toBe(false);
  // O programa da URL fica para as outras abas; aqui o seletor, desligado, diz "todos".
  const programa = screen.getByRole("combobox", {
    name: "Programa",
  }) as HTMLSelectElement;
  expect(programa.disabled).toBe(true);
  expect(programa.selectedOptions[0].textContent).toBe("Todos os programas");

  fireEvent.change(screen.getByLabelText("Até"), {
    target: { value: "2026-10-15" },
  });

  await waitFor(() => expect(pedidos.at(-1)?.get("ate")).toBe("2026-10-15"));
  expect(location.search).toContain("ate=2026-10-15");
});

test("o seletor de usuário mostra o e-mail e manda o uid ao endereço", async () => {
  await abrir("/painel/videos");
  const usuario = (await screen.findByRole("combobox", {
    name: "Usuário",
  })) as HTMLSelectElement;
  await waitFor(() =>
    expect(
      within(usuario).getByRole("option", { name: "ana@redetv.com.br" }),
    ).toBeTruthy(),
  );

  fireEvent.change(usuario, { target: { value: "u1" } });

  await waitFor(() => expect(pedidos.at(-1)?.get("usuario")).toBe("u1"));
  expect(location.search).toContain("usuario=u1");
});

test("na aba API o filtro de usuário lista os sistemas e filtra por eles", async () => {
  await abrir("/painel/videos");
  const naVideos = (await screen.findByRole("combobox", {
    name: "Usuário",
  })) as HTMLSelectElement;
  await waitFor(() =>
    expect(
      within(naVideos).getByRole("option", { name: "ana@redetv.com.br" }),
    ).toBeTruthy(),
  );
  expect(within(naVideos).queryByText("Sistema: ingestao")).toBeNull();
  cleanup();

  await abrir("/painel/api");
  const usuario = (await screen.findByRole("combobox", {
    name: "Usuário",
  })) as HTMLSelectElement;
  const opcao = await within(usuario).findByRole("option", {
    name: "Sistema: ingestao",
  });

  fireEvent.change(usuario, {
    target: { value: (opcao as HTMLOptionElement).value },
  });

  await waitFor(() => expect(pedidos.at(-1)?.get("usuario")).toBe("ingestao"));
});

test("período invertido mostra o aviso e não chama a API", async () => {
  await abrir("/painel/acessos?de=2026-11-10&ate=2026-11-01");

  expect(
    await screen.findByText(/O período começa depois de terminar/),
  ).toBeTruthy();
  expect(pedidos).toHaveLength(0);
  expect(
    (screen.getByRole("button", { name: "Baixar CSV" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

test("Baixar CSV pede o formato csv com os mesmos filtros", async () => {
  const usuario = userEvent.setup();
  const { criar, clique } = simularDownload();
  await abrir("/painel/acessos?usuario=u1");
  await tabela("Acessos por dia");

  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));

  await waitFor(() => expect(clique).toHaveBeenCalled());
  const csv = pedidos.find((p) => p.get("formato") === "csv");
  expect(csv?.get("usuario")).toBe("u1");
  expect(csv?.has("programa")).toBe(false);
  // O CSV nunca é agrupado: traz os dias.
  expect(csv?.has("agrupar")).toBe(false);
  expect(criar).toHaveBeenCalled();
  clique.mockRestore();
});

test("quem só tem painel.ver entra pelo painel, não pelo acervo", async () => {
  permissoes = ["painel.ver"];
  await abrir("/");

  await tabela("Acessos por dia");
  expect(location.pathname).toBe("/painel");
});

test("sem painel.ver, o painel não abre nem chama a API", async () => {
  permissoes = ["decupagem.ver"];
  await abrir("/painel/acessos");

  expect(await screen.findByText("Página não encontrada.")).toBeTruthy();
  expect(pedidos).toHaveLength(0);
});

test("sem acesso nenhum, a tela diz isso", async () => {
  resposta = () =>
    HttpResponse.json({ ...RELATORIO, por_dia: [], por_usuario: [] });
  await abrir("/painel/acessos");

  expect(await screen.findByText("Nenhum acesso neste filtro.")).toBeTruthy();
  expect(
    (screen.getByRole("button", { name: "Baixar CSV" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

test("o gráfico pede o agrupamento automático e segue o que o servidor escolheu", async () => {
  resposta = () =>
    HttpResponse.json(
      {
        ...RELATORIO,
        por_dia: [{ dia: "2026-10-26", acessos: 7, usuarios_ativos: 2 }],
      },
      { headers: { "X-Agrupamento": "semana" } },
    );
  await abrir("/painel/acessos");

  expect(
    await screen.findByRole("img", { name: "Logins por semana: 26/10, 7" }),
  ).toBeTruthy();
  const semanas = await tabela("Acessos por semana");
  expect(within(semanas).getAllByRole("columnheader")[0].textContent).toBe(
    "Semana de",
  );
  expect(linhasDe(semanas)).toEqual([["26/10/2026", "7", "2"]]);
  expect(pedidos[0].get("agrupar")).toBe("auto");

  fireEvent.change(screen.getByRole("combobox", { name: "Agrupar" }), {
    target: { value: "mes" },
  });

  await waitFor(() => expect(pedidos.at(-1)?.get("agrupar")).toBe("mes"));
});

test("o agrupamento escolhido vai para o endereço e o endereço o devolve ao abrir", async () => {
  await abrir("/painel/acessos");
  await screen.findByRole("img", { name: /Logins por/ });

  fireEvent.change(screen.getByRole("combobox", { name: "Agrupar" }), {
    target: { value: "semana" },
  });

  await waitFor(() => expect(location.search).toContain("agrupar=semana"));
});

test("abrir o link com agrupar usa o agrupamento do link", async () => {
  await abrir("/painel/acessos?agrupar=trimestre");

  await waitFor(() => expect(pedidos[0].get("agrupar")).toBe("trimestre"));
  expect(
    (screen.getByRole("combobox", { name: "Agrupar" }) as HTMLSelectElement)
      .value,
  ).toBe("trimestre");
});

test("o agrupamento recusado pela API aparece com o motivo e deixa tentar de novo", async () => {
  let vezes = 0;
  resposta = () => {
    vezes += 1;
    return vezes === 1
      ? HttpResponse.json(
          { detail: "Período longo demais para agrupar por dia." },
          { status: 422 },
        )
      : HttpResponse.json(RELATORIO);
  };
  await abrir("/painel/acessos");

  const alerta = await screen.findByRole("alert");
  expect(alerta.textContent).toContain(
    "Período longo demais para agrupar por dia.",
  );
  expect(alerta.textContent).toContain("http_422");

  fireEvent.click(
    within(alerta).getByRole("button", { name: "Tentar de novo" }),
  );

  await tabela("Acessos por dia");
  expect(vezes).toBe(2);
});

test("a aba Vídeos mostra os totais e as tabelas por dia, programa e usuário", async () => {
  await abrir("/painel/videos");

  const dias = await tabela("Vídeos por dia");
  expect(linhasDe(dias)[0].slice(0, 5)).toEqual([
    "02/11/2026",
    "5",
    "3",
    "1",
    "3,5",
  ]);
  expect(screen.getAllByText("Enviados")[0].nextSibling?.textContent).toBe("5");
  expect(
    screen.getByText("Horas de vídeo concluídas").nextSibling?.textContent,
  ).toBe("3,5");
  const tabelaDeProgramas = await tabela("Vídeos por programa");
  const programas = linhasDe(tabelaDeProgramas);
  expect(programas[0][0]).toBe("TV Fama");
  // Sem tempo médio, um traço.
  expect(programas[0][5]).toBe("—");
  expect(programas[1][0]).toBe("Sem programa");
  expect(screen.getAllByText("Falhas").length).toBeGreaterThan(0);
  expect(screen.queryByText("Com falha")).toBeNull();
  expect(
    screen.getByText(/um vídeo que falhou e depois concluiu aparece nas duas/),
  ).toBeTruthy();
  const tabelaDeUsuarios = await tabela("Vídeos por usuário");
  for (const t of [dias, tabelaDeProgramas, tabelaDeUsuarios]) {
    const colunas = within(t)
      .getAllByRole("columnheader")
      .map((c) => c.textContent);
    expect(colunas.slice(-1)).toEqual(["Tempo médio até concluir"]);
    expect(colunas).toContain("Falhas");
  }
  expect(screen.queryByText("Tempo médio de processamento")).toBeNull();
  expect(
    screen.getByText(/com a espera na fila e as novas tentativas/),
  ).toBeTruthy();
  const quem = linhasDe(tabelaDeUsuarios);
  expect(quem.map((l) => l[0])).toEqual([
    "ana@redetv.com.br",
    "ingestao (sistema)",
  ]);
});

test("a aba Vídeos mostra a fila agora, que não depende dos filtros", async () => {
  await abrir("/painel/videos?programa=TV+Fama&usuario=u1");

  const fila = await screen.findByRole("list", { name: "Fila agora" });
  const estados = within(fila)
    .getAllByRole("listitem")
    .map((i) => i.textContent);
  expect(estados).toEqual([
    "Aguardando envio0Nenhum agora",
    "Em quarentena1O mais antigo há 30s",
    "Decupando2O mais antigo há 2min00s",
    "Esperando GPU: 3O mais antigo há 1min30s",
  ]);
  // Com os filtros recusados, a fila continua; o relatório não é pedido.
  expect(
    screen.getByText(/Escolha o programa ou o usuário, não os dois/),
  ).toBeTruthy();
  expect(pedidos).toHaveLength(0);
});

test("a fila continua visível quando a API não traz esperando_gpu", async () => {
  servidor.use(
    http.get("/v1/painel/fila", () =>
      HttpResponse.json({ por_estado: FILA.por_estado }),
    ),
  );
  await abrir("/painel/videos");

  const fila = await screen.findByRole("list", { name: "Fila agora" });
  expect(
    within(fila)
      .getAllByRole("listitem")
      .map((i) => i.textContent),
  ).toEqual([
    "Aguardando envio0Nenhum agora",
    "Em quarentena1O mais antigo há 30s",
    "Decupando2O mais antigo há 2min00s",
  ]);
  expect(within(fila).queryByText(/Esperando GPU/)).toBeNull();
});

test("Vídeos manda o programa à API e recusa programa e usuário juntos", async () => {
  await abrir("/painel/videos?programa=TV+Fama");
  await tabela("Vídeos por dia");
  expect(pedidos[0].get("programa")).toBe("TV Fama");

  cleanup();
  pedidos.length = 0;
  await abrir("/painel/videos?programa=TV+Fama&usuario=u1");
  expect(
    await screen.findByText(/Escolha o programa ou o usuário, não os dois/),
  ).toBeTruthy();
  expect(pedidos).toHaveLength(0);
});

test("a aba Buscas mostra os totais, o dia e o usuário", async () => {
  await abrir("/painel/buscas");

  expect(linhasDe(await tabela("Buscas por dia"))).toEqual([
    ["03/11/2026", "9", "2", "4"],
  ]);
  expect(
    screen.getByText("Buscas sem resultado").nextSibling?.textContent,
  ).toBe("4");
  expect(linhasDe(await tabela("Buscas por usuário"))).toEqual([
    ["ana@redetv.com.br", "9", "4"],
  ]);
});

test("Buscas com filtro de programa mostra traço onde a API não sabe quem buscou", async () => {
  servidor.use(
    http.get("/v1/painel/buscas", () =>
      HttpResponse.json({
        ...BUSCAS,
        programa: "TV Fama",
        total: { ...BUSCAS.total, usuarios_que_buscam: null },
        por_dia: [{ ...BUSCAS.por_dia[0], usuarios_que_buscam: null }],
        por_usuario: [],
      }),
    ),
  );
  await abrir("/painel/buscas?programa=TV+Fama");

  expect(linhasDe(await tabela("Buscas por dia"))).toEqual([
    ["03/11/2026", "9", "—", "4"],
  ]);
  expect(
    screen.queryByRole("region", { name: "Buscas por usuário" }),
  ).toBeNull();
});

test("Baixar CSV em Vídeos pede o formato csv", async () => {
  const usuario = userEvent.setup();
  const { clique } = simularDownload();
  await abrir("/painel/videos?usuario=u1");
  await tabela("Vídeos por dia");

  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));

  await waitFor(() => expect(clique).toHaveBeenCalled());
  expect(pedidos.find((p) => p.get("formato") === "csv")?.get("usuario")).toBe(
    "u1",
  );
  clique.mockRestore();
});

test("as abas do painel levam de uma para outra", async () => {
  const usuario = userEvent.setup();
  await abrir("/painel/acessos?usuario=u1");
  await tabela("Acessos por dia");

  await usuario.click(screen.getByRole("tab", { name: "Buscas" }));

  await tabela("Buscas por dia");
  expect(location.pathname).toBe("/painel/buscas");
  expect(location.search).toContain("usuario=u1");
  expect(
    screen.getByRole("tab", { name: "Buscas" }).getAttribute("aria-selected"),
  ).toBe("true");
});

test("voltar a uma aba já vista não refaz a chamada", async () => {
  const usuario = userEvent.setup();
  await abrir("/painel/acessos");
  await tabela("Acessos por dia");
  await usuario.click(screen.getByRole("tab", { name: "Buscas" }));
  await tabela("Buscas por dia");

  await usuario.click(screen.getByRole("tab", { name: "Acessos" }));

  await tabela("Acessos por dia");
  // Contam só os pedidos de JSON de cada aba; a fila e os filtros vão por outra rota.
  expect(pedidos).toHaveLength(2);
});

test("a aba Revisão mostra correções, taxa e minutos de revisão", async () => {
  await abrir("/painel/revisao");

  expect(linhasDe(await tabela("Correções por dia"))).toEqual([
    ["02/11/2026", "6"],
  ]);
  expect(linhasDe(await tabela("Correções por tipo"))).toEqual([
    ["texto", "4"],
    ["Sem tipo", "2"],
  ]);
  expect(linhasDe(await tabela("Correções por usuário"))).toEqual([
    ["ana@redetv.com.br", "6"],
  ]);
  expect(linhasDe(await tabela("Taxa de correção por tipo"))).toEqual([
    ["texto", "4", "32", "12,5%"],
  ]);
  expect(linhasDe(await tabela("Taxa de correção por programa"))).toEqual([
    ["Sem programa", "4", "32", "—"],
  ]);
  expect(linhasDe(await tabela("Revisão por pessoa"))).toEqual([
    ["ana@redetv.com.br", "30", "2", "1,5", "20"],
  ]);
  expect(linhasDe(await tabela("Revisão por programa"))).toEqual([
    ["TV Fama", "30", "2", "1,5", "—"],
  ]);
  expect(screen.getAllByText("Correções")[0].nextSibling?.textContent).toBe(
    "6",
  );
});

test("Revisão mostra o rótulo dos tipos conhecidos e mantém a chave dos desconhecidos", async () => {
  const tipos = [
    ["pessoa.renomear", "Renomear pessoa"],
    ["plano.descricao", "Descrição do plano"],
    ["objeto.acrescentar", "Objeto acrescentado"],
    ["texto_na_tela.texto", "Texto na tela"],
    ["texto_na_tela.acrescentar", "Texto na tela acrescentado"],
    ["aprovar", "Aprovação"],
    ["recusar", "Recusa"],
    ["tipo.desconhecido", "tipo.desconhecido"],
  ];
  permissoes = ["painel.ver"];
  servidor.use(
    http.get("/v1/painel/revisao", () =>
      HttpResponse.json({
        ...REVISAO,
        correcoes: {
          ...REVISAO.correcoes,
          total: tipos.length + 1,
          por_tipo: [
            ...tipos.map(([tipo]) => ({ tipo, correcoes: 1 })),
            { tipo: null, correcoes: 1 },
          ],
        },
        taxa_de_correcao: {
          ...REVISAO.taxa_de_correcao,
          por_tipo: tipos.map(([tipo]) => ({
            tipo,
            correcoes: 1,
            itens: 8,
            taxa: 0.125,
          })),
        },
      }),
    ),
  );
  await abrir("/painel/revisao");

  await waitFor(() => {
    const correcoes = screen.getByRole("img", { name: /^Correções por tipo/ });
    const taxa = screen.getByRole("img", {
      name: /^Taxa de correção por tipo/,
    });
    for (const [, rotulo] of tipos) {
      expect(correcoes.getAttribute("aria-label")).toContain(`${rotulo}, 1`);
      expect(taxa.getAttribute("aria-label")).toContain(`${rotulo}, 12,5%`);
    }
    expect(correcoes.getAttribute("aria-label")).toContain("Sem tipo, 1");
  });
  expect(linhasDe(await tabela("Correções por tipo"))).toEqual([
    ...tipos.map(([, rotulo]) => [rotulo, "1"]),
    ["Sem tipo", "1"],
  ]);
  expect(linhasDe(await tabela("Taxa de correção por tipo"))).toEqual(
    tipos.map(([, rotulo]) => [rotulo, "1", "8", "12,5%"]),
  );
});

test("Revisão aceita programa e usuário juntos e os manda à API", async () => {
  await abrir("/painel/revisao?programa=TV+Fama&usuario=u1");

  await tabela("Correções por dia");
  expect(pedidos[0].get("programa")).toBe("TV Fama");
  expect(pedidos[0].get("usuario")).toBe("u1");
});

test("Baixar CSV em Revisão pede o formato csv com programa e usuário", async () => {
  const usuario = userEvent.setup();
  const { clique } = simularDownload();
  await abrir("/painel/revisao?programa=TV+Fama&usuario=u1");
  await tabela("Correções por dia");

  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));

  await waitFor(() => expect(clique).toHaveBeenCalled());
  const csv = pedidos.find((p) => p.get("formato") === "csv");
  expect(csv?.get("programa")).toBe("TV Fama");
  expect(csv?.get("usuario")).toBe("u1");
  clique.mockRestore();
});

test("Revisão só com a taxa mostra a taxa", async () => {
  servidor.use(
    http.get("/v1/painel/revisao", () =>
      HttpResponse.json({
        ...REVISAO,
        correcoes: { total: 0, por_dia: [], por_tipo: [], por_usuario: [] },
        tempo_de_revisao: {
          ...REVISAO.tempo_de_revisao,
          por_pessoa: [],
          por_programa: [],
        },
      }),
    ),
  );
  await abrir("/painel/revisao");

  expect(linhasDe(await tabela("Taxa de correção por tipo"))).toEqual([
    ["texto", "4", "32", "12,5%"],
  ]);
  expect(
    (screen.getByRole("button", { name: "Baixar CSV" }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
});

test("Revisão sem nada no filtro diz que não há correção nem revisão", async () => {
  servidor.use(
    http.get("/v1/painel/revisao", () =>
      HttpResponse.json({
        ...REVISAO,
        correcoes: { total: 0, por_dia: [], por_tipo: [], por_usuario: [] },
        taxa_de_correcao: { por_tipo: [], por_programa: [] },
        tempo_de_revisao: {
          ...REVISAO.tempo_de_revisao,
          por_pessoa: [],
          por_programa: [],
        },
      }),
    ),
  );
  await abrir("/painel/revisao");

  expect(
    await screen.findByText("Nenhuma correção nem revisão neste filtro."),
  ).toBeTruthy();
});

test("a aba API mostra o total, o dia, o sistema e a rota, e nunca manda programa", async () => {
  await abrir("/painel/api?programa=TV+Fama&usuario=ingestao");

  expect(linhasDe(await tabela("API por dia"))).toEqual([
    ["03/11/2026", "10", "2", "1", "3"],
  ]);
  expect(linhasDe(await tabela("API por sistema"))).toEqual([
    ["ingestao (sistema)", "10", "2", "1", "3"],
  ]);
  expect(linhasDe(await tabela("API por rota"))).toEqual([
    ["POST /v1/jobs", "10", "2", "1"],
  ]);
  expect(
    screen.getByText("Vídeos enviados pela API").nextSibling?.textContent,
  ).toBe("3");
  expect(pedidos[0].has("programa")).toBe(false);
  expect(pedidos[0].get("usuario")).toBe("ingestao");
  expect(
    (screen.getByRole("combobox", { name: "Programa" }) as HTMLSelectElement)
      .disabled,
  ).toBe(true);
});

test("Baixar CSV na aba API pede o formato csv sem programa", async () => {
  const usuario = userEvent.setup();
  const { clique } = simularDownload();
  await abrir("/painel/api?programa=TV+Fama");
  await tabela("API por dia");

  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));

  await waitFor(() => expect(clique).toHaveBeenCalled());
  expect(pedidos.find((p) => p.get("formato") === "csv")?.has("programa")).toBe(
    false,
  );
  clique.mockRestore();
});

const REAL = (n: string) => `R$ ${n}`;

test("a aba Custo mostra o total, o mês, o usuário, a etapa e o custo sem dono, e manda o programa", async () => {
  await abrir("/painel/custo?programa=TV+Fama");

  expect(linhasDe(await tabela("Custo por mês"))).toEqual([
    [
      "11/2026",
      REAL("150,00"),
      REAL("100,00"),
      REAL("50,00"),
      "2",
      "4",
      REAL("25,00"),
    ],
  ]);
  expect(linhasDe(await tabela("Custo por usuário"))[0].slice(0, 2)).toEqual([
    "ana@redetv.com.br",
    REAL("100,00"),
  ]);
  expect(linhasDe(await tabela("Custo por etapa"))).toEqual([
    ["analise", REAL("100,00")],
  ]);
  expect(linhasDe(await tabela("Custo sem dono por serviço"))).toEqual([
    ["Cloud Run", REAL("50,00")],
  ]);
  expect(
    screen.getByText("Custo por hora de vídeo").nextSibling?.textContent,
  ).toBe(REAL("25,00"));
  expect(
    screen.getByText(
      /^Custo até 04\/11 — o faturamento do Google chega com 1 a 2 dias de atraso/,
    ),
  ).toBeTruthy();
  expect(pedidos[0].get("programa")).toBe("TV Fama");
  // O custo vem sempre por mês: o agrupamento não vale nesta aba.
  expect(pedidos[0].has("agrupar")).toBe(false);
  expect(
    (screen.getByRole("combobox", { name: "Agrupar" }) as HTMLSelectElement)
      .disabled,
  ).toBe(true);
});

test("a aba Custo escreve R$ 0,00, sem sinal, para um líquido de fração de centavo negativa", async () => {
  const TINHA = -0.0003;
  servidor.use(
    relatorio("custo", () =>
      HttpResponse.json({
        ...CUSTO,
        total: {
          ...CUSTO.total,
          custo: TINHA,
          custo_dos_jobs: TINHA,
          custo_sem_dono: TINHA,
          custo_por_hora: TINHA,
        },
        por_mes: [
          {
            ...CUSTO.por_mes[0],
            custo: TINHA,
            custo_dos_jobs: TINHA,
            custo_sem_dono: TINHA,
            custo_por_hora: TINHA,
          },
        ],
      }),
    ),
  );
  await abrir("/painel/custo");

  expect(
    linhasDe(await tabela("Custo por mês"))[0].filter((c) =>
      c.startsWith("R$"),
    ),
  ).toEqual([REAL("0,00"), REAL("0,00"), REAL("0,00"), REAL("0,00")]);
  for (const rotulo of [
    "Custo dos vídeos",
    "Custo sem dono",
    "Custo por hora de vídeo",
  ]) {
    const indicador = screen
      .getAllByText(rotulo)
      .find((e) => e.tagName === "P");
    expect(indicador?.nextSibling?.textContent).toBe(REAL("0,00"));
  }
  expect(document.body.textContent).not.toMatch(/-\s*R\$|-0/);
});

test("Baixar CSV na aba Custo pede o formato csv", async () => {
  const usuario = userEvent.setup();
  const { clique } = simularDownload();
  await abrir("/painel/custo");
  await tabela("Custo por mês");

  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));

  await waitFor(() => expect(clique).toHaveBeenCalled());
  expect(pedidos.some((p) => p.get("formato") === "csv")).toBe(true);
  clique.mockRestore();
});

test("a falha no CSV avisa sem derrubar o relatório", async () => {
  const usuario = userEvent.setup();
  servidor.use(
    http.get("/v1/painel/buscas", ({ request }) =>
      new URL(request.url).searchParams.get("formato") === "csv"
        ? new HttpResponse(null, { status: 500 })
        : HttpResponse.json(BUSCAS),
    ),
  );
  await abrir("/painel/buscas");
  await tabela("Buscas por dia");

  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));

  expect((await screen.findByRole("alert")).textContent).toContain(
    "Não foi possível baixar o CSV agora.",
  );
  expect(screen.getByRole("table", { name: "Buscas por dia" })).toBeTruthy();
});

test("as abas andam pelo teclado: setas, Home e End abrem a aba, e o Tab sai do grupo", async () => {
  const usuario = userEvent.setup();
  await abrir("/painel/acessos");
  const aba = (nome: string) => screen.getByRole("tab", { name: nome });
  await screen.findByRole("tab", { name: "Acessos" });
  // Só a aba ativa entra na ordem do Tab.
  expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([
    0, -1, -1, -1, -1, -1,
  ]);

  aba("Acessos").focus();
  await usuario.keyboard("{ArrowRight}");
  expect(document.activeElement).toBe(aba("Vídeos"));
  expect(location.pathname).toBe("/painel/videos");
  await waitFor(() =>
    expect(aba("Vídeos").getAttribute("aria-selected")).toBe("true"),
  );
  expect(aba("Vídeos").tabIndex).toBe(0);

  await usuario.keyboard("{End}");
  expect(document.activeElement).toBe(aba("Custo"));
  expect(location.pathname).toBe("/painel/custo");
  await usuario.keyboard("{ArrowRight}");
  expect(document.activeElement).toBe(aba("Acessos"));
  await usuario.keyboard("{ArrowLeft}");
  expect(document.activeElement).toBe(aba("Custo"));
  await usuario.keyboard("{Home}");
  expect(document.activeElement).toBe(aba("Acessos"));
  await waitFor(() => expect(aba("Acessos").tabIndex).toBe(0));

  // Um Tab sai das abas.
  await usuario.tab();
  expect(document.activeElement?.closest('[role="tablist"]')).toBeNull();
});

test("a falha do CSV numa aba não aparece na outra, nem quando o pedido termina depois da troca", async () => {
  const usuario = userEvent.setup();
  let falhar: (() => void) | null = null;
  const falharQuandoChegar = async () => {
    await waitFor(() => expect(falhar).not.toBeNull());
    falhar?.();
    falhar = null;
  };
  servidor.use(
    http.get("/v1/painel/buscas", ({ request }) =>
      new URL(request.url).searchParams.get("formato") === "csv"
        ? new Promise<Response>(
            (r) => (falhar = () => r(new HttpResponse(null, { status: 500 }))),
          )
        : HttpResponse.json(BUSCAS),
    ),
  );
  await abrir("/painel/buscas");
  await tabela("Buscas por dia");

  // O pedido fica no ar; troca de aba e só então ele falha.
  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));
  await usuario.click(screen.getByRole("tab", { name: "Custo" }));
  await screen.findByRole("region", { name: "Custo por mês" });
  await falharQuandoChegar();
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.queryByRole("alert")).toBeNull();

  // A falha na própria aba aparece e some ao trocar.
  await usuario.click(screen.getByRole("tab", { name: "Buscas" }));
  await tabela("Buscas por dia");
  await usuario.click(screen.getByRole("button", { name: "Baixar CSV" }));
  await falharQuandoChegar();
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Não foi possível baixar o CSV agora.",
  );
  await usuario.click(screen.getByRole("tab", { name: "Custo" }));
  await screen.findByRole("region", { name: "Custo por mês" });
  expect(screen.queryByRole("alert")).toBeNull();
});

test("ao abrir sem filtro, o período é os últimos 7 dias, na tela e no pedido; o histórico inteiro continua à escolha", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-07T15:00:00Z"));
  try {
    await abrir("/painel/acessos");

    expect(
      ((await screen.findByLabelText("De")) as HTMLInputElement).value,
    ).toBe("2026-11-01");
    expect((screen.getByLabelText("Até") as HTMLInputElement).value).toBe(
      "2026-11-07",
    );
    await waitFor(() => expect(pedidos.length).toBeGreaterThan(0));
    expect(pedidos[0].get("desde")).toBe("2026-11-01");
    expect(pedidos[0].get("ate")).toBe("2026-11-07");

    cleanup();
    pedidos.length = 0;
    await abrir("/painel/acessos?de=&ate=");

    expect(
      ((await screen.findByLabelText("De")) as HTMLInputElement).value,
    ).toBe("");
    await waitFor(() => expect(pedidos.length).toBeGreaterThan(0));
    expect(pedidos[0].get("desde")).toBe("");
    expect(pedidos[0].get("ate")).toBe("");
  } finally {
    vi.useRealTimers();
  }
});
