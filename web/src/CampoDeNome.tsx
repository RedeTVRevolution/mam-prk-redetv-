import { Loader, Paper, Text, TextInput } from '@mantine/core'
import { createContext, type KeyboardEvent, useContext, useRef, useState } from 'react'
import type { CatalogoDeNomes, ClienteDeNomes, NomeDoCatalogo } from './api.ts'

/** O cliente do catálogo de nomes, para os campos de nome dos formulários (o Visualizador o provê). */
export const NomesDoCatalogo = createContext<ClienteDeNomes | null>(null)

const MINIMO_DE_LETRAS = 2

/**
 * Campo de nome de pessoa ou de marca com autocompletar: a lista abre a partir de 2 letras; ↑ ↓ e Enter
 * escolhem, Shift+Enter (ou o clique na última linha) usa o texto digitado como nome novo, "a revisar".
 * Escolher do catálogo devolve o id junto com o nome.
 */
export function CampoDeNome({
  rotulo,
  catalogo,
  limite,
  valor,
  aoMudar,
}: {
  rotulo: string
  catalogo: CatalogoDeNomes
  limite?: number
  valor: string
  /** `id` é o do catálogo, ou vazio quando o texto é só digitado. */
  aoMudar: (nome: string, id: string) => void
}) {
  const nomes = useContext(NomesDoCatalogo)
  const [achados, setAchados] = useState<NomeDoCatalogo[]>([])
  const [aberta, setAberta] = useState(false)
  const [ativo, setAtivo] = useState(-1)
  const [erro, setErro] = useState<string | null>(null)
  const [criando, setCriando] = useState(false)
  const ultimaBusca = useRef(0)
  const nomeNovo = valor.trim()
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
      setErro('Não foi possível consultar o catálogo. Pode seguir com o nome digitado.')
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
    if (e.key === 'Enter' && e.shiftKey) {
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
    }
  }

  return (
    <div style={{ position: 'relative' }}>
      <TextInput
        size="xs"
        label={rotulo}
        maxLength={limite}
        value={valor}
        role="combobox"
        aria-expanded={comLista}
        aria-autocomplete="list"
        rightSection={criando ? <Loader size="xs" /> : undefined}
        onChange={(e) => {
          aoMudar(e.currentTarget.value, '')
          void buscar(e.currentTarget.value)
        }}
        onKeyDown={aoTeclar}
      />
      {comLista && (
        <Paper withBorder shadow="md" p={4} style={{ position: 'absolute', zIndex: 10, left: 0, right: 0 }}>
          <div role="listbox" aria-label={`${rotulo}: nomes do catálogo`}>
            {achados.map((n, i) => (
              <div
                key={n.id}
                role="option"
                aria-selected={i === ativo}
                tabIndex={-1}
                style={{ cursor: 'pointer', padding: '2px 4px', background: i === ativo ? 'var(--mantine-color-dark-5)' : undefined }}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => escolher(n)}
              >
                <Text size="xs">
                  {n.rotulo ?? n.nome}
                  {n.a_revisar ? ' · a revisar' : ''}
                </Text>
              </div>
            ))}
            {erro && (
              <Text size="xs" role="alert" c="red.4" px={4}>
                {erro}
              </Text>
            )}
            <div
              role="option"
              aria-selected={false}
              tabIndex={-1}
              style={{ cursor: 'pointer', padding: '2px 4px' }}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => void criar()}
            >
              <Text size="xs" c="dimmed">
                {`Shift+Enter: criar '${nomeNovo}' como nova`}
              </Text>
            </div>
          </div>
        </Paper>
      )}
    </div>
  )
}
