import { IconArrowBackUp, IconFlame, IconLock, IconMovie, IconTag, IconTrash, IconUser, type Icon } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { useId, useRef, useState } from 'react'
import { LoginRecenteExigido, SessaoExpirada, codigoDoErro, type ItemDaLixeira, type TipoDeItem } from '../../api.ts'
import { falhaDaAcao, type Falha } from '../../falhaDaAcao.ts'
import { dataDeExibicao } from '../../jobs.ts'
import { frasesDoImpacto, purgaEm, rotuloDoTipo } from '../../lixeira.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'
import { Aba, Aviso, CABECALHO, CAMPO, CELULA, Carregando, Erro, Folga, Selo, TABELA, TopoDaAba, Vazio } from './comum.tsx'
import { gravarNaLista, useColunasVisiveis, useLinhasVirtuais } from './listas.ts'

const CHAVE = ['admin', 'lixeira']
const TUDO = ''
// Em que ponto cada coluna aparece; `null`, sempre.
const COLUNAS = [null, 'sm', 'md', 'lg', 'md', 'lg', null, 'md', null] as const
// A purga que pediu um login novo: ao voltar, a tela reabre o diálogo dela. A mesma chave da tela antiga.
const PURGA_PENDENTE = 'mam:purga-pendente'
const ICONE_DO_TIPO: Record<string, Icon> = {
  video: IconMovie,
  pessoa: IconUser,
  marca: IconTag,
}

const chaveDo = (i: { tipo: string; id: string }) => `${i.tipo}/${i.id}`

function quando(iso: string): string {
  return new Date(iso)
    .toLocaleString('pt-BR', {
      timeZone: 'America/Sao_Paulo',
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
    .replace(',', '')
}

function purgaPendente(): { tipo: string; id: string } | null {
  try {
    return JSON.parse(sessionStorage.getItem(PURGA_PENDENTE) ?? 'null') as {
      tipo: string
      id: string
    } | null
  } catch {
    return null
  }
}

function PurgarAgora({ item, aoFechar, aoPurgar, aoEntrarDeNovo }: { item: ItemDaLixeira; aoFechar: () => void; aoPurgar: () => void; aoEntrarDeNovo: () => void }) {
  const api = useApi()
  const id = useId()
  const tipo = item.tipo as TipoDeItem
  const impacto = useQuery({
    queryKey: [...CHAVE, chaveDo(item), 'impacto'],
    queryFn: async () => frasesDoImpacto(tipo, await api.lixeira.impacto(tipo, item.id)),
    gcTime: 0,
  })
  const [nome, setNome] = useState('')
  const [purgando, setPurgando] = useState(false)
  const [precisaLogin, setPrecisaLogin] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)
  const pronta = nome === item.nome && impacto.isSuccess && !purgando && !precisaLogin

  async function purgar() {
    setPurgando(true)
    setFalha(null)
    try {
      await api.lixeira.purgar(tipo, item.id, nome)
      sessionStorage.removeItem(PURGA_PENDENTE)
      aoPurgar()
    } catch (erro) {
      if (erro instanceof LoginRecenteExigido) setPrecisaLogin(true)
      else if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível purgar ${item.nome}. Tente de novo.`))
      setPurgando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(aberto) => !aberto && !purgando && aoFechar()}>
      <DialogContent mostrarFechar={!purgando} className="sm:max-w-md">
        <DialogTitle>{`Purgar ${item.nome}`}</DialogTitle>
        <DialogDescription>A purga apaga de vez e não tem volta.</DialogDescription>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (pronta) void purgar()
          }}
        >
          {impacto.isPending && <Carregando rotulo="Calculando o que vai junto" />}
          {impacto.data?.map((f) => (
            <p key={f}>{f}</p>
          ))}
          {impacto.isError && <Erro mensagem="Não foi possível calcular o que vai junto. Tente de novo." codigo={codigoDoErro(impacto.error)} aoTentar={() => void impacto.refetch()} />}
          {precisaLogin ? (
            <div role="alert" className="grid gap-2 rounded-sm border border-strong bg-card px-3 py-2">
              <p className="flex items-start gap-2">
                <IconLock size={16} stroke={1.75} className="mt-0.5 shrink-0 text-muted-foreground" aria-hidden />
                Para purgar, é preciso um login recente com o autenticador. Entre de novo e este diálogo volta aberto.
              </p>
              <div>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => {
                    sessionStorage.setItem(PURGA_PENDENTE, JSON.stringify({ tipo: item.tipo, id: item.id }))
                    aoEntrarDeNovo()
                  }}
                >
                  Entrar de novo
                </Button>
              </div>
            </div>
          ) : (
            <>
              <label className="grid gap-1" htmlFor={id}>
                <span className="text-sm">{`Digite o nome do item para confirmar: ${item.nome}`}</span>
                <input id={id} className={CAMPO} value={nome} onChange={(e) => setNome(e.currentTarget.value)} autoComplete="off" autoFocus />
              </label>
              {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={aoFechar} disabled={purgando}>
                  Cancelar
                </Button>
                <Button type="submit" variant="destructive" disabled={nome !== item.nome || !impacto.isSuccess || purgando}>
                  Purgar
                </Button>
              </div>
            </>
          )}
        </form>
      </DialogContent>
    </Dialog>
  )
}

/**
 * `/admin/lixeira`: restaurar e purgar (docs/design/administracao.md, "Apagar com segurança").
 * A API devolve a lixeira inteira, sem páginas (os itens ficam nela só até a purga automática);
 * as linhas são virtuais, para centenas de itens não pesarem no DOM.
 */
export default function Lixeira({ aoEntrarDeNovo }: { aoEntrarDeNovo: () => void }) {
  const api = useApi()
  const consultas = useQueryClient()
  const [filtro, setFiltro] = useState(TUDO)
  const [restaurando, setRestaurando] = useState<string | null>(null)
  const [purgando, setPurgando] = useState<ItemDaLixeira | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [falha, setFalha] = useState<Falha | null>(null)
  const carga = useQuery({
    queryKey: CHAVE,
    queryFn: async () => {
      const lista = await api.lixeira.listar()
      // A volta do login: reabre a purga que ficou pendente, uma vez.
      const volta = purgaPendente()
      sessionStorage.removeItem(PURGA_PENDENTE)
      if (volta) {
        const item = lista.find((i) => chaveDo(i) === chaveDo(volta))
        if (item) setPurgando(item)
        else setAviso('O item que você ia purgar não está mais na lixeira.')
      }
      return lista
    },
  })
  const itens = carga.data ?? []
  const tipos = [...new Set(itens.map((i) => i.tipo))]
  const filtroAtual = tipos.includes(filtro) ? filtro : TUDO
  const visiveis = itens.filter((i) => filtroAtual === TUDO || i.tipo === filtroAtual)
  const rolagem = useRef<HTMLDivElement>(null)
  const { tabela, itens: linhas, antes, depois, medir } = useLinhasVirtuais(visiveis.length, rolagem, (i) => (visiveis[i] ? chaveDo(visiveis[i]) : String(i)))
  const colunas = useColunasVisiveis(COLUNAS)

  async function tirarDaLista(item: ItemDaLixeira, frase: string) {
    await gravarNaLista<ItemDaLixeira[]>(consultas, CHAVE, (atuais) => atuais.filter((i) => chaveDo(i) !== chaveDo(item)))
    setAviso(frase)
  }

  async function restaurar(item: ItemDaLixeira) {
    setRestaurando(null)
    setAviso(null)
    setFalha(null)
    try {
      await api.lixeira.restaurar(item.tipo as TipoDeItem, item.id)
      await tirarDaLista(item, `${item.nome} voltou.`)
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível restaurar ${item.nome}. Tente de novo.`))
    }
  }

  return (
    <Aba ref={rolagem}>
      <TopoDaAba titulo="Lixeira" contagem={carga.isSuccess ? `${itens.length} ${itens.length === 1 ? 'item' : 'itens'}` : undefined}>
        {tipos.length > 0 && (
          <select aria-label="Tipo" className={cn(CAMPO, 'w-40')} value={filtroAtual} onChange={(e) => setFiltro(e.currentTarget.value)}>
            <option value={TUDO}>Tudo</option>
            {tipos.map((t) => (
              <option key={t} value={t}>
                {rotuloDoTipo(t)}
              </option>
            ))}
          </select>
        )}
      </TopoDaAba>
      <p className="max-w-3xl text-muted-foreground">O que vai para a lixeira some do acervo e da busca. Restaurar devolve tudo como estava; a purga apaga de vez.</p>
      <Aviso>{aviso}</Aviso>
      {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
      {carga.isPending && <Carregando rotulo="Carregando a lixeira" />}
      {carga.isError && <Erro mensagem="Não foi possível carregar a lixeira. Tente de novo." codigo={codigoDoErro(carga.error)} aoTentar={() => void carga.refetch()} />}
      {carga.isSuccess && itens.length === 0 && <Vazio Icone={IconTrash}>A lixeira está vazia.</Vazio>}
      {carga.isSuccess && itens.length > 0 && visiveis.length === 0 && <Vazio Icone={IconTrash}>Nada deste tipo na lixeira.</Vazio>}
      {visiveis.length > 0 && (
        <table ref={tabela} aria-label="Lixeira" className={TABELA}>
          <thead>
            <tr>
              <th className={CABECALHO}>Item</th>
              <th className={cn(CABECALHO, 'hidden w-24 sm:table-cell')}>Tipo</th>
              <th className={cn(CABECALHO, 'hidden w-[14%] md:table-cell')}>Programa</th>
              <th className={cn(CABECALHO, 'hidden w-28 lg:table-cell')}>Exibição</th>
              <th className={cn(CABECALHO, 'hidden w-[18%] md:table-cell')}>Apagado por</th>
              <th className={cn(CABECALHO, 'hidden w-28 lg:table-cell')}>Em</th>
              <th className={cn(CABECALHO, 'w-24')}>Purga em</th>
              <th className={cn(CABECALHO, 'hidden w-[16%] md:table-cell')}>Motivo</th>
              <th className={cn(CABECALHO, 'w-20')}>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <Folga altura={antes} colunas={colunas} />
          {linhas.map((linha) => {
            const item = visiveis[linha.index]!
            const chave = chaveDo(item)
            const Icone = ICONE_DO_TIPO[item.tipo] ?? IconTrash
            return (
              <tbody key={linha.key} data-index={linha.index} ref={medir}>
                <tr className="hover:bg-card">
                  <td className={CELULA}>
                    <span className="flex min-w-0 items-center gap-2">
                      <Icone size={16} stroke={1.75} className="shrink-0 text-muted-foreground" aria-hidden />
                      <span className="truncate font-medium">{item.nome}</span>
                    </span>
                  </td>
                  <td className={cn(CELULA, 'hidden sm:table-cell')}>{rotuloDoTipo(item.tipo)}</td>
                  <td className={cn(CELULA, 'hidden truncate md:table-cell')}>{item.programa || '—'}</td>
                  <td className={cn(CELULA, 'hidden tabular-nums whitespace-nowrap lg:table-cell')}>{dataDeExibicao(item.data_exibicao)}</td>
                  <td className={cn(CELULA, 'hidden truncate md:table-cell')}>{item.enviado_por}</td>
                  <td className={cn(CELULA, 'hidden tabular-nums whitespace-nowrap lg:table-cell')}>{quando(item.enviado_em)}</td>
                  <td className={CELULA}>
                    <Selo tom={item.dias_ate_a_purga <= 1 ? 'falha' : 'neutro'}>{purgaEm(item.dias_ate_a_purga)}</Selo>
                  </td>
                  <td className={cn(CELULA, 'hidden truncate md:table-cell')}>{item.motivo}</td>
                  <td className={cn(CELULA, 'text-right whitespace-nowrap')}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button type="button" variant="ghost" size="icon-sm" aria-label={`Restaurar ${item.nome}`} onClick={() => setRestaurando(chave)}>
                          <IconArrowBackUp stroke={1.75} aria-hidden />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Restaurar</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="text-destructive"
                          aria-label={`Purgar agora ${item.nome}`}
                          onClick={() => {
                            setAviso(null)
                            setFalha(null)
                            setPurgando(item)
                          }}
                        >
                          <IconFlame stroke={1.75} aria-hidden />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Purgar agora</TooltipContent>
                    </Tooltip>
                  </td>
                </tr>
                {restaurando === chave && (
                  <tr className="bg-selected" onKeyDown={(e) => e.key === 'Escape' && setRestaurando(null)}>
                    <td colSpan={colunas} className={CELULA}>
                      <div className="flex flex-wrap items-center gap-2 py-1">
                        <span>{`Restaurar ${item.nome}? Volta tudo como estava.`}</span>
                        <Button type="button" size="sm" autoFocus aria-label="Confirmar restauração" onClick={() => void restaurar(item)}>
                          Restaurar
                        </Button>
                        <Button type="button" size="sm" variant="secondary" onClick={() => setRestaurando(null)}>
                          Cancelar
                        </Button>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            )
          })}
          <Folga altura={depois} colunas={colunas} />
        </table>
      )}
      {purgando && (
        <PurgarAgora
          key={chaveDo(purgando)}
          item={purgando}
          aoFechar={() => setPurgando(null)}
          aoPurgar={() => {
            void tirarDaLista(purgando, `${purgando.nome} saiu de vez da lixeira.`)
            setPurgando(null)
          }}
          aoEntrarDeNovo={aoEntrarDeNovo}
        />
      )}
    </Aba>
  )
}
