import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ESTADOS_DO_JOB } from '../../cores.ts'
import { dataDeExibicao, dataEHora } from '../../jobs.ts'
import {
  COLUNA_DO_GRUPO,
  NOME_DO_GRUPO,
  custoLegivel,
  emCentavos,
  horasDeVideo,
  minutosLegiveis,
  rotuloDoGrupo,
  taxaLegivel,
  type Agrupado,
  type Agrupamento,
  type NumerosDeRevisao,
  type NumerosDeVideos,
  type RelatorioDeAcessos,
  type RelatorioDeApi,
  type RelatorioDeBuscas,
  type RelatorioDeCusto,
  type RelatorioDeRevisao,
  type RelatorioDeVideos,
} from '../../painelDaDiretoria.ts'
import { duracaoLegivel } from '../../tempoDeTela.ts'
import { useApi } from '../consultas.ts'
import { chaveDeQuem, nomeDeQuem, nomeDoPrograma, numero, quantos, revisaoVazia, tempoMedio } from './formato.ts'
import { GraficoOuTabela, Indicador, Indicadores, Ranking, Secao, SerieNoTempo, Tabela, type LinhaDaTabela } from './pecas.tsx'

// O conteúdo de cada aba do painel: os mesmos números e tabelas da interface antiga, com o gráfico
// ao lado de cada tabela (séries no tempo em barra, quebras em ranking das 15 maiores).

function Vazio({ texto }: { texto: string }) {
  return <p className="rounded-sm border bg-background px-3 py-6 text-center text-sm text-muted-foreground">{texto}</p>
}

function Grade({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 lg:grid-cols-2">{children}</div>
}

/** Uma quebra (por usuário, por programa…): ranking das 15 maiores no gráfico, todas na tabela. */
function Quebra<T>({
  titulo,
  itens,
  nome,
  valor,
  formato,
  chave,
  colunas,
  celulas,
}: {
  titulo: string
  itens: T[]
  nome: (item: T) => string
  valor: (item: T) => number | null
  formato?: (n: number) => string
  chave: (item: T) => string
  colunas: string[]
  celulas: (item: T) => ReactNode[]
}) {
  const ranqueaveis = itens.flatMap((i) => {
    const v = valor(i)
    return v === null ? [] : [{ nome: nome(i), valor: v }]
  })
  return (
    <GraficoOuTabela
      titulo={titulo}
      descricao={itens.length > 15 ? 'O gráfico mostra os 15 maiores; a tabela, todos.' : undefined}
      grafico={<Ranking rotulo={`${titulo} (${colunas[1].toLowerCase()})`} dados={ranqueaveis} formato={formato} />}
      tabela={<Tabela rotulo={titulo} colunas={colunas} linhas={itens.map((i) => ({ chave: chave(i), celulas: celulas(i) }))} />}
    />
  )
}

/** A série no tempo de uma aba, já no agrupamento que o servidor escolheu, com a tabela completa. */
function NoTempo<T extends { dia: string }>({
  assunto,
  serie,
  agrupamento: grupo,
  dias,
  valor,
  colunas,
  celulas,
  formato,
  minimo,
}: {
  assunto: string
  serie: string
  agrupamento: Agrupamento
  dias: T[]
  valor: (d: T) => number
  colunas: string[]
  celulas: (d: T) => ReactNode[]
  formato?: (n: number) => string
  minimo?: number
}) {
  const titulo = `${assunto} por ${NOME_DO_GRUPO[grupo]}`
  const linhas: LinhaDaTabela[] = dias.map((d) => ({ chave: d.dia, celulas: [rotuloDoGrupo(d.dia, grupo), ...celulas(d)] }))
  return (
    <GraficoOuTabela
      largo
      titulo={titulo}
      grafico={<SerieNoTempo rotulo={`${serie} por ${NOME_DO_GRUPO[grupo]}`} dados={dias} valor={valor} agrupamento={grupo} formato={formato} />}
      tabela={<Tabela rotulo={titulo} colunas={[COLUNA_DO_GRUPO[grupo], ...colunas]} linhas={linhas} minimo={minimo} />}
    />
  )
}

export function Acessos({ relatorio }: { relatorio: Agrupado<RelatorioDeAcessos> }) {
  if (relatorio.por_dia.length === 0) return <Vazio texto="Nenhum acesso neste filtro." />
  return (
    <>
      <Indicadores>
        <Indicador rotulo="Logins no período" valor={relatorio.total.acessos} />
        <Indicador rotulo="Usuários ativos no período" valor={relatorio.total.usuarios_ativos} />
      </Indicadores>
      <Grade>
        <NoTempo
          assunto="Acessos"
          serie="Logins"
          agrupamento={relatorio.agrupamento}
          dias={relatorio.por_dia}
          valor={(d) => d.acessos}
          colunas={['Logins', 'Usuários ativos']}
          celulas={(d) => [numero(d.acessos), numero(d.usuarios_ativos)]}
        />
        <Secao titulo="Usuários ativos por semana" descricao="Cada pessoa conta uma vez na semana.">
          <div className="max-h-72 overflow-y-auto">
            <Tabela
              rotulo="Usuários ativos por semana"
              colunas={['Semana de', 'Usuários ativos']}
              minimo={200}
              linhas={relatorio.por_semana.map((p) => ({ chave: p.inicio, celulas: [dataDeExibicao(p.inicio), numero(p.usuarios_ativos)] }))}
            />
          </div>
        </Secao>
        <Secao titulo="Usuários ativos por mês" descricao="Cada pessoa conta uma vez no mês.">
          <div className="max-h-72 overflow-y-auto">
            <Tabela
              rotulo="Usuários ativos por mês"
              colunas={['Mês', 'Usuários ativos']}
              minimo={200}
              linhas={relatorio.por_mes.map((p) => ({ chave: p.inicio, celulas: [rotuloDoGrupo(p.inicio, 'mes'), numero(p.usuarios_ativos)] }))}
            />
          </div>
        </Secao>
        {relatorio.por_usuario.length > 0 && (
          <Quebra
            titulo="Acessos por usuário"
            itens={relatorio.por_usuario}
            nome={(u) => u.email ?? u.uid}
            valor={(u) => u.acessos}
            chave={(u) => u.uid}
            colunas={['Usuário', 'Logins', 'Dias ativos', 'Último login']}
            celulas={(u) => [u.email ?? u.uid, numero(u.acessos), numero(u.dias_ativos), u.ultimo_acesso ? dataEHora(u.ultimo_acesso) : '—']}
          />
        )}
      </Grade>
    </>
  )
}

const COLUNAS_DE_VIDEOS = ['Enviados', 'Concluídos', 'Com falha', 'Horas de vídeo', 'Tempo médio de processamento']
const celulasDeVideos = (n: NumerosDeVideos) => [numero(n.enviados), numero(n.concluidos), numero(n.falhos), horasDeVideo(n.horas_concluidas), tempoMedio(n)]

/** O que está no pipeline agora, fora dos filtros: lido na hora pela API (`GET /v1/painel/fila`). */
export function FilaAgora() {
  const api = useApi()
  const fila = useQuery({ queryKey: ['painel', 'fila'], queryFn: () => api.filaDoPainel(), refetchInterval: 30_000 })
  return (
    <Secao titulo="Fila agora" descricao="Os vídeos no pipeline neste momento; não depende dos filtros.">
      {fila.isPending && <p className="text-sm text-muted-foreground">Lendo a fila…</p>}
      {fila.isError && <p className="text-sm text-destructive">Não foi possível ler a fila agora.</p>}
      {fila.data && (
        <ul aria-label="Fila agora" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {fila.data.por_estado.map((e) => (
            <li key={e.estado} className="min-w-0">
              <p className="truncate text-xs text-muted-foreground">{ESTADOS_DO_JOB[e.estado].rotulo}</p>
              <p className="text-xl font-semibold">{numero(e.quantidade)}</p>
              <p className="text-xs text-muted-foreground">
                {e.quantidade > 0 ? `O mais antigo há ${duracaoLegivel(e.idade_do_mais_antigo_s * 1000)}` : 'Nenhum agora'}
              </p>
            </li>
          ))}
          {fila.data.esperando_gpu && (
            <li className="min-w-0">
              <p className="text-xl font-semibold">Esperando GPU: {numero(fila.data.esperando_gpu.quantidade)}</p>
              <p className="text-xs text-muted-foreground">
                {fila.data.esperando_gpu.quantidade > 0
                  ? `O mais antigo há ${duracaoLegivel(fila.data.esperando_gpu.idade_do_mais_antigo_s * 1000)}`
                  : 'Nenhum agora'}
              </p>
            </li>
          )}
        </ul>
      )}
    </Secao>
  )
}

export function Videos({ relatorio }: { relatorio: Agrupado<RelatorioDeVideos> }) {
  if (relatorio.por_dia.length === 0) return <Vazio texto="Nenhum vídeo neste filtro." />
  const t = relatorio.total
  return (
    <>
      <Indicadores>
        <Indicador rotulo="Enviados" valor={t.enviados} />
        <Indicador rotulo="Concluídos" valor={t.concluidos} />
        <Indicador rotulo="Com falha" valor={t.falhos} />
        <Indicador rotulo="Horas de vídeo concluídas" valor={horasDeVideo(t.horas_concluidas)} />
        <Indicador rotulo="Tempo médio de processamento" valor={tempoMedio(t)} />
      </Indicadores>
      <Grade>
        <NoTempo
          assunto="Vídeos"
          serie="Vídeos enviados"
          agrupamento={relatorio.agrupamento}
          dias={relatorio.por_dia}
          valor={(d) => d.enviados}
          colunas={COLUNAS_DE_VIDEOS}
          celulas={celulasDeVideos}
          minimo={640}
        />
        {relatorio.por_programa.length > 0 && (
          <Quebra
            titulo="Vídeos por programa"
            itens={relatorio.por_programa}
            nome={(p) => p.programa}
            valor={(p) => p.enviados}
            chave={(p) => p.programa}
            colunas={['Programa', ...COLUNAS_DE_VIDEOS]}
            celulas={(p) => [p.programa, ...celulasDeVideos(p)]}
          />
        )}
        {relatorio.por_usuario.length > 0 && (
          <Quebra
            titulo="Vídeos por usuário"
            itens={relatorio.por_usuario}
            nome={nomeDeQuem}
            valor={(u) => u.enviados}
            chave={chaveDeQuem}
            colunas={['Usuário', ...COLUNAS_DE_VIDEOS]}
            celulas={(u) => [nomeDeQuem(u), ...celulasDeVideos(u)]}
          />
        )}
      </Grade>
    </>
  )
}

export function Buscas({ relatorio }: { relatorio: Agrupado<RelatorioDeBuscas> }) {
  if (relatorio.por_dia.length === 0) return <Vazio texto="Nenhuma busca neste filtro." />
  const t = relatorio.total
  return (
    <>
      <Indicadores>
        <Indicador rotulo="Buscas" valor={t.buscas} />
        <Indicador rotulo="Usuários que buscam" valor={quantos(t.usuarios_que_buscam)} />
        <Indicador rotulo="Buscas sem resultado" valor={t.sem_resultado} />
      </Indicadores>
      <Grade>
        <NoTempo
          assunto="Buscas"
          serie="Buscas"
          agrupamento={relatorio.agrupamento}
          dias={relatorio.por_dia}
          valor={(d) => d.buscas}
          colunas={['Buscas', 'Usuários que buscam', 'Sem resultado']}
          celulas={(d) => [numero(d.buscas), quantos(d.usuarios_que_buscam), numero(d.sem_resultado)]}
        />
        {relatorio.por_usuario.length > 0 && (
          <Quebra
            titulo="Buscas por usuário"
            itens={relatorio.por_usuario}
            nome={nomeDeQuem}
            valor={(u) => u.buscas}
            chave={chaveDeQuem}
            colunas={['Usuário', 'Buscas', 'Sem resultado']}
            celulas={(u) => [nomeDeQuem(u), numero(u.buscas), numero(u.sem_resultado)]}
          />
        )}
      </Grade>
    </>
  )
}

const COLUNAS_DE_REVISAO = ['Minutos de revisão', 'Vídeos', 'Horas de vídeo', 'Minutos por hora de vídeo']
const celulasDeRevisao = (n: NumerosDeRevisao) => [
  minutosLegiveis(n.minutos),
  numero(n.videos),
  horasDeVideo(n.horas_de_video),
  n.minutos_por_hora_de_video === null ? '—' : minutosLegiveis(n.minutos_por_hora_de_video),
]

export function Revisao({ relatorio }: { relatorio: Agrupado<RelatorioDeRevisao> }) {
  const { correcoes, taxa_de_correcao: taxa, tempo_de_revisao: tempo } = relatorio
  if (revisaoVazia(relatorio)) return <Vazio texto="Nenhuma correção nem revisão neste filtro." />
  return (
    <>
      <Indicadores>
        <Indicador rotulo="Correções" valor={correcoes.total} />
        <Indicador rotulo="Minutos de revisão" valor={minutosLegiveis(tempo.total.minutos)} />
        <Indicador
          rotulo="Minutos por hora de vídeo"
          valor={tempo.total.minutos_por_hora_de_video === null ? '—' : minutosLegiveis(tempo.total.minutos_por_hora_de_video)}
        />
      </Indicadores>
      <Grade>
        {correcoes.por_dia.length > 0 && (
          <NoTempo
            assunto="Correções"
            serie="Correções"
            agrupamento={relatorio.agrupamento}
            dias={correcoes.por_dia}
            valor={(d) => d.correcoes}
            colunas={['Correções']}
            celulas={(d) => [numero(d.correcoes)]}
            minimo={200}
          />
        )}
        {correcoes.por_tipo.length > 0 && (
          <Quebra
            titulo="Correções por tipo"
            itens={correcoes.por_tipo}
            nome={(t) => t.tipo ?? 'Sem tipo'}
            valor={(t) => t.correcoes}
            chave={(t) => t.tipo ?? ''}
            colunas={['Tipo', 'Correções']}
            celulas={(t) => [t.tipo ?? 'Sem tipo', numero(t.correcoes)]}
          />
        )}
        {correcoes.por_usuario.length > 0 && (
          <Quebra
            titulo="Correções por usuário"
            itens={correcoes.por_usuario}
            nome={nomeDeQuem}
            valor={(q) => q.correcoes}
            chave={chaveDeQuem}
            colunas={['Usuário', 'Correções']}
            celulas={(q) => [nomeDeQuem(q), numero(q.correcoes)]}
          />
        )}
        {taxa.por_tipo.length > 0 && (
          <Quebra
            titulo="Taxa de correção por tipo"
            itens={taxa.por_tipo}
            nome={(t) => t.tipo}
            valor={(t) => t.taxa}
            formato={taxaLegivel}
            chave={(t) => t.tipo}
            colunas={['Tipo', 'Correções', 'Itens', 'Taxa']}
            celulas={(t) => [t.tipo, numero(t.correcoes), numero(t.itens), taxaLegivel(t.taxa)]}
          />
        )}
        {taxa.por_programa.length > 0 && (
          <Quebra
            titulo="Taxa de correção por programa"
            itens={taxa.por_programa}
            nome={(p) => nomeDoPrograma(p.programa)}
            valor={(p) => p.taxa}
            formato={taxaLegivel}
            chave={(p) => p.programa ?? ''}
            colunas={['Programa', 'Correções', 'Itens', 'Taxa']}
            celulas={(p) => [nomeDoPrograma(p.programa), numero(p.correcoes), numero(p.itens), taxaLegivel(p.taxa)]}
          />
        )}
        {tempo.por_pessoa.length > 0 && (
          <Quebra
            titulo="Revisão por pessoa"
            itens={tempo.por_pessoa}
            nome={(p) => p.email}
            valor={(p) => p.minutos}
            formato={minutosLegiveis}
            chave={(p) => p.uid}
            colunas={['Pessoa', ...COLUNAS_DE_REVISAO]}
            celulas={(p) => [p.email, ...celulasDeRevisao(p)]}
          />
        )}
        {tempo.por_programa.length > 0 && (
          <Quebra
            titulo="Revisão por programa"
            itens={tempo.por_programa}
            nome={(p) => nomeDoPrograma(p.programa)}
            valor={(p) => p.minutos}
            formato={minutosLegiveis}
            chave={(p) => p.programa ?? ''}
            colunas={['Programa', ...COLUNAS_DE_REVISAO]}
            celulas={(p) => [nomeDoPrograma(p.programa), ...celulasDeRevisao(p)]}
          />
        )}
      </Grade>
    </>
  )
}

const COLUNAS_DE_CHAMADAS = ['Chamadas', 'Erros do cliente', 'Erros do servidor']

export function Api({ relatorio }: { relatorio: Agrupado<RelatorioDeApi> }) {
  const t = relatorio.total
  if (relatorio.por_dia.length === 0 && relatorio.por_sistema.length === 0) return <Vazio texto="Nenhuma chamada de API neste filtro." />
  const rota = (r: RelatorioDeApi['por_rota'][number]) => `${r.metodo ?? ''} ${r.rota ?? ''}`.trim() || '—'
  return (
    <>
      <Indicadores>
        <Indicador rotulo="Chamadas" valor={t.chamadas} />
        <Indicador rotulo="Sistemas" valor={t.sistemas} />
        <Indicador rotulo="Erros do cliente" valor={t.erros_do_cliente} />
        <Indicador rotulo="Erros do servidor" valor={t.erros_do_servidor} />
        <Indicador rotulo="Vídeos enviados pela API" valor={t.videos_enviados} />
      </Indicadores>
      <Grade>
        <NoTempo
          assunto="API"
          serie="Chamadas"
          agrupamento={relatorio.agrupamento}
          dias={relatorio.por_dia}
          valor={(d) => d.chamadas}
          colunas={[...COLUNAS_DE_CHAMADAS, 'Vídeos enviados']}
          celulas={(d) => [numero(d.chamadas), numero(d.erros_do_cliente), numero(d.erros_do_servidor), numero(d.videos_enviados)]}
          minimo={480}
        />
        <Quebra
          titulo="API por sistema"
          itens={relatorio.por_sistema}
          nome={nomeDeQuem}
          valor={(s) => s.chamadas}
          chave={chaveDeQuem}
          colunas={['Sistema', ...COLUNAS_DE_CHAMADAS, 'Vídeos enviados']}
          celulas={(s) => [nomeDeQuem(s), numero(s.chamadas), numero(s.erros_do_cliente), numero(s.erros_do_servidor), numero(s.videos_enviados)]}
        />
        <Quebra
          titulo="API por rota"
          itens={relatorio.por_rota}
          nome={rota}
          valor={(r) => r.chamadas}
          chave={(r) => `${r.metodo ?? ''} ${r.rota ?? ''}`}
          colunas={['Rota', ...COLUNAS_DE_CHAMADAS]}
          celulas={(r) => [rota(r), numero(r.chamadas), numero(r.erros_do_cliente), numero(r.erros_do_servidor)]}
        />
      </Grade>
    </>
  )
}

export function Custo({ relatorio }: { relatorio: RelatorioDeCusto }) {
  const { total: t, moeda } = relatorio
  const valor = (custo: number) => custoLegivel(custo, moeda)
  const porHora = (custo: number | null) => (custo === null ? '—' : valor(custo))
  if (relatorio.por_mes.length === 0 && relatorio.sem_dono_por_servico.length === 0) return <Vazio texto="Nenhum custo neste filtro." />
  // O custo vem sempre por mês: o mês vira o primeiro dia dele, como os grupos das outras abas.
  const meses = relatorio.por_mes.map((m) => ({ ...m, dia: `${m.mes}-01` }))
  return (
    <>
      <Indicadores>
        <Indicador rotulo="Custo" valor={valor(t.custo)} />
        <Indicador rotulo="Custo dos vídeos" valor={valor(t.custo_dos_jobs)} />
        <Indicador rotulo="Custo sem dono" valor={valor(t.custo_sem_dono)} />
        <Indicador rotulo="Vídeos concluídos" valor={t.videos} />
        <Indicador rotulo="Horas de vídeo" valor={horasDeVideo(t.horas_de_video)} />
        <Indicador rotulo="Custo por hora de vídeo" valor={porHora(t.custo_por_hora)} />
      </Indicadores>
      <Grade>
        {meses.length > 0 && (
          <NoTempo
            assunto="Custo"
            serie="Custo"
            agrupamento="mes"
            dias={meses}
            valor={(m) => emCentavos(m.custo)}
            formato={valor}
            colunas={['Custo', 'Custo dos vídeos', 'Custo sem dono', 'Vídeos', 'Horas de vídeo', 'Custo por hora']}
            celulas={(m) => [valor(m.custo), valor(m.custo_dos_jobs), valor(m.custo_sem_dono), numero(m.videos), horasDeVideo(m.horas_de_video), porHora(m.custo_por_hora)]}
            minimo={720}
          />
        )}
        {relatorio.por_quem.length > 0 && (
          <Quebra
            titulo="Custo por usuário"
            itens={relatorio.por_quem}
            nome={nomeDeQuem}
            valor={(q) => emCentavos(q.custo)}
            formato={valor}
            chave={chaveDeQuem}
            colunas={['Usuário', 'Custo', 'Vídeos', 'Horas de vídeo', 'Custo por hora']}
            celulas={(q) => [nomeDeQuem(q), valor(q.custo), numero(q.videos), horasDeVideo(q.horas_de_video), porHora(q.custo_por_hora)]}
          />
        )}
        {relatorio.por_etapa.length > 0 && (
          <Quebra
            titulo="Custo por etapa"
            itens={relatorio.por_etapa}
            nome={(e) => e.etapa}
            valor={(e) => emCentavos(e.custo)}
            formato={valor}
            chave={(e) => e.etapa}
            colunas={['Etapa', 'Custo']}
            celulas={(e) => [e.etapa, valor(e.custo)]}
          />
        )}
        {relatorio.sem_dono_por_servico.length > 0 && (
          <Quebra
            titulo="Custo sem dono por serviço"
            itens={relatorio.sem_dono_por_servico}
            nome={(s) => s.servico ?? 'Sem serviço'}
            valor={(s) => emCentavos(s.custo)}
            formato={valor}
            chave={(s) => s.servico ?? ''}
            colunas={['Serviço', 'Custo']}
            celulas={(s) => [s.servico ?? 'Sem serviço', valor(s.custo)]}
          />
        )}
      </Grade>
    </>
  )
}
