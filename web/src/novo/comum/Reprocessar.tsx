import { IconBrain, IconDatabase, IconFaceId, IconListSearch, IconLoader2, IconRefresh, IconScan, type Icon } from '@tabler/icons-react'
import { cn } from 'cn'
import { useId, useState } from 'react'
import { codigoDoErro, ConflitoNaApi, PedidoInvalido, SessaoExpirada } from '../../api.ts'
import { ETAPAS_ESCOLHIVEIS, impactoDoReprocessamento, nomeDaEtapa, type EtapaEscolhivel } from '../../etapas.ts'
import type { Job } from '../../jobs.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog.tsx'
import { Falha } from './Falha.tsx'

const ICONES: Record<EtapaEscolhivel, Icon> = {
  analise: IconBrain,
  identificacao: IconFaceId,
  quadros_chave: IconScan,
  inventario_de_objetos: IconListSearch,
  indexacao: IconDatabase,
}

type Alvo = Pick<Job, 'id' | 'nome'>

/** Reprocessar a partir de uma etapa, com o motivo (fica na auditoria). O Job que a API devolve vai a `aoReprocessar`. */
export function Reprocessar({
  video,
  aoFechar,
  aoReprocessar,
}: {
  video: Alvo | null
  aoFechar: () => void
  aoReprocessar: (job: Job, etapa: EtapaEscolhivel) => void
}) {
  return (
    <Dialog open={video !== null} onOpenChange={(aberto) => !aberto && aoFechar()}>
      {video && <Corpo key={video.id} video={video} aoFechar={aoFechar} aoReprocessar={aoReprocessar} />}
    </Dialog>
  )
}

function Corpo({ video, aoFechar, aoReprocessar }: { video: Alvo; aoFechar: () => void; aoReprocessar: (job: Job, etapa: EtapaEscolhivel) => void }) {
  const api = useApi()
  const ids = useId()
  const [etapa, setEtapa] = useState<EtapaEscolhivel>('analise')
  const [motivo, setMotivo] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [falha, setFalha] = useState<{ mensagem: string; codigo: string | null } | null>(null)
  const indice = ETAPAS_ESCOLHIVEIS.findIndex((e) => e.valor === etapa)

  async function confirmar() {
    setEnviando(true)
    setFalha(null)
    try {
      aoReprocessar(await api.job(video.id).reprocessar(etapa, motivo.trim()), etapa)
    } catch (e) {
      if (e instanceof SessaoExpirada) return
      setFalha(
        e instanceof ConflitoNaApi || e instanceof PedidoInvalido
          ? { mensagem: e.message, codigo: null }
          : { mensagem: 'Não foi possível reprocessar. Tente de novo em instantes.', codigo: codigoDoErro(e) },
      )
    } finally {
      setEnviando(false)
    }
  }

  const segurar = (e: Event) => enviando && e.preventDefault()
  return (
    <DialogContent className="sm:max-w-xl" mostrarFechar={!enviando} onEscapeKeyDown={segurar} onPointerDownOutside={segurar} onInteractOutside={segurar}>
      <DialogTitle className="flex items-center gap-2 pr-8">
        <IconRefresh size={20} stroke={1.75} className="shrink-0 text-muted-foreground" aria-hidden /> Reprocessar
      </DialogTitle>
      <DialogDescription className="break-all">{video.nome}</DialogDescription>
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (motivo.trim() && !enviando) void confirmar()
        }}
      >
        <fieldset className="grid gap-1">
          <legend className="mb-2 text-sm text-muted-foreground">A partir de qual etapa? Ela e as seguintes rodam de novo; as anteriores ficam como estão.</legend>
          {ETAPAS_ESCOLHIVEIS.map((e, i) => {
            const marcada = e.valor === etapa
            const Icone = ICONES[e.valor]
            return (
              <label
                key={e.valor}
                className={cn(
                  'flex cursor-pointer items-center gap-3 rounded-sm border px-3 py-2 transition-colors has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring',
                  marcada ? 'border-primary bg-selected' : i > indice ? 'border-strong bg-card hover:bg-accent' : 'border-border hover:bg-accent',
                )}
              >
                <input type="radio" name={ids} value={e.valor} checked={marcada} onChange={() => setEtapa(e.valor)} disabled={enviando} className="sr-only" />
                <Icone size={20} stroke={1.5} className={cn('shrink-0', marcada ? 'text-link' : 'text-muted-foreground')} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{nomeDaEtapa(e.valor)}</span>
                  <span className="block text-xs text-muted-foreground">{e.refaz}</span>
                </span>
                {i >= indice && (
                  <span className="hidden shrink-0 text-xs text-muted-foreground sm:block" aria-hidden>
                    {marcada ? 'começa aqui' : 'roda de novo'}
                  </span>
                )}
              </label>
            )
          })}
        </fieldset>
        <div className="grid gap-1">
          <label htmlFor={`${ids}-motivo`} className="text-xs font-medium">
            Motivo <span className="text-destructive">*</span>
          </label>
          <textarea
            id={`${ids}-motivo`}
            required
            rows={2}
            maxLength={500}
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            aria-describedby={`${ids}-auditoria`}
            className="rounded-sm border border-strong bg-input px-2 py-1 text-sm"
          />
          <span id={`${ids}-auditoria`} className="text-xs text-muted-foreground">
            Fica na auditoria.
          </span>
        </div>
        <p className="text-base">{impactoDoReprocessamento(etapa)}</p>
        {falha && <Falha mensagem={falha.mensagem} codigo={falha.codigo} />}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="secondary" onClick={aoFechar} disabled={enviando}>
            Cancelar
          </Button>
          <Button type="submit" disabled={motivo.trim() === '' || enviando}>
            {enviando ? <IconLoader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <IconRefresh stroke={1.75} aria-hidden />}
            Reprocessar
          </Button>
        </div>
      </form>
    </DialogContent>
  )
}
