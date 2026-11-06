import { cn } from 'cn'
import { type KeyboardEvent, type RefObject, useEffect, useRef, useState } from 'react'
import { emCampoDeTexto } from '../../atalhos.ts'
import type { Editor, Pedido } from '../../catalogacao.ts'
import type { CatalogoDeCorrecoes } from '../../catalogo.ts'
import type { Pessoa } from '../../decupagem.ts'
import type { Intervalo } from '../../linhaDoTempo.ts'
import { ABAS_DO_TRECHO, type AbaDoTrecho, editorDoTrecho } from '../../trecho.ts'
import { FormularioDeCorrecao } from './Correcao.tsx'

/** O campo único do trecho marcado: o tipo em abas (`1` a `5` ou o clique) e o formulário do tipo. */
export function FormularioDoTrecho({
  trecho,
  catalogo,
  pessoas,
  salvarRef,
  aoSalvar,
  aoCancelar,
}: {
  trecho: Intervalo
  catalogo: CatalogoDeCorrecoes
  /** As pessoas do vídeo, para o dono do objeto. */
  pessoas: Pessoa[]
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
    setEditor(aba ? editorDoTrecho(aba, trecho, catalogo, pessoas) : null)
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
    <div ref={raiz} tabIndex={-1} onKeyDown={aoTeclar} className="grid gap-2 border-b border-border p-3 outline-none">
      <div role="tablist" aria-label="Tipo do trecho" className="flex flex-wrap gap-1">
        {ABAS_DO_TRECHO.map((a) => (
          <button
            key={a.valor}
            type="button"
            role="tab"
            aria-selected={aba === a.valor}
            title={`${a.rotulo} (${a.tecla})`}
            onClick={() => setAba(a.valor)}
            className={cn(
              'h-7 rounded-sm border px-2 text-xs font-medium whitespace-nowrap transition-colors',
              aba === a.valor ? 'border-transparent bg-selected text-link' : 'border-strong text-muted-foreground hover:bg-accent hover:text-foreground',
            )}
          >
            {a.rotulo}
          </button>
        ))}
      </div>
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
        <p className="text-xs text-muted-foreground">Escolha o tipo: {ABAS_DO_TRECHO.map((a) => `${a.tecla} ${a.rotulo}`).join(' · ')} · Esc cancela</p>
      )}
    </div>
  )
}
