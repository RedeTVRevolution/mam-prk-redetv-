import { IconBadgeTm, IconTag } from "@tabler/icons-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { codigoDoErro } from "../../api.ts";
import {
  nomeDoTipo,
  TIPOS_DE_INSERCAO,
  type FiltrosDeMarcas,
  type MarcaResumida,
} from "../../marcas.ts";
import { enderecoDasMarcas, enderecoDoVideo, navegar, seguir } from "../../rotas.ts";
import { duracaoLegivel } from "../../tempoDeTela.ts";
import { Falha } from "../comum/Falha.tsx";
import { mensagemDoErro, repetirFalha } from "../comum/relatorio.ts";
import { BaixarCsv } from "../comum/relatorio.tsx";
import { useApi } from "../consultas.ts";
import { Faceta } from "../acervo/Filtros.tsx";
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
import { Matriz } from "./Matriz.tsx";
import { useTabelaPaginada } from "./pilha.ts";

// O relatório de marcas (`/relatorios/marcas`): o ranking vem de 50 em 50 marcas com cursor, e as
// inserções de cada marca só quando a linha abre.

/** Quantas marcas o gráfico e a matriz mostram, as primeiras da API; a tabela tem todas, por página. */
const NO_GRAFICO = 15;

function useRanking(filtros: FiltrosDeMarcas, cursor: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["relatorios", "marcas", filtros, cursor],
    queryFn: () => api.rankingDeMarcas(filtros, cursor),
    retry: repetirFalha,
  });
}

/** As inserções da marca (e do tipo, se a célula da matriz escolheu um), pedidas quando a linha abre, 25 por vez. */
function Insercoes({ filtros, marca, tipo }: { filtros: FiltrosDeMarcas; marca: string; tipo: string }) {
  const api = useApi();
  const consulta = useInfiniteQuery({
    queryKey: ["relatorios", "marcas", "insercoes", filtros, marca, tipo],
    queryFn: ({ pageParam }) => api.insercoesDaMarca(filtros, marca, tipo ? [tipo] : undefined, pageParam),
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
        Carregando as inserções…
      </p>
    );
  }
  const insercoes = consulta.data.pages.flatMap((p) => p.insercoes);
  return (
    <div className="grid gap-2">
      {tipo && <p className="text-xs text-muted-foreground">Só {nomeDoTipo(tipo)}</p>}
      <Tabela
        rotulo={`Inserções de ${marca}`}
        colunas={["Vídeo", "Tipo", "Trecho", "Duração"]}
        linhas={insercoes.map((i, n) => ({
          // Duas inserções iguais no mesmo vídeo podem existir: a posição desempata.
          chave: `${n}-${i.job_id}-${i.inicio_ms}`,
          celulas: [
            <a
              key="v"
              href={enderecoDoVideo(i.job_id, i.inicio_ms / 1000)}
              onClick={(e) => seguir(e, enderecoDoVideo(i.job_id, i.inicio_ms / 1000))}
              className="text-link hover:underline"
            >
              {i.nome ?? i.job_id}
            </a>,
            nomeDoTipo(i.tipo),
            `${duracaoLegivel(i.inicio_ms)} – ${duracaoLegivel(i.fim_ms)}`,
            duracaoLegivel(i.fim_ms - i.inicio_ms),
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
          Ver mais inserções
        </Button>
      )}
    </div>
  );
}

const porTipo = (m: MarcaResumida) =>
  m.por_tipo.map((t) => `${nomeDoTipo(t.tipo)}: ${t.insercoes} (${duracaoLegivel(t.tempo_ms)})`).join(" · ");

/** "Relatórios › Marcas": inserções, tempo somado e vídeos por marca, com o detalhe por tipo. */
export default function Marcas({ filtros }: { filtros: FiltrosDeMarcas }) {
  const api = useApi();
  const tabela = useTabelaPaginada(JSON.stringify(filtros));
  const primeira = useRanking(filtros, "");
  const atual = useRanking(filtros, tabela.cursor);

  function mudar(parte: Partial<FiltrosDeMarcas>) {
    navegar(enderecoDasMarcas({ ...filtros, ...parte }), { substituir: true });
  }

  const resumo = primeira.data;
  const vazio = resumo?.marcas.length === 0;
  const pagina = atual.data;
  const noGrafico = resumo?.marcas.slice(0, NO_GRAFICO) ?? [];
  const maximo = Math.max(0, ...(pagina?.marcas ?? []).map((m) => m.tempo_ms));
  useEffect(() => {
    if (tabela.aberta) document.getElementById(`marca-${tabela.aberta}`)?.scrollIntoView({ block: "nearest" });
  }, [tabela.aberta]);

  return (
    <div className="mx-auto grid w-full max-w-[1600px] content-start gap-3 p-3 md:p-4">
      <div className="flex items-center gap-2">
        <IconBadgeTm size={20} stroke={1.75} className="text-muted-foreground" aria-hidden />
        <h1 className="text-xl font-semibold">Marcas</h1>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <FiltrosDoPeriodo filtros={filtros} aoMudar={mudar}>
          <div className="grid min-w-0 gap-1">
            <span className="text-xs text-muted-foreground">Tipo de inserção</span>
            <Faceta
              rotulo="Tipo de inserção"
              Icone={IconTag}
              opcoes={Object.entries(TIPOS_DE_INSERCAO).map(([valor, rotulo]) => ({ valor, rotulo }))}
              valor={filtros.tipos}
              aoMudar={(tipos) => mudar({ tipos })}
              tudoMarcado
            />
          </div>
        </FiltrosDoPeriodo>
        <BaixarCsv
          key={JSON.stringify(filtros)}
          arquivo="marcas.csv"
          pedir={() => api.marcasEmCsv(filtros)}
          desligado={!resumo || vazio === true}
        />
      </div>
      <p className="max-w-[110ch] text-xs text-muted-foreground">
        O tempo é a soma das durações das inserções; inserções que se sobrepõem contam cada uma.
      </p>

      <AvisoDaConsulta consulta={primeira} espera="Montando o relatório" />
      {vazio && <p className="text-sm">Nenhuma inserção de marca neste filtro.</p>}

      {resumo && !vazio && (
        <>
          <section aria-label="Resumo do período">
            <Indicadores>
              <Indicador rotulo="Marcas" valor={resumo.total.marcas} />
              <Indicador rotulo="Inserções" valor={resumo.total.insercoes} />
              <Indicador rotulo="Tempo" valor={duracaoLegivel(resumo.total.tempo_ms)} />
              <Indicador rotulo="Vídeos" valor={resumo.total.videos} />
            </Indicadores>
          </section>
          <GraficoOuTabela
            titulo="Marcas com mais tempo"
            descricao="As 15 maiores; as demais estão na tabela. Clique numa barra para abrir a marca."
            grafico={
              <Ranking
                rotulo="Marcas com mais tempo"
                dados={noGrafico.map((m) => ({ id: m.marca, nome: m.marca, valor: m.tempo_ms }))}
                formato={duracaoLegivel}
                escolhido={tabela.aberta}
                aoEscolher={(marca) => tabela.mostrarNaPrimeira(marca)}
              />
            }
            tabela={
              <Tabela
                rotulo="Marcas com mais tempo"
                colunas={["Marca", "Tempo"]}
                linhas={noGrafico.map((m) => ({ chave: m.marca, celulas: [m.marca, duracaoLegivel(m.tempo_ms)] }))}
              />
            }
          />
          <Secao titulo="Tempo por marca e tipo" descricao="As 15 marcas do gráfico. Clique numa célula para ver só aquele tipo.">
            <Matriz marcas={noGrafico} aoEscolher={tabela.mostrarNaPrimeira} />
          </Secao>
        </>
      )}

      {!vazio && resumo && (
        <Secao titulo="Inserções por marca">
          {pagina && (
            <Tabela
              rotulo="Inserções por marca"
              colunas={["Marca", "Inserções", "Tempo", "Vídeos", "Por tipo"]}
              minimo={720}
              linhas={pagina.marcas.map((m) => {
                const aberta = tabela.aberta === m.marca;
                return {
                  chave: m.marca,
                  celulas: [
                    <BotaoDaLinha
                      key="n"
                      id={`marca-${m.marca}`}
                      aberta={aberta}
                      aoAlternar={() => tabela.abrir(aberta ? null : m.marca)}
                    >
                      {m.marca}
                    </BotaoDaLinha>,
                    numero(m.insercoes),
                    <ComBarra key="t" valor={m.tempo_ms} maximo={maximo}>
                      {duracaoLegivel(m.tempo_ms)}
                    </ComBarra>,
                    numero(m.videos),
                    <span key="p" className="text-xs whitespace-normal text-muted-foreground">
                      {porTipo(m)}
                    </span>,
                  ],
                  detalhe: aberta ? <Insercoes filtros={filtros} marca={m.marca} tipo={tabela.recorte} /> : undefined,
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
