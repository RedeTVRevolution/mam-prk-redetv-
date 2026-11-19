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
 * o histórico. `entrar` só liga o modo (começar uma correção fora dele, #743). Aprovar espera a
 * correção aberta e as gravações em curso (`ocupar`), para não indexar antes de a correção chegar.
 * `desfazer` (Ctrl+Z) desfaz a correção mais recente do próprio editor.
 */
export function useRevisao({
  id,
  pode,
  decupagemPronta,
  catalogo,
  historico,
  mostrarAviso,
  aoAlternar,
  comCorrecaoAberta,
}: {
  id: string
  pode: boolean
  decupagemPronta: boolean
  catalogo: CatalogoDeCorrecoes | undefined
  historico: ItemDoHistorico[] | undefined
  mostrarAviso: (texto: string) => void
  /** Chamado a cada entrada e saída: o que a revisão abriu (trecho, marcas) se descarta aqui. */
  aoAlternar: () => void
  /** Um formulário ou uma confirmação de correção aberta (inclusive juntar, dividir e trecho): aprovar a revisão espera por ela. */
  comCorrecaoAberta: boolean
}) {
  const api = useApi()
  const consultas = useQueryClient()
  const cliente = useMemo(() => api.job(id), [api, id])
  const [revisando, setRevisando] = useState(false)
  const desfazendo = useRef(false)
  // Uma ref, não um estado: a gravação pode terminar entre o render e o E.
  const gravando = useRef(0)
  const eu = useQuery({ queryKey: ['eu'], queryFn: () => api.eu(), enabled: pode && revisando, retry: false, staleTime: Infinity })
  const doEditor = (h: ItemDoHistorico[]) => h.find((c) => c.autor_email === eu.data?.email && desfazivel(c))
  const temParaDesfazer = !!historico && !!doEditor(historico)

  function alternar() {
    if (!pode) return
    if (!decupagemPronta) {
      mostrarAviso('Espere a decupagem carregar para revisar ou aprovar a revisão.')
      return
    }
    if (revisando && comCorrecaoAberta) {
      mostrarAviso('Salve ou cancele a correção aberta antes de aprovar a revisão.')
      return
    }
    if (revisando && gravando.current > 0) {
      mostrarAviso('Espere a correção ser gravada para aprovar a revisão.')
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

  /** Liga o modo sem aprovar nada. Não espera a decupagem: uma decisão da gaveta grava sem ela (#744). */
  function entrar() {
    if (!pode || revisando) return
    aoAlternar()
    setRevisando(true)
  }

  /** Conta a gravação em curso até ela terminar, mesmo que o formulário ou a gaveta saiam da tela. */
  async function ocupar<T>(gravacao: Promise<T>): Promise<T> {
    gravando.current += 1
    try {
      return await gravacao
    } finally {
      gravando.current -= 1
    }
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

  return { revisando, alternar, entrar, ocupar, desfazer, temParaDesfazer }
}

export type Revisao = ReturnType<typeof useRevisao>
