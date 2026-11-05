// Testa o loop AFK e o hook de contexto com claude e gh falsos, no noSandbox: sem Docker e sem rede.
// Uso: make testar-afk
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { noSandbox } from "@ai-hero/sandcastle/sandboxes/no-sandbox";
import { leCurto, loop, specDe, type Config } from "./main.mts";

const aqui = dirname(fileURLToPath(import.meta.url));
const tmp = mkdtempSync(join(tmpdir(), "afk-"));
const bin = join(tmp, "bin");
mkdirSync(bin);

// claude falso: executa a próxima linha de $FAKE/roteiro ("<ação> <ticket>") do ticket do prompt.
// Registra em $FAKE/claude.log a ação, o ticket, o --model e se o hook de contexto está ligado,
// e guarda o prompt em $FAKE/prompt.<modelo>.
writeFileSync(join(bin, "claude"), String.raw`#!/usr/bin/env bash
set -euo pipefail
modelo=padrão
while [ $# -gt 0 ]; do
  case $1 in
    -p) prompt=$2 ;;
    --model) modelo=$2 ;;
  esac
  shift
done
printf '%s' "$prompt" > "$FAKE/prompt.$modelo"
ticket=$(grep -o 'Ticket: #[0-9]*' <<< "$prompt" | tail -n 1 | tr -dc 0-9)
until mkdir "$FAKE/trava" 2> /dev/null; do sleep 0.05; done # as vagas leem o roteiro juntas
linha=$(grep -m 1 " $ticket\$" "$FAKE/roteiro" || true)
awk -v l="$linha" '!f && $0 == l { f = 1; next } 1' "$FAKE/roteiro" > "$FAKE/roteiro.novo" && mv "$FAKE/roteiro.novo" "$FAKE/roteiro"
rmdir "$FAKE/trava"
read -r acao _ <<< "$linha"
echo "$acao $ticket $modelo${"${AFK_AVISO_TOKENS:+ aviso}"}" >> "$FAKE/claude.log"
uso() { printf '{"type":"assistant","parent_tool_use_id":%s,"message":{"usage":{"input_tokens":1,"cache_read_input_tokens":%s,"cache_creation_input_tokens":0}}}\n' "$1" "$2"; }
fim() { printf '{"type":"result","result":"Pronto.\\n<ticket>%s</ticket>\\n<status>%s</status>"}\n' "$ticket" "$1"; }
fim_revisao() { printf '{"type":"result","result":"Revisado.\\n<revisao>%s</revisao>"}\n' "$1"; }
commit() { echo "$1" > "$1"; git add "$1"; git commit -qm "#$ticket: $1"; }
espera() { # até 60 s; se expirar, fica no log (sob carga, a outra vaga pode demorar a chegar)
  for _ in $(seq 600); do [ -e "$1" ] && return; sleep 0.1; done
  echo "espera expirou: $1" >> "$FAKE/claude.log"; return 1
}
nota() { echo "- nota de $acao $ticket" >> .afk/progresso.md; }
uso null 5000
uso '"subagente"' 999999 # contexto de subagente: não conta
case $acao in
  feito) commit "t$ticket"; nota; fim feito ;;
  parcial) commit "t$ticket-parte-$RANDOM"; fim parcial ;;
  quebra) commit quebrado; fim feito ;;
  bloqueado)
    commit "t$ticket-parte"
    gh issue comment "$ticket" --body "Qual opção?"
    gh issue edit "$ticket" --remove-label ready-for-agent --add-label ready-for-human
    fim bloqueado ;;
  estouro) commit "t$ticket-parte"; echo lixo > lixo.txt; uso null 999999; echo $$ > "$FAKE/pid"; exec sleep 30 ;;
  mudo) commit "t$ticket-parte"; echo $$ > "$FAKE/pid"; exec sleep 30 ;;
  revisa) commit "r$ticket"; echo lixo > lixo-revisao.txt; fim_revisao feita ;;
  revisa_quebra) commit quebrado; fim_revisao feita ;;
  revisa_erro) fim_revisao erro ;;
  revisa_mudo) commit "r$ticket" ;;
  # Conserta numa ref fora do branch do ticket: o portão confere o HEAD, e é ele que segue.
  foge) commit quebrado; git checkout -q -b "fuga-$ticket"; git rm -q quebrado; git commit -qm "#$ticket: conserta"; fim feito ;;
  # Ref intrusa e branch do PR movido, de dentro da vaga (o .git é compartilhado).
  intrusa) commit "t$ticket"; git branch afk/intrusa; git branch afk/teste-intrusa; fim feito ;;
  sabota) commit "t$ticket"; git update-ref refs/heads/afk/teste HEAD; fim feito ;;
  # Registra no .git um worktree do próprio branch numa pasta fora de .sandcastle/worktrees.
  escapa)
    alvo="$FAKE/alvo"; git init -q "$alvo"; echo x > "$alvo/importante"
    proprio=$(cat "$(git rev-parse --git-dir)/gitdir")
    wt="$(cd "$(git rev-parse --git-common-dir)" && pwd)/worktrees/x"; mkdir -p "$wt"
    echo "ref: refs/heads/$(git branch --show-current)" > "$wt/HEAD"; echo ../.. > "$wt/commondir"
    echo "$(dirname "$(dirname "$proprio")")/../../../alvo/.git" > "$wt/gitdir" # .sandcastle/worktrees/../../../alvo
    commit "t$ticket-parte"; fim parcial ;;
  # Troca por symlink uma entrada de .git/worktrees, ou a própria pasta: o prune do Mac apagaria o alvo.
  link_entrada)
    mkdir -p "$FAKE/alvo"; echo x > "$FAKE/alvo/importante"
    ln -s "$FAKE/alvo" "$(cd "$(git rev-parse --git-common-dir)" && pwd)/worktrees/zz"
    commit "t$ticket-parte"; fim parcial ;;
  link_worktrees)
    mkdir -p "$FAKE/alvo"; echo x > "$FAKE/alvo/importante"
    commit "t$ticket-parte"
    w="$(cd "$(git rev-parse --git-common-dir)" && pwd)/worktrees"; mv "$w" "$w-2"; ln -s "$FAKE/alvo" "$w"
    fim parcial ;;
  # Commit vermelho, e a vaga não reabre depois do corte: o commit fica no branch sem portão.
  estouro_quebra) commit quebrado; touch "$FAKE/falha-instalar"; uso null 999999; echo $$ > "$FAKE/pid"; exec sleep 30 ;;
  nada) fim feito ;;
  revisa_nada) fim_revisao feita ;;
  # Cria antes o branch de um ticket futuro, com um commit.
  planta) commit "t$ticket"; git branch afk-t/teste/2; git checkout -q afk-t/teste/2; commit plantado; git checkout -q -; fim feito ;;
  # Ocupa o nome em que o loop guardaria o ticket.
  ocupa) commit "t$ticket-parte"; git branch "afk/teste-parcial-$ticket" main; fim parcial ;;
  # Duas vagas: só termina se a outra estiver rodando ao mesmo tempo.
  junto_parcial) touch "$FAKE/vivo.$ticket"; espera "$FAKE/vivo.$((3 - ticket))"; commit "t$ticket-parte"; fim parcial ;;
  junto) touch "$FAKE/vivo.$ticket"; espera "$FAKE/vivo.$((3 - ticket))"; commit "t$ticket"; fim feito ;;
  # Mesma spec: anota se outra vaga estiver rodando ao mesmo tempo.
  sozinho)
    touch "$FAKE/vivo.$ticket"; sleep 0.5
    if ls "$FAKE"/vivo.* | grep -qv "vivo.$ticket\$"; then echo colidiu >> "$FAKE/claude.log"; fi
    rm "$FAKE/vivo.$ticket"; commit "t$ticket"; fim feito ;;
  comum) echo "$ticket" > comum; git add comum; git commit -qm "#$ticket: comum"; fim feito ;;
  mescla)
    git merge -q afk/teste 2> /dev/null || { echo junto > comum; git add comum; git commit -qm "#$ticket: merge"; }
    fim feito ;;
  nao_mescla) fim feito ;;
  # Um merge limpo que, com o outro ticket, quebra a verificação.
  cria) commit "c$ticket"; fim feito ;;
  # #849: o agente estraga os metadados do próprio worktree e só commita depois de outra vaga ser criada.
  estraga)
    echo /nao/existe/.git > "$(git rev-parse --git-dir)/gitdir"; touch "$FAKE/estragou"
    espera "$FAKE/vivo.2"; commit "t$ticket"; fim feito ;;
  # A vaga seguinte do ticket só é criada depois do estraga.
  depois_do_estraga) espera "$FAKE/estragou"; commit "t$ticket-parte"; fim parcial ;;
  marca) touch "$FAKE/vivo.$ticket"; commit "t$ticket"; fim feito ;;
esac
`);

// gh falso: serve $FAKE/issues.json e registra edições e comentários em $FAKE/gh.log. Os PRs vão no
// mesmo arquivo, com o estado em "pr" (pr(9, "MERGED")): a consulta das issues não os vê.
writeFileSync(join(bin, "gh"), String.raw`#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "api graphql")
    # $FAKE/graphql-falha: quantas leituras da fila ainda falham.
    if [ -s "$FAKE/graphql-falha" ] && [ "$(cat "$FAKE/graphql-falha")" -gt 0 ]; then
      echo $(($(cat "$FAKE/graphql-falha") - 1)) > "$FAKE/graphql-falha"; echo "gh falso: falha de rede" >&2; exit 1
    fi
    jq '[{data: {repository: {issues: {nodes: map(select(.pr == null)), pageInfo: {hasNextPage: false}}}}}]' "$FAKE/issues.json" ;;
  "pr list")
    echo "pr list" >> "$FAKE/gh.log"
    # Um PR com estado SEM_PERMISSAO faz a leitura falhar, como um token sem "Pull requests: leitura".
    if jq -e 'any(.[]; .pr == "SEM_PERMISSAO")' "$FAKE/issues.json" > /dev/null; then echo "gh falso: HTTP 403" >&2; exit 1; fi
    jq '[.[] | select(.pr == "MERGED") | {number}]' "$FAKE/issues.json" ;;
  "issue comment")
    echo "comment $3" >> "$FAKE/gh.log"
    if [ -s "$FAKE/gh-falha" ] && [[ "$*" == *"$(cat "$FAKE/gh-falha")"* ]]; then echo "gh falso: falha de rede" >&2; exit 1; fi ;;
  "issue edit")
    # As vagas podem editar ao mesmo tempo: uma de cada vez em issues.json.
    until mkdir "$FAKE/trava-gh" 2> /dev/null; do sleep 0.05; done
    trap 'rmdir "$FAKE/trava-gh"' EXIT
    if [ -s "$FAKE/gh-falha" ] && [[ "$*" == *"$(cat "$FAKE/gh-falha")"* ]]; then echo "gh falso: falha de rede" >&2; exit 1; fi
    n=$3; shift 3
    echo "edit $n $*" >> "$FAKE/gh.log"
    while [ $# -gt 0 ]; do
      case $1 in
        --add-label) filtro='.labels.nodes += [{name: $l}]' ;;
        --remove-label) filtro='.labels.nodes |= map(select(.name != $l))' ;;
      esac
      jq --argjson n "$n" --arg l "$2" "map(if .number == \$n then $filtro else . end)" "$FAKE/issues.json" > "$FAKE/i.json"
      mv "$FAKE/i.json" "$FAKE/issues.json"
      shift 2
    done ;;
  *) echo "gh falso: comando inesperado: $*" >&2; exit 1 ;;
esac
`);
chmodSync(join(bin, "claude"), 0o755);
chmodSync(join(bin, "gh"), 0o755);

process.env.PATH = `${bin}:${process.env.PATH}`;
// No noSandbox, o git do Sandcastle roda no Mac: o config global é um arquivo do teste.
process.env.GIT_CONFIG_GLOBAL = join(tmp, "gitconfig");
Object.assign(process.env, {
  GIT_AUTHOR_NAME: "teste", GIT_AUTHOR_EMAIL: "teste@exemplo", GIT_COMMITTER_NAME: "teste", GIT_COMMITTER_EMAIL: "teste@exemplo",
  FIRESTORE_EMULATOR_HOST: "localhost:8686", STORAGE_EMULATOR_HOST: "http://localhost:4443",
});

const issue = (number: number, state: string, labels: string, bloqueios: number[] = [], body = "") => ({
  number, state, body,
  labels: { nodes: labels.split(",").filter(Boolean).map((name) => ({ name })) },
  blockedBy: { nodes: bloqueios.map((n) => ({ number: n })) },
});

const pr = (number: number, estado: "OPEN" | "CLOSED" | "MERGED" | "SEM_PERMISSAO") => ({ number, pr: estado });

let caso = 0;
// Roda o loop num repositório novo com as issues e o roteiro do claude dados.
async function roda(maxIteracoes: number, fila: object[], roteiro: string[], extra: Partial<Config> = {}, notasDeAntes = "") {
  const fake = join(tmp, `caso${++caso}`);
  const repo = join(fake, "repo");
  mkdirSync(repo, { recursive: true });
  writeFileSync(join(fake, "issues.json"), JSON.stringify(fila));
  writeFileSync(join(fake, "roteiro"), roteiro.map((l) => `${l}\n`).join(""));
  writeFileSync(join(fake, "claude.log"), "");
  writeFileSync(join(fake, "gh.log"), "");
  process.env.FAKE = fake;
  const g = (...a: string[]) => execFileSync("git", a, { cwd: repo, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  g("init", "-q", "-b", "main");
  writeFileSync(join(repo, ".gitignore"), ".afk/\n.sandcastle/\n");
  g("add", ".gitignore");
  g("commit", "-qm", "inicial");
  mkdirSync(join(repo, ".afk"));
  writeFileSync(join(repo, ".afk", "progresso.md"), notasDeAntes);
  const inicio = Date.now();
  const saida = await loop({
    clone: repo, branch: "afk/teste", maxIteracoes, vagas: 1, caixa: () => noSandbox(),
    claude: join(bin, "claude"), instalar: "true", verificar: "test ! -e quebrado",
    modeloRevisor: "opus", aviso: 120000, corte: 140000, maxTurnos: 300, maxFalhas: 3, maxParciais: 3, ocioso: 60, pausaGh: 0,
    ...extra,
  });
  const ler = (f: string) => readFileSync(join(fake, f), "utf8");
  const notas = () => readFileSync(join(repo, ".afk", "progresso.md"), "utf8");
  return {
    saida, repo, g, notas,
    duracao: (Date.now() - inicio) / 1000,
    rodou: () => ler("claude.log").trim().split("\n").filter(Boolean).join(";"),
    ghLog: () => ler("gh.log"),
    prompt: (modelo: string) => ler(`prompt.${modelo}`),
    feitos: () => readFileSync(join(repo, ".afk", "feitos"), "utf8").split("\n").filter(Boolean).join(" "),
    noPR: (arquivo: string) => existe(g, `afk/teste:${arquivo}`),
    existe: (ref: string) => existe(g, ref),
  };
}
const existe = (g: (...a: string[]) => string, ref: string) => {
  try { g("cat-file", "-e", ref); return true; } catch { return false; }
};

test("ticket feito, na ordem dos bloqueios", async () => {
  const r = await roda(5, [
    issue(1, "OPEN", "ready-for-agent"),
    issue(2, "OPEN", "ready-for-agent", [1]),
    issue(3, "OPEN", "ready-for-agent", [], "## Bloqueio\n\nBloqueado por: #2"),
    issue(4, "OPEN", "ready-for-human"),
    issue(5, "CLOSED", "ready-for-agent"),
  ], ["feito 1", "revisa 1", "feito 2", "revisa 2", "feito 3", "revisa 3"]);
  assert.equal(r.saida, 0);
  assert.equal(r.feitos(), "1 2 3");
  assert.match(r.ghLog(), /edit 3 --add-label afk-feito/);
  assert.ok(r.noPR("t3") && r.noPR("r3"), "commits do agente e da revisão no branch do PR");
  assert.equal(r.rodou(), "feito 1 padrão aviso;revisa 1 opus;feito 2 padrão aviso;revisa 2 opus;feito 3 padrão aviso;revisa 3 opus");
  assert.match(r.prompt("opus"), /Ticket: #3/);
  assert.match(r.prompt("opus"), new RegExp(r.g("rev-parse", "afk/teste^1")), "a revisão recebe o commit de antes do ticket");
  assert.ok(!r.noPR("lixo-revisao.txt"));
  assert.match(r.notas(), /nota de feito 3/, "as notas do agente voltam ao progresso");
  assert.match(r.notas(), /sem_tickets/);
  assert.ok(existsSync(join(r.repo, ".afk", "afk.bundle")));
  assert.match(r.g("bundle", "list-heads", ".afk/afk.bundle"), /refs\/heads\/afk\/teste/);
});

test("notas grandes e acentuadas voltam sem se repetir", async () => {
  const antes = "- ação já anotada, é ç ã õ\n".repeat(8000); // ~250 KB: vários pedaços do stdout
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["feito 1", "revisa 1"], {}, antes);
  assert.equal(r.feitos(), "1");
  assert.ok(r.notas().startsWith(antes));
  assert.equal(r.notas().split("ação já anotada").length - 1, 8000);
  assert.match(r.notas(), /nota de feito 1/);
});

test("estouro de contexto", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["estouro 1", "feito 1", "revisa 1"], { corte: 100000 });
  assert.equal(r.rodou(), "estouro 1 padrão aviso;feito 1 padrão aviso;revisa 1 opus", "não revisa ticket cortado");
  assert.ok(r.duracao < 20, "mata a iteração sem esperar o agente");
  assert.match(r.notas(), /corte duro/);
  assert.ok(!r.noPR("lixo.txt"), "descarta o que não foi commitado");
  assert.ok(r.noPR("t1-parte"), "mantém o que foi commitado");
  assert.equal(r.feitos(), "1", "a iteração seguinte continua e termina o ticket");
  // No noSandbox o agente cortado segue vivo (no Docker, o close() remove o contêiner com ele).
  process.kill(Number(readFileSync(join(process.env.FAKE!, "pid"), "utf8")));
});

test("agente mudo além do tempo ocioso", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["mudo 1", "feito 1", "revisa 1"], { ocioso: 1 });
  process.kill(Number(readFileSync(join(process.env.FAKE!, "pid"), "utf8")));
  assert.ok(r.duracao < 20, "não espera o agente");
  assert.match(r.notas(), /iteração terminou sem <ticket>1<\/ticket>/, "conta como falha");
  assert.ok(r.noPR("t1-parte") && r.noPR("t1"), "o que passou no portão segue; a iteração seguinte termina o ticket");
});

test("ticket bloqueado", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent"), issue(2, "OPEN", "ready-for-agent")],
    ["parcial 1", "bloqueado 1", "feito 2", "revisa 2"]);
  assert.equal(r.rodou(), "parcial 1 padrão aviso;bloqueado 1 padrão aviso;feito 2 padrão aviso;revisa 2 opus");
  assert.match(r.ghLog(), /edit 1 --remove-label ready-for-agent --add-label ready-for-human/);
  assert.match(r.ghLog(), /comment 1/);
  assert.ok(r.existe("afk/teste-bloqueado-1:t1-parte"), "guarda o trabalho num branch que vai no bundle");
  assert.ok(!r.noPR("t1-parte"));
  assert.equal(r.feitos(), "2");
});

test("verificação falhando depois do commit", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")],
    ["quebra 1", "revisa 1", "quebra 1", "revisa 1", "quebra 1", "revisa 1", "feito 1"]);
  assert.ok(!r.existe("afk-t/teste/1:quebrado"), "desfaz os commits da iteração");
  assert.match(r.notas(), /make verificar falhou/);
  assert.equal(r.rodou().split(";").length, 6, "para depois de 3 falhas seguidas");
  assert.equal(r.saida, 1);
  assert.doesNotMatch(r.ghLog(), /afk-feito/);
});

test("make verificar que falha uma vez passa ao repetir, e a nota diz o que falhou", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["feito 1", "revisa 1"],
    { verificar: `test ! -e quebrado && { [ -e "$FAKE/ja" ] || { touch "$FAKE/ja"; echo ' FAIL  src/X.test.tsx > o teste lento'; false; }; }` });
  assert.equal(r.saida, 0);
  assert.equal(r.feitos(), "1");
  assert.equal(r.rodou(), "feito 1 padrão aviso;revisa 1 opus", "sem iteração a mais");
  assert.match(r.notas(), /#1: make verificar falhou e passou ao repetir \(.*FAIL {2}src\/X\.test\.tsx > o teste lento/);
  assert.doesNotMatch(r.notas(), /commits da iteração desfeitos/);
});

test("make verificar que estoura o prazo (124) não repete", async () => {
  const r = await roda(1, [issue(1, "OPEN", "ready-for-agent")], ["feito 1", "revisa 1"],
    { verificar: `echo x >> "$FAKE/verificacoes"; exit 124` });
  assert.match(r.notas(), /make verificar falhou depois da iteração; commits da iteração desfeitos/);
  assert.equal(readFileSync(join(process.env.FAKE!, "verificacoes"), "utf8"), "x\n", "uma tentativa só");
  assert.equal(r.feitos(), "");
});

test("revisão quebra a verificação", async () => {
  const r = await roda(1, [issue(1, "OPEN", "ready-for-agent")], ["feito 1", "revisa_quebra 1"]);
  assert.ok(!r.noPR("t1") && !r.existe("afk/teste-parcial-1"), "o portão desfaz a iteração inteira");
  assert.doesNotMatch(r.ghLog(), /afk-feito/);
});

test("revisão sem sinal", async () => {
  const r = await roda(1, [issue(1, "OPEN", "ready-for-agent")], ["feito 1", "revisa_mudo 1"]);
  assert.match(r.notas(), /a revisão não terminou/);
  assert.doesNotMatch(r.ghLog(), /afk-feito/);
  assert.ok(!r.noPR("t1") && r.existe("afk/teste-parcial-1:r1"), "tira o ticket do branch do PR");
});

test("revisão com erro de ambiente", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["feito 1", "revisa_erro 1"], { modeloRevisor: "sonnet" });
  assert.equal(r.rodou(), "feito 1 padrão aviso;revisa_erro 1 sonnet");
  assert.equal(r.saida, 2);
  assert.doesNotMatch(r.ghLog(), /afk-feito/);
  assert.ok(!r.noPR("t1") && r.existe("afk/teste-parcial-1:t1"));
});

test("parciais seguidas", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["parcial 1", "parcial 1", "parcial 1"]);
  assert.match(r.ghLog(), /edit 1 --remove-label ready-for-agent/, "devolve para humano na 3ª parcial");
  assert.ok(r.existe("afk/teste-bloqueado-1"));
});

test("merge pelo SHA conferido no portão, não pela ref do ticket", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["foge 1", "revisa 1"]);
  assert.equal(r.feitos(), "1");
  assert.ok(!r.noPR("quebrado") && r.noPR("r1"), "o PR leva o que passou no portão");
});

test("o bundle só leva os branches da rodada", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["intrusa 1", "revisa 1"]);
  assert.equal(r.feitos(), "1");
  const heads = r.g("bundle", "list-heads", ".afk/afk.bundle");
  assert.match(heads, /refs\/heads\/afk\/teste$/m);
  assert.doesNotMatch(heads, /intrusa/);
});

test("worktree registrado fora de .sandcastle/worktrees: o loop para sem tocar na pasta", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["escapa 1", "feito 1", "revisa 1"]);
  assert.equal(r.saida, 2);
  assert.match(r.notas(), /fora de \.sandcastle\/worktrees/);
  assert.ok(existsSync(join(process.env.FAKE!, "alvo", "importante")), "a pasta segue lá");
  assert.equal(r.rodou(), "escapa 1 padrão aviso");
});

// Num git depois do 2.50 (visto no 2.56 do CI), o git que o close() do Sandcastle roda no Mac segue uma
// entrada trocada por symlink e apaga o alvo antes de o loop vê-la. Risco do Sandcastle, aceito no #390.
const [maior, menor] = execFileSync("git", ["--version"], { encoding: "utf8" }).match(/(\d+)\.(\d+)/)!.slice(1).map(Number);
const gitNovo = maior > 2 || (maior === 2 && menor > 50);
for (const [acao, nome] of [["link_entrada", "uma entrada"], ["link_worktrees", "a pasta worktrees"]]) {
  test(`symlink em ${nome} de .git/worktrees: o loop para sem apagar o alvo`, { skip: acao === "link_entrada" && gitNovo }, async () => {
    const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], [`${acao} 1`, "feito 1", "revisa 1"]);
    assert.equal(r.saida, 2);
    assert.match(r.notas(), /não é uma pasta/);
    assert.ok(existsSync(join(process.env.FAKE!, "alvo", "importante")), "o alvo segue lá");
  });
}

test("leCurto: só arquivo regular pequeno, sem travar num FIFO", () => {
  const d = mkdtempSync(join(tmp, "le-"));
  writeFileSync(join(d, "ok"), "/x/.git\n");
  assert.equal(leCurto(join(d, "ok")), "/x/.git\n");
  assert.equal(leCurto(join(d, "nao-existe")), "");
  execFileSync("mkfifo", [join(d, "fifo")]);
  symlinkSync("/dev/zero", join(d, "zero"));
  writeFileSync(join(d, "grande"), "x".repeat(5000));
  for (const f of ["fifo", "zero", "grande"]) assert.throws(() => leCurto(join(d, f)), f);
});

test("a label afk-feito não entra: o ticket não volta para a fila e libera quem ele bloqueia", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent"), issue(2, "OPEN", "ready-for-agent", [1])],
    ["feito 1", "revisa 1", "feito 2", "revisa 2"], { instalar: 'echo afk-feito > "$FAKE/gh-falha"' });
  assert.equal(r.feitos(), "1 2");
  assert.equal(r.rodou(), "feito 1 padrão aviso;revisa 1 opus;feito 2 padrão aviso;revisa 2 opus");
  assert.match(r.notas(), /a label afk-feito não entrou/);
});

test("o gh falha por um tempo ao ler a fila: o loop tenta de novo", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent"), issue(2, "OPEN", "ready-for-agent")],
    ["feito 1", "revisa 1", "feito 2", "revisa 2"], { instalar: 'echo 2 > "$FAKE/graphql-falha"' });
  assert.equal(r.saida, 0);
  assert.equal(r.feitos(), "1 2");
  assert.match(r.notas(), /gh api graphql: gh falso: falha de rede; nova tentativa/);
});

test("um comentário que falha não é repetido", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["parcial 1", "parcial 1", "parcial 1"],
    { instalar: 'echo "Loop AFK" > "$FAKE/gh-falha"' });
  assert.equal(r.ghLog().split("\n").filter((l) => l.startsWith("comment")).length, 1);
  assert.match(r.notas(), /#1: o gh não devolveu o ticket/);
});

test("o gh não devolve o ticket para humano: o loop segue com o próximo", async () => {
  const r = await roda(6, [issue(1, "OPEN", "ready-for-agent"), issue(2, "OPEN", "ready-for-agent")],
    ["parcial 1", "parcial 1", "parcial 1", "feito 2", "revisa 2"], { instalar: 'echo ready-for-human > "$FAKE/gh-falha"' });
  assert.equal(r.saida, 0);
  assert.equal(r.feitos(), "2");
  assert.match(r.notas(), /#1: o gh não devolveu o ticket .*confira à mão/);
  assert.ok(r.existe("afk/teste-bloqueado-1"));
});

test("commit sem portão de uma vaga que não reabriu passa pelo portão depois", async () => {
  const r = await roda(3, [issue(1, "OPEN", "ready-for-agent")], ["estouro_quebra 1", "nada 1", "revisa_nada 1"],
    { corte: 100000, instalar: `f="$FAKE/falha-instalar"; [ ! -e "$f" ] || { rm "$f"; exit 1; }` });
  process.kill(Number(readFileSync(join(process.env.FAKE!, "pid"), "utf8")));
  assert.match(r.notas(), /a vaga não abriu/);
  assert.ok(!r.noPR("quebrado"), "o commit vermelho não entra no PR");
  assert.doesNotMatch(r.ghLog(), /afk-feito/);
});

test("branch de ticket criado antes pelo agente é descartado", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent"), issue(2, "OPEN", "ready-for-agent", [1])],
    ["planta 1", "revisa 1", "feito 2", "revisa 2"]);
  assert.equal(r.feitos(), "1 2");
  assert.ok(r.noPR("t2") && !r.noPR("plantado"));
});

test("nome do branch guardado ocupado pelo agente", async () => {
  const r = await roda(1, [issue(1, "OPEN", "ready-for-agent")], ["ocupa 1"]);
  assert.ok(r.existe("afk/teste-parcial-1:t1-parte"), "o loop guarda o ticket por cima");
  assert.ok(existsSync(join(r.repo, ".afk", "afk.bundle")));
  assert.match(r.g("bundle", "list-heads", ".afk/afk.bundle"), /afk\/teste-parcial-1/);
});

test("branch do PR movido pelo agente: sem bundle", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["sabota 1", "revisa 1"]);
  assert.equal(r.saida, 2);
  assert.match(r.notas(), /o branch do PR mudou fora do integrador/);
  assert.ok(!existsSync(join(r.repo, ".afk", "afk.bundle")));
});

test("vaga que não abre conta como falha da iteração", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["feito 1", "revisa 1"], { instalar: 'case "$PWD" in *afk-t-*) exit 1 ;; esac' });
  assert.equal(r.rodou(), "");
  assert.equal(r.saida, 1, "para depois de 3 falhas seguidas, sem erro do loop");
  assert.equal(r.notas().split("a vaga não abriu").length - 1, 3);
});

test("fila sem tickets elegíveis", async () => {
  const r = await roda(5, [
    issue(1, "OPEN", "ready-for-agent", [], "Bloqueado por: #2"),
    issue(2, "OPEN", "ready-for-human"),
    issue(3, "OPEN", "ready-for-agent", [2]),
  ], []);
  assert.equal(r.rodou(), "");
  assert.equal(r.saida, 0);
  assert.match(r.notas(), /sem_tickets/);
  assert.equal(readFileSync(join(r.repo, ".afk", "fila"), "utf8"), "#1\tespera #2\n#3\tespera #2\n");
});

test("bloqueio por PR: mesclado libera, aberto ou fechado sem merge segura (#87)", async () => {
  const r = await roda(5, [
    issue(1, "OPEN", "ready-for-agent", [], "Bloqueado por: #7"),
    issue(2, "OPEN", "ready-for-agent", [], "Bloqueado por: #8"),
    issue(3, "OPEN", "ready-for-agent", [], "Blocked by: #9"),
    issue(4, "OPEN", "ready-for-agent", [6]),
    issue(6, "OPEN", "ready-for-human"),
    pr(7, "MERGED"), pr(8, "OPEN"), pr(9, "CLOSED"),
  ], ["feito 1", "revisa 1"]);
  assert.equal(r.saida, 0);
  assert.equal(r.feitos(), "1");
  assert.equal(readFileSync(join(r.repo, ".afk", "fila"), "utf8"), "#2\tespera #8\n#3\tespera #9\n#4\tespera #6\n");
});

test("bloqueio por PR sem permissão para ler PRs: anota uma vez e segue com o resto (#87)", async () => {
  const r = await roda(5, [
    issue(1, "OPEN", "ready-for-agent", [], "Bloqueado por: #7"),
    issue(2, "OPEN", "ready-for-agent"),
    issue(3, "OPEN", "ready-for-agent"),
    pr(7, "MERGED"), pr(8, "SEM_PERMISSAO"),
  ], ["feito 2", "revisa 2", "feito 3", "revisa 3"]);
  assert.equal(r.saida, 0);
  assert.equal(r.feitos(), "2 3");
  assert.equal(r.notas().split("não li os PRs mesclados").length - 1, 1, "anota uma vez só");
  assert.equal(r.ghLog().split("\n").filter((l) => l === "pr list").length, 5, "as 5 tentativas do gh, e não mais");
  assert.equal(readFileSync(join(r.repo, ".afk", "fila"), "utf8"), "#1\tespera #7\n");
});

test("sem bloqueio fora das issues, os PRs não são lidos (#87)", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent"), issue(2, "OPEN", "ready-for-agent", [1])],
    ["feito 1", "revisa 1", "feito 2", "revisa 2"]);
  assert.equal(r.feitos(), "1 2");
  assert.doesNotMatch(r.ghLog(), /pr list/);
});

test("PR anterior sem merge", async () => {
  const r = await roda(5, [issue(1, "OPEN", "ready-for-agent,afk-feito")], []);
  assert.equal(r.rodou(), "");
  assert.equal(r.saida, 3);
});

test("sem os emuladores", async () => {
  const antes = process.env.STORAGE_EMULATOR_HOST;
  process.env.STORAGE_EMULATOR_HOST = "";
  try {
    const r = await roda(5, [issue(1, "OPEN", "ready-for-agent")], ["feito 1", "revisa 1"]);
    assert.equal(r.rodou(), "");
    assert.equal(r.saida, 2);
  } finally {
    process.env.STORAGE_EMULATOR_HOST = antes;
  }
});

test("hook de contexto", () => {
  const transcricao = join(tmp, "transcricao.jsonl");
  const uso = (lateral: boolean, tokens: number) =>
    `${JSON.stringify({ type: "assistant", isSidechain: lateral, message: { usage: { input_tokens: 1, cache_read_input_tokens: tokens, cache_creation_input_tokens: 0 } } })}\n`;
  const hook = (aviso?: string) => {
    const env = { ...process.env };
    delete env.AFK_AVISO_TOKENS;
    if (aviso) env.AFK_AVISO_TOKENS = aviso;
    return execFileSync(join(aqui, "hook-contexto.sh"), { input: JSON.stringify({ transcript_path: transcricao }), encoding: "utf8", env });
  };
  writeFileSync(transcricao, uso(false, 50000) + uso(false, 119000) + uso(true, 500000));
  assert.equal(hook("120000"), "", "abaixo do aviso: silêncio");
  writeFileSync(transcricao, readFileSync(transcricao, "utf8") + uso(false, 130000));
  assert.equal(JSON.parse(hook("120000")).decision, "block", "acima do aviso: bloqueia com instrução");
  assert.equal(hook(), "", "fora do loop: silêncio");
});

test("a spec vem da seção Parte de", () => {
  assert.equal(specDe("## Parte de\n\nE1 · Piloto. Esta é a parte de código do #252: o caminho (#253)."), "#252");
  assert.equal(specDe("x\n## Parte de\n\n`docs/design/catalogacao-manual.md` (objetos). Os tipos vêm do #149."), "`docs/design/catalogacao-manual.md`");
  assert.equal(specDe("## Contexto\n\nVeja #3."), "");
});

const duas = { vagas: 2 };
const doisTickets = (corpo = "") => [issue(1, "OPEN", "ready-for-agent", [], corpo), issue(2, "OPEN", "ready-for-agent", [], corpo)];
const ordenado = (s: string) => s.split(" ").sort().join(" ");

test("duas vagas: dois tickets ao mesmo tempo", async () => {
  const r = await roda(5, doisTickets(), ["junto 1", "revisa 1", "junto 2", "revisa 2"], duas);
  assert.equal(r.saida, 0);
  assert.equal(ordenado(r.feitos()), "1 2");
  assert.ok(r.noPR("t1") && r.noPR("r1") && r.noPR("t2") && r.noPR("r2"));
  assert.match(r.notas(), /sem_tickets/);
});

test("duas vagas: dois tickets devolvidos ao mesmo tempo", async () => {
  const r = await roda(4, doisTickets(), ["junto_parcial 1", "junto_parcial 2"], { ...duas, maxParciais: 1 });
  assert.equal(r.saida, 0);
  assert.equal(r.rodou().split(";").length, 2, "nenhum ticket devolvido volta para a fila");
  assert.ok(r.existe("afk/teste-bloqueado-1:t1-parte") && r.existe("afk/teste-bloqueado-2:t2-parte"), "os dois guardados");
  assert.equal(r.ghLog().split("\n").filter((l) => l.startsWith("comment")).length, 2);
});

test("duas vagas: tickets da mesma spec, um depois do outro", async () => {
  const r = await roda(5, doisTickets("## Parte de\n\n#9, a spec."), ["sozinho 1", "revisa 1", "sozinho 2", "revisa 2"], duas);
  assert.equal(ordenado(r.feitos()), "1 2");
  assert.doesNotMatch(r.rodou(), /colidiu/);
});

test("duas vagas: conflito no merge vira uma iteração de merge", async () => {
  const r = await roda(8, doisTickets(), ["comum 1", "revisa 1", "comum 2", "revisa 2", "mescla 1", "mescla 2"], duas);
  assert.equal(r.saida, 0);
  assert.equal(ordenado(r.feitos()), "1 2");
  assert.match(r.notas(), /\(conflito\); a próxima iteração faz o merge/);
  assert.equal(r.rodou().split(";").filter((l) => l.startsWith("mescla")).length, 1);
  assert.equal(r.g("show", "afk/teste:comum"), "junto");
});

test("duas vagas: merge que segue em conflito vai para humano", async () => {
  const r = await roda(8, doisTickets(), ["comum 1", "revisa 1", "comum 2", "revisa 2", "nao_mescla 1", "nao_mescla 2"], duas);
  assert.equal(r.feitos().split(" ").length, 1);
  const humano = r.feitos() === "1" ? "2" : "1";
  assert.match(r.ghLog(), new RegExp(`edit ${humano} --remove-label ready-for-agent --add-label ready-for-human`));
  assert.ok(r.existe(`afk/teste-bloqueado-${humano}:comum`));
});

test("duas vagas: verde sozinho, vermelho junto", async () => {
  const r = await roda(8, doisTickets(), ["cria 1", "revisa 1", "cria 2", "revisa 2", "nao_mescla 1", "nao_mescla 2"],
    { ...duas, verificar: "test ! -e quebrado && ! { test -e c1 && test -e c2; }" });
  assert.match(r.notas(), /make verificar falhou depois do merge/);
  assert.equal(r.feitos().split(" ").length, 1);
  assert.ok(!(r.noPR("c1") && r.noPR("c2")), "o merge vermelho sai do branch do PR");
  const humano = r.feitos() === "1" ? "2" : "1";
  assert.match(r.ghLog(), new RegExp(`edit ${humano} --remove-label ready-for-agent --add-label ready-for-human`));
});

test("duas vagas: make verificar que falha uma vez depois do merge passa ao repetir", async () => {
  const r = await roda(5, doisTickets(), ["junto 1", "revisa 1", "junto 2", "revisa 2"], {
    ...duas,
    verificar: `test ! -e quebrado && { [ "$(git branch --show-current)" != afk/teste ] || [ -e "$FAKE/ja" ] || { touch "$FAKE/ja"; false; }; }`,
  });
  assert.equal(r.saida, 0);
  assert.equal(ordenado(r.feitos()), "1 2");
  assert.match(r.notas(), /make verificar falhou e passou ao repetir/);
  assert.doesNotMatch(r.notas(), /falhou depois do merge/);
});

test("duas vagas: make verificar que reescreve um arquivo no integrador não dá alarme falso", async () => {
  const r = await roda(8, [...doisTickets(), issue(3, "OPEN", "ready-for-agent", [1, 2])],
    ["junto 1", "revisa 1", "junto 2", "revisa 2", "feito 3", "revisa 3"],
    { ...duas, verificar: 'test ! -e quebrado && if [ "$(git branch --show-current)" = afk/teste ]; then echo sujo >> .gitignore; fi' });
  assert.equal(r.saida, 0);
  assert.equal(ordenado(r.feitos()), "1 2 3");
  assert.doesNotMatch(r.notas(), /mudou fora do integrador/);
});

test("duas vagas: os metadados de uma vaga viva sobrevivem à criação de outra (#849)", async () => {
  const r = await roda(5, doisTickets(), ["estraga 1", "revisa 1", "depois_do_estraga 2", "marca 2", "revisa 2"], duas);
  assert.equal(ordenado(r.feitos()), "1 2");
  assert.ok(r.noPR("t1"));
});
