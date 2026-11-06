import { IconAlertTriangle, IconExternalLink } from '@tabler/icons-react'
import { QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useState } from 'react'
import type { ClienteDaApi } from '../api.ts'
import type { Autenticador } from '../auth/autenticador.ts'
import { naInterfaceAtual } from '../interface.ts'
import { ACERVO, seguir, useRota, type Rota } from '../rotas.ts'
import { useSessao, type Usuario } from '../sessao.ts'
import { AtalhosProvider } from './Atalhos.tsx'
import { Acervo } from './acervo/Acervo.tsx'
import { Busca, Parecidos } from './busca/Busca.tsx'
import { Casca } from './Casca.tsx'
import { ContextoDaApi, criarClienteDeConsultas } from './consultas.ts'
import Administracao from './admin/Administracao.tsx'
import Login from './Login.tsx'
import { Button } from './ui/button.tsx'
import { TelaDoVideo } from './video/TelaDoVideo.tsx'

// Cada tela chega no próprio pedaço: os gráficos não pesam na casca.
const PainelDaDiretoria = lazy(() => import('./painel/PainelDaDiretoria.tsx'))
const TempoDeTela = lazy(() => import('./relatorios/TempoDeTela.tsx'))
const Marcas = lazy(() => import('./relatorios/Marcas.tsx'))

/** O que a área de trabalho mostra. As telas que ainda não migraram levam à interface atual. */
function AreaDeTrabalho({ rota, usuario, aoSair }: { rota: Rota; usuario: Usuario; aoSair: () => void }) {
  if (rota.tipo === 'raiz') return null
  // O login recente que a purga pede passa pela saída: a Lixeira guarda o pedido e o reabre na volta.
  if (rota.tipo === 'admin') return <Administracao aba={rota.aba} busca={rota.busca} usuario={usuario} aoEntrarDeNovo={aoSair} />
  // O front só esconde o painel; quem barra é a API.
  if (rota.tipo === 'nao_encontrada' || (rota.tipo === 'painel' && !usuario.permissoes.includes('painel.ver'))) {
    return (
      <div className="m-auto grid justify-items-center gap-2 p-8 text-center">
        <p>Página não encontrada.</p>
        <a href={ACERVO} onClick={(e) => seguir(e, ACERVO)} className="text-link hover:underline">
          Ir ao acervo
        </a>
      </div>
    )
  }
  if (rota.tipo === 'acervo') return <Acervo filtros={rota.filtros} permissoes={usuario.permissoes} />
  if (rota.tipo === 'busca') return <Busca consulta={rota.consulta} />
  if (rota.tipo === 'parecidos') return <Parecidos key={`${rota.job}:${rota.plano}`} job={rota.job} plano={rota.plano} />
  if (rota.tipo === 'video') return <TelaDoVideo key={rota.id} id={rota.id} t={rota.t} permissoes={usuario.permissoes} />
  if (rota.tipo === 'painel') {
    return (
      <Suspense>
        <PainelDaDiretoria aba={rota.aba} filtros={rota.filtros} />
      </Suspense>
    )
  }
  if (rota.tipo === 'tempo_de_tela') {
    return (
      <Suspense>
        <TempoDeTela filtros={rota.filtros} />
      </Suspense>
    )
  }
  if (rota.tipo === 'marcas') {
    return (
      <Suspense>
        <Marcas filtros={rota.filtros} />
      </Suspense>
    )
  }
  return <AindaNaoMigrou />
}

function AindaNaoMigrou() {
  return (
    <div className="m-auto grid max-w-md justify-items-center gap-2 p-8 text-center">
      <p>Esta tela ainda não chegou à interface nova.</p>
      {/* Um link de verdade: só a carga da página troca a interface. */}
      <a href={naInterfaceAtual()} className="flex items-center gap-1 text-link hover:underline">
        <IconExternalLink size={16} stroke={1.75} aria-hidden /> Abrir na interface atual
      </a>
    </div>
  )
}

/** A sessão aberta. Montada de novo a cada login: o cache das consultas nunca passa de uma pessoa a outra. */
function SessaoAtiva({ api, usuario, rota, aoSair }: { api: ClienteDaApi; usuario: Usuario; rota: Rota; aoSair: () => void }) {
  const [consultas] = useState(criarClienteDeConsultas)
  return (
    <QueryClientProvider client={consultas}>
      <ContextoDaApi.Provider value={api}>
        <Casca usuario={usuario} rota={rota} aoSair={aoSair}>
          <AreaDeTrabalho rota={rota} usuario={usuario} aoSair={aoSair} />
        </Casca>
      </ContextoDaApi.Provider>
    </QueryClientProvider>
  )
}

function Telas({ autenticador }: { autenticador: Autenticador }) {
  const rota = useRota()
  // A amostra do sistema visual é da interface atual e abre sem login.
  const naAmostra = rota.tipo === 'amostra'
  const { sessao, saidas, api, sair, reverificar } = useSessao(autenticador, naAmostra)

  if (naAmostra) {
    return (
      <div className="flex min-h-dvh">
        <AindaNaoMigrou />
      </div>
    )
  }
  if (sessao.tipo === 'verificando') {
    return (
      <p role="status" className="grid min-h-dvh place-items-center text-muted-foreground">
        Verificando a sessão…
      </p>
    )
  }
  if (sessao.tipo === 'sem_sessao') {
    return <Login key={saidas} autenticador={autenticador} aoEntrar={reverificar} />
  }
  if (sessao.tipo === 'api_indisponivel') {
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        <div className="grid w-full max-w-sm gap-4">
          <p role="alert" className="flex items-center gap-2 rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2 text-destructive">
            <IconAlertTriangle size={16} stroke={1.75} className="shrink-0" aria-hidden /> Não foi possível falar com a API.
          </p>
          <div className="flex gap-2">
            <Button type="button" onClick={reverificar}>
              Tentar de novo
            </Button>
            <Button type="button" variant="secondary" onClick={() => void sair()}>
              Sair
            </Button>
          </div>
        </div>
      </div>
    )
  }
  return <SessaoAtiva api={api} usuario={sessao.usuario} rota={rota} aoSair={() => void sair()} />
}

export default function App({ autenticador }: { autenticador: Autenticador }) {
  return (
    <AtalhosProvider>
      <Telas autenticador={autenticador} />
    </AtalhosProvider>
  )
}
