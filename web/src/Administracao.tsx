import { Group, Stack, Text, Title } from '@mantine/core'
import { useEffect } from 'react'
import type { ClienteDaApi } from './api.ts'
import type { Usuario } from './App.tsx'
import { abasPermitidas } from './administracao.ts'
import { Link } from './Link.tsx'
import { ACERVO, enderecoDaAba, navegar } from './rotas.ts'
import { CORES } from './tema.ts'
import Auditoria from './Auditoria.tsx'
import { filtrosDaAuditoria } from './auditoria.ts'
import Chaves from './Chaves.tsx'
import Entradas from './Entradas.tsx'
import { filtrosDasEntradas } from './entradas.ts'
import Lixeira from './Lixeira.tsx'
import Usuarios from './Usuarios.tsx'

/** `/admin`: as abas são links com endereço próprio; `/admin` abre a primeira permitida. */
export default function Administracao({ api, aba, busca, usuario, aoEntrarDeNovo }: { api: ClienteDaApi; aba: string | null; busca: string; usuario: Usuario; aoEntrarDeNovo: () => void }) {
  const permitidas = abasPermitidas(usuario.permissoes)
  const atual = permitidas.find((a) => a.aba === aba)
  const primeira = permitidas[0]?.aba

  useEffect(() => {
    if (aba === null && primeira) navegar(enderecoDaAba(primeira), { substituir: true })
  }, [aba, primeira])

  if (!atual) {
    if (aba === null && primeira) return null
    return (
      <Stack align="center" mt="xl">
        <Text>Página não encontrada.</Text>
        <Link para={ACERVO}>Ir ao acervo</Link>
      </Stack>
    )
  }
  return (
    <Stack gap="md" maw={1200}>
      <Title order={2} size="h3">
        Administração
      </Title>
      <nav aria-label="Abas da administração">
        <Group gap="md">
          {permitidas.map((a) => (
            <Link
              key={a.aba}
              para={enderecoDaAba(a.aba)}
              size="sm"
              underline={a === atual ? 'always' : 'hover'}
              c={a === atual ? CORES.texto : CORES.textoSecundario}
              aria-current={a === atual ? 'page' : undefined}
            >
              {a.rotulo}
            </Link>
          ))}
        </Group>
      </nav>
      {atual.aba === 'entradas' && (
        <Entradas
          api={api}
          filtros={filtrosDasEntradas(busca)}
          podeReprocessar={usuario.permissoes.includes('video.reprocessar')}
          podeEscolherEtapa={usuario.permissoes.includes('video.reprocessar_etapa')}
          podeVerSistemas={usuario.permissoes.includes('chaves.gerir')}
        />
      )}
      {atual.aba === 'usuarios' && <Usuarios api={api} eu={usuario} />}
      {atual.aba === 'chaves' && <Chaves api={api} />}
      {atual.aba === 'auditoria' && <Auditoria api={api} filtros={filtrosDaAuditoria(busca)} />}
      {atual.aba === 'lixeira' && <Lixeira api={api} aoEntrarDeNovo={aoEntrarDeNovo} />}
    </Stack>
  )
}
