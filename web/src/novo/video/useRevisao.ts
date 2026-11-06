import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import { SessaoExpirada } from '../../api.ts'
import { desfazivel } from '../../catalogacao.ts'
import { type CatalogoDeCorrecoes, rotuloDe } from '../../catalogo.ts'
import type { ItemDoHistorico } from '../../decupagem.ts'
import { useApi } from '../consultas.ts'
import { chaveDoVideo } from './tipos.ts'

const MOTIVO_DO_DESFAZER = 'correção desfeita pelo editor'

/**
 * O modo de revisão (tecla E): `alternar` entra nele e, dentro dele, aprova a revisão. Aprovar sai do
 * modo na hora e pede a reindexação em segundo plano (#328): a tela não espera por ela, só acompanha
 * o histórico. `desfazer` (Ctrl+Z) desfaz a correção mais recente do próprio editor.
 */
export function useRevisao({
  id,
  pode,
  decupagemPronta,
  catalogo,
  historico,
  mostrarAviso,
  aoAlternar,
}: {
  id: string
  pode: boolean
  decupagemPronta: boolean
  catalogo: CatalogoDeCorrecoes | undefined
  historico: ItemDoHistorico[] | undefined
  mostrarAviso: (texto: string) => void
  /** Chamado a cada entrada e saída: o que a revisão abriu (trecho, marcas) se descarta aqui. */
  aoAlternar: () => void
}) {
  const api = useApi()
  const consultas = useQueryClient()
  const cliente = useMemo(() => api.job(id), [api, id])
  const [revisando, setRevisando] = useState(false)
  const desfazendo = useRef(false)
  const eu = useQuery({ queryKey: ['eu'], queryFn: () => api.eu(), enabled: pode && revisando, retry: false, staleTime: Infinity })
  const doEditor = (h: ItemDoHistorico[]) => h.find((c) => c.autor_email === eu.data?.email && desfazivel(c))
  const temParaDesfazer = !!historico && !!doEditor(historico)

  function alternar() {
    if (!pode) return
    if (!decupagemPronta) {
      mostrarAviso('Espere a decupagem carregar para revisar ou aprovar a revisão.')
      return
    }
    aoAlternar()
    if (revisando)
      cliente.aprovarRevisao().then(
        () => void consultas.invalidateQueries({ queryKey: chaveDoVideo(id, 'historico') }),
        (e) => {
          if (!(e instanceof SessaoExpirada)) mostrarAviso('Não foi possível atualizar o índice: aprove a revisão de novo.')
        },
      )
    setRevisando(!revisando)
  }

  async function desfazer() {
    if (!revisando || desfazendo.current) return
    desfazendo.current = true
    try {
      const [quem, todas] = await Promise.all([
        consultas.fetchQuery({ queryKey: ['eu'], queryFn: () => api.eu(), staleTime: Infinity }),
        consultas.fetchQuery({ queryKey: chaveDoVideo(id, 'historico'), queryFn: () => cliente.historico(), staleTime: 0 }),
      ])
      const ultima = todas.find((c) => c.autor_email === quem.email && desfazivel(c))
      if (!ultima) {
        mostrarAviso('Nada para desfazer neste vídeo.')
        return
      }
      await cliente.desfazer(ultima.id, MOTIVO_DO_DESFAZER)
      void consultas.invalidateQueries({ queryKey: chaveDoVideo(id, 'decupagem') })
      void consultas.invalidateQueries({ queryKey: chaveDoVideo(id, 'historico') })
      const rotulo = catalogo ? rotuloDe(catalogo.tipos, ultima.tipo) : ultima.tipo
      mostrarAviso(`Desfeito: ${rotulo} (${ultima.depois_legivel} → ${ultima.antes_legivel})`)
    } catch (e) {
      if (!(e instanceof SessaoExpirada)) mostrarAviso('Não foi possível desfazer a correção.')
    } finally {
      desfazendo.current = false
    }
  }

  return { revisando, alternar, desfazer, temParaDesfazer }
}

export type Revisao = ReturnType<typeof useRevisao>
