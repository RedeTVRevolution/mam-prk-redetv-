import { IconUserScan } from "@tabler/icons-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { codigoDoErro } from "../../api.ts";
import { enderecoDoTempoDeTela, enderecoDoVideo, navegar, seguir } from "../../rotas.ts";
import {
  duracaoLegivel,
  type FiltrosDoRelatorio,
  type PessoaResumida,
} from "../../tempoDeTela.ts";
import { Falha } from "../comum/Falha.tsx";
import { mensagemDoErro, repetirFalha } from "../comum/relatorio.ts";
import { BaixarCsv } from "../comum/relatorio.tsx";
import { useApi } from "../consultas.ts";
import { numero } from "../painel/formato.ts";
import {
  GraficoOuTabela,
  Indicador,
  Indicadores,
  Ranking,
  Secao,
  Tabela,
} from "../painel/pecas.tsx";
import { Button } from "../ui/button.tsx";
import {
  AvisoDaConsulta,
  BotaoDaLinha,
  ComBarra,
  FiltrosDoPeriodo,
  Paginacao,
} from "./comuns.tsx";
import { useTabelaPaginada } from "./pilha.ts";

// O relatório de tempo de tela (`/relatorios/tempo-de-tela`): o ranking vem de 50 em 50 pessoas com
// cursor, e os vídeos de cada pessoa só quando a linha abre.

// As cores de série do design system (2.6), na ordem da divisão.
const SERIES = [
  ["Aparições", "bg-chart-1", (p: PessoaResumida) => p.aparicoes],
  ["Menções na fala", "bg-chart-2", (p: PessoaResumida) => p.mencoes_na_fala],
  ["Menções no texto", "bg-chart-3", (p: PessoaResumida) => p.mencoes_no_texto],
] as const;

/** Uma faixa com a divisão em partes proporcionais e a contagem de cada uma logo abaixo. */
function Divisao({ pessoa }: { pessoa: PessoaResumida }) {
  const partes = SERIES.map(([nome, cor, valor]) => ({ nome, cor, valor: valor(pessoa) }));
  const total = partes.reduce((soma, p) => soma + p.valor, 0);
  return (
    <div role="img" aria-label={`Divisão por tipo de ${pessoa.nome}`} className="grid gap-2">
      <div className="flex h-4 gap-0.5">
        {total === 0 && <div className="h-4 w-full rounded-xs border" />}
        {partes
          .filter((p) => p.valor > 0)
          .map((p) => (
            <div
              key={p.nome}
              className={`h-4 rounded-xs ${p.cor}`}
              style={{ flexGrow: p.valor, flexBasis: 0 }}
            />
          ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {partes.map((p) => (
          <div key={p.nome} className="flex items-center gap-1.5 text-xs">
            <span aria-hidden className={`size-2 rounded-xs ${p.cor}`} />
            <span className="text-muted-foreground">{p.nome}</span>
            <span className="font-semibold tabular-nums">{p.valor}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function useRanking(filtros: FiltrosDoRelatorio, cursor: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["relatorios", "tempo-de-tela", filtros, cursor],
    queryFn: () => api.rankingDoTempoDeTela(filtros, cursor),
    retry: repetirFalha,
  });
}

/** Os vídeos da pessoa, pedidos quando a linha abre (existe só enquanto ela está aberta), 25 por vez. */
function Videos({ filtros, pessoa }: { filtros: FiltrosDoRelatorio; pessoa: PessoaResumida }) {
  const api = useApi();
  const consulta = useInfiniteQuery({
    queryKey: ["relatorios", "tempo-de-tela", "videos", filtros, pessoa.pessoa_id],
    queryFn: ({ pageParam }) => api.videosDaPessoa(filtros, pessoa.pessoa_id, pageParam),
    initialPageParam: "",
    getNextPageParam: (ultima) => ultima.proximo ?? undefined,
    retry: repetirFalha,
  });
  if (consulta.isError) {
    return (
      <Falha
        mensagem={mensagemDoErro(consulta.error)}
        codigo={codigoDoErro(consulta.error)}
        aoTentar={() => void consulta.refetch()}
      />
    );
  }
  if (!consulta.data) {
    return (
      <p role="status" className="py-2 text-xs text-muted-foreground">
        Carregando os vídeos…
      </p>
    );
  }
  const videos = consulta.data.pages.flatMap((p) => p.videos);
  return (
    <div className="grid gap-2">
      <Tabela
        rotulo={`Vídeos de ${pessoa.nome}`}
        colunas={["Vídeo", "Tempo de tela", "Aparições", "Na fala", "No texto"]}
        linhas={videos.map((v, n) => ({
          // O mesmo vídeo não repete numa pessoa, mas a posição não custa nada.
          chave: `${n}-${v.job_id}`,
          celulas: [
            <a
              key="v"
              href={enderecoDoVideo(v.job_id)}
              onClick={(e) => seguir(e, enderecoDoVideo(v.job_id))}
              className="text-link hover:underline"
            >
              {v.nome ?? v.job_id}
            </a>,
            duracaoLegivel(v.tempo_de_tela_ms),
            `${v.aparicoes} aparições`,
            `${v.mencoes_na_fala} na fala`,
            `${v.mencoes_no_texto} no texto`,
          ],
        }))}
      />
      {consulta.hasNextPage && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="justify-self-start"
          disabled={consulta.isFetchingNextPage}
          onClick={() => void consulta.fetchNextPage()}
        >
          Ver mais vídeos
        </Button>
      )}
    </div>
  );
}

/** "Relatórios › Tempo de tela": só aparições somam; as menções ficam em colunas à parte. */
export default function TempoDeTela({ filtros }: { filtros: FiltrosDoRelatorio }) {
  const api = useApi();
  const tabela = useTabelaPaginada(JSON.stringify(filtros));
  const primeira = useRanking(filtros, "");
  const atual = useRanking(filtros, tabela.cursor);

  function mudar(parte: Partial<FiltrosDoRelatorio>) {
    navegar(enderecoDoTempoDeTela({ ...filtros, ...parte }), { substituir: true });
  }

  const resumo = primeira.data;
  const vazio = resumo?.pessoas.length === 0;
  const pagina = atual.data;
  const emFoco =
    [...(resumo?.pessoas ?? []), ...(pagina?.pessoas ?? [])].find((p) => p.pessoa_id === tabela.aberta) ??
    resumo?.pessoas[0];
  const maximo = Math.max(0, ...(pagina?.pessoas ?? []).map((p) => p.tempo_de_tela_ms));
  useEffect(() => {
    if (tabela.aberta) document.getElementById(`pessoa-${tabela.aberta}`)?.scrollIntoView({ block: "nearest" });
  }, [tabela.aberta]);

  return (
    <div className="mx-auto grid w-full max-w-[1600px] content-start gap-3 p-3 md:p-4">
      <div className="flex items-center gap-2">
        <IconUserScan size={20} stroke={1.75} className="text-muted-foreground" aria-hidden />
        <h1 className="text-xl font-semibold">Tempo de tela</h1>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <FiltrosDoPeriodo filtros={filtros} aoMudar={mudar} />
        <BaixarCsv
          key={JSON.stringify(filtros)}
          arquivo="tempo-de-tela.csv"
          pedir={() => api.tempoDeTelaEmCsv(filtros)}
          desligado={!resumo || vazio === true}
        />
      </div>
      <p className="max-w-[110ch] text-xs text-muted-foreground">
        Só aparições somam tempo de tela. Menções na fala e no texto da tela são só contagem.
      </p>

      <AvisoDaConsulta consulta={primeira} espera="Montando o relatório" />
      {vazio && <p className="text-sm">Nenhuma pessoa com aparição ou menção neste filtro.</p>}

      {resumo && !vazio && emFoco && (
        <>
          <section aria-label="Resumo do período">
            <Indicadores>
              <Indicador rotulo="Pessoas" valor={resumo.total.pessoas} />
              <Indicador rotulo="Tempo de tela" valor={duracaoLegivel(resumo.total.tempo_de_tela_ms)} />
              <Indicador rotulo="Vídeos" valor={resumo.total.videos} />
              <Indicador rotulo="Aparições" valor={resumo.total.aparicoes} />
              <Indicador rotulo="Menções na fala" valor={resumo.total.mencoes_na_fala} />
              <Indicador rotulo="Menções no texto" valor={resumo.total.mencoes_no_texto} />
            </Indicadores>
          </section>
          <div className="grid items-start gap-3 lg:grid-cols-[3fr_2fr]">
            <GraficoOuTabela
              titulo="Pessoas com mais tempo de tela"
              descricao="As 15 maiores; as demais estão na tabela. Clique numa barra para abrir a pessoa."
              grafico={
                <Ranking
                  rotulo="Pessoas com mais tempo de tela"
                  dados={resumo.pessoas.map((p) => ({ id: p.pessoa_id, nome: p.nome, valor: p.tempo_de_tela_ms }))}
                  formato={duracaoLegivel}
                  escolhido={tabela.aberta}
                  aoEscolher={tabela.mostrarNaPrimeira}
                />
              }
              tabela={
                <Tabela
                  rotulo="Pessoas com mais tempo de tela"
                  colunas={["Pessoa", "Tempo de tela"]}
                  linhas={resumo.pessoas.slice(0, 15).map((p) => ({
                    chave: p.pessoa_id,
                    celulas: [p.nome, duracaoLegivel(p.tempo_de_tela_ms)],
                  }))}
                />
              }
            />
            <Secao titulo="Divisão por tipo" descricao={emFoco.nome}>
              <Divisao pessoa={emFoco} />
            </Secao>
          </div>
        </>
      )}

      {!vazio && resumo && (
        <Secao titulo="Tempo de tela por pessoa">
          {pagina && (
            <Tabela
              rotulo="Tempo de tela por pessoa"
              colunas={["Pessoa", "Tempo de tela", "Vídeos", "Aparições", "Menções na fala", "Menções no texto"]}
              minimo={640}
              linhas={pagina.pessoas.map((p) => {
                const aberta = tabela.aberta === p.pessoa_id;
                return {
                  chave: p.pessoa_id,
                  celulas: [
                    <BotaoDaLinha
                      key="n"
                      id={`pessoa-${p.pessoa_id}`}
                      aberta={aberta}
                      aoAlternar={() => tabela.abrir(aberta ? null : p.pessoa_id)}
                    >
                      {p.nome}
                    </BotaoDaLinha>,
                    <ComBarra key="t" valor={p.tempo_de_tela_ms} maximo={maximo}>
                      {duracaoLegivel(p.tempo_de_tela_ms)}
                    </ComBarra>,
                    numero(p.videos),
                    numero(p.aparicoes),
                    numero(p.mencoes_na_fala),
                    numero(p.mencoes_no_texto),
                  ],
                  detalhe: aberta ? <Videos filtros={filtros} pessoa={p} /> : undefined,
                };
              })}
            />
          )}
          {/* O erro da primeira página já saiu acima; aqui só a falha de uma página seguinte. */}
          {!pagina && tabela.cursor !== "" && <AvisoDaConsulta consulta={atual} espera="Carregando a página" />}
          <Paginacao
            pagina={tabela.pagina}
            temProxima={pagina?.proximo != null}
            aoVoltar={tabela.voltar}
            aoAvancar={() => pagina?.proximo && tabela.avancar(pagina.proximo)}
          />
        </Secao>
      )}
    </div>
  );
}
