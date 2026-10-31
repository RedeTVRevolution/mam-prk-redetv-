import { AppShell, Badge, Button, Group, Menu, Text } from '@mantine/core'
import { IconChevronDown, IconKeyboard, IconLogout } from '@tabler/icons-react'
import { useMostrarAtalhos } from './atalhos.ts'
import { Link } from './Link.tsx'
import { ACERVO } from './rotas.ts'
import { CORES } from './tema.ts'

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
