import {
  IconApi,
  IconChartBar,
  IconCoin,
  IconEdit,
  IconLogin2,
  IconMovie,
  IconSearch,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "cn";
import {
  useId,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import {
  PedidoInvalido,
  SessaoExpirada,
  codigoDoErro,
  type ClienteDaApi,
} from "../../api.ts";
import { periodoInvertido } from "../../auditoria.ts";
import {
  ABAS_DO_PAINEL,
  programaEUsuarioJuntos,
  type AbaDoPainel,
  type FiltrosDoPainel,
  type PedidoDeAgrupamento,
  type RelatorioDeAcessos,
  type RelatorioDeApi,
  type RelatorioDeBuscas,
  type RelatorioDeCusto,
  type RelatorioDeRevisao,
  type RelatorioDeVideos,
} from "../../painelDaDiretoria.ts";
import { enderecoDoPainel, navegar } from "../../rotas.ts";
import { Falha } from "../comum/Falha.tsx";
import { CAMPO, mensagemDoErro } from "../comum/relatorio.ts";
import { BaixarCsv, Campo } from "../comum/relatorio.tsx";
import { useApi } from "../consultas.ts";
import {
  Acessos,
  Api,
  Buscas,
  Custo,
  FilaAgora,
  Revisao,
  Videos,
} from "./abas.tsx";
import { NOTA_DO_DIA, revisaoVazia } from "./formato.ts";

/** O que cada aba pede à API, o arquivo do CSV, quando está vazia, a nota e o conteúdo. */
interface DefinicaoDaAba<T> {
  buscar: (
    api: ClienteDaApi,
    f: FiltrosDoPainel,
    agrupar: PedidoDeAgrupamento,
  ) => Promise<T>;
  csv: (api: ClienteDaApi, f: FiltrosDoPainel) => Promise<Blob>;
  vazio: (r: T) => boolean;
  nota: string;
  mostrar: (r: T) => ReactNode;
  /** Programa e usuário juntos não se combinam nesta aba. */
  exclusivos?: boolean;
  semPrograma?: boolean;
}

const definir = <T,>(d: DefinicaoDaAba<T>) => d as DefinicaoDaAba<unknown>;

const ABAS: Record<AbaDoPainel, DefinicaoDaAba<unknown>> = {
  acessos: definir<Awaited<ReturnType<ClienteDaApi["acessosDoPainel"]>>>({
    buscar: (api, f, agrupar) => api.acessosDoPainel(f, agrupar),
    csv: (api, f) => api.acessosDoPainelEmCsv(f),
    vazio: (r: RelatorioDeAcessos) => r.por_dia.length === 0,
    nota: `Logins não têm programa: o filtro de programa vale para as outras abas. ${NOTA_DO_DIA} A primeira e a última semana ou mês contam só os dias do período.`,
    mostrar: (r) => <Acessos relatorio={r} />,
    semPrograma: true,
  }),
  videos: definir<Awaited<ReturnType<ClienteDaApi["videosDoPainel"]>>>({
    buscar: (api, f, agrupar) => api.videosDoPainel(f, agrupar),
    csv: (api, f) => api.videosDoPainelEmCsv(f),
    vazio: (r: RelatorioDeVideos) => r.por_dia.length === 0,
    nota: `Os vídeos de sistemas entram junto com os das pessoas. O tempo de processamento é o dos concluídos, do registro ao fim. Com um programa escolhido não há quebra por usuário, e com um usuário não há por programa. ${NOTA_DO_DIA}`,
    mostrar: (r) => <Videos relatorio={r} />,
    exclusivos: true,
  }),
  buscas: definir<Awaited<ReturnType<ClienteDaApi["buscasDoPainel"]>>>({
    buscar: (api, f, agrupar) => api.buscasDoPainel(f, agrupar),
    csv: (api, f) => api.buscasDoPainelEmCsv(f),
    vazio: (r: RelatorioDeBuscas) => r.por_dia.length === 0,
    nota: `Busca sem resultado é a que não trouxe nenhum vídeo; as feitas antes de o sistema contar isso não entram nela. A busca só tem programa quando foi filtrada por ele, e então não se sabe quem buscou. ${NOTA_DO_DIA}`,
    mostrar: (r) => <Buscas relatorio={r} />,
    exclusivos: true,
  }),
  revisao: definir<Awaited<ReturnType<ClienteDaApi["revisaoDoPainel"]>>>({
    buscar: (api, f, agrupar) => api.revisaoDoPainel(f, agrupar),
    csv: (api, f) => api.revisaoDoPainelEmCsv(f),
    vazio: (r: RelatorioDeRevisao) => revisaoVazia(r),
    nota: `A taxa de correção não tem pessoa: com um usuário escolhido ela some. Os minutos de revisão são o acumulado das medidas cujo último pulso cai no período. ${NOTA_DO_DIA}`,
    mostrar: (r) => <Revisao relatorio={r} />,
  }),
  api: definir<Awaited<ReturnType<ClienteDaApi["apiDoPainel"]>>>({
    buscar: (api, f, agrupar) => api.apiDoPainel(f, agrupar),
    csv: (api, f) => api.apiDoPainelEmCsv(f),
    vazio: (r: RelatorioDeApi) =>
      r.por_dia.length === 0 && r.por_sistema.length === 0,
    nota: `A chamada não tem programa: o filtro de programa vale para as outras abas. O filtro de usuário escolhe o sistema. Vídeos enviados pela API são só os de sistemas. ${NOTA_DO_DIA}`,
    mostrar: (r) => <Api relatorio={r} />,
    semPrograma: true,
  }),
  custo: definir<RelatorioDeCusto>({
    buscar: (api, f) => api.custoDoPainel(f),
    csv: (api, f) => api.custoDoPainelEmCsv(f),
    vazio: (r) => r.por_mes.length === 0 && r.sem_dono_por_servico.length === 0,
    nota: "O custo é o da exportação do faturamento, líquido de créditos. O custo de um vídeo conta no mês em que ele foi enviado; as horas e o custo por hora são só dos concluídos. O que não tem dono (a réplica do índice, os Jobs do Cloud Run, a busca) só entra sem filtro de programa ou de usuário. O faturamento chega com atraso de horas.",
    mostrar: (r) => <Custo relatorio={r} />,
  }),
};

const ICONES: Record<AbaDoPainel, typeof IconLogin2> = {
  acessos: IconLogin2,
  videos: IconMovie,
  buscas: IconSearch,
  revisao: IconEdit,
  api: IconApi,
  custo: IconCoin,
};

const AGRUPAMENTOS: { valor: PedidoDeAgrupamento; rotulo: string }[] = [
  { valor: "auto", rotulo: "Automático" },
  { valor: "dia", rotulo: "Por dia" },
  { valor: "semana", rotulo: "Por semana" },
  { valor: "mes", rotulo: "Por mês" },
  { valor: "trimestre", rotulo: "Por trimestre" },
];

function Filtros({
  filtros,
  comPrograma,
  aoMudar,
}: {
  filtros: FiltrosDoPainel;
  comPrograma: boolean;
  aoMudar: (parte: Partial<FiltrosDoPainel>) => void;
}) {
  const api = useApi();
  const opcoes = useQuery({
    queryKey: ["painel", "opcoes"],
    queryFn: () => api.opcoesDoPainel(),
    staleTime: 5 * 60_000,
  });
  const programas = opcoes.data?.programas ?? [];
  const usuarios = opcoes.data?.usuarios ?? [];
  const programa = comPrograma ? filtros.programa : "";
  return (
    <>
      <Campo rotulo="Programa">
        {(id) => (
          <select
            id={id}
            aria-label="Programa"
            className={cn(CAMPO, "w-48")}
            disabled={!comPrograma}
            value={programa}
            onChange={(e) => aoMudar({ programa: e.target.value })}
          >
            <option value="">Todos os programas</option>
            {/* O programa do endereço que não está na lista continua escolhido. */}
            {programa && !programas.includes(programa) && (
              <option value={programa}>{programa}</option>
            )}
            {programas.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        )}
      </Campo>
      <Campo rotulo="Usuário">
        {(id) => (
          <select
            id={id}
            aria-label="Usuário"
            className={cn(CAMPO, "w-56")}
            value={filtros.usuario}
            onChange={(e) => aoMudar({ usuario: e.target.value })}
          >
            <option value="">Todos os usuários</option>
            {filtros.usuario &&
              !usuarios.some((u) => u.uid === filtros.usuario) && (
                <option value={filtros.usuario}>{filtros.usuario}</option>
              )}
            {usuarios.map((u) => (
              <option key={u.uid} value={u.uid}>
                {u.email ?? u.uid}
              </option>
            ))}
          </select>
        )}
      </Campo>
      <Campo rotulo="De">
        {(id) => (
          <input
            id={id}
            type="date"
            aria-label="De"
            className={CAMPO}
            value={filtros.de}
            onChange={(e) => aoMudar({ de: e.target.value })}
          />
        )}
      </Campo>
      <Campo rotulo="Até">
        {(id) => (
          <input
            id={id}
            type="date"
            aria-label="Até"
            className={CAMPO}
            value={filtros.ate}
            onChange={(e) => aoMudar({ ate: e.target.value })}
          />
        )}
      </Campo>
    </>
  );
}

/** Troca de aba sem empilhar no histórico, como na interface antiga; com modificador, abre noutra aba do navegador. */
function trocarDeAba(e: MouseEvent<HTMLAnchorElement>, destino: string) {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
    return;
  e.preventDefault();
  navegar(destino, { substituir: true });
}

/**
 * As setas, Home e End movem o foco entre as abas e já abrem a escolhida, como nas abas da
 * interface antiga; só a aba ativa entra na ordem do Tab (tabindex móvel).
 */
function moverComTeclado(e: KeyboardEvent<HTMLDivElement>) {
  const abas = [
    ...e.currentTarget.querySelectorAll<HTMLAnchorElement>('[role="tab"]'),
  ];
  const atual = abas.indexOf(document.activeElement as HTMLAnchorElement);
  if (atual < 0) return;
  const destinos: Record<string, number> = {
    ArrowRight: atual + 1,
    ArrowLeft: atual - 1 + abas.length,
    Home: 0,
    End: abas.length - 1,
  };
  if (!(e.key in destinos)) return;
  e.preventDefault();
  const alvo = abas[destinos[e.key] % abas.length];
  alvo.focus();
  navegar(alvo.getAttribute("href") ?? "", { substituir: true });
}

/** O painel da diretoria (`/painel/<aba>`): filtros no endereço, uma aba por relatório, CSV em cada uma. */
export default function PainelDaDiretoria({
  aba,
  filtros,
}: {
  aba: AbaDoPainel;
  filtros: FiltrosDoPainel;
}) {
  const api = useApi();
  const [agrupar, setAgrupar] = useState<PedidoDeAgrupamento>("auto");
  const definicao = ABAS[aba];
  const idDaAba = useId();

  const periodo = periodoInvertido(filtros)
    ? { mensagem: "O período começa depois de terminar.", codigo: "periodo" }
    : null;
  const juntos =
    definicao.exclusivos && programaEUsuarioJuntos(filtros)
      ? {
          mensagem: "Escolha o programa ou o usuário, não os dois.",
          codigo: "filtros",
        }
      : null;
  const bloqueio = periodo ?? juntos;
  const grupo = aba === "custo" ? null : agrupar;

  const relatorio = useQuery({
    queryKey: ["painel", aba, filtros, grupo],
    queryFn: () => definicao.buscar(api, filtros, agrupar),
    enabled: bloqueio === null,
    retry: (falhas, erro) =>
      !(erro instanceof SessaoExpirada) &&
      !(erro instanceof PedidoInvalido) &&
      falhas < 2,
  });

  function mudar(parte: Partial<FiltrosDoPainel>) {
    navegar(enderecoDoPainel(aba, { ...filtros, ...parte }), {
      substituir: true,
    });
  }

  return (
    <div className="mx-auto grid w-full max-w-[1600px] content-start gap-3 p-3 md:p-4">
      <div className="flex items-center gap-2">
        <IconChartBar
          size={20}
          stroke={1.75}
          className="text-muted-foreground"
          aria-hidden
        />
        <h1 className="text-xl font-semibold">Painel da diretoria</h1>
      </div>

      <div
        role="tablist"
        aria-label="Abas do painel"
        className="grid grid-cols-3 border-b sm:flex"
        onKeyDown={moverComTeclado}
      >
        {ABAS_DO_PAINEL.map((a) => {
          const Icone = ICONES[a.chave];
          const ativa = a.chave === aba;
          const destino = enderecoDoPainel(a.chave, filtros);
          return (
            <a
              key={a.chave}
              id={ativa ? idDaAba : undefined}
              role="tab"
              aria-selected={ativa}
              tabIndex={ativa ? 0 : -1}
              href={destino}
              onClick={(e) => trocarDeAba(e, destino)}
              className={cn(
                "relative flex h-9 shrink-0 items-center gap-1.5 px-2 text-sm whitespace-nowrap sm:px-3",
                ativa
                  ? "font-semibold text-foreground after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:bg-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icone size={16} stroke={1.75} aria-hidden /> {a.rotulo}
            </a>
          );
        })}
      </div>

      <div
        role="tabpanel"
        aria-labelledby={idDaAba}
        className="grid min-w-0 gap-3"
      >
        <div className="flex flex-wrap items-end gap-3">
          <Filtros
            filtros={filtros}
            comPrograma={!definicao.semPrograma}
            aoMudar={mudar}
          />
          <Campo rotulo="Agrupar">
            {(id) => (
              <select
                id={id}
                aria-label="Agrupar"
                title={
                  aba === "custo" ? "O custo vem sempre por mês." : undefined
                }
                className={cn(CAMPO, "w-36")}
                disabled={aba === "custo"}
                value={aba === "custo" ? "mes" : agrupar}
                onChange={(e) =>
                  setAgrupar(e.target.value as PedidoDeAgrupamento)
                }
              >
                {AGRUPAMENTOS.map((g) => (
                  <option key={g.valor} value={g.valor}>
                    {g.rotulo}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <BaixarCsv
            key={aba}
            arquivo={`${aba}.csv`}
            pedir={() => definicao.csv(api, filtros)}
            desligado={
              bloqueio !== null ||
              !relatorio.data ||
              definicao.vazio(relatorio.data)
            }
          />
        </div>
        <p className="max-w-[110ch] text-xs text-muted-foreground">
          {definicao.nota}
        </p>

        {aba === "videos" && <FilaAgora />}
        {bloqueio && (
          <Falha mensagem={bloqueio.mensagem} codigo={bloqueio.codigo} />
        )}
        {!bloqueio && relatorio.isPending && (
          <p
            role="status"
            aria-label="Montando o painel"
            className="py-6 text-center text-sm text-muted-foreground"
          >
            Montando o painel…
          </p>
        )}
        {!bloqueio && relatorio.isError && (
          <Falha
            mensagem={mensagemDoErro(relatorio.error)}
            codigo={codigoDoErro(relatorio.error)}
            aoTentar={() => void relatorio.refetch()}
          />
        )}
        {!bloqueio &&
          relatorio.data !== undefined &&
          definicao.mostrar(relatorio.data)}
      </div>
    </div>
  );
}
