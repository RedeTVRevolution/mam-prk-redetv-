import { Button, Group, Stack, Text, Tooltip } from '@mantine/core'
import { type KeyboardEvent, type RefObject, useEffect, useRef, useState } from 'react'
import { emCampoDeTexto } from './atalhos.ts'
import type { Editor, Pedido } from './catalogacao.ts'
import type { CatalogoDeCorrecoes } from './catalogo.ts'
import { FormularioDeCorrecao } from './FormularioDeCorrecao.tsx'
import type { Intervalo } from './linhaDoTempo.ts'
import { ABAS_DO_TRECHO, type AbaDoTrecho, editorDoTrecho } from './trecho.ts'

/** O campo único do trecho marcado: o tipo em abas (`1` a `5` ou o clique) e o formulário do tipo. */
export function FormularioDoTrecho({
  trecho,
  catalogo,
  salvarRef,
  aoSalvar,
  aoCancelar,
}: {
  trecho: Intervalo
  catalogo: CatalogoDeCorrecoes
  /** Recebe o salvar do formulário aberto, para o Enter nas alças gravar como o Enter nos campos. */
  salvarRef?: RefObject<(() => void) | null>
  aoSalvar: (pedidos: Pedido[], motivo: string) => Promise<string | null>
  aoCancelar: () => void
}) {
  const [aba, setAba] = useState<AbaDoTrecho | null>(null)
  const raiz = useRef<HTMLDivElement>(null)
  // O foco começa fora dos campos, para o número da aba não ser digitado num campo.
  useEffect(() => raiz.current?.focus(), [])
  const [editor, setEditor] = useState<Editor | null>(null)
  const [editorDe, setEditorDe] = useState<AbaDoTrecho | null>(null)
  // O editor nasce com a aba e com o trecho de então; as alças ajustam os campos depois (`tempos`).
  if (aba !== editorDe) {
    setEditorDe(aba)
    setEditor(aba ? editorDoTrecho(aba, trecho, catalogo) : null)
  }

  function aoTeclar(e: KeyboardEvent<HTMLDivElement>) {
    if (emCampoDeTexto(e.target)) return
    const doNumero = ABAS_DO_TRECHO.find((a) => a.tecla === e.key)
    if (doNumero) {
      e.preventDefault()
      setAba(doNumero.valor)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      aoCancelar()
    }
  }

  return (
    <Stack ref={raiz} gap="xs" tabIndex={-1} mb="xs" style={{ outline: 'none' }} onKeyDown={aoTeclar}>
      <Group gap="xs" role="tablist" aria-label="Tipo do trecho">
        {ABAS_DO_TRECHO.map((a) => (
          <Tooltip key={a.valor} label={`${a.rotulo} (${a.tecla})`}>
            <Button
              size="compact-xs"
              role="tab"
              aria-selected={aba === a.valor}
              variant={aba === a.valor ? 'filled' : 'default'}
              onClick={() => setAba(a.valor)}
            >
              {a.rotulo}
            </Button>
          </Tooltip>
        ))}
      </Group>
      {editor && aba ? (
        <FormularioDeCorrecao
          key={aba}
          editor={editor}
          rotulo="Descrever o trecho"
          limiteDoMotivo={catalogo.limites.motivo}
          tempos={trecho}
          salvarRef={salvarRef}
          aoSalvar={aoSalvar}
          aoCancelar={aoCancelar}
        />
      ) : (
        <Text size="xs" c="dimmed">
          Escolha o tipo: {ABAS_DO_TRECHO.map((a) => `${a.tecla} ${a.rotulo}`).join(' · ')} · Esc cancela
        </Text>
      )}
    </Stack>
  )
}
