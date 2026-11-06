import { IconDots, IconPlus, IconSearch, IconUsers } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { useId, useRef, useState } from 'react'
import { SessaoExpirada, codigoDoErro, type ContaDaLista } from '../../api.ts'
import { falhaDaAcao, type Falha } from '../../falhaDaAcao.ts'
import { NOME_DO_PAPEL, PAPEIS } from '../../papeis.ts'
import type { Usuario } from '../../sessao.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/dialog.tsx'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '../ui/dropdown-menu.tsx'
import { Aba, Aviso, CABECALHO, CAMPO, CELULA, Carregando, Erro, Iniciais, TABELA, TopoDaAba, Vazio } from './comum.tsx'
import { gravarNaLista, useColunasVisiveis } from './listas.ts'

// Em que ponto cada coluna aparece; `null`, sempre.
const COLUNAS = [null, null, 'lg', null, null] as const
const TODOS = ''
const CHAVE = ['admin', 'usuarios']

function ultimoAcesso(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' })
}

/** Uma caixa por papel; o que ele pode vai na descrição, para o nome acessível ser só o papel. */
function CaixasDePapeis({ marcados, aoMudar, travado }: { marcados: string[]; aoMudar: (papeis: string[]) => void; travado?: string }) {
  const id = useId()
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-sm font-medium">Papéis</legend>
      {PAPEIS.map((p) => (
        <div key={p.valor} className="flex items-start gap-2">
          <input
            id={`${id}-${p.valor}`}
            type="checkbox"
            className="mt-0.5 size-4 shrink-0 accent-primary"
            aria-describedby={`${id}-${p.valor}-d`}
            checked={marcados.includes(p.valor)}
            disabled={p.valor === travado}
            onChange={(e) => aoMudar(PAPEIS.map((q) => q.valor).filter((v) => (v === p.valor ? e.currentTarget.checked : marcados.includes(v))))}
          />
          <div className="grid">
            <label htmlFor={`${id}-${p.valor}`} className="text-sm">
              {p.nome}
            </label>
            <span id={`${id}-${p.valor}-d`} className="text-xs text-muted-foreground">{`${p.nome}: ${p.pode}`}</span>
          </div>
        </div>
      ))}
    </fieldset>
  )
}

/** Roda a gravação de um diálogo: a falha fica no diálogo, aberto. */
function useGravacao() {
  const [salvando, setSalvando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)
  async function gravar(acao: () => Promise<void>) {
    setSalvando(true)
    setFalha(null)
    try {
      await acao()
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro))
    } finally {
      setSalvando(false)
    }
  }
  return { salvando, falha, gravar }
}

/** Montado só enquanto aberto: fechar e abrir de novo começa com o formulário vazio. */
function NovaConta({ aoFechar, aoSalvar }: { aoFechar: () => void; aoSalvar: (corpo: { email: string; nome: string; papeis: string[] }) => Promise<void> }) {
  const [email, setEmail] = useState('')
  const [nome, setNome] = useState('')
  const [papeis, setPapeis] = useState<string[]>([])
  const { salvando, falha, gravar } = useGravacao()
  const completa = email.trim() !== '' && nome.trim() !== ''
  const id = useId()
  return (
    <Dialog open onOpenChange={(aberto) => !aberto && aoFechar()}>
      <DialogContent className="sm:max-w-md">
        <DialogTitle>Nova conta</DialogTitle>
        <DialogDescription>A pessoa recebe por e-mail o link para definir a senha.</DialogDescription>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (completa && !salvando) void gravar(() => aoSalvar({ email: email.trim(), nome: nome.trim(), papeis }))
          }}
        >
          <label className="grid gap-1" htmlFor={`${id}-email`}>
            <span className="text-sm">E-mail</span>
            <input id={`${id}-email`} type="email" className={CAMPO} value={email} onChange={(e) => setEmail(e.currentTarget.value)} autoFocus />
          </label>
          <label className="grid gap-1" htmlFor={`${id}-nome`}>
            <span className="text-sm">Nome</span>
            <input id={`${id}-nome`} className={CAMPO} value={nome} onChange={(e) => setNome(e.currentTarget.value)} />
          </label>
          <CaixasDePapeis marcados={papeis} aoMudar={setPapeis} />
          {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={aoFechar}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!completa || salvando}>
              Criar conta
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function EditarPapeis({ conta, propria, aoFechar, aoSalvar }: { conta: ContaDaLista; propria: boolean; aoFechar: () => void; aoSalvar: (papeis: string[]) => Promise<void> }) {
  const [papeis, setPapeis] = useState(conta.papeis)
  const { salvando, falha, gravar } = useGravacao()
  const travado = propria && conta.papeis.includes('administrador') ? 'administrador' : undefined
  return (
    <Dialog open onOpenChange={(aberto) => !aberto && aoFechar()}>
      <DialogContent className="sm:max-w-md">
        <DialogTitle>{`Papéis de ${conta.nome}`}</DialogTitle>
        <DialogDescription>{conta.email}</DialogDescription>
        <CaixasDePapeis marcados={papeis} aoMudar={setPapeis} travado={travado} />
        {travado && <p className="text-xs text-muted-foreground">Você não pode tirar o seu próprio papel de Administrador.</p>}
        {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={aoFechar}>
            Cancelar
          </Button>
          <Button type="button" disabled={salvando} onClick={() => void gravar(() => aoSalvar(papeis))}>
            Salvar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Situacao({ desativada }: { desativada: boolean }) {
  return (
    <span className={cn('inline-flex h-5 items-center rounded-xs px-1.5 text-xs', desativada ? 'bg-destructive/12 text-destructive' : 'bg-ok/12 text-ok')}>
      {desativada ? 'Desativada' : 'Ativa'}
    </span>
  )
}

/** `/admin/usuarios`: contas e papéis. A lista é a da equipe, curta: tabela comum, sem rolagem virtual. */
export default function Usuarios({ eu }: { eu: Usuario }) {
  const api = useApi()
  const consultas = useQueryClient()
  const carga = useQuery({ queryKey: CHAVE, queryFn: () => api.usuarios.listar() })
  const colunas = useColunasVisiveis(COLUNAS)
  const [busca, setBusca] = useState('')
  const [papel, setPapel] = useState(TODOS)
  const [situacao, setSituacao] = useState(TODOS)
  const [criando, setCriando] = useState(false)
  const [editando, setEditando] = useState<string | null>(null)
  const [desativando, setDesativando] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [falha, setFalha] = useState<Falha | null>(null)
  // O item "Desativar" leva o foco ao botão de confirmar, não de volta ao menu.
  const focoNaConfirmacao = useRef(false)

  const contas = carga.data ?? []
  const mudarLista = (mudanca: (atuais: ContaDaLista[]) => ContaDaLista[]) => gravarNaLista(consultas, CHAVE, mudanca)
  const trocar = (nova: ContaDaLista) => mudarLista((atuais) => atuais.map((c) => (c.uid === nova.uid ? nova : c)))

  /** Roda uma ação da linha: sucesso avisa, falha mostra a mensagem sem derrubar a tela. */
  async function agir(acao: () => Promise<string>) {
    setAviso(null)
    setFalha(null)
    try {
      setAviso(await acao())
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro))
    }
  }

  const termo = busca.trim().toLowerCase()
  const visiveis = contas.filter(
    (c) =>
      (!termo || c.nome.toLowerCase().includes(termo) || c.email.toLowerCase().includes(termo)) &&
      (papel === TODOS || c.papeis.includes(papel)) &&
      (situacao === TODOS || c.situacao === situacao),
  )
  const emEdicao = contas.find((c) => c.uid === editando)

  return (
    <Aba>
      <TopoDaAba titulo="Usuários" contagem={carga.isSuccess ? `${contas.length} ${contas.length === 1 ? 'conta' : 'contas'}` : undefined}>
        <label className={cn(CAMPO, 'flex w-full items-center gap-1.5 focus-within:border-primary sm:w-64')}>
          <IconSearch size={16} stroke={1.75} className="shrink-0 text-muted-foreground" aria-hidden />
          <input
            aria-label="Buscar por nome ou e-mail"
            placeholder="Buscar por nome ou e-mail…"
            className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-subtle"
            value={busca}
            onChange={(e) => setBusca(e.currentTarget.value)}
          />
        </label>
        <select aria-label="Papel" className={CAMPO} value={papel} onChange={(e) => setPapel(e.currentTarget.value)}>
          <option value={TODOS}>Todos os papéis</option>
          {PAPEIS.map((p) => (
            <option key={p.valor} value={p.valor}>
              {p.nome}
            </option>
          ))}
        </select>
        <select aria-label="Situação" className={CAMPO} value={situacao} onChange={(e) => setSituacao(e.currentTarget.value)}>
          <option value={TODOS}>Todas as situações</option>
          <option value="ativa">Ativa</option>
          <option value="desativada">Desativada</option>
        </select>
        <Button type="button" onClick={() => setCriando(true)}>
          <IconPlus stroke={1.75} aria-hidden /> Nova conta
        </Button>
      </TopoDaAba>
      <Aviso>{aviso}</Aviso>
      {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
      {carga.isPending && <Carregando rotulo="Carregando as contas" />}
      {carga.isError && <Erro mensagem={falhaDaAcao(carga.error).mensagem} codigo={codigoDoErro(carga.error)} aoTentar={() => void carga.refetch()} />}
      {carga.isSuccess && visiveis.length === 0 && <Vazio Icone={IconUsers}>Nenhuma conta neste filtro.</Vazio>}
      {carga.isSuccess && visiveis.length > 0 && (
        <table aria-label="Usuários" className={TABELA}>
          <thead>
            <tr>
              <th className={cn(CABECALHO, 'w-[55%] md:w-auto')}>Nome e e-mail</th>
              <th className={CABECALHO}>Papéis</th>
              <th className={cn(CABECALHO, 'hidden w-36 lg:table-cell')}>Último acesso</th>
              <th className={cn(CABECALHO, 'w-24')}>Situação</th>
              <th className={cn(CABECALHO, 'w-10')}>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visiveis.map((c) => {
              const propria = c.uid === eu.uid
              const desativada = c.situacao === 'desativada'
              const papeis = c.papeis.map((p) => NOME_DO_PAPEL[p] ?? p).join(', ') || '—'
              return [
                <tr key={c.uid} className="hover:bg-card">
                  <td className={CELULA}>
                    <div className="flex min-w-0 items-center gap-2">
                      <Iniciais nome={c.nome} />
                      <div className="grid min-w-0">
                        <span className="truncate">{c.nome}</span>
                        <span className="truncate text-xs text-muted-foreground">{c.email}</span>
                      </div>
                    </div>
                  </td>
                  <td className={cn(CELULA, 'truncate')} title={papeis}>
                    {papeis}
                  </td>
                  <td className={cn(CELULA, 'hidden whitespace-nowrap text-muted-foreground lg:table-cell')}>{ultimoAcesso(c.ultimo_acesso)}</td>
                  <td className={CELULA}>
                    <Situacao desativada={desativada} />
                  </td>
                  <td className={cn(CELULA, 'text-right')}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`Ações de ${c.nome}`}>
                          <IconDots stroke={1.75} aria-hidden />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="end"
                        onCloseAutoFocus={(e) => {
                          if (!focoNaConfirmacao.current) return
                          focoNaConfirmacao.current = false
                          e.preventDefault()
                        }}
                      >
                        <DropdownMenuItem onSelect={() => setEditando(c.uid)}>Editar papéis</DropdownMenuItem>
                        <DropdownMenuItem
                          onSelect={() =>
                            void agir(async () => {
                              await api.usuarios.reenviarLink(c.uid)
                              return `Link de senha reenviado para ${c.email}.`
                            })
                          }
                        >
                          Reenviar link de senha
                        </DropdownMenuItem>
                        {desativada ? (
                          <DropdownMenuItem
                            onSelect={() =>
                              void agir(async () => {
                                await trocar(await api.usuarios.reativar(c.uid))
                                return `${c.nome} foi reativada.`
                              })
                            }
                          >
                            Reativar
                          </DropdownMenuItem>
                        ) : (
                          <>
                            <DropdownMenuItem
                              disabled={propria}
                              className="text-destructive focus:text-destructive"
                              onSelect={() => {
                                focoNaConfirmacao.current = true
                                setDesativando(c.uid)
                              }}
                            >
                              Desativar
                            </DropdownMenuItem>
                            {propria && <DropdownMenuLabel>Você não pode desativar a própria conta.</DropdownMenuLabel>}
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                </tr>,
                desativando === c.uid && (
                  <tr
                    key={`${c.uid}:desativar`}
                    className="bg-destructive/12"
                    onKeyDown={(e) => {
                      if (e.key === 'Escape') setDesativando(null)
                    }}
                  >
                    <td colSpan={colunas}className={CELULA}>
                      <div className="flex flex-wrap items-center gap-2 py-1">
                        <span>{`Desativar ${c.nome}? A conta sai na hora. Enter confirma`}</span>
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          autoFocus
                          aria-label="Confirmar desativação"
                          onClick={() => {
                            setDesativando(null)
                            void agir(async () => {
                              await trocar(await api.usuarios.desativar(c.uid))
                              return `${c.nome} foi desativada e saiu do sistema.`
                            })
                          }}
                        >
                          Desativar
                        </Button>
                        <Button type="button" size="sm" variant="secondary" onClick={() => setDesativando(null)}>
                          Cancelar
                        </Button>
                      </div>
                    </td>
                  </tr>
                ),
              ]
            })}
          </tbody>
        </table>
      )}
      {criando && (
        <NovaConta
          aoFechar={() => setCriando(false)}
          aoSalvar={async (corpo) => {
            const nova = await api.usuarios.criar(corpo)
            await mudarLista((atuais) => [...atuais, nova])
            setCriando(false)
            setFalha(null)
            setAviso(`Conta criada. O link para definir a senha foi enviado para ${nova.email}.`)
          }}
        />
      )}
      {emEdicao && (
        <EditarPapeis
          key={emEdicao.uid}
          conta={emEdicao}
          propria={emEdicao.uid === eu.uid}
          aoFechar={() => setEditando(null)}
          aoSalvar={async (papeis) => {
            await trocar(await api.usuarios.trocarPapeis(emEdicao.uid, papeis))
            setEditando(null)
            setFalha(null)
            setAviso(`Papéis de ${emEdicao.nome} atualizados.`)
          }}
        />
      )}
    </Aba>
  )
}
