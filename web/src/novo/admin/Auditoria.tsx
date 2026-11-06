import {
  IconBroadcast,
  IconChartBar,
  IconChecklist,
  IconEye,
  IconHistory,
  IconKey,
  IconRefresh,
  IconTrash,
  IconUser,
  IconUsers,
  IconX,
  type Icon,
} from '@tabler/icons-react'
import { cn } from 'cn'
import { useRef, useState, type KeyboardEvent } from 'react'
import { codigoDoErro } from '../../api.ts'
import { useAtalhos, type Atalho } from '../../atalhos.ts'
import {
  ACOES_DA_AUDITORIA,
  ACOES_DE_ACESSO,
  autorDoRegistro,
  detalhesEmFrases,
  FILTRO_DE_ACESSOS,
  FRASE_DA_ACAO,
  fraseDaAcao,
  haFiltroDaAuditoria,
  periodoInvertido,
  SEM_FILTROS_DA_AUDITORIA,
  type FiltrosDaAuditoria,
  type RegistroDeAuditoria,
} from '../../auditoria.ts'
import { dataEHora } from '../../jobs.ts'
import { enderecoDaAuditoria, navegar } from '../../rotas.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'
import { Aba, CABECALHO, CAMPO, CELULA, Carregando, Erro, Folga, LINHA_CLICAVEL, TABELA, TopoDaAba, Vazio } from './comum.tsx'
import { useColunasVisiveis, useLinhasVirtuais, useListaPorCursor } from './listas.ts'

const POR_PAGINA = 50
// Em que ponto cada coluna aparece; `null`, sempre.
const COLUNAS = [null, 'md', null, null, 'lg'] as const
const ATALHOS: Atalho[] = [{ tecla: 'Enter', acao: 'Na tabela: mostrar ou esconder os detalhes da linha', grupo: 'Auditoria' }]

/** O tipo do evento, pelo começo da ação: o ícone de 16 px e o nome na dica. */
function tipoDoEvento(acao: string): { Icone: Icon; nome: string } {
  if ((ACOES_DE_ACESSO as string[]).includes(acao)) return { Icone: IconEye, nome: 'Acesso' }
  const [grupo] = acao.split('.')
  switch (grupo) {
    case 'conta':
    case 'papeis':
      return { Icone: IconUsers, nome: 'Conta' }
    case 'chave':
      return { Icone: IconKey, nome: 'Chave de sistema' }
    case 'item':
      return { Icone: IconTrash, nome: 'Lixeira' }
    case 'painel':
      return { Icone: IconChartBar, nome: 'Painel' }
    case 'programa':
      return { Icone: IconBroadcast, nome: 'Programa' }
    case 'aprovacao':
      return { Icone: IconChecklist, nome: 'Regra de aprovação' }
    case 'video':
    case 'job':
      return { Icone: IconRefresh, nome: 'Processamento' }
    case 'pessoa':
      return { Icone: IconUser, nome: 'Catálogo' }
    default:
      return { Icone: IconHistory, nome: 'Outro' }
  }
}

function TipoDoEvento({ acao }: { acao: string }) {
  const { Icone, nome } = tipoDoEvento(acao)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span role="img" aria-label={nome} className="grid size-4 shrink-0 place-items-center text-muted-foreground">
          <Icone size={16} stroke={1.75} aria-hidden />
        </span>
      </TooltipTrigger>
      <TooltipContent>{nome}</TooltipContent>
    </Tooltip>
  )
}

function Detalhes({ registro }: { registro: RegistroDeAuditoria }) {
  const frases = detalhesEmFrases(registro)
  return (
    <div className="grid gap-0.5 py-1 pl-6">
      {/* No celular, quem e o motivo não cabem na linha e descem para cá. */}
      <p className="text-muted-foreground md:hidden">{`Quem: ${autorDoRegistro(registro)}`}</p>
      {registro.motivo && <p className="text-muted-foreground lg:hidden">{`Motivo: ${registro.motivo}`}</p>}
      {frases.length === 0 ? <p className="text-muted-foreground">Sem detalhes para este registro.</p> : frases.map((f) => <p key={f}>{f}</p>)}
    </div>
  )
}

function irPara(filtros: FiltrosDaAuditoria) {
  navegar(enderecoDaAuditoria(filtros), { substituir: true })
}

/** `/admin/auditoria`: o que a administração fez, só de leitura. Pagina por cursor; a tabela é virtual. */
export default function Auditoria({ filtros }: { filtros: FiltrosDaAuditoria }) {
  const api = useApi()
  const invertido = periodoInvertido(filtros)
  const lista = useListaPorCursor(['admin', 'auditoria', filtros], (cursor) => api.auditoria(filtros, POR_PAGINA, cursor), !invertido)
  const [abertas, setAbertas] = useState<string[]>([])
  const rolagem = useRef<HTMLDivElement>(null)
  useAtalhos(ATALHOS)

  const registros = lista.data?.pages.flatMap((p) => p.registros) ?? []
  const { tabela, itens, antes, depois, medir } = useLinhasVirtuais(registros.length, rolagem, (i) => registros[i]?.id ?? String(i))
  const colunas = useColunasVisiveis(COLUNAS)
  const mudar = (parte: Partial<FiltrosDaAuditoria>) => irPara({ ...filtros, ...parte })
  const alternar = (id: string) => setAbertas((atuais) => (atuais.includes(id) ? atuais.filter((a) => a !== id) : [...atuais, id]))
  // Com a página seguinte em falha, a lista carregada continua na tela, com o erro embaixo.
  const pronta = !invertido && lista.data !== undefined

  return (
    <Aba ref={rolagem}>
      <TopoDaAba titulo="Auditoria">
        <input aria-label="Pessoa" placeholder="E-mail da pessoa" className={cn(CAMPO, 'w-full sm:w-52')} value={filtros.pessoa} onChange={(e) => mudar({ pessoa: e.currentTarget.value })} />
        <input aria-label="Alvo" placeholder="Código do alvo (ex.: um vídeo)" className={cn(CAMPO, 'w-full sm:w-56')} value={filtros.alvo} onChange={(e) => mudar({ alvo: e.currentTarget.value })} />
        <select aria-label="Ação" className={cn(CAMPO, 'w-full sm:w-52')} value={filtros.acao} onChange={(e) => mudar({ acao: e.currentTarget.value })}>
          <option value="">Todas as ações</option>
          {ACOES_DA_AUDITORIA.filter((a) => !ACOES_DE_ACESSO.includes(a)).map((a) => (
            <option key={a} value={a}>
              {FRASE_DA_ACAO[a]}
            </option>
          ))}
          <optgroup label="Acessos">
            <option value={FILTRO_DE_ACESSOS}>Todos os acessos</option>
            {ACOES_DE_ACESSO.map((a) => (
              <option key={a} value={a}>
                {FRASE_DA_ACAO[a]}
              </option>
            ))}
          </optgroup>
        </select>
        <input type="date" aria-label="De" className={CAMPO} value={filtros.de} onChange={(e) => mudar({ de: e.currentTarget.value })} />
        <input type="date" aria-label="Até" className={CAMPO} value={filtros.ate} onChange={(e) => mudar({ ate: e.currentTarget.value })} />
        {haFiltroDaAuditoria(filtros) && (
          <Button type="button" variant="ghost" size="sm" onClick={() => irPara(SEM_FILTROS_DA_AUDITORIA)}>
            <IconX stroke={1.75} aria-hidden /> Limpar filtros
          </Button>
        )}
      </TopoDaAba>
      {invertido && <p>A data em "De" é depois da data em "Até". Troque uma das duas para ver os registros.</p>}
      {!invertido && lista.isPending && <Carregando rotulo="Carregando a auditoria" />}
      {!invertido && lista.isError && !lista.data && (
        <Erro mensagem="Não foi possível carregar a auditoria. Tente de novo." codigo={codigoDoErro(lista.error)} aoTentar={() => void lista.refetch()} />
      )}
      {pronta && registros.length === 0 && (
        <Vazio Icone={IconHistory}>{haFiltroDaAuditoria(filtros) ? 'Nenhum registro com esses filtros.' : 'Nenhum registro ainda.'}</Vazio>
      )}
      {pronta && registros.length > 0 && (
        <table ref={tabela} aria-label="Auditoria" className={TABELA}>
          <thead>
            <tr>
              <th className={cn(CABECALHO, 'w-28 sm:w-36')}>Quando</th>
              <th className={cn(CABECALHO, 'hidden w-[22%] md:table-cell')}>Quem</th>
              <th className={cn(CABECALHO, 'w-[38%] md:w-[26%]')}>Ação</th>
              <th className={CABECALHO}>Alvo</th>
              <th className={cn(CABECALHO, 'hidden w-[18%] lg:table-cell')}>Motivo</th>
            </tr>
          </thead>
          <Folga altura={antes} colunas={colunas} />
          {itens.map((item) => {
            const r = registros[item.index]!
            const aberta = abertas.includes(r.id)
            const aoTeclar = (e: KeyboardEvent<HTMLTableRowElement>) => {
              if (e.target !== e.currentTarget || e.key !== 'Enter') return
              e.preventDefault()
              alternar(r.id)
            }
            return (
              <tbody key={item.key} data-index={item.index} ref={medir}>
                <tr tabIndex={0} aria-expanded={aberta} onClick={() => alternar(r.id)} onKeyDown={aoTeclar} className={LINHA_CLICAVEL}>
                  <td className={cn(CELULA, 'whitespace-nowrap text-muted-foreground')}>{dataEHora(r.quando)}</td>
                  <td className={cn(CELULA, 'hidden truncate md:table-cell')}>{autorDoRegistro(r)}</td>
                  <td className={CELULA}>
                    <span className="flex min-w-0 items-center gap-2">
                      <TipoDoEvento acao={r.acao} />
                      <span className="truncate">{fraseDaAcao(r.acao)}</span>
                    </span>
                  </td>
                  <td className={cn(CELULA, 'truncate')}>{r.alvo_nome}</td>
                  <td className={cn(CELULA, 'hidden truncate lg:table-cell')}>{r.motivo ?? '—'}</td>
                </tr>
                {aberta && (
                  <tr className="bg-card">
                    <td colSpan={colunas} className="border-b px-2 py-1">
                      <Detalhes registro={r} />
                    </td>
                  </tr>
                )}
              </tbody>
            )
          })}
          <Folga altura={depois} colunas={colunas} />
        </table>
      )}
      {pronta && lista.isFetchNextPageError && (
        <Erro mensagem="Não foi possível carregar mais registros. Tente de novo." codigo={codigoDoErro(lista.error)} aoTentar={() => void lista.fetchNextPage()} />
      )}
      {pronta && lista.hasNextPage && (
        <div className="flex justify-center">
          <Button type="button" variant="secondary" size="sm" disabled={lista.isFetchingNextPage} onClick={() => void lista.fetchNextPage()}>
            Carregar mais
          </Button>
        </div>
      )}
    </Aba>
  )
}
