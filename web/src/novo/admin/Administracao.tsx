import { IconBroadcast, IconChecklist, IconHistory, IconInbox, IconKey, IconSettings, IconTrash, IconUsers, type Icon } from '@tabler/icons-react'
import { cn } from 'cn'
import { useEffect } from 'react'
import { abasPermitidas, type Aba } from '../../administracao.ts'
import { ACERVO, enderecoDaAba, navegar, seguir } from '../../rotas.ts'
import type { Usuario } from '../../sessao.ts'
import { filtrosDaAuditoria } from '../../auditoria.ts'
import { filtrosDasEntradas } from '../../entradas.ts'
import Auditoria from './Auditoria.tsx'
import Entradas from './Entradas.tsx'
import Usuarios from './Usuarios.tsx'

const ICONE: Record<string, Icon> = {
  entradas: IconInbox,
  usuarios: IconUsers,
  chaves: IconKey,
  aprovacao: IconChecklist,
  programas: IconBroadcast,
  lixeira: IconTrash,
  auditoria: IconHistory,
}

function Conteudo({ aba, busca, usuario, aoEntrarDeNovo }: { aba: Aba['aba']; busca: string; usuario: Usuario; aoEntrarDeNovo: () => void }) {
  void aoEntrarDeNovo
  const pode = (p: string) => usuario.permissoes.includes(p)
  if (aba === 'entradas') {
    return (
      <Entradas
        filtros={filtrosDasEntradas(busca)}
        podeReprocessar={pode('video.reprocessar')}
        podeEscolherEtapa={pode('video.reprocessar_etapa')}
        podeVerSistemas={pode('chaves.gerir')}
      />
    )
  }
  if (aba === 'usuarios') return <Usuarios eu={usuario} />
  if (aba === 'auditoria') return <Auditoria filtros={filtrosDaAuditoria(busca)} />
  return null
}

/** `/admin`: as abas são links com endereço próprio; `/admin` abre a primeira permitida. */
export default function Administracao({ aba, busca, usuario, aoEntrarDeNovo }: { aba: string | null; busca: string; usuario: Usuario; aoEntrarDeNovo: () => void }) {
  const permitidas = abasPermitidas(usuario.permissoes)
  const atual = permitidas.find((a) => a.aba === aba)
  const primeira = permitidas[0]?.aba

  useEffect(() => {
    if (aba === null && primeira) navegar(enderecoDaAba(primeira), { substituir: true })
  }, [aba, primeira])

  if (!atual) {
    if (aba === null && primeira) return null
    return (
      <div className="m-auto grid justify-items-center gap-2 p-8 text-center">
        <p>Página não encontrada.</p>
        <a href={ACERVO} onClick={(e) => seguir(e, ACERVO)} className="text-link hover:underline">
          Ir ao acervo
        </a>
      </div>
    )
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="shrink-0 border-b px-3 pt-3 md:px-4">
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <IconSettings size={20} stroke={1.75} className="text-muted-foreground" aria-hidden /> Administração
        </h1>
        <nav aria-label="Abas da administração" className="-mx-3 mt-2 overflow-x-auto px-3 md:-mx-4 md:px-4">
          <ul className="flex min-w-max gap-1">
            {permitidas.map((a) => {
              const ativa = a === atual
              const Icone = ICONE[a.aba] ?? IconSettings
              const endereco = enderecoDaAba(a.aba)
              return (
                <li key={a.aba}>
                  <a
                    href={endereco}
                    onClick={(e) => seguir(e, endereco)}
                    aria-current={ativa ? 'page' : undefined}
                    className={cn(
                      'relative flex h-10 items-center gap-2 rounded-t-sm px-3 text-sm whitespace-nowrap transition-colors',
                      ativa
                        ? 'text-foreground after:absolute after:inset-x-2 after:bottom-0 after:h-[3px] after:rounded-t-xs after:bg-primary'
                        : 'text-muted-foreground hover:bg-card hover:text-foreground',
                    )}
                  >
                    <Icone size={16} stroke={1.75} className={ativa ? 'text-link' : undefined} aria-hidden />
                    {a.rotulo}
                  </a>
                </li>
              )
            })}
          </ul>
        </nav>
      </div>
      <Conteudo key={atual.aba} aba={atual.aba} busca={busca} usuario={usuario} aoEntrarDeNovo={aoEntrarDeNovo} />
    </div>
  )
}
