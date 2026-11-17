import { IconGitMerge, IconPencil, IconPlus, IconTag, IconX } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { useId, useState } from 'react'
import { SessaoExpirada, codigoDoErro, type MarcaCadastrada } from '../../api.ts'
import { falhaDaAcao, type Falha } from '../../falhaDaAcao.ts'
import { nomeNormalizado } from '../../painel.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog.tsx'
import { Aba, CABECALHO, CAMPO, CELULA, Carregando, Erro, TABELA, TopoDaAba, Vazio } from './comum.tsx'

const CHAVE = ['admin', 'marcas']
const LIMITE_DO_NOME = 100

/** Nome (só na criação) e apelidos da marca; o 409 da API (grafia que já é de outra marca) aparece no próprio diálogo. */
function Formulario({ marca, aoFechar, aoGravar }: { marca: MarcaCadastrada | null; aoFechar: () => void; aoGravar: () => void }) {
  const api = useApi()
  const id = useId()
  const [nome, setNome] = useState('')
  const [apelidos, setApelidos] = useState<string[]>(marca?.apelidos ?? [])
  const [novo, setNovo] = useState('')
  const [texto, setTexto] = useState('')
  const [gravando, setGravando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)

  // Na criação os apelidos vão num campo só, separados por vírgula; na edição, um por um (o que ficou digitado e não acrescentado entra ao gravar).
  const comPendente = (atuais: string[]) => (novo.trim() && !atuais.includes(novo.trim()) ? [...atuais, novo.trim()] : atuais)

  function acrescentar() {
    setApelidos(comPendente)
    setNovo('')
  }

  async function gravar() {
    setGravando(true)
    setFalha(null)
    try {
      if (marca) {
        await api.cadastroDeMarcas.mudarApelidos(marca.id, comPendente(apelidos))
      } else {
        const lista = texto
          .split(',')
          .map((a) => a.trim())
          .filter(Boolean)
        await api.cadastroDeMarcas.criar(nome.trim(), lista)
      }
      aoGravar()
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível gravar a marca. Tente de novo.'))
      setGravando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(aberto) => !aberto && !gravando && aoFechar()}>
      <DialogContent mostrarFechar={!gravando} className="sm:max-w-lg">
        <DialogTitle>{marca ? `Apelidos de ${marca.nome}` : 'Nova marca'}</DialogTitle>
        <DialogDescription>
          {marca
            ? 'Cada apelido é uma grafia que passa a contar como esta marca na busca e nos relatórios.'
            : 'O nome é a grafia certa; os apelidos são as grafias erradas ou antigas que contam como ela.'}
        </DialogDescription>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if ((marca || nome.trim()) && !gravando) void gravar()
          }}
        >
          {marca ? (
            <>
              {apelidos.length === 0 && <p className="text-muted-foreground">Nenhum apelido.</p>}
              <ul className="flex flex-wrap gap-1.5">
                {apelidos.map((a) => (
                  <li key={a} className="flex items-center gap-1 rounded-full bg-card py-0.5 pr-0.5 pl-2 text-xs">
                    {a}
                    <Button type="button" variant="ghost" size="icon-sm" aria-label={`Tirar ${a}`} onClick={() => setApelidos((atuais) => atuais.filter((x) => x !== a))}>
                      <IconX stroke={1.75} aria-hidden />
                    </Button>
                  </li>
                ))}
              </ul>
              <div className="flex items-end gap-2">
                <label className="grid min-w-0 flex-1 gap-1" htmlFor={`${id}-novo`}>
                  <span className="text-sm">Novo apelido</span>
                  <input
                    id={`${id}-novo`}
                    className={CAMPO}
                    value={novo}
                    maxLength={LIMITE_DO_NOME}
                    autoFocus
                    onChange={(e) => setNovo(e.currentTarget.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        acrescentar()
                      }
                    }}
                  />
                </label>
                <Button type="button" variant="secondary" disabled={!novo.trim()} onClick={acrescentar}>
                  <IconPlus stroke={1.75} aria-hidden /> Acrescentar
                </Button>
              </div>
            </>
          ) : (
            <>
              <label className="grid gap-1" htmlFor={`${id}-nome`}>
                <span className="text-sm">Nome</span>
                <input id={`${id}-nome`} className={CAMPO} value={nome} maxLength={LIMITE_DO_NOME} onChange={(e) => setNome(e.currentTarget.value)} autoFocus />
              </label>
              <label className="grid gap-1" htmlFor={`${id}-apelidos`}>
                <span className="text-sm">Apelidos (separados por vírgula)</span>
                <input id={`${id}-apelidos`} className={CAMPO} value={texto} onChange={(e) => setTexto(e.currentTarget.value)} />
              </label>
            </>
          )}
          {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={aoFechar} disabled={gravando}>
              Cancelar
            </Button>
            <Button type="submit" disabled={(!marca && !nome.trim()) || gravando}>
              Gravar
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Escolhe a outra marca; a confirmação diz que ela deixa de existir e vira apelido desta. */
function Juntar({ marca, outras, aoFechar, aoJuntar }: { marca: MarcaCadastrada; outras: MarcaCadastrada[]; aoFechar: () => void; aoJuntar: () => void }) {
  const api = useApi()
  const id = useId()
  const [outraId, setOutraId] = useState('')
  const [juntando, setJuntando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)
  const outra = outras.find((m) => m.id === outraId)

  async function juntar() {
    if (!outra) return
    setJuntando(true)
    setFalha(null)
    try {
      await api.cadastroDeMarcas.juntar(marca.id, outra.id)
      aoJuntar()
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível juntar as marcas. Tente de novo.'))
      setJuntando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(aberto) => !aberto && !juntando && aoFechar()}>
      <DialogContent mostrarFechar={!juntando} className="sm:max-w-md">
        <DialogTitle>{`Juntar a ${marca.nome}`}</DialogTitle>
        <DialogDescription>Escolha a marca que é a mesma que esta, com outra grafia.</DialogDescription>
        <label className="grid gap-1" htmlFor={`${id}-outra`}>
          <span className="text-sm">Marca a juntar</span>
          <select id={`${id}-outra`} className={CAMPO} value={outraId} autoFocus onChange={(e) => setOutraId(e.currentTarget.value)}>
            <option value="">Escolha a marca…</option>
            {outras.map((m) => (
              <option key={m.id} value={m.id}>
                {m.nome}
              </option>
            ))}
          </select>
        </label>
        {outra && <p>{`${outra.nome} deixa de existir e passa a ser apelido de ${marca.nome}.`}</p>}
        {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={aoFechar} disabled={juntando}>
            Cancelar
          </Button>
          <Button type="button" disabled={!outra || juntando} onClick={() => void juntar()}>
            Juntar marcas
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** `/admin/marcas`: cadastrar marcas, as grafias que contam como cada uma e juntar duplicadas. */
export default function Marcas() {
  const api = useApi()
  const consultas = useQueryClient()
  const filtroId = useId()
  const carga = useQuery({ queryKey: CHAVE, queryFn: () => api.cadastroDeMarcas.listar() })
  const [editando, setEditando] = useState<MarcaCadastrada | 'nova' | null>(null)
  const [juntando, setJuntando] = useState<MarcaCadastrada | null>(null)
  const [filtro, setFiltro] = useState('')
  const lista = carga.data ?? []
  const procurado = nomeNormalizado(filtro)
  const visiveis = procurado ? lista.filter((m) => [m.nome, ...m.apelidos].some((t) => nomeNormalizado(t).includes(procurado))) : lista
  const recarregar = () => {
    void consultas.invalidateQueries({ queryKey: CHAVE, exact: true })
    // O relatório de marcas agrupa pelo nome certo: refaz com a grafia nova.
    void consultas.invalidateQueries({ queryKey: ['relatorios', 'marcas'] })
  }

  return (
    <Aba>
      <TopoDaAba titulo="Marcas" contagem={carga.isSuccess ? `${lista.length} ${lista.length === 1 ? 'marca' : 'marcas'}` : undefined}>
        <label htmlFor={filtroId} className="sr-only">
          Filtrar marcas
        </label>
        <input id={filtroId} type="search" placeholder="Filtrar marcas" className={cn(CAMPO, 'min-w-0 flex-1 sm:w-56 sm:flex-none')} value={filtro} onChange={(e) => setFiltro(e.currentTarget.value)} />
        <Button type="button" onClick={() => setEditando('nova')} disabled={!carga.isSuccess}>
          <IconPlus stroke={1.75} aria-hidden /> Nova marca
        </Button>
      </TopoDaAba>
      <p className="text-sm text-muted-foreground">
        Cadastre a grafia errada como apelido da marca certa: a busca e os relatórios passam a contar tudo como ela. Grafias que só mudam em maiúscula, acento, pontuação ou espaço já se juntam sozinhas.
      </p>
      {carga.isPending && <Carregando rotulo="Carregando as marcas" />}
      {carga.isError && <Erro mensagem="Não foi possível carregar as marcas. Tente de novo." codigo={codigoDoErro(carga.error)} aoTentar={() => void carga.refetch()} />}
      {carga.isSuccess && lista.length === 0 && <Vazio Icone={IconTag}>Nenhuma marca cadastrada.</Vazio>}
      {carga.isSuccess && lista.length > 0 && visiveis.length === 0 && <Vazio Icone={IconTag}>Nenhuma marca com esse texto.</Vazio>}
      {visiveis.length > 0 && (
        <table aria-label="Marcas" className={TABELA}>
          <thead>
            <tr>
              <th className={cn(CABECALHO, 'w-[40%] sm:w-[28%]')}>Marca</th>
              <th className={CABECALHO}>Apelidos</th>
              <th className={cn(CABECALHO, 'w-20')}>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visiveis.map((m) => (
              <tr key={m.id} className="hover:bg-card">
                <td className={cn(CELULA, 'py-1.5 font-medium')}>
                  <p className="truncate">{m.nome}</p>
                </td>
                <td className={cn(CELULA, 'py-1.5')}>
                  {m.apelidos.length === 0 ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    <ul className="flex flex-wrap gap-1.5">
                      {m.apelidos.map((a) => (
                        <li key={a} className="rounded-full bg-card px-2 py-0.5 text-xs">
                          {a}
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className={cn(CELULA, 'text-right whitespace-nowrap')}>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`Editar apelidos de ${m.nome}`} onClick={() => setEditando(m)}>
                    <IconPencil stroke={1.75} aria-hidden />
                  </Button>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`Juntar a ${m.nome}`} disabled={lista.length < 2} onClick={() => setJuntando(m)}>
                    <IconGitMerge stroke={1.75} aria-hidden />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editando && (
        <Formulario
          marca={editando === 'nova' ? null : editando}
          aoFechar={() => setEditando(null)}
          aoGravar={() => {
            setEditando(null)
            recarregar()
          }}
        />
      )}
      {juntando && (
        <Juntar
          marca={juntando}
          outras={lista.filter((m) => m.id !== juntando.id)}
          aoFechar={() => setJuntando(null)}
          aoJuntar={() => {
            setJuntando(null)
            recarregar()
          }}
        />
      )}
    </Aba>
  )
}
