import {
  Alert,
  AppShell,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { lazy, Suspense } from 'react'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import type { Autenticador } from './auth/autenticador.ts'
import Barra from './Barra.tsx'
import Acervo from './Acervo.tsx'
import Busca from './Busca.tsx'
import { PlanosParecidos } from './PlanosParecidos.tsx'
import Login from './Login.tsx'
import { Link } from './Link.tsx'
import { ACERVO, useRota } from './rotas.ts'
import { useSessao } from './sessao.ts'
import { ALTURA_DA_BARRA } from './tema.ts'
import TelaDoVideo from './TelaDoVideo.tsx'
import Administracao from './Administracao.tsx'
import { podeAdministrar } from './administracao.ts'
import Marcas from './Marcas.tsx'
import PainelDaDiretoria from './PainelDaDiretoria.tsx'
import TempoDeTela from './TempoDeTela.tsx'

// A amostra do sistema visual é grande e sem login: fica num pedaço à parte do bundle.
const Amostra = lazy(() => import('./Amostra.tsx'))

export default function App({ autenticador }: { autenticador: Autenticador }) {
  return (
    <AtalhosProvider>
      <Telas autenticador={autenticador} />
    </AtalhosProvider>
  )
}

function Telas({ autenticador }: { autenticador: Autenticador }) {
  const rota = useRota()
  // A amostra abre sem login e sem a API: só verifica a sessão fora dela.
  const naAmostra = rota.tipo === 'amostra'
  const { sessao, saidas, api, sair, reverificar } = useSessao(autenticador, naAmostra)

  if (naAmostra) {
    return (
      <Suspense fallback={null}>
        <Amostra />
      </Suspense>
    )
  }
  if (sessao.tipo === 'verificando') {
    return (
      <Center h="100vh">
        <Loader role="status" aria-label="Verificando a sessão" />
      </Center>
    )
  }
  if (sessao.tipo === 'sem_sessao') {
    return <Login key={saidas} autenticador={autenticador} aoEntrar={reverificar} />
  }
  if (sessao.tipo === 'api_indisponivel') {
    return (
      <Center h="100vh">
        <Stack w={360}>
          <Alert color="red" variant="light" icon={<IconAlertTriangle />} role="alert">
            Não foi possível falar com a API.
          </Alert>
          <Group>
            <Button type="button" onClick={reverificar}>
              Tentar de novo
            </Button>
            <Button type="button" variant="default" onClick={() => void sair()}>
              Sair
            </Button>
          </Group>
        </Stack>
      </Center>
    )
  }
  const podeEditar = sessao.usuario.permissoes.includes('decupagem.editar')
  const podeAprovar = sessao.usuario.permissoes.includes('correcao.aprovar')
  const podeReprocessar = sessao.usuario.permissoes.includes('video.reprocessar_etapa')
  const podeVerAuditoria = sessao.usuario.permissoes.includes('auditoria.ver')
  const podeFundir = sessao.usuario.permissoes.includes('catalogo.fundir')
  const podeApagar = sessao.usuario.permissoes.includes('lixeira.gerir')
  const podeEnviar = sessao.usuario.permissoes.includes('video.enviar')
  const podeVerPainel = sessao.usuario.permissoes.includes('painel.ver')
  return (
    <AppShell
      header={{ height: ALTURA_DA_BARRA }}
      padding="sm"
    >
      <Barra
        email={sessao.usuario.email}
        aoSair={() => void sair()}
        podeAdministrar={podeAdministrar(sessao.usuario.permissoes)}
        podeVerPainel={podeVerPainel}
      />
      {rota.tipo === 'video' ? (
        <AppShell.Main bg="dark.7">
          <TelaDoVideo
            api={api}
            id={rota.id}
            t={rota.t}
            busca={rota.busca}
            podeEditar={podeEditar}
            podeAprovar={podeAprovar}
            podeReprocessar={podeReprocessar}
            podeVerAuditoria={podeVerAuditoria}
            podeFundir={podeFundir}
          />
        </AppShell.Main>
      ) : rota.tipo === 'acervo' ? (
        // O front só esconde o envio; quem barra é a API.
        <Acervo api={api} filtros={rota.filtros} podeEnviar={podeEnviar} podeApagar={podeApagar} />
      ) : rota.tipo === 'busca' ? (
        <AppShell.Main bg="dark.7">
          <Busca api={api} consulta={rota.consulta} />
        </AppShell.Main>
      ) : rota.tipo === 'parecidos' ? (
        <AppShell.Main bg="dark.7">
          <PlanosParecidos api={api} job={rota.job} plano={rota.plano} />
        </AppShell.Main>
      ) : rota.tipo === 'tempo_de_tela' ? (
        <AppShell.Main bg="dark.7">
          <TempoDeTela api={api} filtros={rota.filtros} />
        </AppShell.Main>
      ) : rota.tipo === 'marcas' ? (
        <AppShell.Main bg="dark.7">
          <Marcas api={api} filtros={rota.filtros} />
        </AppShell.Main>
      ) : rota.tipo === 'painel' && podeVerPainel ? (
        // O front só esconde a área; quem barra é a API.
        <AppShell.Main bg="dark.7">
          <PainelDaDiretoria api={api} aba={rota.aba} filtros={rota.filtros} />
        </AppShell.Main>
      ) : rota.tipo === 'admin' ? (
        <AppShell.Main bg="dark.7">
          <Administracao api={api} aba={rota.aba} busca={rota.busca} usuario={sessao.usuario} aoEntrarDeNovo={() => void sair()} />
        </AppShell.Main>
      ) : (
        <AppShell.Main bg="dark.7">
          <Center h="60vh">
            <Stack align="center">
              <Text>Página não encontrada.</Text>
              <Link para={ACERVO}>Ir ao acervo</Link>
            </Stack>
          </Center>
        </AppShell.Main>
      )}
    </AppShell>
  )
}
