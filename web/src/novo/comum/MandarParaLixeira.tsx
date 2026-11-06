import { IconLoader2, IconTrash } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { SessaoExpirada } from '../../api.ts'
import { falhaDaAcao, type Falha as FalhaDaAcao } from '../../falhaDaAcao.ts'
import type { Job } from '../../jobs.ts'
import { frasesDoImpacto } from '../../lixeira.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog.tsx'
import { Falha } from './Falha.tsx'

type Alvo = Pick<Job, 'id' | 'nome'>

/**
 * Mandar o vídeo para a lixeira: mostra o que vai junto, pede o motivo e manda com um clique.
 * O botão só se solta com o impacto calculado e o motivo preenchido. `video` nulo fecha.
 */
export function MandarParaLixeira({ video, aoFechar, aoMandar }: { video: Alvo | null; aoFechar: () => void; aoMandar: (video: Alvo) => void }) {
  return (
    <Dialog open={video !== null} onOpenChange={(aberto) => !aberto && aoFechar()}>
      {/* O corpo é montado a cada abertura: o motivo e a falha não passam de um vídeo a outro. */}
      {video && <Corpo key={video.id} video={video} aoFechar={aoFechar} aoMandar={aoMandar} />}
    </Dialog>
  )
}

function Corpo({ video, aoFechar, aoMandar }: { video: Alvo; aoFechar: () => void; aoMandar: (video: Alvo) => void }) {
  const api = useApi()
  const idDoMotivo = useId()
  const [motivo, setMotivo] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [falha, setFalha] = useState<FalhaDaAcao | null>(null)
  const impacto = useQuery({
    queryKey: ['lixeira', 'impacto', video.id],
    queryFn: () => api.lixeira.impacto('video', video.id),
    retry: false,
    gcTime: 0,
  })
  const frases = impacto.data ? frasesDoImpacto('video', impacto.data) : null
  const falhaDoImpacto =
    impacto.isError && !(impacto.error instanceof SessaoExpirada)
      ? falhaDaAcao(impacto.error, 'Não foi possível calcular o que vai junto. Tente de novo.')
      : null
  const pronto = frases !== null && motivo.trim() !== '' && !enviando

  async function mandar() {
    setEnviando(true)
    setFalha(null)
    try {
      await api.lixeira.enviar('video', video.id, motivo.trim())
      aoMandar(video)
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível mandar ${video.nome} para a lixeira. Tente de novo.`))
    } finally {
      setEnviando(false)
    }
  }

  // Enquanto manda, nem o Esc nem o clique fora fecham.
  const segurar = (e: Event) => enviando && e.preventDefault()
  return (
    <DialogContent className="sm:max-w-lg" mostrarFechar={!enviando} onEscapeKeyDown={segurar} onPointerDownOutside={segurar} onInteractOutside={segurar}>
      <DialogTitle className="flex items-start gap-2 pr-8">
        <IconTrash size={20} stroke={1.75} className="mt-0.5 shrink-0 text-destructive" aria-hidden />
        <span className="min-w-0 break-words">Mandar {video.nome} para a lixeira</span>
      </DialogTitle>
      <DialogDescription>Sai da busca, do acervo e dos relatórios na hora. Nada é destruído: dá para restaurar em até 30 dias.</DialogDescription>
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (pronto) void mandar()
        }}
      >
        <section aria-label="O que vai junto" className="grid gap-1 rounded-sm border bg-card p-3 text-base">
          {impacto.isPending && (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <IconLoader2 size={16} className="animate-spin motion-reduce:animate-none" aria-hidden /> Calculando o que vai junto…
            </p>
          )}
          {frases?.map((f) => <p key={f}>{f}</p>)}
          {falhaDoImpacto && <Falha mensagem={falhaDoImpacto.mensagem} codigo={falhaDoImpacto.codigo} aoTentar={() => void impacto.refetch()} />}
        </section>
        <div className="grid gap-1">
          <label htmlFor={idDoMotivo} className="text-xs font-medium">
            Motivo <span className="text-destructive">*</span>
          </label>
          <input
            id={idDoMotivo}
            required
            autoFocus
            value={motivo}
            maxLength={500}
            onChange={(e) => setMotivo(e.target.value)}
            className="h-8 rounded-sm border border-strong bg-input px-2 text-sm"
          />
        </div>
        {falha && <Falha mensagem={falha.mensagem} codigo={falha.codigo} />}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="secondary" onClick={aoFechar} disabled={enviando}>
            Cancelar
          </Button>
          <Button type="submit" variant="destructive" disabled={!pronto}>
            {enviando ? <IconLoader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <IconTrash stroke={1.75} aria-hidden />}
            Mandar para a lixeira
          </Button>
        </div>
      </form>
    </DialogContent>
  )
}
