import { IconLoader2, IconPencil } from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { useState } from 'react'
import { SessaoExpirada } from '../../api.ts'
import { hoje } from '../../envio/arquivo.ts'
import { falhaDaAcao, type Falha as FalhaDaAcao } from '../../falhaDaAcao.ts'
import type { Job } from '../../jobs.ts'
import { trocarNoAcervo } from '../acervo/useAcervo.ts'
import { Falha } from '../comum/Falha.tsx'
import { useApi, useProgramas } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog.tsx'
import { BotaoDeIcone } from './comum.tsx'
import { chaveDoVideo } from './tipos.ts'

const CAMPO = 'h-8 w-full rounded-sm border border-strong bg-input px-2 text-sm font-normal disabled:opacity-50'

/** O botão "Editar" ao lado da data e do programa: abre o diálogo que muda os dois (#519). */
export function EdicaoDoVideo({ job }: { job: Job }) {
  const [aberto, setAberto] = useState(false)
  return (
    <>
      <BotaoDeIcone rotulo="Editar data e programa" onClick={() => setAberto(true)}>
        <IconPencil size={16} stroke={1.75} aria-hidden />
      </BotaoDeIcone>
      <Dialog open={aberto} onOpenChange={setAberto}>
        {/* O corpo é montado a cada abertura: os campos partem do que o vídeo tem agora. */}
        {aberto && <Corpo job={job} aoFechar={() => setAberto(false)} />}
      </Dialog>
    </>
  )
}

function Corpo({ job, aoFechar }: { job: Job; aoFechar: () => void }) {
  const api = useApi()
  const consultas = useQueryClient()
  const programas = useProgramas()
  const [data, setData] = useState(job.data_exibicao ?? '')
  const [programa, setPrograma] = useState(job.programa ?? '')
  const [salvando, setSalvando] = useState(false)
  const [falha, setFalha] = useState<FalhaDaAcao | null>(null)
  const corpo = {
    ...(data && data !== job.data_exibicao ? { data_exibicao: data } : {}),
    ...(programa && programa !== job.programa ? { programa } : {}),
  }
  const mudou = Object.keys(corpo).length > 0

  async function salvar() {
    setSalvando(true)
    setFalha(null)
    try {
      const novo = await api.job(job.id).editar(corpo)
      consultas.setQueryData(chaveDoVideo(job.id, 'job'), novo)
      trocarNoAcervo(consultas, novo)
      aoFechar()
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível salvar. Tente de novo.'))
      setSalvando(false)
    }
  }

  return (
    <DialogContent className="sm:max-w-md" mostrarFechar={!salvando}>
      <DialogTitle>Editar data e programa</DialogTitle>
      <DialogDescription>O vídeo é indexado de novo na busca e nos relatórios. A decupagem não é refeita.</DialogDescription>
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (mudou && !salvando) void salvar()
        }}
      >
        <label className="grid gap-1 text-xs font-medium">
          Data de exibição
          <input type="date" value={data} max={hoje()} onChange={(e) => setData(e.target.value)} disabled={salvando} className={cn(CAMPO, 'scheme-dark')} />
        </label>
        <label className="grid gap-1 text-xs font-medium">
          Programa
          <select value={programa} onChange={(e) => setPrograma(e.target.value)} disabled={salvando} className={CAMPO}>
            {!job.programa && <option value="">Sem programa</option>}
            {programas.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        {falha && <Falha mensagem={falha.mensagem} codigo={falha.codigo} />}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="secondary" onClick={aoFechar} disabled={salvando}>
            Cancelar
          </Button>
          <Button type="submit" disabled={!mudou || salvando}>
            {salvando && <IconLoader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
            Salvar
          </Button>
        </div>
      </form>
    </DialogContent>
  )
}
