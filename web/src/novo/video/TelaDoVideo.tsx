import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { codigoDoErro, NaoEncontrado, SessaoExpirada } from '../../api.ts'
import { finalizando, type Job } from '../../jobs.ts'
import { ACERVO, seguir } from '../../rotas.ts'
import { useApi } from '../consultas.ts'
import { AvisoDeFalha } from './comum.tsx'
import { chaveDoVideo } from './tipos.ts'
import { Video, type Permissoes } from './Video.tsx'

/** De quanto em quanto a tela pergunta pelo Job enquanto as etapas rodam, e pelo índice depois de uma correção. */
export interface Intervalos {
  acompanhamentoMs: number
  indexacaoMs: number
}

const INTERVALOS: Intervalos = { acompanhamentoMs: 5000, indexacaoMs: 2000 }

/**
 * A tela do vídeo a partir do endereço: busca o Job e, com ele, o player, a linha do tempo e o
 * inspetor. Com as etapas rodando (aberto assim ou depois de reprocessar), acompanha o Job até o
 * fim e então recarrega a decupagem.
 */
export function TelaDoVideo({
  id,
  t,
  permissoes,
  intervalos = INTERVALOS,
}: {
  id: string
  t: number | null
  permissoes: readonly string[]
  intervalos?: Intervalos
}) {
  const api = useApi()
  const consultas = useQueryClient()
  // Aberto com as etapas depois da análise rodando, a tela já acompanha até o fim.
  const [acompanhando, setAcompanhando] = useState<boolean | null>(null)
  const [reprocessou, setReprocessou] = useState(false)
  const consulta = useQuery({
    queryKey: chaveDoVideo(id, 'job'),
    queryFn: () => api.job(id).detalhe(),
    retry: false,
    staleTime: Infinity,
    refetchInterval: (q) => (acompanhando && q.state.data && emAndamento(q.state.data) ? intervalos.acompanhamentoMs : false),
  })
  const job = consulta.data

  if (job && acompanhando === null) setAcompanhando(finalizando(job))
  const andando = job ? emAndamento(job) : false
  useEffect(() => {
    if (!acompanhando || andando) return
    // Identificação e quadros-chave regravam a Decupagem com o Job sempre `concluido`.
    // oxlint-disable-next-line react/set-state-in-effect
    setAcompanhando(false)
    void consultas.invalidateQueries({ queryKey: chaveDoVideo(id, 'decupagem') })
  }, [acompanhando, andando, consultas, id])

  if (consulta.isPending) {
    return (
      <p role="status" className="m-auto p-8 text-muted-foreground">
        Carregando o vídeo…
      </p>
    )
  }
  if (consulta.isError) {
    if (consulta.error instanceof SessaoExpirada) return null
    const ausente = consulta.error instanceof NaoEncontrado
    return (
      <div className="m-auto grid w-full max-w-sm gap-3 p-6">
        <AvisoDeFalha
          mensagem={ausente ? 'Vídeo não encontrado.' : 'Não foi possível abrir o vídeo. Tente de novo em instantes.'}
          codigo={ausente ? null : codigoDoErro(consulta.error)}
          aoTentar={ausente ? undefined : () => void consulta.refetch()}
        />
        <a href={ACERVO} onClick={(e) => seguir(e, ACERVO)} className="text-sm text-link hover:underline">
          Voltar ao acervo
        </a>
      </div>
    )
  }

  function aoReprocessar(novo: Job, etapa: string) {
    consultas.setQueryData(chaveDoVideo(id, 'job'), novo)
    setAcompanhando(true)
    setReprocessou(true)
    // Com a análise, a Decupagem antiga some até a nova terminar.
    if (etapa === 'analise') consultas.removeQueries({ queryKey: chaveDoVideo(id, 'decupagem') })
  }

  return (
    <Video
      job={consulta.data}
      t={t}
      pode={permissoesDoVideo(permissoes)}
      reprocessou={reprocessou}
      aoReprocessar={aoReprocessar}
      intervaloDaIndexacaoMs={intervalos.indexacaoMs}
    />
  )
}

/** A análise rodando ou as etapas depois dela (a regra do intervalo entre etapas está em `finalizando`). */
const emAndamento = (job: Job): boolean => job.estado === 'analisando' || finalizando(job)

function permissoesDoVideo(p: readonly string[]): Permissoes {
  return {
    editar: p.includes('decupagem.editar'),
    reprocessar: p.includes('video.reprocessar_etapa'),
    verAuditoria: p.includes('auditoria.ver'),
    apagar: p.includes('lixeira.gerir'),
  }
}
