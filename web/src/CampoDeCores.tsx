import { Button, Group, Text, Tooltip } from '@mantine/core'
import { type KeyboardEvent, useState } from 'react'
import { useAtalhos } from './atalhos.ts'
import { teclasDasOpcoes } from './catalogacao.ts'
import type { Opcao } from './catalogo.ts'

const GRUPO = 'Cor base do objeto'

/**
 * As cores da lista fechada como botões ligáveis, cada um com a letra do atalho: a tecla (com o foco
 * no grupo) e o clique marcam e desmarcam. Passou de `maximo`, a cor não marca e o campo diz por quê.
 */
export function CampoDeCores({
  rotulo,
  opcoes,
  maximo,
  valor,
  aoMudar,
}: {
  rotulo: string
  opcoes: Opcao[]
  maximo: number
  valor: string[]
  aoMudar: (valor: string[]) => void
}) {
  const teclas = teclasDasOpcoes(opcoes)
  const [recusada, setRecusada] = useState(false)
  const marcadas = valor.filter((v) => opcoes.some((o) => o.valor === v))

  useAtalhos(
    opcoes.flatMap((o) => {
      const letra = teclas.get(o.valor)
      return letra ? [{ tecla: letra.toUpperCase(), acao: `Marcar ou desmarcar ${o.rotulo}`, grupo: GRUPO }] : []
    }),
  )

  function alternar(o: Opcao) {
    if (valor.includes(o.valor)) {
      setRecusada(false)
      aoMudar(valor.filter((v) => v !== o.valor))
    } else if (marcadas.length >= maximo) {
      setRecusada(true)
    } else {
      setRecusada(false)
      aoMudar([...valor, o.valor])
    }
  }

  function aoTeclar(e: KeyboardEvent<HTMLDivElement>) {
    if (e.ctrlKey || e.metaKey || e.altKey) return
    const o = opcoes.find((x) => teclas.get(x.valor) === e.key.toLowerCase())
    if (!o) return
    // O atalho é do grupo: nem o registro global das telas, nem o Enter do formulário veem esta tecla.
    e.preventDefault()
    e.stopPropagation()
    alternar(o)
  }

  return (
    <div>
      <Text size="xs" fw={500}>
        {rotulo}
      </Text>
      <Group role="group" aria-label={rotulo} gap={4} mt={2} onKeyDown={aoTeclar}>
        {opcoes.map((o) => {
          const letra = teclas.get(o.valor)
          const ligada = valor.includes(o.valor)
          return (
            <Tooltip key={o.valor} label={letra ? `Tecla ${letra.toUpperCase()}` : o.rotulo} disabled={!letra}>
              <Button
                size="compact-xs"
                variant={ligada ? 'filled' : 'default'}
                aria-pressed={ligada}
                aria-label={o.rotulo}
                aria-keyshortcuts={letra?.toUpperCase()}
                onClick={() => alternar(o)}
              >
                {o.rotulo}
                {letra ? ` (${letra.toUpperCase()})` : ''}
              </Button>
            </Tooltip>
          )
        })}
      </Group>
      {recusada && (
        <Text size="xs" role="alert" c="red.4" mt={2}>
          {`No máximo ${maximo} cores: desmarque uma antes de marcar outra.`}
        </Text>
      )}
    </div>
  )
}
