import { AppShell, Badge, Button, Group, Kbd, Menu, Text, TextInput } from '@mantine/core'
import { IconChevronDown, IconKeyboard, IconLogout, IconSearch } from '@tabler/icons-react'
import { useRef, useState } from 'react'
import { useAtalhos, useMostrarAtalhos } from './atalhos.ts'
import { Link } from './Link.tsx'
import { ACERVO, enderecoDaBusca, navegar, useRota } from './rotas.ts'
import { CORES } from './tema.ts'

const ATALHO_DA_BUSCA = {
  tecla: '/',
  acao: 'Buscar no acervo',
  grupo: 'Geral',
}

/** A caixa de busca do centro da barra: Enter vai a `/busca?q=…`; `/` a foca de qualquer tela. */
function CaixaDeBusca() {
  const rota = useRota()
  const daUrl = rota.tipo === 'busca' ? rota.consulta.q : ''
  const [texto, setTexto] = useState(daUrl)
  // A caixa acompanha a busca da URL (voltar, abrir um link); sem ela, guarda o que se digitou.
  const [urlVista, setUrlVista] = useState(daUrl)
  if (daUrl !== urlVista) {
    setUrlVista(daUrl)
    setTexto(daUrl)
  }
  const campo = useRef<HTMLInputElement>(null)
  useAtalhos([
    {
      ...ATALHO_DA_BUSCA,
      executar: () => {
        campo.current?.focus()
        campo.current?.select()
      },
    },
  ])
  return (
    <form
      role="search"
      style={{ flex: '0 1 460px', minWidth: 0 }}
      onSubmit={(e) => {
        e.preventDefault()
        const q = texto.trim()
        if (q) navegar(enderecoDaBusca({ q, evidencias: null, programa: null, ano: null, ordem: 'relevancia' }))
      }}
    >
      <TextInput
        ref={campo}
        size="xs"
        aria-label="Buscar no acervo"
        placeholder="Buscar no acervo…"
        value={texto}
        onChange={(e) => setTexto(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') e.currentTarget.blur()
        }}
        leftSection={<IconSearch size={14} aria-hidden />}
        rightSection={<Kbd size="xs">/</Kbd>}
        rightSectionWidth={32}
      />
    </form>
  )
}

/** A barra fixa de toda tela depois do login (`ALTURA_DA_BARRA`, no tema). */
export default function Barra({ email, aoSair }: { email: string; aoSair: () => void }) {
  const mostrarAtalhos = useMostrarAtalhos()
  return (
    <AppShell.Header>
      <Group h="100%" px="md" justify="space-between" wrap="nowrap">
        <Group gap="md" wrap="nowrap">
          <Link para={ACERVO} underline="never" c="inherit" aria-label="MAM, ir ao acervo">
            <Group gap="xs" wrap="nowrap">
              <Badge color={CORES.marca} variant="filled" radius="sm">
                RedeTV
              </Badge>
              <Text fw={700}>MAM</Text>
            </Group>
          </Link>
          <nav aria-label="Principal">
            <Link para={ACERVO} size="sm" c="dimmed" underline="hover">
              Acervo
            </Link>
          </nav>
        </Group>
        <CaixaDeBusca />
        <Menu position="bottom-end">
          <Menu.Target>
            <Button
              type="button"
              variant="subtle"
              color="gray"
              size="compact-sm"
              rightSection={<IconChevronDown size={14} />}
              aria-label={`Conta: ${email}`}
            >
              {email}
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconKeyboard size={16} />} onClick={mostrarAtalhos}>
              Atalhos (?)
            </Menu.Item>
            <Menu.Item leftSection={<IconLogout size={16} />} onClick={aoSair}>
              Sair
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
    </AppShell.Header>
  )
}
