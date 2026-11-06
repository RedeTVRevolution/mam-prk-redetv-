import { cn } from 'cn'
import { type KeyboardEvent, type ReactNode, type RefObject, useContext, useEffect, useId, useRef, useState } from 'react'
import type { CatalogoDeNomes, NomeDoCatalogo } from '../../api.ts'
import { useAtalhos } from '../../atalhos.ts'
import { type CampoDoEditor, type Editor, idDoNome, teclasDasOpcoes, type Valor } from '../../catalogacao.ts'
import type { Opcao } from '../../catalogo.ts'
import { type Intervalo, relogio } from '../../linhaDoTempo.ts'
import { NomesDoCatalogo } from '../../nomesDoCatalogo.ts'
import { Button } from '../ui/button.tsx'

// A mesma regra do `FormularioDeCorrecao.tsx` da interface atual (o `Editor` do `catalogacao.ts`),
// com os campos em Tailwind: Enter salva e Esc cancela, sem diálogo.

export const CAMPO =
  'h-8 w-full min-w-0 rounded-sm border border-strong bg-input px-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary'

export function Rotulo({ texto, children }: { texto: string; children: ReactNode }) {
  return (
    <label className="grid gap-1 text-xs font-medium">
      <span>{texto}</span>
      {children}
    </label>
  )
}

export function FormularioDeCorrecao({
  editor,
  rotulo,
  limiteDoMotivo,
  tempos,
  salvarRef,
  aoSalvar,
  aoCancelar,
}: {
  editor: Editor
  /** O nome acessível do formulário ("Corrigir Leão Lobo"). */
  rotulo: string
  limiteDoMotivo: number
  /** Os tempos que as alças da linha do tempo ajustaram; valem no lugar dos campos de tempo. */
  tempos?: Intervalo | null
  /** Recebe o salvar do formulário, para o Enter nas alças gravar como o Enter nos campos. */
  salvarRef?: RefObject<(() => void) | null>
  /** Grava os pedidos com o motivo; devolve a mensagem de erro, ou `null` quando gravou. */
  aoSalvar: (pedidos: NonNullable<ReturnType<Editor['pedidos']>>, motivo: string) => Promise<string | null>
  aoCancelar: () => void
}) {
  const [valores, setValores] = useState<Record<string, Valor>>(editor.inicial)
  const [motivo, setMotivo] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)
  // As alças mandam nos campos de tempo até a pessoa digitar neles.
  const [exatos, setExatos] = useState<Intervalo | null>(null)
  const [temposVistos, setTemposVistos] = useState<Intervalo | null | undefined>(undefined)
  if (tempos !== temposVistos) {
    setTemposVistos(tempos)
    if (tempos) {
      setExatos(tempos)
      setValores((v) => ({ ...v, inicio: relogio(tempos.inicio_ms), fim: relogio(tempos.fim_ms) }))
    }
  }
  const raiz = useRef<HTMLFormElement>(null)
  useEffect(() => {
    raiz.current?.querySelector<HTMLElement>('input, textarea, select')?.focus()
  }, [])

  const pedidos = editor.pedidos(valores, exatos)
  const doGesto = pedidos && pedidos.length > 0 ? editor.motivo(pedidos) : ''

  function mudar(campo: CampoDoEditor, valor: Valor) {
    if (campo.tipo === 'tempo') setExatos(null)
    setValores((v) => ({ ...v, [campo.chave]: valor }))
  }

  async function salvar() {
    if (salvando) return
    if (!pedidos) {
      setErro('Confira os campos: há um valor em branco ou um tempo fora do formato MM:SS ou H:MM:SS.')
      return
    }
    if (pedidos.length === 0) {
      aoCancelar()
      return
    }
    setErro(null)
    setSalvando(true)
    const falha = await aoSalvar(pedidos, (motivo ?? '').trim() || doGesto)
    setSalvando(false)
    if (falha) setErro(falha)
  }

  useEffect(() => {
    if (!salvarRef) return
    salvarRef.current = () => void salvar()
    return () => {
      salvarRef.current = null
    }
  })

  function aoTeclar(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      aoCancelar()
    } else if (
      e.key === 'Enter' &&
      !(e.target instanceof HTMLButtonElement) &&
      !(e.target instanceof HTMLTextAreaElement && e.shiftKey)
    ) {
      e.preventDefault()
      void salvar()
    }
  }

  function campo(c: CampoDoEditor) {
    if (c.visivel && !c.visivel(valores)) return null
    const valor = valores[c.chave]
    switch (c.tipo) {
      case 'nome':
        return (
          <CampoDeNome
            key={c.chave}
            rotulo={c.rotulo}
            catalogo={c.catalogo ?? 'pessoas'}
            limite={c.limite}
            valor={String(valor ?? '')}
            aoMudar={(nome, id) => setValores((v) => ({ ...v, [c.chave]: nome, [idDoNome(c.chave)]: id }))}
          />
        )
      case 'texto':
      case 'tempo':
        return (
          <Rotulo key={c.chave} texto={c.rotulo}>
            <input className={CAMPO} maxLength={c.limite} value={String(valor ?? '')} onChange={(e) => mudar(c, e.currentTarget.value)} />
          </Rotulo>
        )
      case 'area':
        return (
          <Rotulo key={c.chave} texto={c.rotulo}>
            <textarea
              className={cn(CAMPO, 'h-auto py-1.5')}
              rows={3}
              maxLength={c.limite}
              value={String(valor ?? '')}
              onChange={(e) => mudar(c, e.currentTarget.value)}
            />
          </Rotulo>
        )
      case 'opcoes':
        // Também as listas longas (as pessoas do vídeo): o select nativo acha a opção pela letra digitada.
        return (
          <Rotulo key={c.chave} texto={c.rotulo}>
            <select className={CAMPO} value={String(valor ?? '')} onChange={(e) => mudar(c, e.currentTarget.value)}>
              {(c.opcoes ?? []).map((o) => (
                <option key={o.valor} value={o.valor}>
                  {o.rotulo}
                </option>
              ))}
            </select>
          </Rotulo>
        )
      case 'multiplas': {
        const marcadas = (valor as string[]) ?? []
        return (
          <fieldset key={c.chave} className="grid gap-1">
            <legend className="mb-1 text-xs font-medium">{c.rotulo}</legend>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {(c.opcoes ?? []).map((o) => (
                <label key={o.valor} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={marcadas.includes(o.valor)}
                    onChange={(e) => mudar(c, e.currentTarget.checked ? [...marcadas, o.valor] : marcadas.filter((x) => x !== o.valor))}
                  />
                  {o.rotulo}
                </label>
              ))}
            </div>
          </fieldset>
        )
      }
      case 'cores':
        return (
          <CampoDeCores
            key={c.chave}
            rotulo={c.rotulo}
            opcoes={c.opcoes ?? []}
            maximo={c.maximo ?? 1}
            valor={Array.isArray(valor) ? valor : []}
            aoMudar={(v) => mudar(c, v)}
          />
        )
      case 'booleano':
        return (
          <label key={c.chave} className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" className="size-4 accent-primary" checked={valor === true} onChange={(e) => mudar(c, e.currentTarget.checked)} />
            {c.rotulo}
          </label>
        )
    }
  }

  return (
    <form ref={raiz} aria-label={rotulo} onKeyDown={aoTeclar} onSubmit={(e) => e.preventDefault()} className="grid gap-3">
      <h4 className="text-sm font-semibold">{rotulo}</h4>
      {editor.campos.map(campo)}
      <Rotulo texto="Motivo (opcional)">
        <input className={CAMPO} maxLength={limiteDoMotivo} value={motivo ?? doGesto} onChange={(e) => setMotivo(e.currentTarget.value)} />
      </Rotulo>
      {erro && (
        <p role="alert" className="text-xs text-destructive">
          {erro}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">Enter salva · Esc cancela</span>
        <div className="flex gap-1">
          <Button type="button" size="sm" variant="secondary" title="Esc" onClick={aoCancelar}>
            Cancelar
          </Button>
          <Button type="button" size="sm" title="Enter" aria-busy={salvando} disabled={salvando} onClick={() => void salvar()}>
            Salvar
          </Button>
        </div>
      </div>
    </form>
  )
}

/** A confirmação do "não é isto", no próprio detalhe: Enter confirma e Esc cancela. */
export function ConfirmacaoDeRemocao({
  texto,
  aoConfirmar,
  aoCancelar,
}: {
  texto: string
  /** Grava a remoção; enquanto grava, um segundo Enter ou clique não pede outra. */
  aoConfirmar: () => Promise<void>
  aoCancelar: () => void
}) {
  const raiz = useRef<HTMLDivElement>(null)
  useEffect(() => raiz.current?.focus(), [])
  const [removendo, setRemovendo] = useState(false)
  async function confirmar() {
    if (removendo) return
    setRemovendo(true)
    try {
      await aoConfirmar()
    } finally {
      setRemovendo(false)
    }
  }
  return (
    <div
      ref={raiz}
      role="group"
      aria-label="Confirmar a remoção"
      tabIndex={-1}
      className="grid gap-2 outline-none"
      onKeyDown={(e) => {
        // O Enter num dos botões é o clique dele: no "Cancelar", não pode remover.
        if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement)) {
          e.preventDefault()
          void confirmar()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          aoCancelar()
        }
      }}
    >
      <p className="text-sm">{texto}</p>
      <div className="flex justify-end gap-1">
        <Button type="button" size="sm" variant="secondary" title="Esc" onClick={aoCancelar}>
          Cancelar
        </Button>
        <Button type="button" size="sm" variant="destructive" title="Enter" aria-busy={removendo} disabled={removendo} onClick={() => void confirmar()}>
          Remover
        </Button>
      </div>
    </div>
  )
}

const MINIMO_DE_LETRAS = 2

/**
 * Campo de nome de pessoa ou de marca com autocompletar: a lista abre a partir de 2 letras; ↑ ↓ e Enter
 * escolhem, Shift+Enter (ou o clique na última linha) usa o texto digitado como nome novo, "a revisar".
 * Escolher do catálogo devolve o id junto com o nome. O tipo de objeto só sugere: não há nome a criar.
 */
export function CampoDeNome({
  rotulo,
  catalogo,
  limite,
  soDoCatalogo = false,
  valor,
  aoMudar,
}: {
  rotulo: string
  catalogo: CatalogoDeNomes
  limite?: number
  /** Só escolhe um nome que já existe: sem "criar como nova" (a fusão, por exemplo). */
  soDoCatalogo?: boolean
  valor: string
  /** `id` é o do catálogo, ou vazio quando o texto é só digitado. */
  aoMudar: (nome: string, id: string) => void
}) {
  const nomes = useContext(NomesDoCatalogo)
  const lista = useId()
  const [achados, setAchados] = useState<NomeDoCatalogo[]>([])
  const [aberta, setAberta] = useState(false)
  const [ativo, setAtivo] = useState(-1)
  const [erro, setErro] = useState<string | null>(null)
  const [criando, setCriando] = useState(false)
  const ultimaBusca = useRef(0)
  const nomeNovo = valor.trim()
  const soSugere = catalogo === 'tipos_de_objeto' || soDoCatalogo
  const comLista = aberta && nomes !== null && nomeNovo.length >= MINIMO_DE_LETRAS

  async function buscar(texto: string) {
    const busca = ++ultimaBusca.current
    if (!nomes || texto.trim().length < MINIMO_DE_LETRAS) {
      setAberta(false)
      return
    }
    try {
      const achadas = await nomes.achar(catalogo, texto.trim())
      if (busca !== ultimaBusca.current) return
      setAchados(achadas)
      setErro(null)
      setAberta(true)
      setAtivo(-1)
    } catch {
      if (busca !== ultimaBusca.current) return
      setAchados([])
      setErro(`Não foi possível consultar ${catalogo === 'tipos_de_objeto' ? 'os tipos' : 'o catálogo'}. ${soDoCatalogo ? 'Tente de novo.' : 'Pode seguir com o texto digitado.'}`)
      setAberta(true)
    }
  }

  function escolher(n: NomeDoCatalogo) {
    ultimaBusca.current++
    setAberta(false)
    aoMudar(n.nome, n.id)
  }

  async function criar() {
    if (!nomes || criando || nomeNovo.length === 0) return
    ultimaBusca.current++
    setCriando(true)
    try {
      const criada = await nomes.criar(catalogo, nomeNovo)
      setAberta(false)
      aoMudar(criada.nome, criada.id)
    } catch {
      setErro('Não foi possível criar o nome novo no catálogo. Tente de novo.')
      setAberta(true)
    } finally {
      setCriando(false)
    }
  }

  function aoTeclar(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && e.shiftKey && !soSugere) {
      e.preventDefault()
      e.stopPropagation()
      void criar()
    } else if (comLista && e.key === 'ArrowDown') {
      e.preventDefault()
      setAtivo((a) => Math.min(a + 1, achados.length - 1))
    } else if (comLista && e.key === 'ArrowUp') {
      e.preventDefault()
      setAtivo((a) => Math.max(a - 1, 0))
    } else if (comLista && e.key === 'Enter' && ativo >= 0 && achados[ativo]) {
      // Escolher da lista não salva o formulário: o Enter seguinte salva.
      e.preventDefault()
      e.stopPropagation()
      escolher(achados[ativo])
    } else if (comLista && e.key === 'Escape') {
      // O Esc fecha a lista; o seguinte cancela o formulário.
      e.preventDefault()
      e.stopPropagation()
      setAberta(false)
    }
  }

  const opcao = 'block w-full cursor-pointer rounded-xs px-2 py-1 text-left text-sm'
  return (
    <div className="relative">
      <Rotulo texto={rotulo}>
        <input
          className={CAMPO}
          maxLength={limite}
          value={valor}
          role="combobox"
          aria-expanded={comLista}
          aria-controls={lista}
          aria-autocomplete="list"
          aria-busy={criando}
          aria-activedescendant={comLista && ativo >= 0 ? `${lista}-${ativo}` : undefined}
          onChange={(e) => {
            aoMudar(e.currentTarget.value, '')
            void buscar(e.currentTarget.value)
          }}
          onKeyDown={aoTeclar}
        />
      </Rotulo>
      {comLista && (
        <div
          id={lista}
          role="listbox"
          aria-label={`${rotulo}: nomes do catálogo`}
          className="absolute inset-x-0 z-50 mt-1 max-h-60 overflow-y-auto rounded-md border bg-popover p-1 shadow-float"
        >
          {achados.map((n, i) => (
            <div
              key={n.id}
              id={`${lista}-${i}`}
              role="option"
              aria-selected={i === ativo}
              tabIndex={-1}
              className={cn(opcao, i === ativo ? 'bg-selected' : 'hover:bg-accent')}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => escolher(n)}
            >
              {n.rotulo ?? n.nome}
              {n.a_revisar ? ' · a revisar' : ''}
            </div>
          ))}
          {erro && (
            <p role="alert" className="px-2 py-1 text-xs text-destructive">
              {erro}
            </p>
          )}
          {!soSugere && (
            <div
              role="option"
              aria-selected={false}
              tabIndex={-1}
              className={cn(opcao, 'text-muted-foreground hover:bg-accent')}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => void criar()}
            >
              {`Shift+Enter: criar '${nomeNovo}' como nova`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const GRUPO_DAS_CORES = 'Cor base do objeto'

/**
 * As cores da lista fechada como botões ligáveis, cada um com a letra do atalho: a tecla (com o foco
 * no grupo) e o clique marcam e desmarcam. Passou de `maximo`, a cor não marca e o campo diz por quê.
 * Uma cor de fora da lista só se desmarca: ela não conta para o `maximo` e o pedido a deixa de fora.
 */
function CampoDeCores({
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
  const deFora: Opcao[] = valor.filter((v) => !marcadas.includes(v)).map((v) => ({ valor: v, rotulo: v }))

  useAtalhos(
    opcoes.flatMap((o) => {
      const letra = teclas.get(o.valor)
      return letra ? [{ tecla: letra.toUpperCase(), acao: `Marcar ou desmarcar ${o.rotulo}`, grupo: GRUPO_DAS_CORES }] : []
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

  return (
    <div className="grid gap-1">
      <span className="text-xs font-medium">{rotulo}</span>
      <div
        role="group"
        aria-label={rotulo}
        className="flex flex-wrap gap-1"
        onKeyDown={(e) => {
          if (e.ctrlKey || e.metaKey || e.altKey) return
          const o = opcoes.find((x) => teclas.get(x.valor) === e.key.toLowerCase())
          if (!o) return
          // O atalho é do grupo: nem o registro global das telas, nem o Enter do formulário veem esta tecla.
          e.preventDefault()
          e.stopPropagation()
          alternar(o)
        }}
      >
        {[...opcoes, ...deFora].map((o) => {
          const letra = teclas.get(o.valor)
          const ligada = valor.includes(o.valor)
          return (
            <button
              key={o.valor}
              type="button"
              aria-pressed={ligada}
              aria-label={o.rotulo}
              aria-keyshortcuts={letra?.toUpperCase()}
              title={letra ? `Tecla ${letra.toUpperCase()}` : undefined}
              onClick={() => alternar(o)}
              className={cn(
                'h-7 rounded-sm border px-2 text-xs',
                ligada ? 'border-primary bg-selected text-link' : 'border-strong text-muted-foreground hover:text-foreground',
              )}
            >
              {o.rotulo}
              {letra ? ` (${letra.toUpperCase()})` : ''}
            </button>
          )
        })}
      </div>
      {recusada && (
        <p role="alert" className="text-xs text-destructive">
          {`No máximo ${maximo} cores: desmarque uma antes de marcar outra.`}
        </p>
      )}
    </div>
  )
}
