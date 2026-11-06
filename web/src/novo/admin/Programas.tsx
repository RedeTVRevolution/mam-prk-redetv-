import { IconBroadcast, IconPencil, IconPlus, IconTrash, IconUserPlus, IconX } from '@tabler/icons-react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { useId, useState, type KeyboardEvent } from 'react'
import { SessaoExpirada, codigoDoErro, type DadosDoPrograma, type NomeDoCatalogo, type PessoaNoPrograma, type ProgramaCadastrado } from '../../api.ts'
import { falhaDaAcao, type Falha } from '../../falhaDaAcao.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog.tsx'
import { Aba, CABECALHO, CAMPO, CELULA, Carregando, Erro, Iniciais, TABELA, TopoDaAba, Vazio } from './comum.tsx'

const CHAVE = ['admin', 'programas']
const LIMITE_DO_NOME = 100
const LIMITE_DO_PERFIL = 4000
const LIMITE_DO_PAPEL = 100
const MINIMO_DE_LETRAS = 2

/** Escolhe uma pessoa do catálogo: a lista abre a partir de 2 letras; ↑ ↓ e Enter escolhem, Esc fecha. */
function PessoaDoCatalogo({ valor, aoDigitar, aoEscolher }: { valor: string; aoDigitar: (texto: string) => void; aoEscolher: (n: NomeDoCatalogo) => void }) {
  const api = useApi()
  const id = useId()
  const [aberta, setAberta] = useState(true)
  const [ativo, setAtivo] = useState(-1)
  const texto = valor.trim()
  const busca = useQuery({
    queryKey: ['admin', 'nomes', 'pessoas', texto],
    queryFn: () => api.nomes.achar('pessoas', texto),
    enabled: texto.length >= MINIMO_DE_LETRAS,
    placeholderData: keepPreviousData,
  })
  const achados = busca.data ?? []
  const comLista = aberta && texto.length >= MINIMO_DE_LETRAS && (achados.length > 0 || busca.isError)

  function escolher(n: NomeDoCatalogo) {
    setAberta(false)
    aoEscolher(n)
  }

  function aoTeclar(e: KeyboardEvent<HTMLInputElement>) {
    if (!comLista) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setAtivo((a) => (e.key === 'ArrowDown' ? Math.min(a + 1, achados.length - 1) : Math.max(a - 1, 0)))
    } else if (e.key === 'Enter' && achados[ativo]) {
      // Escolher da lista não grava o formulário.
      e.preventDefault()
      escolher(achados[ativo])
    } else if (e.key === 'Escape') {
      // Fecha só a lista, não o diálogo.
      e.preventDefault()
      e.stopPropagation()
      setAberta(false)
    }
  }

  return (
    <div className="relative grid gap-1">
      <label htmlFor={id} className="text-sm">
        Incluir pessoa do catálogo
      </label>
      <input
        id={id}
        role="combobox"
        aria-expanded={comLista}
        aria-autocomplete="list"
        aria-controls={`${id}-lista`}
        aria-activedescendant={comLista && ativo >= 0 ? `${id}-${ativo}` : undefined}
        autoComplete="off"
        placeholder="Digite ao menos 2 letras do nome"
        className={CAMPO}
        value={valor}
        onChange={(e) => {
          setAberta(true)
          setAtivo(-1)
          aoDigitar(e.currentTarget.value)
        }}
        onKeyDown={aoTeclar}
      />
      {comLista && (
        <div id={`${id}-lista`} role="listbox" aria-label="Pessoas do catálogo" className="absolute top-full right-0 left-0 z-10 mt-1 grid max-h-60 overflow-y-auto rounded-sm border bg-popover p-1 shadow-float">
          {achados.map((n, i) => (
            <div
              key={n.id}
              id={`${id}-${i}`}
              role="option"
              aria-selected={i === ativo}
              className={cn('flex cursor-pointer items-center gap-2 rounded-xs px-2 py-1', i === ativo ? 'bg-selected' : 'hover:bg-card')}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => escolher(n)}
            >
              <span>{n.rotulo ?? n.nome}</span>
              {n.a_revisar && <span className="text-xs text-muted-foreground">a revisar</span>}
            </div>
          ))}
          {busca.isError && (
            <p role="alert" className="px-2 py-1 text-xs text-destructive">
              Não foi possível consultar o catálogo. Tente de novo.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function Formulario({ programa, aoFechar, aoGravar }: { programa: ProgramaCadastrado | null; aoFechar: () => void; aoGravar: () => void }) {
  const api = useApi()
  const id = useId()
  const [nome, setNome] = useState(programa?.nome ?? '')
  const [perfil, setPerfil] = useState(programa?.perfil ?? '')
  const [pessoas, setPessoas] = useState<PessoaNoPrograma[]>(programa?.pessoas ?? [])
  const [busca, setBusca] = useState('')
  const [apelidos, setApelidos] = useState('')
  const [criandoPessoa, setCriandoPessoa] = useState(false)
  const [gravando, setGravando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)

  function incluir(p: PessoaNoPrograma) {
    setPessoas((atuais) => (atuais.some((a) => a.pessoa_id === p.pessoa_id) ? atuais : [...atuais, { ...p, papel: '' }]))
    setBusca('')
    setApelidos('')
  }

  async function criarPessoa() {
    setCriandoPessoa(true)
    setFalha(null)
    try {
      const lista = apelidos
        .split(',')
        .map((a) => a.trim())
        .filter(Boolean)
      incluir(await api.cadastroDeProgramas.criarPessoa(busca.trim(), lista))
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível criar a pessoa. Tente de novo.'))
    } finally {
      setCriandoPessoa(false)
    }
  }

  async function gravar() {
    setGravando(true)
    setFalha(null)
    const dados: DadosDoPrograma = { nome: nome.trim(), perfil, pessoas: pessoas.map((p) => ({ pessoa_id: p.pessoa_id, papel: p.papel })) }
    try {
      await (programa ? api.cadastroDeProgramas.mudar(programa.id, dados) : api.cadastroDeProgramas.criar(dados))
      aoGravar()
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível gravar o programa. Tente de novo.'))
      setGravando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(aberto) => !aberto && !gravando && aoFechar()}>
      <DialogContent mostrarFechar={!gravando} className="sm:max-w-lg">
        <DialogTitle>{programa ? `Editar ${programa.nome}` : 'Novo programa'}</DialogTitle>
        <DialogDescription>O nome aparece no envio e no acervo; o perfil e as pessoas ajudam o modelo na decupagem.</DialogDescription>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (nome.trim() && !gravando) void gravar()
          }}
        >
          <label className="grid gap-1" htmlFor={`${id}-nome`}>
            <span className="text-sm">Nome</span>
            <input id={`${id}-nome`} className={CAMPO} value={nome} maxLength={LIMITE_DO_NOME} onChange={(e) => setNome(e.currentTarget.value)} autoFocus />
          </label>
          <label className="grid gap-1" htmlFor={`${id}-perfil`}>
            <span className="text-sm">Perfil: o contexto que o modelo recebe (tipo de programa, merchandising frequente)</span>
            <textarea id={`${id}-perfil`} rows={4} className={cn(CAMPO, 'h-auto py-1')} value={perfil} maxLength={LIMITE_DO_PERFIL} onChange={(e) => setPerfil(e.currentTarget.value)} />
          </label>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">Pessoas</legend>
            {pessoas.length === 0 && <p className="text-muted-foreground">Nenhuma pessoa neste programa.</p>}
            {pessoas.map((p, i) => (
              <div key={p.pessoa_id} className="flex items-center gap-2">
                <Iniciais nome={p.nome} />
                <span className="w-32 truncate sm:w-40">{p.nome}</span>
                <input
                  aria-label={`Papel de ${p.nome}`}
                  placeholder="apresentador, repórter…"
                  className={cn(CAMPO, 'flex-1')}
                  value={p.papel}
                  maxLength={LIMITE_DO_PAPEL}
                  onChange={(e) => {
                    const papel = e.currentTarget.value
                    setPessoas((atuais) => atuais.map((a, j) => (j === i ? { ...a, papel } : a)))
                  }}
                />
                <Button type="button" variant="ghost" size="icon-sm" aria-label={`Tirar ${p.nome}`} onClick={() => setPessoas((atuais) => atuais.filter((_, j) => j !== i))}>
                  <IconX stroke={1.75} aria-hidden />
                </Button>
              </div>
            ))}
          </fieldset>
          <PessoaDoCatalogo valor={busca} aoDigitar={setBusca} aoEscolher={(n) => incluir({ pessoa_id: n.id, nome: n.nome, apelidos: [], papel: '' })} />
          {busca.trim().length >= MINIMO_DE_LETRAS && (
            <div className="flex flex-wrap items-end gap-2">
              <label className="grid min-w-0 flex-1 gap-1" htmlFor={`${id}-apelidos`}>
                <span className="text-xs text-muted-foreground">Apelidos (separados por vírgula)</span>
                <input id={`${id}-apelidos`} className={CAMPO} value={apelidos} onChange={(e) => setApelidos(e.currentTarget.value)} />
              </label>
              <Button type="button" variant="secondary" disabled={criandoPessoa} onClick={() => void criarPessoa()}>
                <IconUserPlus stroke={1.75} aria-hidden /> Criar pessoa «{busca.trim()}»
              </Button>
            </div>
          )}
          {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={aoFechar} disabled={gravando}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!nome.trim() || gravando}>
              Gravar
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function Apagar({ programa, aoFechar, aoApagar }: { programa: ProgramaCadastrado; aoFechar: () => void; aoApagar: () => void }) {
  const api = useApi()
  const impacto = useQuery({ queryKey: [...CHAVE, programa.id, 'impacto'], queryFn: () => api.cadastroDeProgramas.impacto(programa.id), gcTime: 0 })
  const [apagando, setApagando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)
  const videos = impacto.data?.videos ?? null

  async function apagar() {
    setApagando(true)
    setFalha(null)
    try {
      await api.cadastroDeProgramas.apagar(programa.id)
      aoApagar()
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível apagar ${programa.nome}. Tente de novo.`))
      setApagando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(aberto) => !aberto && !apagando && aoFechar()}>
      <DialogContent mostrarFechar={!apagando} className="sm:max-w-md">
        <DialogTitle>{`Apagar ${programa.nome}`}</DialogTitle>
        <DialogDescription>O programa sai do cadastro e da lista do envio. As pessoas continuam no catálogo.</DialogDescription>
        {impacto.isPending && <Carregando rotulo="Contando os vídeos do programa" />}
        {videos !== null && (
          <p>
            {videos === 0
              ? 'Nenhum vídeo usa este programa.'
              : `${videos} ${videos === 1 ? 'vídeo usa' : 'vídeos usam'} este programa e ${videos === 1 ? 'continua' : 'continuam'} com o nome dele no acervo.`}
          </p>
        )}
        {impacto.isError && (
          <Erro mensagem="Não foi possível contar os vídeos do programa. Tente de novo." codigo={codigoDoErro(impacto.error)} aoTentar={() => void impacto.refetch()} />
        )}
        {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={aoFechar} disabled={apagando}>
            Cancelar
          </Button>
          <Button type="button" variant="destructive" disabled={videos === null || apagando} onClick={() => void apagar()}>
            Apagar programa
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** `/admin/programas`: criar, editar e apagar programas, com as pessoas e o papel de cada uma nele. */
export default function Programas() {
  const api = useApi()
  const consultas = useQueryClient()
  const carga = useQuery({ queryKey: CHAVE, queryFn: () => api.cadastroDeProgramas.listar() })
  const [editando, setEditando] = useState<ProgramaCadastrado | 'novo' | null>(null)
  const [apagando, setApagando] = useState<ProgramaCadastrado | null>(null)
  const lista = carga.data ?? []
  const recarregar = () => void consultas.invalidateQueries({ queryKey: CHAVE, exact: true })

  return (
    <Aba>
      <TopoDaAba titulo="Programas" contagem={carga.isSuccess ? `${lista.length} ${lista.length === 1 ? 'programa' : 'programas'}` : undefined}>
        <Button type="button" onClick={() => setEditando('novo')} disabled={!carga.isSuccess}>
          <IconPlus stroke={1.75} aria-hidden /> Novo programa
        </Button>
      </TopoDaAba>
      {carga.isPending && <Carregando rotulo="Carregando os programas" />}
      {carga.isError && <Erro mensagem="Não foi possível carregar os programas. Tente de novo." codigo={codigoDoErro(carga.error)} aoTentar={() => void carga.refetch()} />}
      {carga.isSuccess && lista.length === 0 && <Vazio Icone={IconBroadcast}>Nenhum programa cadastrado.</Vazio>}
      {carga.isSuccess && lista.length > 0 && (
        <table aria-label="Programas" className={TABELA}>
          <thead>
            <tr>
              <th className={cn(CABECALHO, 'w-[40%] sm:w-[28%]')}>Programa</th>
              <th className={CABECALHO}>Pessoas</th>
              <th className={cn(CABECALHO, 'w-20')}>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lista.map((p) => (
              <tr key={p.id} className="hover:bg-card">
                <td className={cn(CELULA, 'py-1.5')}>
                  <p className="truncate font-medium">{p.nome}</p>
                  {p.perfil && (
                    <p className="truncate text-xs text-muted-foreground" title={p.perfil}>
                      {p.perfil}
                    </p>
                  )}
                </td>
                <td className={cn(CELULA, 'py-1.5')}>
                  {p.pessoas.length === 0 ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    <ul className="flex flex-wrap gap-1.5">
                      {p.pessoas.map((x) => (
                        <li key={x.pessoa_id} className="flex min-w-0 items-center gap-1.5 rounded-full bg-card py-0.5 pr-2 pl-0.5">
                          <Iniciais nome={x.nome} />
                          <span className="truncate text-xs">{x.papel ? `${x.nome} (${x.papel})` : x.nome}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className={cn(CELULA, 'text-right whitespace-nowrap')}>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`Editar ${p.nome}`} onClick={() => setEditando(p)}>
                    <IconPencil stroke={1.75} aria-hidden />
                  </Button>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`Apagar ${p.nome}`} onClick={() => setApagando(p)}>
                    <IconTrash stroke={1.75} aria-hidden />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editando && (
        <Formulario
          programa={editando === 'novo' ? null : editando}
          aoFechar={() => setEditando(null)}
          aoGravar={() => {
            setEditando(null)
            recarregar()
          }}
        />
      )}
      {apagando && (
        <Apagar
          programa={apagando}
          aoFechar={() => setApagando(null)}
          aoApagar={() => {
            setApagando(null)
            recarregar()
          }}
        />
      )}
    </Aba>
  )
}
