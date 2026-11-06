import {
  IconBadgeTm,
  IconChartBar,
  IconCloudUpload,
  IconKeyboard,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconLogout,
  IconMenu2,
  IconMovie,
  IconSearch,
  IconSettings,
  IconUserScan,
  type Icon,
} from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import logo from '../assets/redetv-logo.png'
import { podeAdministrar } from '../administracao.ts'
import { haJanelaAberta, useAtalhos, useMostrarAtalhos, type Atalho } from '../atalhos.ts'
import { consultaNova } from '../busca.ts'
import { NOME_DO_PAPEL } from '../papeis.ts'
import { ACERVO, ADMIN, enderecoDaBusca, MARCAS, navegar, PAINEL, seguir, TEMPO_DE_TELA, type Rota } from '../rotas.ts'
import type { Usuario } from '../sessao.ts'
import { EnvioDeVideo } from './EnvioDeVideo.tsx'
import { Button } from './ui/button.tsx'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from './ui/command.tsx'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu.tsx'
import { Kbd } from './ui/kbd.tsx'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
} from './ui/sidebar.tsx'
import { useSidebar } from './ui/sidebar-contexto.ts'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './ui/tooltip.tsx'

interface Destino {
  endereco: string
  rotulo: string
  Icone: Icon
  /** A letra depois do `G`; a busca usa a `/`. */
  letra?: string
  ativo: (rota: Rota) => boolean
}

const ACERVO_D: Destino = { endereco: ACERVO, rotulo: 'Acervo', Icone: IconMovie, letra: 'a', ativo: (r) => r.tipo === 'acervo' || r.tipo === 'video' }
const BUSCA_D: Destino = { endereco: '/busca', rotulo: 'Busca', Icone: IconSearch, ativo: (r) => r.tipo === 'busca' || r.tipo === 'parecidos' }
const TEMPO_D: Destino = { endereco: TEMPO_DE_TELA, rotulo: 'Tempo de tela', Icone: IconUserScan, letra: 't', ativo: (r) => r.tipo === 'tempo_de_tela' }
const MARCAS_D: Destino = { endereco: MARCAS, rotulo: 'Marcas', Icone: IconBadgeTm, letra: 'm', ativo: (r) => r.tipo === 'marcas' }
const PAINEL_D: Destino = { endereco: PAINEL, rotulo: 'Painel da diretoria', Icone: IconChartBar, letra: 'p', ativo: (r) => r.tipo === 'painel' }
const ADMIN_D: Destino = { endereco: ADMIN, rotulo: 'Administração', Icone: IconSettings, letra: 'd', ativo: (r) => r.tipo === 'admin' }

/** Os grupos do trilho, com os mesmos critérios da barra da interface antiga (o front só esconde; quem barra é a API). */
function gruposDoTrilho(permissoes: string[]): Destino[][] {
  return [
    [ACERVO_D, BUSCA_D],
    [TEMPO_D, MARCAS_D, ...(permissoes.includes('painel.ver') ? [PAINEL_D] : [])],
    podeAdministrar(permissoes) ? [ADMIN_D] : [],
  ].filter((g) => g.length > 0)
}

function tecla(d: Destino) {
  return d.letra ? `G ${d.letra.toUpperCase()}` : '/'
}

function Trilho({ grupos, rota }: { grupos: Destino[][]; rota: Rota }) {
  const { aberto, movel, alternar, setAbertoNoMovel } = useSidebar()
  return (
    <Sidebar className="top-10">
      <nav aria-label="Principal" className="contents">
        <SidebarContent className="py-1">
          {grupos.map((grupo, i) => (
            <div key={grupo[0].endereco} className="contents">
              {i > 0 && <SidebarSeparator className="my-1" />}
              <SidebarMenu className="p-1">
                {grupo.map((d) => {
                  const ativo = d.ativo(rota)
                  return (
                    <SidebarMenuItem key={d.endereco}>
                      <SidebarMenuButton
                        asChild
                        isActive={ativo}
                        dica={
                          <>
                            {d.rotulo} <Kbd>{tecla(d)}</Kbd>
                          </>
                        }
                        className={
                          ativo
                            ? 'bg-selected before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-r-xs before:bg-primary hover:bg-selected'
                            : undefined
                        }
                      >
                        <a
                          href={d.endereco}
                          aria-current={ativo ? 'page' : undefined}
                          onClick={(e) => {
                            setAbertoNoMovel(false)
                            seguir(e, d.endereco)
                          }}
                        >
                          <d.Icone stroke={1.75} className={ativo ? 'text-link' : 'text-muted-foreground'} />
                          <span>{d.rotulo}</span>
                        </a>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </div>
          ))}
        </SidebarContent>
      </nav>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={alternar}
              className="text-muted-foreground"
              dica={
                <>
                  Abrir o menu <Kbd>[</Kbd>
                </>
              }
            >
              {aberto ? <IconLayoutSidebarLeftCollapse stroke={1.75} /> : <IconLayoutSidebarLeftExpand stroke={1.75} />}
              <span>{movel ? 'Fechar o menu' : aberto ? 'Recolher o menu' : 'Abrir o menu'}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}

/** A paleta de comandos (`/` ou `Ctrl K`): buscar no conteúdo ou ir a uma tela. */
function BuscaGlobal({ aberta, aoMudar, destinos }: { aberta: boolean; aoMudar: (v: boolean) => void; destinos: Destino[] }) {
  const [texto, setTexto] = useState('')
  const ir = (destino: string) => () => {
    aoMudar(false)
    setTexto('')
    navegar(destino)
  }
  const q = texto.trim()
  return (
    <CommandDialog open={aberta} onOpenChange={aoMudar} titulo="Buscar no acervo" descricao="Busca no conteúdo e atalhos para as telas" className="sm:max-w-2xl">
      <CommandInput placeholder="Buscar nas falas, nos textos da tela e nos planos…" value={texto} onValueChange={setTexto} />
      <CommandList>
        <CommandEmpty>Nenhuma tela com esse nome.</CommandEmpty>
        {q && (
          <CommandGroup heading="Buscar no conteúdo">
            <CommandItem value={`buscar ${q}`} onSelect={ir(enderecoDaBusca(consultaNova(q)))}>
              <IconSearch stroke={1.75} />
              <span className="truncate">Buscar “{q}” nas falas, nos textos da tela e nos planos</span>
              <CommandShortcut>Enter</CommandShortcut>
            </CommandItem>
          </CommandGroup>
        )}
        <CommandGroup heading="Ir para">
          {destinos.map((d) => (
            <CommandItem key={d.endereco} value={`ir ${d.rotulo}`} onSelect={ir(d.endereco)}>
              <d.Icone stroke={1.75} className="text-muted-foreground" /> {d.rotulo}
              <CommandShortcut>{tecla(d)}</CommandShortcut>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}

function BotaoDoMenu() {
  const { alternar } = useSidebar()
  useAtalhos([{ tecla: '[', acao: 'Abrir ou recolher o menu', grupo: 'Em toda tela', executar: alternar }])
  return (
    <button
      type="button"
      aria-label="Abrir o menu"
      onClick={alternar}
      className="flex size-8 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent md:hidden"
    >
      <IconMenu2 size={20} stroke={1.75} />
    </button>
  )
}

const ESPERA_DO_G_MS = 1200

/** A casca da interface nova: barra de 40 px, trilho, busca global e atalhos. Só a área de trabalho muda. */
export function Casca({ usuario, rota, aoSair, children }: { usuario: Usuario; rota: Rota; aoSair: () => void; children: ReactNode }) {
  const [buscaAberta, setBuscaAberta] = useState(false)
  const [envioAberto, setEnvioAberto] = useState(false)
  const podeEnviar = usuario.permissoes.includes('video.enviar')
  const consultas = useQueryClient()
  const mostrarAtalhos = useMostrarAtalhos()
  const grupos = gruposDoTrilho(usuario.permissoes)
  const destinos = grupos.flat()

  // `G` e uma letra vão a uma tela; a letra vale por pouco tempo depois do `G`.
  const ultimoG = useRef(0)
  const atalhos: Atalho[] = [
    { tecla: '/', acao: 'Buscar', grupo: 'Em toda tela', executar: () => setBuscaAberta(true) },
    ...(podeEnviar ? [{ tecla: 'U', acao: 'Enviar vídeo', grupo: 'Em toda tela', casa: (e: KeyboardEvent) => e.key.toLowerCase() === 'u', executar: () => setEnvioAberto(true) }] : []),
    { tecla: 'G', acao: 'Começa um atalho de navegação', grupo: 'Navegação', casa: (e) => e.key.toLowerCase() === 'g', executar: () => (ultimoG.current = Date.now()) },
    ...destinos
      .filter((d) => d.letra)
      .map((d) => ({
        tecla: tecla(d),
        acao: `Ir para ${d.rotulo}`,
        grupo: 'Navegação',
        casa: (e: KeyboardEvent) => e.key.toLowerCase() === d.letra && Date.now() - ultimoG.current < ESPERA_DO_G_MS,
        executar: () => {
          ultimoG.current = 0
          navegar(d.endereco)
        },
      })),
  ]
  useAtalhos(atalhos)

  // Ctrl K e Cmd K abrem a busca até de dentro de um campo; o registro de atalhos ignora o Cmd.
  useEffect(() => {
    function aoTeclar(e: KeyboardEvent) {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey) && !e.altKey && !haJanelaAberta()) {
        e.preventDefault()
        setBuscaAberta(true)
      }
    }
    document.addEventListener('keydown', aoTeclar)
    return () => document.removeEventListener('keydown', aoTeclar)
  }, [])

  const papeis = (usuario.papeis ?? []).map((p) => NOME_DO_PAPEL[p] ?? p).join(', ')

  return (
    <TooltipProvider>
      <SidebarProvider className="h-dvh flex-col">
        <header className="flex h-10 shrink-0 items-center gap-2 border-b bg-background px-2 md:gap-3 md:px-3">
          <BotaoDoMenu />
          <a href={ACERVO} onClick={(e) => seguir(e, ACERVO)} className="flex shrink-0 items-center gap-2 rounded-xs" aria-label="MAM RedeTV, ir ao acervo">
            <img src={logo} alt="" className="h-5 w-auto" />
            <span className="hidden text-sm font-semibold sm:inline">MAM</span>
          </a>
          <button
            type="button"
            onClick={() => setBuscaAberta(true)}
            className="mx-auto flex h-7 w-full max-w-xl min-w-0 items-center gap-2 rounded-sm border border-strong bg-input px-2 text-left text-sm text-muted-foreground hover:border-muted-foreground/40"
          >
            <IconSearch size={16} stroke={1.75} className="shrink-0" aria-hidden />
            <span className="flex-1 truncate">
              Buscar<span className="hidden sm:inline"> no acervo…</span>
            </span>
            <Kbd className="hidden sm:inline-flex">/</Kbd>
          </button>
          {podeEnviar && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button type="button" size="sm" onClick={() => setEnvioAberto(true)} aria-label="Enviar vídeo" className="shrink-0">
                  <IconCloudUpload stroke={1.75} aria-hidden />
                  <span className="hidden lg:inline">Enviar vídeo</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Enviar vídeo <Kbd>U</Kbd>
              </TooltipContent>
            </Tooltip>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label="Atalhos de teclado"
                onClick={mostrarAtalhos}
                className="hidden size-7 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground md:flex"
              >
                <IconKeyboard size={20} stroke={1.75} />
              </button>
            </TooltipTrigger>
            <TooltipContent>
              Atalhos de teclado <Kbd>?</Kbd>
            </TooltipContent>
          </Tooltip>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`Conta: ${usuario.email}`}
                className="flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold uppercase hover:ring-2 hover:ring-strong"
              >
                {usuario.email.charAt(0)}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              <DropdownMenuLabel className="grid gap-0.5">
                <span className="truncate text-sm text-foreground">{usuario.email}</span>
                {papeis && <span className="font-normal">{papeis}</span>}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={mostrarAtalhos}>
                <IconKeyboard stroke={1.75} /> Atalhos de teclado
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={aoSair}>
                <IconLogout stroke={1.75} /> Sair
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <div className="flex min-h-0 flex-1">
          <Trilho grupos={grupos} rota={rota} />
          <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-canvas">{children}</main>
        </div>
        <BuscaGlobal aberta={buscaAberta} aoMudar={setBuscaAberta} destinos={destinos} />
        {/* O vídeo novo entra no topo: o acervo recomeça da primeira página. */}
        {podeEnviar && <EnvioDeVideo aberto={envioAberto} aoMudar={setEnvioAberto} aoCriar={() => void consultas.resetQueries({ queryKey: ['acervo'] })} />}
      </SidebarProvider>
    </TooltipProvider>
  )
}
