import { IconChartBar, IconTable } from "@tabler/icons-react";
import { cn } from "cn";
import {
  Fragment,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { rotuloDoGrupo, type Agrupamento } from "../../painelDaDiretoria.ts";
import { numero } from "./formato.ts";

// As peças do painel da diretoria: seção, indicador, tabela e os gráficos (docs/design/MAM_DESIGN_SYSTEM.md, seção 11).

/** Um painel com cabeçalho; o título nomeia a região para o leitor de tela. */
export function Secao({
  titulo,
  descricao,
  acoes,
  largo = false,
  children,
}: {
  titulo: string;
  descricao?: string;
  acoes?: ReactNode;
  /** Ocupa a linha inteira da grade (as séries no tempo). */
  largo?: boolean;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      className={cn(
        "flex min-w-0 flex-col rounded-sm border bg-background",
        largo && "lg:col-span-2",
      )}
    >
      <header className="flex min-h-10 flex-wrap items-center gap-2 border-b px-3 py-2">
        <div className="min-w-0 flex-1">
          <h2 id={id} className="text-sm font-semibold">
            {titulo}
          </h2>
          {descricao && (
            <p className="text-xs text-muted-foreground">{descricao}</p>
          )}
        </div>
        {acoes}
      </header>
      <div className="min-w-0 p-3">{children}</div>
    </section>
  );
}

/** Os números do período, em cartões que se ajustam à largura. */
export function Indicadores({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-3">
      {children}
    </div>
  );
}

/** O rótulo e, logo depois, o valor. */
export function Indicador({
  rotulo,
  valor,
}: {
  rotulo: string;
  valor: number | string;
}) {
  const texto = typeof valor === "number" ? numero(valor) : valor;
  return (
    <div className="min-w-0 rounded-sm border bg-background px-3 py-2.5">
      <p className="truncate text-xs text-muted-foreground" title={rotulo}>
        {rotulo}
      </p>
      <p className="mt-0.5 truncate text-xl font-semibold" title={texto}>
        {texto}
      </p>
    </div>
  );
}

export interface LinhaDaTabela {
  chave: string;
  celulas: ReactNode[];
  /** Uma linha a mais, sob esta, na largura da tabela (o detalhe que abre). */
  detalhe?: ReactNode;
}

/** Tabela de números: a primeira coluna é o nome, as outras alinham à direita. Larga demais, rola dentro da caixa. */
export function Tabela({
  rotulo,
  colunas,
  linhas,
  minimo = colunas.length * 104,
}: {
  rotulo: string;
  colunas: string[];
  linhas: LinhaDaTabela[];
  minimo?: number;
}) {
  return (
    <div className="overflow-x-auto">
      <table
        aria-label={rotulo}
        className="w-full text-sm"
        style={{ minWidth: minimo }}
      >
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            {colunas.map((c, i) => (
              <th
                key={c}
                scope="col"
                className={cn(
                  "h-8 px-2 font-semibold first:pl-0 last:pr-0",
                  i === 0 ? "text-left" : "text-right",
                )}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {linhas.map((l) => (
            <Fragment key={l.chave}>
              <tr
                className={cn(
                  "h-8 hover:bg-card",
                  !l.detalhe && "border-b border-border/60 last:border-b-0",
                )}
              >
                {l.celulas.map((c, i) => (
                  <td
                    key={i}
                    className={cn(
                      "px-2 first:pl-0 last:pr-0",
                      i === 0
                        ? "min-w-32 text-left [overflow-wrap:anywhere]"
                        : "text-right whitespace-nowrap",
                    )}
                  >
                    {c}
                  </td>
                ))}
              </tr>
              {l.detalhe && (
                <tr className="border-b border-border/60 last:border-b-0">
                  <td colSpan={colunas.length} className="pb-3 pl-3">
                    {l.detalhe}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Visao = "grafico" | "tabela";

function AlternarVisao({
  visao,
  aoMudar,
}: {
  visao: Visao;
  aoMudar: (v: Visao) => void;
}) {
  const opcoes = [
    ["grafico", "Gráfico", IconChartBar],
    ["tabela", "Tabela", IconTable],
  ] as const;
  return (
    <div
      role="group"
      aria-label="Exibir como"
      className="flex h-7 items-center rounded-sm border border-strong p-0.5"
    >
      {opcoes.map(([v, rotulo, Icone]) => (
        <button
          key={v}
          type="button"
          aria-pressed={visao === v}
          onClick={() => aoMudar(v)}
          className={cn(
            "flex h-full items-center gap-1.5 rounded-xs px-2 text-xs",
            visao === v
              ? "bg-selected text-link"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icone size={14} stroke={1.75} aria-hidden /> {rotulo}
        </button>
      ))}
    </div>
  );
}

/** Toda visualização troca para a tabela, que é também a forma acessível de ler os números. */
export function GraficoOuTabela({
  titulo,
  descricao,
  largo,
  grafico,
  tabela,
}: {
  titulo: string;
  descricao?: string;
  largo?: boolean;
  grafico: ReactNode;
  tabela: ReactNode;
}) {
  const [visao, setVisao] = useState<Visao>("grafico");
  return (
    <Secao
      titulo={titulo}
      descricao={descricao}
      largo={largo}
      acoes={<AlternarVisao visao={visao} aoMudar={setVisao} />}
    >
      {visao === "grafico" ? grafico : tabela}
    </Secao>
  );
}

const TICK = { fill: "var(--color-muted-foreground)", fontSize: 11 };

/** O eixo do valor em forma curta ("1,2 mil"); a dica e a tabela dão o número inteiro. */
const curto = new Intl.NumberFormat("pt-BR", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** A dica do gráfico: o nome em 600 e o número, sobre a superfície sobreposta. */
function Dica({ titulo, valor }: { titulo: string; valor: string }) {
  return (
    <div className="rounded-sm border bg-popover px-2 py-1.5 text-xs shadow-float">
      <p className="font-semibold">{titulo}</p>
      <p className="text-muted-foreground">{valor}</p>
    </div>
  );
}

interface PontoNoTempo {
  dia: string;
}

/**
 * Uma série no tempo, já somada pelo servidor (até ~90 pontos com `agrupar=auto`): barra para
 * contagem, linha para evolução. O `aria-label` lê os pontos; a tabela ao lado é a leitura completa.
 */
export function SerieNoTempo<T extends PontoNoTempo>({
  rotulo,
  dados,
  valor,
  agrupamento,
  forma = "barra",
  formato = numero,
}: {
  rotulo: string;
  dados: T[];
  valor: (ponto: T) => number;
  agrupamento: Agrupamento;
  forma?: "barra" | "linha";
  formato?: (n: number) => string;
}) {
  const [ref, visivel] = useVisivel();
  const pontos = dados.map((d) => ({ dia: d.dia, valor: valor(d) }));
  const resumo = `${rotulo}: ${pontos.map((p) => `${rotuloDoGrupo(p.dia, agrupamento, true)}, ${formato(p.valor)}`).join("; ")}`;
  const eixos = (
    <>
      <CartesianGrid vertical={false} stroke="var(--color-border)" />
      <XAxis
        dataKey="dia"
        tickLine={false}
        axisLine={false}
        minTickGap={16}
        tick={TICK}
        tickFormatter={(d: string) => rotuloDoGrupo(d, agrupamento, true)}
      />
      <YAxis
        width={48}
        tickLine={false}
        axisLine={false}
        tick={TICK}
        tickFormatter={(n: number) => curto.format(n)}
      />
      <Tooltip
        cursor={
          forma === "barra"
            ? { fill: "var(--color-card)" }
            : { stroke: "var(--color-strong)" }
        }
        isAnimationActive={false}
        content={({ active, payload, label }) =>
          active && payload?.length ? (
            <Dica
              titulo={rotuloDoGrupo(String(label), agrupamento)}
              valor={`${rotulo}: ${formato(Number(payload[0].value))}`}
            />
          ) : null
        }
      />
    </>
  );
  return (
    <div
      ref={ref}
      role="img"
      aria-label={resumo}
      className="h-[200px] w-full min-w-0"
    >
      {visivel && (
        <ResponsiveContainer width="100%" height="100%">
          {forma === "barra" ? (
            <BarChart
              data={pontos}
              margin={{ left: 0, right: 4, top: 8, bottom: 0 }}
            >
              {eixos}
              <Bar
                dataKey="valor"
                fill="var(--color-primary)"
                activeBar={{ fill: "var(--color-link)" }}
                radius={[2, 2, 0, 0]}
                maxBarSize={32}
                isAnimationActive={false}
              />
            </BarChart>
          ) : (
            <LineChart
              data={pontos}
              margin={{ left: 0, right: 8, top: 8, bottom: 0 }}
            >
              {eixos}
              <Line
                dataKey="valor"
                type="linear"
                stroke="var(--color-primary)"
                strokeWidth={2}
                dot={pontos.length <= 31}
                activeDot={{ r: 4, fill: "var(--color-link)" }}
                isAnimationActive={false}
              />
            </LineChart>
          )}
        </ResponsiveContainer>
      )}
    </div>
  );
}

/**
 * Monta o gráfico só quando a caixa chega perto da tela. Uma aba cheia tem até sete gráficos, e
 * montar todos de uma vez passava de 200 ms num computador lento. Sem IntersectionObserver, monta logo.
 */
function useVisivel() {
  const ref = useRef<HTMLDivElement>(null);
  const [visivel, setVisivel] = useState(
    typeof IntersectionObserver === "undefined",
  );
  useEffect(() => {
    const el = ref.current;
    if (visivel || !el) return;
    const observador = new IntersectionObserver(
      (e) => e.some((x) => x.isIntersecting) && setVisivel(true),
      { rootMargin: "200px" },
    );
    observador.observe(el);
    return () => observador.disconnect();
  }, [visivel]);
  return [ref, visivel] as const;
}

const MAIS_NO_RANKING = 15;
const ALTURA_DA_BARRA = 16;
const VAO = 4;

/** Ranking horizontal de uma série: as 15 maiores, o nome à esquerda e o valor na ponta. O resto fica na tabela. */
export function Ranking({
  rotulo,
  dados,
  formato = numero,
  escolhido,
  aoEscolher,
}: {
  rotulo: string;
  dados: { id?: string; nome: string; valor: number }[];
  formato?: (n: number) => string;
  /** A barra em destaque (a linha aberta na tabela) e o que o clique numa barra faz; os dois juntos. */
  escolhido?: string | null;
  aoEscolher?: (id: string) => void;
}) {
  const [ref, visivel] = useVisivel();
  const primeiros = [...dados]
    .sort((a, b) => b.valor - a.valor)
    .slice(0, MAIS_NO_RANKING)
    // A cor vai no dado: o recharts pinta a barra com o `fill` de cada item.
    .map((d) => ({
      ...d,
      fill:
        d.id !== undefined && d.id === escolhido
          ? "var(--color-link)"
          : "var(--color-primary)",
    }));
  const resumo = `${rotulo}: ${primeiros.map((d) => `${d.nome}, ${formato(d.valor)}`).join("; ")}`;
  return (
    <div
      ref={ref}
      role="img"
      aria-label={resumo}
      className="w-full min-w-0"
      style={{ height: primeiros.length * (ALTURA_DA_BARRA + VAO * 2) + 8 }}
    >
      {visivel && (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={primeiros}
            layout="vertical"
            margin={{ left: 0, right: 72, top: 4, bottom: 4 }}
          >
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="nome"
              width={150}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "var(--color-foreground)", fontSize: 12 }}
              tickFormatter={(n: string) =>
                n.length > 19 ? `${n.slice(0, 18)}…` : n
              }
            />
            <Tooltip
              cursor={{ fill: "var(--color-card)" }}
              isAnimationActive={false}
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <Dica
                    titulo={String(payload[0].payload.nome)}
                    valor={formato(Number(payload[0].value))}
                  />
                ) : null
              }
            />
            <Bar
              dataKey="valor"
              fill="var(--color-primary)"
              activeBar={{ fill: "var(--color-link)" }}
              radius={[0, 2, 2, 0]}
              barSize={ALTURA_DA_BARRA}
              isAnimationActive={false}
              cursor={aoEscolher ? "pointer" : undefined}
              onClick={(d: { id?: string }) =>
                d.id !== undefined && aoEscolher?.(d.id)
              }
            >
              <LabelList
                dataKey="valor"
                position="right"
                formatter={(v: unknown) => formato(Number(v))}
                fill="var(--color-muted-foreground)"
                fontSize={12}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
