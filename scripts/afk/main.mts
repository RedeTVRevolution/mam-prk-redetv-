// Loop AFK com o Sandcastle (#22): até K tickets ao mesmo tempo, cada iteração numa vaga nova (um
// contêiner num worktree do branch do ticket). O integrador, outro sandbox, junta ao branch do PR os
// tickets feitos, um por vez. Roda no Mac, chamado pelo rodar.sh:
// node scripts/afk/main.mts <clone> <branch do PR> <máximo de iterações>
import { appendFileSync, closeSync, constants, fstatSync, lstatSync, mkdirSync, openSync, readdirSync, readFileSync, readSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import * as sc from "@ai-hero/sandcastle";

type Caixa = Parameters<typeof sc.createSandbox>[0]["sandbox"];
type Vaga = sc.Sandbox;

export type Config = {
  clone: string; // fica em main; os worktrees moram em .sandcastle/ dentro dele
  branch: string; // afk/<data-hora>, o do PR
  maxIteracoes: number;
  vagas: number; // tickets ao mesmo tempo
  caixa: (papel: "vaga" | "integrador") => Caixa;
  claude: string; // o comando, dentro da caixa
  instalar: string; // roda em cada sandbox novo
  verificar: string;
  modelo?: string;
  modeloRevisor: string;
  pluginDir?: string;
  aviso: number;
  corte: number;
  maxTurnos: number;
  maxFalhas: number;
  maxParciais: number;
  ocioso: number; // segundos sem saída do agente; uma tool call longa conta como silêncio
  pausaGh?: number; // ms antes da 2ª tentativa do gh, que dobra a cada nova; 30 s se faltar
};

const aqui = dirname(fileURLToPath(import.meta.url));
const q = (s: string) => `'${s.replaceAll("'", `'\\''`)}'`;
const ultimo = (texto: string, re: RegExp) => [...texto.matchAll(re)].at(-1)?.[1] ?? "";
const leitor = sc.claudeCode("qualquer"); // só o parseStreamLine
const real = (p: string) => { try { return realpathSync(p); } catch { return ""; } };
// A saída de um git que roda onde o agente alcança (um ~/.gitconfig com trace2 no stdout, por exemplo)
// só segue para outro comando se for um SHA.
const sha = (s: string) => {
  if (!/^[0-9a-f]{40}([0-9a-f]{24})?$/.test(s)) throw new Error(`não é um SHA: ${s.slice(0, 200)}`);
  return s;
};
// Um erro que para o loop, e não só a iteração.
class Parada extends Error {}
// O Mac lê arquivos de .git/worktrees/, que o agente alcança: só arquivo regular, sem symlink, até 4 KB
// (um FIFO travaria o loop, um symlink para /dev/zero o encheria). Sem o arquivo, "".
export const leCurto = (p: string) => {
  let fd: number;
  try {
    fd = openSync(p, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return "";
    throw new Parada(`${p}: ${(e as NodeJS.ErrnoException).code}`);
  }
  try {
    const st = fstatSync(fd);
    if (!st.isFile() || st.size > 4096) throw new Parada(`${p} não é um arquivo regular pequeno`);
    const b = Buffer.alloc(4096);
    return b.subarray(0, readSync(fd, b)).toString("utf8");
  } finally {
    closeSync(fd);
  }
};
const pastaDeVerdade = (p: string) => lstatSync(p, { throwIfNoEntry: false })?.isDirectory() === true;

// Mutex: cada chamada espera a anterior terminar.
const emSerie = () => {
  let fila: Promise<unknown> = Promise.resolve();
  return function <T>(f: () => Promise<T>): Promise<T> {
    const p = fila.then(f);
    fila = p.catch(() => {});
    return p;
  };
};

const CONSULTA = `query($owner: String!, $name: String!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $endCursor) {
      nodes { number state body labels(first: 20) { nodes { name } } blockedBy(first: 50) { nodes { number } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}`;

// A spec de um ticket: a primeira referência (#N ou `....md`) do primeiro parágrafo de "## Parte de".
export const specDe = (corpo: string) => {
  const secao = /^##\s*Parte de\s*\n+([^\n]+)/im.exec(corpo)?.[1] ?? "";
  return /#\d+|`[^`]+\.md`/.exec(secao)?.[0] ?? "";
};

export async function loop(c: Config): Promise<number> {
  const afk = join(c.clone, ".afk");
  const logs = join(afk, "logs", new Date().toLocaleString("sv").replace(" ", "-").replace(/[^\d-]/g, ""));
  const progresso = join(afk, "progresso.md");
  mkdirSync(logs, { recursive: true });
  writeFileSync(join(afk, "feitos"), "");
  appendFileSync(progresso, `\n## Execução em ${c.branch}\n\n`);

  const anota = (s: string) => {
    const linha = `- ${new Date().toLocaleString("sv")} · ${s}\n`;
    process.stdout.write(linha);
    appendFileSync(progresso, linha);
  };
  // Fora do clone: o .git dele é do agente, que poderia trocar o remote. O repositório vem do GH_REPO.
  // Uma falha de rede não encerra uma rodada de horas: 5 tentativas, com 30 s, 1, 2 e 4 min entre elas.
  // Com prazo, e sem travar o processo: as outras vagas seguem enquanto o gh roda. Um comentário vai uma
  // vez só: o GitHub pode tê-lo publicado mesmo quando a resposta não chega. Falta de permissão do token
  // não passa com o tempo e também vai uma vez só; o 403 de limite de requisições passa, e segue repetindo.
  const gh = async (...args: string[]) => {
    const tentativas = args[1] === "comment" ? 1 : 5;
    for (let n = 0; ; n++) {
      try {
        return (await promisify(execFile)("gh", args, { cwd: aqui, encoding: "utf8", timeout: 120_000, maxBuffer: 64 << 20 })).stdout;
      } catch (e) {
        const erro = `gh ${args.slice(0, 2).join(" ")}: ${String((e as any)?.stderr || (e as Error)?.message || e).trim().slice(-300)}`;
        const semPermissao = /Resource not accessible|HTTP 403/i.test(erro) && !/rate limit|abuse/i.test(erro);
        if (n >= tentativas - 1 || semPermissao) throw new Error(erro);
        anota(`${erro}; nova tentativa`);
        await new Promise((r) => setTimeout(r, (c.pausaGh ?? 30_000) * 2 ** n));
      }
    }
  };

  // Sem os emuladores, o pytest pula os testes de nuvem em silêncio e o portão passa sem eles.
  if (!process.env.FIRESTORE_EMULATOR_HOST || !process.env.STORAGE_EMULATOR_HOST) {
    console.error("FIRESTORE_EMULATOR_HOST e STORAGE_EMULATOR_HOST são obrigatórias; o rodar.sh sobe os emuladores.");
    return 2;
  }

  // Os PRs mesclados resolvem um "Bloqueado por: #N" (#87): a consulta das issues não traz PRs, e as
  // dependências nativas do GitHub só aceitam issues. PR aberto ou fechado sem merge segue bloqueando.
  // A leitura pede "Pull requests: leitura" no token; sem ela, falha uma vez na rodada, fica anotado e
  // quem espera um PR segue esperando, como antes.
  let semPRs = false;
  const prsMesclados = async (): Promise<number[]> => {
    if (semPRs) return [];
    try {
      return (JSON.parse(await gh("pr", "list", "--state", "merged", "--limit", "10000", "--json", "number")) as { number: number }[]).map((p) => p.number);
    } catch (e) {
      semPRs = true;
      anota(`não li os PRs mesclados (${String((e as Error)?.message ?? e)}); nesta rodada, quem espera um PR segue esperando`);
      return [];
    }
  };

  // Todas as issues, com os bloqueios nativos somados aos da linha "Bloqueado por: #N".
  const issues = async () =>
    (JSON.parse(await gh("api", "graphql", "--paginate", "--slurp", "-F", "owner={owner}", "-F", "name={repo}", "-f", `query=${CONSULTA}`)) as any[])
      .flatMap((p) => p.data.repository.issues.nodes)
      .map((i: any) => ({
        number: i.number as number,
        state: i.state as string,
        labels: i.labels.nodes.map((l: any) => l.name) as string[],
        spec: specDe(i.body ?? ""),
        bloqueios: [...new Set<number>([
          ...i.blockedBy.nodes.map((b: any) => b.number),
          ...(i.body ?? "").split(/\r?\n/)
            .filter((l: string) => /^\s*(bloqueado por|blocked by)\s*:/i.test(l))
            .flatMap((l: string) => [...l.matchAll(/#(\d+)/g)].map((m) => Number(m[1]))),
        ])].sort((a, b) => a - b),
      }));

  // conferido: o último SHA do ticket que passou no portão; começa na base.
  type Ticket = {
    ticket: string; spec: string; ramo: string; base: string; conferido: string;
    parciais: number; falhas: number; mesclar: string; mesclagens: number; iteracoes: number;
  };
  const emAndamento = new Map<string, Ticket>();
  // Os tickets feitos ou devolvidos nesta rodada: não voltam à fila nem se o gh falhar ao trocar a label.
  const saidos = new Set<string>();
  // Os feitos nesta rodada liberam quem eles bloqueiam, com ou sem a label afk-feito.
  const feitos = new Set<number>();

  // A fila, por número: os ready-for-agent abertos e ainda não feitos, cada um com o que o segura: os
  // bloqueadores que não estão fechados nem afk-feito ("#3	espera #2"), estar numa vaga ou ser da mesma
  // spec de um ticket numa vaga. O primeiro livre é o próximo. Grava em .afk/fila, para quem acompanha.
  const proximoTicket = async () => {
    const todas = await issues();
    const resolvido = new Set(todas.filter((i) => i.state === "CLOSED" || i.labels.includes("afk-feito") || feitos.has(i.number)).map((i) => i.number));
    const specs = new Set([...emAndamento.values()].map((t) => t.spec).filter(Boolean));
    const candidatos = todas
      .filter((i) => i.state === "OPEN" && i.labels.includes("ready-for-agent") && !i.labels.includes("afk-feito"))
      .filter((i) => !saidos.has(String(i.number)));
    // Um bloqueador que não é issue é PR (ou não existe): só então os PRs mesclados são lidos.
    const issuesDaFila = new Set(todas.map((i) => i.number));
    if (candidatos.some((i) => i.bloqueios.some((b) => !issuesDaFila.has(b)))) {
      for (const n of await prsMesclados()) resolvido.add(n);
    }
    const fila = candidatos
      .sort((a, b) => a.number - b.number)
      .map((i) => {
        const espera = i.bloqueios.filter((b) => !resolvido.has(b));
        const motivo = emAndamento.has(String(i.number)) ? "em andamento"
          : espera.length ? `espera ${espera.map((b) => `#${b}`).join(" ")}`
          : specs.has(i.spec) ? `espera a spec ${i.spec}` : "";
        return { i, linha: `#${i.number}` + (motivo ? `\t${motivo}` : "") };
      });
    writeFileSync(join(afk, "fila"), fila.map((f) => `${f.linha}\n`).join(""));
    const livre = fila.find((f) => !f.linha.includes("\t"))?.i;
    return livre && { ticket: String(livre.number), spec: livre.spec };
  };

  const git = async (sb: Vaga, comando: string) => {
    const r = await sb.exec(comando);
    if (r.exitCode !== 0) throw new Error(`${comando}: ${r.stderr.trim()}`);
    return r.stdout.trim();
  };
  const head = async (sb: Vaga) => sha(await git(sb, "git rev-parse HEAD"));
  // Um make verificar vermelho roda de novo uma vez antes de contar: com as vagas dividindo o Mac, os
  // testes da web falham sob carga, cada vez um diferente (rodada de 2026-11-04: 14 de 62, todos no
  // vitest). Vermelho duas vezes é vermelho; o prazo estourado (124) não repete, que seria mais uma hora.
  // Só repete com um teste falhando (FAIL do vitest, FAILED ou ERROR do pytest, os "Unhandled Errors"
  // do vitest): lint, mypy, typecheck e build não mudam de uma vez para outra, e o vermelho deles desfaz direto.
  // Devolve o log da última tentativa. A nota leva o que falhou na primeira: os logs ficam no clone,
  // que a próxima rodada apaga, e só o progresso.md chega à pasta principal.
  const verifica = async (sb: Vaga, arquivo: string, ticket: string) => {
    const r = await sb.exec(c.verificar);
    writeFileSync(arquivo, r.stdout + r.stderr);
    if (r.exitCode === 0 || r.exitCode === 124) return { verde: r.exitCode === 0, log: arquivo };
    const falhas = new Set((r.stdout + r.stderr).replace(/\x1b\[[0-9;]*m/g, "").match(/^ *(FAIL|FAILED|ERROR) .*$|^.*Unhandled Errors?\b.*$/gm)?.map((l) => l.trim().slice(0, 200)));
    if (!falhas.size) return { verde: false, log: arquivo };
    const repetido = `${arquivo}-repetido`;
    const r2 = await sb.exec(c.verificar);
    writeFileSync(repetido, r2.stdout + r2.stderr);
    if (r2.exitCode !== 0) return { verde: false, log: repetido };
    anota(`#${ticket}: make verificar falhou e passou ao repetir (${arquivo}): ${[...falhas].slice(0, 5).join("; ")}`);
    return { verde: true, log: arquivo };
  };
  // Só o que foi commitado segue adiante.
  const descarta = (sb: Vaga) => git(sb, "git reset -q --hard && git clean -fdq");

  // O worktree é do agente, e o contêiner vivo pode trocar um arquivo por um symlink a qualquer hora:
  // o Mac não lê nem grava nele. Quem lê e grava é o shell do contêiner, que só alcança o que o agente
  // já alcança. Sem stdin (#845 do Sandcastle): o texto vai em base64 no comando, em pedaços de 48000
  // bytes (múltiplo de 3, cada um decodifica sozinho), abaixo dos 128 KB por argumento do Linux.
  const gravaNaVaga = async (vaga: Vaga, nome: string, texto: string) => {
    const f = q(`.afk/${nome}`);
    await git(vaga, `mkdir -p .afk && rm -rf ${f} && : > ${f}`);
    const bytes = Buffer.from(texto);
    for (let i = 0; i < bytes.length; i += 48000) {
      await git(vaga, `printf %s ${bytes.subarray(i, i + 48000).toString("base64")} | base64 -d >> ${f}`);
    }
  };
  // A leitura volta em base64: o stdout chega em pedaços, e um caractere partido entre dois viraria lixo.
  // Só arquivo regular (nem FIFO, que travaria, nem symlink para /dev/zero), até 2 MB, com prazo.
  const leDaVaga = async (vaga: Vaga, nome: string) => {
    const f = q(`.afk/${nome}`);
    const r = await vaga.exec(`[ -f ${f} ] && [ ! -L ${f} ] && $(command -v timeout > /dev/null && echo timeout 30) head -c 2000000 ${f} | base64`);
    return Buffer.from(r.stdout, "base64").toString("utf8");
  };

  // Roda um claude -p novo na vaga e o corta se o contexto passar do corte; o jsonl cru fica no log.
  // O aviso vai para o hook de contexto; sem ele, o hook não faz nada. As notas do .afk/progresso.md, que
  // o git ignora, vão para o worktree antes e voltam depois; volta só o que o agente acrescentou.
  const roda = async (vaga: Vaga, log: string, prompt: string, modelo: string | undefined, aviso?: number) => {
    const notas = readFileSync(progresso, "utf8");
    await gravaNaVaga(vaga, "progresso.md", notas);
    await gravaNaVaga(vaga, "prompt.md", prompt);
    const comando = [
      aviso ? `AFK_AVISO_TOKENS=${aviso}` : "",
      q(c.claude), '-p "$(cat .afk/prompt.md)"',
      "--output-format stream-json --verbose --dangerously-skip-permissions",
      `--max-turns ${c.maxTurnos}`,
      modelo ? `--model ${q(modelo)}` : "",
      c.pluginDir ? `--plugin-dir ${q(c.pluginDir)}` : "",
    ].filter(Boolean).join(" ");
    const ac = new AbortController();
    let resposta = "";
    let tokens = 0;
    const agent: sc.AgentProvider = {
      name: "claude-code",
      env: {},
      captureSessions: false,
      buildPrintCommand: () => ({ command: comando }),
      parseStreamLine: (linha) => {
        appendFileSync(log, `${linha}\n`);
        const eventos = leitor.parseStreamLine(linha);
        for (const e of eventos) {
          if (e.type === "result") resposta = e.result;
          if (e.type === "context_window" && e.contextWindow.tokens > c.corte && !ac.signal.aborted) {
            tokens = e.contextWindow.tokens;
            ac.abort(new Error("corte"));
          }
        }
        return eventos;
      },
    };
    // No Docker, nem o corte nem o tempo ocioso matam o agente: quem mata é fechar a vaga (vivo).
    let vivo = false;
    try {
      await vaga.run({ agent, prompt: "-", signal: ac.signal, idleTimeoutSeconds: c.ocioso, logging: { type: "file", path: `${log}.sandcastle` } });
    } catch (e) {
      vivo = true; // o abort por sinal também lança
      if (!ac.signal.aborted) appendFileSync(`${log}.err`, `${String((e as Error)?.message ?? e)}\n`);
    }
    const depois = await leDaVaga(vaga, "progresso.md");
    if (depois.length > notas.length) appendFileSync(progresso, depois.startsWith(notas) ? depois.slice(notas.length) : `\n${depois}`);
    return { resposta, cortado: ac.signal.aborted, tokens, vivo };
  };

  // #849 do Sandcastle: um `git worktree repair` dentro de um contêiner grava nos metadados do worktree
  // o caminho do contêiner, e o `git worktree prune` de cada createSandbox apaga então o worktree de
  // outra vaga viva. Antes de cada criação, os metadados das vagas vivas voltam ao caminho do Mac. A
  // escrita passa pelo contêiner do integrador: um symlink que o agente ponha no caminho não a leva
  // para fora do .git. ponytail: sobra uma janela entre a restauração e o prune do createSandbox.
  const metadados = new Map<string, { gitdir: string; conteudo: string }>(); // por worktree, no Mac
  let escritor: Vaga | undefined; // o integrador, depois de criado
  // Logo depois da criação, antes de qualquer agente: o gitdir ainda é o que o git do Mac escreveu.
  const registra = (worktree: string) => {
    const raiz = join(c.clone, ".git", "worktrees");
    for (const nome of readdirSync(raiz)) {
      const gitdir = join(raiz, nome, "gitdir");
      const conteudo = leCurto(gitdir);
      if (conteudo && real(dirname(conteudo.trim())) === real(worktree)) metadados.set(worktree, { gitdir, conteudo });
    }
  };
  const restaura = async () => {
    for (const { gitdir, conteudo } of metadados.values()) {
      if (leCurto(gitdir) === conteudo) continue;
      await git(escritor!, `rm -rf ${q(gitdir)} && printf %s ${Buffer.from(conteudo).toString("base64")} | base64 -d > ${q(gitdir)}`);
    }
  };

  // Furo do Sandcastle: o createSandbox reaproveita qualquer worktree registrado no .git com o branch da
  // vaga se o caminho começar, em texto, por .sandcastle/worktrees/, sem resolver "..". O agente alcança
  // .git/worktrees/ e poderia fazer a vaga seguinte montar uma pasta qualquer do Mac (a principal, por
  // exemplo); o Sandcastle ainda roda git nela e, ao fechar, a removeria. Antes de cada criação, nenhum
  // worktree registrado aponta para uma pasta existente fora de .sandcastle/worktrees/; depois, o sandbox
  // tem de estar na pasta do seu branch. Se não, o loop para sem fechá-lo. ponytail: com outras vagas
  // vivas, sobra uma janela entre a conferência e o createSandbox; o conserto é no Sandcastle.
  const pastaDosWorktrees = join(realpathSync(c.clone), ".sandcastle", "worktrees");
  const gerenciado = (p: string) => { const r = real(p); return r !== "" && dirname(r) === pastaDosWorktrees; };
  // O git worktree prune que o Sandcastle roda no Mac apaga cada .git/worktrees/<id> sem gitdir seguindo
  // um symlink no caminho: .git/worktrees e as entradas têm de ser pastas de verdade.
  const confereWorktrees = () => {
    const raiz = join(c.clone, ".git", "worktrees");
    if (!lstatSync(raiz, { throwIfNoEntry: false })) return;
    if (!pastaDeVerdade(raiz)) throw new Parada(".git/worktrees não é uma pasta");
    for (const nome of readdirSync(raiz)) {
      if (!pastaDeVerdade(join(raiz, nome))) throw new Parada(`.git/worktrees/${nome} não é uma pasta`);
      const gitdir = leCurto(join(raiz, nome, "gitdir")).trim();
      if (!gitdir) continue;
      const pasta = dirname(resolve(raiz, nome, gitdir));
      if (real(pasta) && !gerenciado(pasta)) throw new Parada(`o worktree ${nome} do .git aponta para ${pasta}, fora de .sandcastle/worktrees`);
    }
  };

  // Uma falha ao abrir (Docker, rede no uv sync ou no npm ci) é falha da iteração, não do loop. A
  // instalação roda aqui, e não num hook onSandboxReady, que o Sandcastle roda sem olhar a saída.
  class VagaNaoAbriu extends Error {}
  const criacao = emSerie(); // o prune de uma criação não corre junto com a criação de outra
  const abre = async (ramo: string, base: string, papel: "vaga" | "integrador") => {
    const sb = await criacao(async () => {
      confereWorktrees(); // antes da restauração, que grava em .git/worktrees/
      await restaura();
      const novo = await sc.createSandbox({ branch: ramo, baseBranch: base, sandbox: c.caixa(papel), cwd: c.clone });
      if (real(novo.worktreePath) !== join(pastaDosWorktrees, ramo.replaceAll("/", "-"))) {
        throw new Parada(`o sandbox de ${ramo} subiu em ${novo.worktreePath}; o contêiner ficou aberto`);
      }
      registra(novo.worktreePath);
      return novo;
    }).catch((e) => { throw e instanceof Parada ? e : new VagaNaoAbriu(String(e?.message ?? e)); });
    const r = await sb.exec(c.instalar).catch((e) => ({ exitCode: -1, stderr: String(e?.message ?? e) }));
    if (r.exitCode === 0) return sb;
    await fecha(sb).catch(() => {});
    throw new VagaNaoAbriu(`a instalação saiu com ${r.exitCode}: ${r.stderr.trim().slice(-500)}`);
  };

  // O close() preserva o worktree com sujeira (um agente cortado, um arquivo do make verificar), e a
  // vaga seguinte do ticket o reaproveitaria. Apagado, o createSandbox seguinte o recria do branch.
  const fecha = async (vaga: Vaga) => {
    metadados.delete(vaga.worktreePath);
    const { preservedWorktreePath } = await vaga.close();
    if (preservedWorktreePath && gerenciado(preservedWorktreePath)) rmSync(preservedWorktreePath, { recursive: true, force: true });
  };

  // Uma iteração: implementação, revisão e portão, numa vaga nova que fecha no fim. Na iteração de merge,
  // o agente traz o branch do PR para o do ticket e resolve o conflito; não há revisão, que veria no
  // base..HEAD os outros tickets.
  const itera = async (t: Ticket, i: number) => {
    const log = join(logs, `iteracao-${i}`);
    let vaga: Vaga | undefined;
    try {
      vaga = await abre(t.ramo, t.base, "vaga");
      const inicio = await head(vaga);
      let esta = `\n\n## Esta iteração\n\n- Ticket: #${t.ticket}\n- Commit de antes do ticket: ${t.base}`;
      if (t.base !== inicio) {
        esta += `\n- Continuação: o ticket já tem commits. Leia \`git log ${t.base}..HEAD\` e as notas de .afk/progresso.md.`;
      }
      const mesclagem = t.mesclar;
      if (mesclagem) {
        esta += `\n- Merge: o ticket estava feito, mas não entrou em \`${c.branch}\` (${mesclagem}). Rode \`git merge ${c.branch}\`, ` +
          "resolva os conflitos mantendo o que os dois lados fazem, rode `make verificar` até passar e faça o commit do merge. " +
          "Nada além disso; termine com o status `feito`.";
      }
      // Depois de um corte ou de um erro do run o agente pode seguir vivo no contêiner: só fechá-lo o mata.
      const depoisDoCorte = async (r: { cortado: boolean; tokens: number; vivo: boolean }) => {
        if (r.cortado) anota(`#${t.ticket}: corte duro com ${r.tokens} tokens; o que não foi commitado é descartado`);
        if (!r.vivo) return;
        await fecha(vaga!);
        vaga = undefined;
        vaga = await abre(t.ramo, t.base, "vaga");
      };

      const impl = await roda(vaga, `${log}.jsonl`, readFileSync(join(aqui, "prompt.md"), "utf8") + esta, c.modelo, c.aviso);
      let status = ultimo(impl.resposta, /<status>([a-z_]*)<\/status>/g);
      if (impl.cortado) status = "parcial";
      else if (ultimo(impl.resposta, /<ticket>#*(\d*)<\/ticket>/g) !== t.ticket) status = "";
      await depoisDoCorte(impl);
      await descarta(vaga);

      // Revisão: outro claude -p, com contexto novo e outro modelo, sobre o ticket inteiro (base..HEAD).
      // Sem aviso de contexto, que manda terminar como parcial: o revisor só tem o corte duro.
      let motivo = "";
      if (status === "feito" && !mesclagem && (await head(vaga)) !== t.base) {
        const rev = await roda(vaga, `${log}-revisao.jsonl`, readFileSync(join(aqui, "revisao.md"), "utf8") + esta, c.modeloRevisor);
        const revisao = ultimo(rev.resposta, /<revisao>([a-z]*)<\/revisao>/g);
        await depoisDoCorte(rev);
        await descarta(vaga);
        if (!rev.cortado && revisao === "erro") {
          status = "erro";
        } else if (rev.cortado || revisao !== "feita") {
          status = "";
          motivo = `a revisão não terminou com <revisao>feita</revisao> (${log}-revisao.jsonl)`;
        }
      }

      // Portão, depois da revisão: confere tudo o que foi commitado desde o último SHA conferido (uma
      // iteração cuja vaga não reabriu deixa commits sem portão). Segue adiante o SHA conferido, não a
      // ref do branch do ticket, que o agente pode ter deixado em outro lugar.
      let verde = true;
      let logDoPortao = `${log}.verificar`;
      const ponta = await head(vaga);
      if (ponta !== t.conferido) {
        const v = await verifica(vaga, logDoPortao, t.ticket);
        logDoPortao = v.log;
        if (!v.verde) {
          await git(vaga, `git reset -q --hard ${t.conferido}`);
          verde = false;
        } else {
          t.conferido = ponta;
        }
      }
      return { status, verde, motivo, log, logDoPortao, ponta: t.conferido };
    } catch (e) {
      // Um erro numa vaga é falha da iteração; as falhas seguidas do ticket param o loop.
      if (e instanceof Parada) throw e;
      const m = String((e as Error)?.message ?? e);
      return { status: "", verde: true, motivo: e instanceof VagaNaoAbriu ? `a vaga não abriu: ${m}` : `erro na vaga: ${m}`, log, logDoPortao: "", ponta: "" };
    } finally {
      // Um erro ao fechar não derruba o loop: o resultado da iteração já está nos commits.
      if (vaga) await fecha(vaga).catch((e) => anota(`#${t.ticket}: a vaga não fechou (${String((e as Error)?.message ?? e)})`));
    }
  };

  const pendentes = (await issues()).filter((i) => i.state === "OPEN" && i.labels.includes("afk-feito")).map((i) => `#${i.number}`);
  if (pendentes.length) {
    anota(`parada: ${pendentes.join(" ")} têm afk-feito e seguem abertos. Faça o merge do PR anterior (ou tire a label) antes de rodar de novo.`);
    return 3;
  }

  const integ = await abre(c.branch, "main", "integrador");
  escritor = integ;
  let main = "";
  let esperada = ""; // a ponta que o branch do PR deve ter: o agente alcança a ref e pode movê-la
  try {
    // Antes de qualquer agente: depois, as refs do .git (uma tag main, um update-ref) são dele.
    main = sha(await git(integ, "git rev-parse refs/heads/main"));
    esperada = await head(integ);
    // Um `git worktree prune` do agente na vaga, onde os outros worktrees não existem, apagaria os
    // metadados do integrador; o prune pula um worktree travado.
    await git(integ, `echo loop AFK > "$(git rev-parse --git-dir)/locked"`);
  } catch (e) {
    await fecha(integ).catch(() => {});
    throw e;
  }
  const conferePR = async (ponta = esperada) => {
    const r = await integ.exec(`git rev-parse -q --verify ${q(`refs/heads/${c.branch}`)}`);
    if (r.stdout.trim() !== ponta) throw new Error(`o branch do PR mudou fora do integrador (${r.stdout.trim() || "sumiu"}, esperado ${ponta})`);
  };
  const integracao = emSerie();
  // Junta ao branch do PR o SHA que passou no portão. Devolve o motivo se não deu, e o branch do PR volta
  // a como estava. Um branch do PR movido por fora (antes, durante o make verificar ou depois) para o loop.
  // A instalação roda de novo antes do make verificar: um ticket já juntado pode ter mudado um lockfile.
  const integra = (t: Ticket, log: string, ponta: string) =>
    integracao(async () => {
      await conferePR();
      const antes = esperada;
      // Sobras da instalação ou do make verificar do merge anterior (um arquivo reescrito, outro gerado)
      // sujariam este merge e dariam o alarme falso do branch do PR mudado.
      await git(integ, `git reset -q --hard ${antes} && git clean -fdq`);
      const volta = () => integ.exec(`git merge --abort; git reset -q --hard ${antes}`);
      try {
        const m = await integ.exec(`git merge -q --no-ff -m ${q(`#${t.ticket}: merge do loop AFK`)} ${ponta}`);
        if (m.exitCode !== 0) {
          await volta();
          return "conflito";
        }
        const feito = await head(integ);
        if (feito === antes) return ""; // o ticket já estava no branch do PR
        // O SHA vem da ref, que outra vaga pode ter trocado logo depois do merge: um commit forjado tem
        // outra árvore e não bate com o índice e o worktree, que são os do merge de verdade.
        if ((await integ.exec("git diff --quiet --cached HEAD && git diff --quiet")).exitCode !== 0) {
          throw new Error(`o branch do PR mudou fora do integrador durante o merge do #${t.ticket} (${feito})`);
        }
        if ((await git(integ, `git rev-parse ${feito}^1 ${feito}^2`)) !== `${antes}\n${ponta}`) {
          throw new Error(`o merge do #${t.ticket} não tem os pais esperados (${feito})`);
        }
        // Árvore igual à da ponta do ticket: o make verificar da vaga já conferiu exatamente isto.
        if ((await git(integ, `git rev-parse ${feito}^{tree}`)) !== (await git(integ, `git rev-parse ${ponta}^{tree}`))) {
          const arquivo = `${log}-integracao.verificar`;
          const i = await integ.exec(c.instalar);
          if (i.exitCode !== 0) writeFileSync(arquivo, i.stdout + i.stderr);
          const v = i.exitCode === 0 ? await verifica(integ, arquivo, t.ticket) : { verde: false, log: arquivo };
          if (!v.verde) {
            await volta();
            const oque = i.exitCode === 0 ? "make verificar" : "a instalação";
            anota(`#${t.ticket}: ${oque} falhou depois do merge (${v.log})`);
            return `${oque} falhou depois do merge`;
          }
        }
        await conferePR(feito);
        esperada = feito;
        return "";
      } catch (e) {
        await volta();
        throw e;
      }
    });
  // Tira o branch do ticket do caminho do PR: com commits, vira afk/<data>-<sufixo>-N e vai no bundle.
  // Por update-ref, que passa por cima de um branch com o mesmo nome que o agente tenha criado: o
  // `git branch -m` também renomeia a seção do branch no .git/config, que é só leitura no sandbox.
  const guardados: string[] = [];
  // Em série com os merges: o integrador faz uma coisa por vez no .git (dois `git branch -M` juntos colidiam).
  const guarda = (t: Ticket, sufixo: string) => {
    saidos.add(t.ticket);
    emAndamento.delete(t.ticket);
    return integracao(async () => {
      const ponta = (await integ.exec(`git rev-parse -q --verify ${q(t.ramo)}`)).stdout.trim();
      if (!ponta || ponta === t.base) return "";
      const guardado = `${c.branch}-${sufixo}-${t.ticket}`;
      await git(integ, `git update-ref ${q(`refs/heads/${guardado}`)} ${sha(ponta)} && git update-ref -d ${q(`refs/heads/${t.ramo}`)}`);
      guardados.push(guardado);
      return guardado;
    });
  };
  const paraHumano = async (t: Ticket, motivo: string) => {
    const guardado = await guarda(t, "bloqueado");
    anota(`#${t.ticket} → ready-for-human: ${motivo}${guardado ? `; trabalho guardado em ${guardado}` : ""}`);
    // O ticket já saiu da rodada: sem o gh, a troca de label e o comentário ficam para o humano.
    try {
      await gh("issue", "edit", t.ticket, "--remove-label", "ready-for-agent", "--add-label", "ready-for-human");
      await gh("issue", "comment", t.ticket, "--body",
        `Loop AFK: ticket devolvido para humano (${motivo}).${guardado ? ` O trabalho parcial ficou no branch local \`${guardado}\`.` : ""}`);
    } catch (e) {
      anota(`#${t.ticket}: o gh não devolveu o ticket (${String((e as Error)?.message ?? e)}); confira à mão a label ready-for-human e o comentário`);
    }
  };

  // As iterações são do loop inteiro, somadas as vagas; as falhas seguidas, de cada ticket. Com `parar`,
  // nenhuma vaga começa iteração nova: as que estão no meio terminam a sua.
  const loopa = { iteracoes: 0, saida: 0, parar: false };
  const para = (saida: number, motivo: string) => {
    anota(motivo);
    loopa.saida ||= saida;
    loopa.parar = true;
  };

  // Um ticket do começo ao fim, uma iteração atrás da outra. Ao voltar, o ticket ou saiu de emAndamento
  // (feito, bloqueado) ou fica lá para o fim do loop guardá-lo como parcial.
  const trabalha = async (t: Ticket) => {
    while (!loopa.parar && loopa.iteracoes < c.maxIteracoes) {
      const i = ++loopa.iteracoes;
      t.iteracoes++;
      anota(`iteração ${i}: #${t.ticket}${t.mesclar ? " (merge)" : ""}`);
      const { status, verde, motivo, log, logDoPortao, ponta } = await itera(t, i);

      if (status === "erro") {
        para(2, `#${t.ticket}: erro de ambiente informado pelo agente; o loop para (veja as notas acima e ${log}*)`);
        return;
      } else if (status === "bloqueado") {
        await paraHumano(t, "o agente precisa de uma decisão; veja o comentário anterior");
        return;
      } else if (!verde || !status) {
        t.falhas++;
        anota(`#${t.ticket}: ${!verde
          ? `make verificar falhou depois da iteração; commits da iteração desfeitos (${logDoPortao})`
          : motivo || `iteração terminou sem <ticket>${t.ticket}</ticket> e <status> válidos (${log}.jsonl)`}`);
        if (t.falhas >= c.maxFalhas) para(1, `parada: ${t.falhas} falhas seguidas do #${t.ticket}`);
        continue;
      } else if (status === "feito") {
        t.falhas = 0;
        const nao = await integra(t, log, ponta);
        if (!nao) {
          saidos.add(t.ticket);
          emAndamento.delete(t.ticket);
          feitos.add(Number(t.ticket));
          appendFileSync(join(afk, "feitos"), `${t.ticket}\n`);
          anota(`#${t.ticket}: feito`);
          try {
            await gh("issue", "edit", t.ticket, "--add-label", "afk-feito");
          } catch (e) {
            anota(`#${t.ticket}: a label afk-feito não entrou (${String((e as Error)?.message ?? e).trim()}); ponha à mão`);
          }
          return;
        }
        if (t.mesclagens >= 1) {
          await paraHumano(t, `não entrou em ${c.branch} nem depois de uma iteração de merge (${nao})`);
          return;
        }
        t.mesclagens++;
        t.mesclar = nao;
        anota(`#${t.ticket}: não entrou em ${c.branch} (${nao}); a próxima iteração faz o merge`);
        continue;
      } else if (status === "parcial") {
        t.parciais++;
        if (t.parciais >= c.maxParciais) {
          await paraHumano(t, `${t.parciais} iterações parciais seguidas`);
          return;
        }
        anota(`#${t.ticket}: parcial (${t.parciais}/${c.maxParciais}); a próxima iteração continua`);
      } else {
        para(2, `#${t.ticket}: status desconhecido '${status}'; o loop para`);
        return;
      }
      t.falhas = 0;
    }
  };

  const vivas = new Set<Promise<void>>();
  try {
    for (;;) {
      while (!loopa.parar && vivas.size < c.vagas && loopa.iteracoes < c.maxIteracoes) {
        const proximo = await proximoTicket();
        // O gh pode levar minutos tentando de novo, e as vagas seguem: o loop pode ter parado nesse meio-tempo.
        if (!proximo || loopa.parar || loopa.iteracoes >= c.maxIteracoes) break;
        const ramo = `afk-t/${c.branch.replace(/^afk\//, "")}/${proximo.ticket}`;
        // Um branch do ticket criado antes pelo agente faria o createSandbox ignorar a base.
        await git(integ, `git update-ref -d ${q(`refs/heads/${ramo}`)}`);
        const t: Ticket = {
          ...proximo, ramo, base: esperada, conferido: esperada, parciais: 0, falhas: 0, mesclar: "", mesclagens: 0, iteracoes: 0,
        };
        emAndamento.set(t.ticket, t);
        const p: Promise<void> = trabalha(t)
          .catch((e) => para(2, `erro do loop no #${t.ticket}: ${String((e as Error)?.message ?? e)}`))
          .finally(() => vivas.delete(p));
        vivas.add(p);
      }
      if (!vivas.size) {
        if (!loopa.parar && loopa.iteracoes < c.maxIteracoes) anota("sem_tickets: nenhum ticket elegível");
        break;
      }
      await Promise.race(vivas);
    }
  } catch (e) {
    loopa.saida = 2;
    anota(`erro do loop: ${String((e as Error)?.message ?? e)}`);
  } finally {
    // Depois de um erro do despachante, as vagas vivas terminam a iteração antes do bundle.
    loopa.parar = true;
    await Promise.allSettled(vivas);
    // O PR só leva tickets feitos: os ainda em andamento ficam em branches à parte.
    for (const t of [...emAndamento.values()]) {
      try {
        const guardado = await guarda(t, "parcial");
        if (t.iteracoes) anota(`#${t.ticket}: ficou em andamento${guardado ? `; trabalho guardado em ${guardado}` : ""}`);
      } catch (e) {
        anota(`#${t.ticket}: ficou em andamento e não foi guardado (${String((e as Error)?.message ?? e)})`);
      }
    }
    anota(`fim: feitos: ${readFileSync(join(afk, "feitos"), "utf8").split("\n").filter(Boolean).join(" ")}`);
    try {
      // O bundle sai do sandbox, fora do worktree (que tem os commits do agente), pelo stdout em base64:
      // o Mac não roda git nos objetos do agente nem lê arquivo que ele possa trocar. Só o que está além
      // da main, que a pasta principal já tem; sem nada além dela, o git recusa e não há bundle.
      // Só os branches que o loop montou, pelo nome: o agente pode criar outro afk/... no .git compartilhado.
      // Sem bundle se o branch do PR não for o que o integrador montou.
      await conferePR();
      const refs = [c.branch, ...guardados].map((b) => q(`refs/heads/${b}`)).join(" ");
      const b = await integ.exec(`f=$(mktemp) && git bundle create -q \"$f\" ${refs} ^${main} && base64 < \"$f\"`);
      if (b.exitCode === 0) writeFileSync(join(afk, "afk.bundle"), Buffer.from(b.stdout, "base64"));
      else anota(`sem bundle: ${b.stderr.trim()}`);
    } catch (e) {
      anota(`sem bundle: ${String((e as Error)?.message ?? e)}`);
      loopa.saida = 2;
    } finally {
      await fecha(integ);
    }
  }
  return loopa.saida;
}

if (realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) {
  const { docker } = await import("@ai-hero/sandcastle/sandboxes/docker");
  const [clone, branch, n] = process.argv.slice(2);
  const e = process.env;
  const vagas = Number(e.AFK_VAGAS || 1);
  const repassa = ["CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN", "FIRESTORE_EMULATOR_HOST", "STORAGE_EMULATOR_HOST",
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"];
  // O pre-commit do projeto (gitleaks) nos commits do agente: o config do .git é só leitura no sandbox.
  // Só nas vagas: no integrador, os hooks do branch (escritos pelo agente) não rodam. Em todos, o git
  // ignora os refs/replace do agente, que trocariam o conteúdo de um commit no checkout e no merge.
  const hooks = { GIT_CONFIG_COUNT: "1", GIT_CONFIG_KEY_0: "core.hooksPath", GIT_CONFIG_VALUE_0: ".githooks" };
  // Com mais de uma vaga, os testes dividem o Mac. Com 3 e 2 processos, as duas vagas somavam de 1,2 a 3
  // dos 8 CPUs do Docker (rodada de 2026-11-04): cada make verificar ficava lento com a máquina sobrando.
  const divide = vagas > 1
    ? { PYTEST_XDIST_AUTO_NUM_WORKERS: e.AFK_PYTEST_PROCESSOS || "6", VITEST_MAX_WORKERS: e.AFK_VITEST_PROCESSOS || "4" }
    : {};
  const plugin = "/opt/plugins/mattpocock-skills";
  process.exitCode = await loop({
    clone, branch, maxIteracoes: Number(n), vagas,
    caixa: (papel) => docker({
      imageName: "mam-afk", containerUid: 1000, containerGid: 1000, network: e.AFK_REDE,
      env: { ...Object.fromEntries(repassa.map((k) => [k, e[k] ?? ""])), GIT_NO_REPLACE_OBJECTS: "1", ...(papel === "vaga" ? hooks : {}), ...divide },
      mounts: [{ hostPath: e.AFK_PLUGIN_HOST!, sandboxPath: plugin, readonly: true }],
    }),
    claude: "claude",
    // O make instalar também faz git config, que falha dentro do sandbox (o config é só leitura).
    // O timeout vai no comando: o exec do Sandcastle não tem prazo.
    instalar: "timeout 600 sh -c 'uv sync --locked && npm ci --prefix web' > /dev/null",
    verificar: "timeout 3600 make verificar",
    modelo: e.AFK_MODELO || undefined,
    modeloRevisor: e.AFK_MODELO_REVISOR || "opus",
    pluginDir: plugin,
    aviso: Number(e.AFK_AVISO_TOKENS || 120000),
    corte: Number(e.AFK_CORTE_TOKENS || 140000),
    maxTurnos: Number(e.AFK_MAX_TURNOS || 300),
    maxFalhas: Number(e.AFK_MAX_FALHAS || 3),
    maxParciais: Number(e.AFK_MAX_PARCIAIS || 3),
    ocioso: 1200,
  });
}
