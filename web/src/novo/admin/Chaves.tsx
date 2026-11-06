import { IconCopy, IconKey, IconKeyOff, IconPlus } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { Fragment, useId, useState } from 'react'
import { SessaoExpirada, codigoDoErro, type ChaveDaLista } from '../../api.ts'
import { falhaDaAcao, type Falha } from '../../falhaDaAcao.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'
import { Aba, Aviso, CABECALHO, CAMPO, CELULA, Carregando, Erro, Selo, TABELA, TopoDaAba, Vazio } from './comum.tsx'

// A mesma chave das Entradas, que tiram daqui os sistemas do filtro.
const CHAVE = ['admin', 'chaves']

/** Os escopos do `api/auth.py`, com o que cada um permite. */
const ESCOPOS = [
  { valor: 'criar', pode: 'cria vídeos para decupar' },
  { valor: 'ler', pode: 'lê a decupagem e o estado dos vídeos' },
  { valor: 'cancelar', pode: 'cancela vídeos em andamento' },
]

function data(iso: string): string {
  return new Date(iso).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' })
}

/** A chave emitida, uma vez: só "Já guardei" fecha (sem X, sem Esc, sem clique fora). */
function ChaveEmitida({ chave, aoFechar }: { chave: string; aoFechar: () => void }) {
  const [copiada, setCopiada] = useState(false)
  const id = useId()
  const impedir = (e: Event) => e.preventDefault()
  return (
    <Dialog open>
      <DialogContent mostrarFechar={false} onEscapeKeyDown={impedir} onInteractOutside={impedir} className="sm:max-w-md">
        <DialogTitle>Chave emitida</DialogTitle>
        <DialogDescription>Guarde agora: ela não será mostrada de novo.</DialogDescription>
        <div className="flex items-end gap-2">
          <label className="grid min-w-0 flex-1 gap-1" htmlFor={id}>
            <span className="text-sm">Chave</span>
            <input id={id} readOnly value={chave} className={cn(CAMPO, 'font-mono')} onFocus={(e) => e.currentTarget.select()} />
          </label>
          <Button
            type="button"
            variant="secondary"
            onClick={() => void navigator.clipboard?.writeText(chave).then(() => setCopiada(true), () => {})}
          >
            <IconCopy stroke={1.75} aria-hidden />
            {copiada ? 'Copiada' : 'Copiar'}
          </Button>
        </div>
        <div className="flex justify-end">
          <Button type="button" onClick={aoFechar} autoFocus>
            Já guardei
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Montado só enquanto aberto. A chave emitida vive só no estado deste diálogo: ao fechar,
 * o componente some e ela não fica em nenhum outro lugar.
 */
function EmitirChave({ aoFechar, aoEmitir }: { aoFechar: () => void; aoEmitir: (corpo: { sistema: string; escopos: string[] }) => Promise<string> }) {
  const [sistema, setSistema] = useState('')
  const [escopos, setEscopos] = useState<string[]>([])
  const [chave, setChave] = useState<string | null>(null)
  const [emitindo, setEmitindo] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)
  const completa = sistema.trim() !== '' && escopos.length > 0
  const id = useId()

  async function emitir() {
    setEmitindo(true)
    setFalha(null)
    try {
      setChave(await aoEmitir({ sistema: sistema.trim(), escopos }))
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível emitir a chave. Tente de novo.'))
    } finally {
      setEmitindo(false)
    }
  }

  if (chave !== null) return <ChaveEmitida chave={chave} aoFechar={aoFechar} />

  return (
    // Enquanto a emissão está no ar o diálogo não fecha: a chave chegaria sem ser vista.
    <Dialog open onOpenChange={(aberto) => !aberto && !emitindo && aoFechar()}>
      <DialogContent mostrarFechar={!emitindo} className="sm:max-w-md">
        <DialogTitle>Emitir chave</DialogTitle>
        <DialogDescription>A chave dá a um sistema de fora o acesso dos escopos marcados.</DialogDescription>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (completa && !emitindo) void emitir()
          }}
        >
          <label className="grid gap-1" htmlFor={`${id}-sistema`}>
            <span className="text-sm">Sistema</span>
            <input id={`${id}-sistema`} className={CAMPO} value={sistema} onChange={(e) => setSistema(e.currentTarget.value)} autoFocus />
          </label>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">Escopos</legend>
            {ESCOPOS.map((e) => (
              <label key={e.valor} className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 shrink-0 accent-primary"
                  checked={escopos.includes(e.valor)}
                  onChange={(ev) => {
                    const marcado = ev.currentTarget.checked
                    setEscopos(ESCOPOS.map((q) => q.valor).filter((v) => (v === e.valor ? marcado : escopos.includes(v))))
                  }}
                />
                <span className="grid">
                  <span className="font-mono">{e.valor}</span>
                  <span className="text-xs text-muted-foreground">{e.pode}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={aoFechar} disabled={emitindo}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!completa || emitindo}>
              Emitir chave
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** `/admin/chaves`: sistemas e chaves de API (docs/design/administracao.md). */
export default function Chaves() {
  const api = useApi()
  const consultas = useQueryClient()
  const carga = useQuery({ queryKey: CHAVE, queryFn: () => api.chaves.listar() })
  const [emitindo, setEmitindo] = useState(false)
  const [revogando, setRevogando] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [falha, setFalha] = useState<Falha | null>(null)
  const chaves = carga.data ?? []
  const gravar = (mudar: (atuais: ChaveDaLista[]) => ChaveDaLista[]) => consultas.setQueryData<ChaveDaLista[]>(CHAVE, (atuais) => mudar(atuais ?? []))

  async function revogar(chave: ChaveDaLista) {
    setRevogando(null)
    setAviso(null)
    setFalha(null)
    try {
      const nova = await api.chaves.revogar(chave.id)
      gravar((atuais) => atuais.map((c) => (c.id === nova.id ? nova : c)))
      setAviso(`A chave de ${chave.sistema} foi revogada.`)
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível revogar a chave de ${chave.sistema}. Tente de novo.`))
    }
  }

  const emitir = (
    <Button type="button" onClick={() => setEmitindo(true)}>
      <IconPlus stroke={1.75} aria-hidden /> Emitir chave
    </Button>
  )

  return (
    <Aba>
      <TopoDaAba titulo="Sistemas e chaves" contagem={carga.isSuccess ? `${chaves.filter((c) => !c.revogada_em).length} ativas de ${chaves.length}` : undefined}>
        {emitir}
      </TopoDaAba>
      <Aviso>{aviso}</Aviso>
      {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
      {carga.isPending && <Carregando rotulo="Carregando as chaves" />}
      {carga.isError && (
        <Erro mensagem="Não foi possível carregar as chaves. Tente de novo." codigo={codigoDoErro(carga.error)} aoTentar={() => void carga.refetch()} />
      )}
      {carga.isSuccess && chaves.length === 0 && <Vazio Icone={IconKey}>Nenhuma chave emitida.</Vazio>}
      {carga.isSuccess && chaves.length > 0 && (
        <table aria-label="Chaves" className={TABELA}>
          <thead>
            <tr>
              <th className={CABECALHO}>Sistema</th>
              <th className={cn(CABECALHO, 'w-[22%]')}>Escopos</th>
              <th className={cn(CABECALHO, 'hidden w-[18%] md:table-cell')}>Id</th>
              <th className={cn(CABECALHO, 'hidden w-28 sm:table-cell')}>Criada em</th>
              <th className={cn(CABECALHO, 'w-[30%] sm:w-48')}>Situação</th>
              <th className={cn(CABECALHO, 'w-10')}>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {chaves.map((c) => {
              const revogada = c.revogada_em !== null
              return (
                <Fragment key={c.id}>
                  <tr className="hover:bg-card">
                    <td className={cn(CELULA, 'truncate font-medium')}>{c.sistema}</td>
                    <td className={cn(CELULA, 'truncate font-mono text-xs')}>{c.escopos.join(', ')}</td>
                    <td className={cn(CELULA, 'hidden truncate font-mono text-xs text-muted-foreground md:table-cell')}>{c.id}</td>
                    <td className={cn(CELULA, 'hidden tabular-nums sm:table-cell')}>{data(c.criada_em)}</td>
                    <td className={CELULA}>
                      {revogada ? <Selo tom="neutro">{`Revogada em ${data(c.revogada_em!)}`}</Selo> : <Selo tom="ok">Ativa</Selo>}
                    </td>
                    <td className={cn(CELULA, 'text-right')}>
                      {!revogada && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon-sm" aria-label={`Revogar a chave de ${c.sistema}`} onClick={() => setRevogando(c.id)}>
                              <IconKeyOff stroke={1.75} aria-hidden />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Revogar</TooltipContent>
                        </Tooltip>
                      )}
                    </td>
                  </tr>
                  {revogando === c.id && (
                    <tr className="bg-destructive/12" onKeyDown={(e) => e.key === 'Escape' && setRevogando(null)}>
                      <td colSpan={6} className={CELULA}>
                        <div className="flex flex-wrap items-center gap-2 py-1">
                          <span>{`Revogar a chave de ${c.sistema}? Ela para de funcionar na hora.`}</span>
                          <Button type="button" size="sm" variant="destructive" autoFocus aria-label="Confirmar revogação" onClick={() => void revogar(c)}>
                            Revogar
                          </Button>
                          <Button type="button" size="sm" variant="secondary" onClick={() => setRevogando(null)}>
                            Cancelar
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      )}
      {emitindo && (
        <EmitirChave
          aoFechar={() => setEmitindo(false)}
          aoEmitir={async (corpo) => {
            const { chave, ...registro } = await api.chaves.emitir(corpo)
            gravar((atuais) => [registro, ...atuais])
            setFalha(null)
            setAviso(null)
            return chave
          }}
        />
      )}
    </Aba>
  )
}
