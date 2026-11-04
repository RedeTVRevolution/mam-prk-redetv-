import { Button, Group, Stack, Text, TextInput, Tooltip } from '@mantine/core'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import type { ClienteDaFusao, ImpactoDaFusao } from './api.ts'
import { CampoDeNome } from './CampoDeNome.tsx'
import { falhaDaAcao } from './falhaDaAcao.ts'

const MOTIVO_PADRAO = 'nome duplicado'

const videos = (n: number) => `${n} ${n === 1 ? 'vídeo' : 'vídeos'}`

/** O efeito da fusão, na frase que a pessoa lê antes de confirmar. */
function efeitoDaFusao(i: ImpactoDaFusao): string {
  const fotos = i.fotos_apagadas > 0 ? ` As fotos de referência de ${i.origem_nome} serão apagadas.` : ''
  return `${i.origem_nome} passa a ser ${i.destino_nome} em ${videos(i.videos)}.${fotos} Enter confirma · Esc cancela.`
}

/**
 * "Fundir com…" na linha da pessoa: escolhe o destino no autocompletar do catálogo, mostra o efeito e,
 * com Enter, funde. O motivo vem preenchido ("nome duplicado") e é editável.
 */
export function FusaoDePessoa({
  origemId,
  nomeDaOrigem,
  fusao,
  limiteDoMotivo,
  aoFundir,
  aoCancelar,
}: {
  /** O id da pessoa no catálogo. */
  origemId: string
  nomeDaOrigem: string
  fusao: ClienteDaFusao
  limiteDoMotivo: number
  /** Chamado depois de fundir, para a tela recarregar a Decupagem. */
  aoFundir: () => void
  aoCancelar: () => void
}) {
  const [destino, setDestino] = useState({ nome: '', id: '' })
  const [motivo, setMotivo] = useState(MOTIVO_PADRAO)
  const [impacto, setImpacto] = useState<ImpactoDaFusao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [fundindo, setFundindo] = useState(false)
  const pedido = useRef(0)
  const raiz = useRef<HTMLFormElement>(null)

  useEffect(() => raiz.current?.querySelector('input')?.focus(), [])

  function escolher(nome: string, id: string) {
    const este = ++pedido.current
    setDestino({ nome, id })
    setImpacto(null)
    setErro(null)
    if (!id) return
    fusao.impacto(origemId, id).then(
      (i) => {
        if (este === pedido.current) setImpacto(i)
      },
      (e: unknown) => {
        if (este === pedido.current) setErro(falhaDaAcao(e, 'Não foi possível calcular o efeito da fusão. Escolha o destino de novo.').mensagem)
      },
    )
  }

  async function confirmar() {
    if (!impacto || fundindo || motivo.trim().length === 0) return
    setFundindo(true)
    setErro(null)
    try {
      await fusao.fundir(origemId, destino.id, motivo.trim())
      aoFundir()
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível fundir as pessoas. Tente de novo.').mensagem)
      setFundindo(false)
    }
  }

  function aoTeclar(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      aoCancelar()
    } else if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault()
      void confirmar()
    }
  }

  return (
    <form ref={raiz} aria-label={`Fundir ${nomeDaOrigem} com`} onKeyDown={aoTeclar} onSubmit={(e) => e.preventDefault()}>
      <Stack gap="xs">
        <CampoDeNome rotulo="Fundir com" catalogo="pessoas" soDoCatalogo valor={destino.nome} aoMudar={escolher} />
        <TextInput
          size="xs"
          label="Motivo"
          maxLength={limiteDoMotivo}
          value={motivo}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {impacto && <Text size="xs">{efeitoDaFusao(impacto)}</Text>}
        {erro && (
          <Text size="xs" role="alert" c="red.4">
            {erro}
          </Text>
        )}
        <Group gap="xs" justify="flex-end">
          <Tooltip label="Esc">
            <Button size="compact-xs" variant="default" onClick={aoCancelar}>
              Cancelar
            </Button>
          </Tooltip>
          <Tooltip label="Enter">
            <Button size="compact-xs" loading={fundindo} disabled={!impacto} onClick={() => void confirmar()}>
              Fundir
            </Button>
          </Tooltip>
        </Group>
      </Stack>
    </form>
  )
}
