import { Group, Stack, Text, Title } from '@mantine/core'
import { useEffect } from 'react'
import type { ClienteDaApi } from './api.ts'
import type { Usuario } from './App.tsx'
import { Link } from './Link.tsx'
import { ACERVO, enderecoDaAba, navegar } from './rotas.ts'
import { CORES } from './tema.ts'
import Usuarios from './Usuarios.tsx'

interface Aba {
  aba: string
  rotulo: string
  permissao: string
}

// Cada ticket da área acrescenta a sua aba aqui (chaves, entradas, lixeira, auditoria).
const ABAS: Aba[] = [{ aba: 'usuarios', rotulo: 'Usuários', permissao: 'usuarios.gerir' }]

/** `/admin`: as abas são links com endereço próprio; `/admin` abre a primeira permitida. */
export default function Administracao({ api, aba, usuario }: { api: ClienteDaApi; aba: string | null; usuario: Usuario }) {
  const permitidas = ABAS.filter((a) => usuario.permissoes.includes(a.permissao))
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
      {atual.aba === 'usuarios' && <Usuarios api={api} eu={usuario} />}
    </Stack>
  )
}
