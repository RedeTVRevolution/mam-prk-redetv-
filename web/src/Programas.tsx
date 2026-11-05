import { Button, Group, Loader, Modal, Stack, Table, Text, TextInput, Textarea, Title } from '@mantine/core'
import { useCallback, useEffect, useState } from 'react'
import { SessaoExpirada, type ClienteDaApi, type DadosDoPrograma, type PessoaNoPrograma, type ProgramaCadastrado } from './api.ts'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { CampoDeNome } from './CampoDeNome.tsx'
import { falhaDaAcao, type Falha } from './falhaDaAcao.ts'
import { NomesDoCatalogo } from './nomesDoCatalogo.ts'
import { CORES } from './tema.ts'

const LIMITE_DO_NOME = 100
const LIMITE_DO_PERFIL = 4000
const LIMITE_DO_PAPEL = 100

type Carga = { tipo: 'carregando' } | { tipo: 'pronta' } | { tipo: 'erro'; mensagem: string; codigo: string }

function Formulario({
  api,
  programa,
  aoFechar,
  aoGravar,
}: {
  api: ClienteDaApi
  /** `null` cria um programa novo. */
  programa: ProgramaCadastrado | null
  aoFechar: () => void
  aoGravar: (p: ProgramaCadastrado) => void
}) {
  const [nome, setNome] = useState(programa?.nome ?? '')
  const [perfil, setPerfil] = useState(programa?.perfil ?? '')
  const [pessoas, setPessoas] = useState<PessoaNoPrograma[]>(programa?.pessoas ?? [])
  const [busca, setBusca] = useState('')
  const [apelidos, setApelidos] = useState('')
  const [criandoPessoa, setCriandoPessoa] = useState(false)
  const [gravando, setGravando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)

  function incluir(p: PessoaNoPrograma) {
    setPessoas((atuais) => (atuais.some((a) => a.pessoa_id === p.pessoa_id) ? atuais : [...atuais, { ...p, papel: '' }]))
    setBusca('')
    setApelidos('')
  }

  async function criarPessoa() {
    setCriandoPessoa(true)
    setFalha(null)
    try {
      const lista = apelidos
        .split(',')
        .map((a) => a.trim())
        .filter(Boolean)
      incluir(await api.cadastroDeProgramas.criarPessoa(busca.trim(), lista))
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível criar a pessoa. Tente de novo.'))
    } finally {
      setCriandoPessoa(false)
    }
  }

  async function gravar() {
    setGravando(true)
    setFalha(null)
    const dados: DadosDoPrograma = { nome: nome.trim(), perfil, pessoas: pessoas.map((p) => ({ pessoa_id: p.pessoa_id, papel: p.papel })) }
    try {
      const gravado = programa ? await api.cadastroDeProgramas.mudar(programa.id, dados) : await api.cadastroDeProgramas.criar(dados)
      aoGravar(gravado)
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível gravar o programa. Tente de novo.'))
    } finally {
      setGravando(false)
    }
  }

  return (
    <Modal opened onClose={gravando ? () => {} : aoFechar} title={programa ? `Editar ${programa.nome}` : 'Novo programa'} size="lg" closeOnEscape={!gravando}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (nome.trim() && !gravando) void gravar()
        }}
      >
        <Stack gap="sm">
          <TextInput label="Nome" value={nome} maxLength={LIMITE_DO_NOME} onChange={(e) => setNome(e.currentTarget.value)} data-autofocus />
          <Textarea
            label="Perfil: o contexto que o modelo recebe (tipo de programa, merchandising frequente)"
            value={perfil}
            maxLength={LIMITE_DO_PERFIL}
            rows={5}
            onChange={(e) => setPerfil(e.currentTarget.value)}
          />
          <Title order={3} size="h5">
            Pessoas
          </Title>
          {pessoas.length === 0 && (
            <Text size="sm" c={CORES.textoSecundario}>
              Nenhuma pessoa neste programa.
            </Text>
          )}
          {pessoas.map((p, i) => (
            <Group key={p.pessoa_id} gap="sm" align="flex-end">
              <Text size="sm" w={200}>
                {p.nome}
              </Text>
              <TextInput
                size="xs"
                aria-label={`Papel de ${p.nome}`}
                placeholder="apresentador, repórter…"
                value={p.papel}
                maxLength={LIMITE_DO_PAPEL}
                onChange={(e) => {
                  const papel = e.currentTarget.value
                  setPessoas((atuais) => atuais.map((a, j) => (j === i ? { ...a, papel } : a)))
                }}
              />
              <Button type="button" size="xs" variant="default" onClick={() => setPessoas((atuais) => atuais.filter((_, j) => j !== i))}>
                Tirar {p.nome}
              </Button>
            </Group>
          ))}
          <NomesDoCatalogo.Provider value={api.nomes}>
            <CampoDeNome
              rotulo="Incluir pessoa do catálogo"
              catalogo="pessoas"
              soDoCatalogo
              valor={busca}
              aoMudar={(texto, id) => {
                if (id) incluir({ pessoa_id: id, nome: texto, apelidos: [], papel: '' })
                else setBusca(texto)
              }}
            />
          </NomesDoCatalogo.Provider>
          {busca.trim().length >= 2 && (
            <Group gap="sm" align="flex-end">
              <TextInput size="xs" label="Apelidos (separados por vírgula)" value={apelidos} onChange={(e) => setApelidos(e.currentTarget.value)} />
              <Button type="button" size="xs" variant="default" loading={criandoPessoa} onClick={() => void criarPessoa()}>
                Criar pessoa «{busca.trim()}»
              </Button>
            </Group>
          )}
          {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
          <Group justify="flex-end">
            <Button type="button" variant="default" onClick={aoFechar} disabled={gravando}>
              Cancelar
            </Button>
            <Button type="submit" loading={gravando} disabled={!nome.trim()}>
              Gravar
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}

function Apagar({
  api,
  programa,
  aoFechar,
  aoApagar,
}: {
  api: ClienteDaApi
  programa: ProgramaCadastrado
  aoFechar: () => void
  aoApagar: () => void
}) {
  const [videos, setVideos] = useState<number | null>(null)
  const [apagando, setApagando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)

  useEffect(() => {
    let ativo = true
    api.cadastroDeProgramas.impacto(programa.id).then(
      (i) => ativo && setVideos(i.videos),
      (erro: unknown) => {
        if (ativo && !(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível contar os vídeos do programa. Tente de novo.'))
      },
    )
    return () => {
      ativo = false
    }
  }, [api, programa.id])

  async function apagar() {
    setApagando(true)
    setFalha(null)
    try {
      await api.cadastroDeProgramas.apagar(programa.id)
      aoApagar()
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível apagar ${programa.nome}. Tente de novo.`))
    } finally {
      setApagando(false)
    }
  }

  return (
    <Modal opened onClose={apagando ? () => {} : aoFechar} title={`Apagar ${programa.nome}`} closeOnEscape={!apagando}>
      <Stack gap="sm">
        {videos === null && !falha && <Loader size="sm" role="status" aria-label="Contando os vídeos do programa" />}
        {videos !== null && (
          <Text size="sm">
            {videos === 0 ? 'Nenhum vídeo usa este programa.' : `${videos} ${videos === 1 ? 'vídeo usa' : 'vídeos usam'} este programa e ${videos === 1 ? 'continua' : 'continuam'} com o nome dele no acervo.`}
          </Text>
        )}
        <Text size="sm">O programa sai do cadastro e da lista do envio. As pessoas continuam no catálogo.</Text>
        {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={aoFechar} disabled={apagando}>
            Cancelar
          </Button>
          <Button type="button" variant="outline" color={CORES.falhou} loading={apagando} disabled={videos === null} onClick={() => void apagar()}>
            Apagar programa
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** `/admin/programas`: criar, editar e apagar programas, com as pessoas e o papel de cada uma nele. */
export default function Programas({ api }: { api: ClienteDaApi }) {
  const [lista, setLista] = useState<ProgramaCadastrado[]>([])
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [editando, setEditando] = useState<ProgramaCadastrado | 'novo' | null>(null)
  const [apagando, setApagando] = useState<ProgramaCadastrado | null>(null)

  const carregar = useCallback(async () => {
    setCarga({ tipo: 'carregando' })
    try {
      setLista(await api.cadastroDeProgramas.listar())
      setCarga({ tipo: 'pronta' })
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro', ...falhaDaAcao(erro, 'Não foi possível carregar os programas. Tente de novo.') })
    }
  }, [api])

  useEffect(() => {
    // Sincroniza com a API, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void carregar()
  }, [carregar])

  return (
    <Stack gap="sm">
      <Group>
        <Button size="xs" onClick={() => setEditando('novo')} disabled={carga.tipo !== 'pronta'}>
          Novo programa
        </Button>
      </Group>
      {carga.tipo === 'carregando' && <Loader size="sm" role="status" aria-label="Carregando os programas" />}
      {carga.tipo === 'erro' && <AlertaDeErro mensagem={carga.mensagem} codigo={carga.codigo} aoTentar={() => void carregar()} />}
      {carga.tipo === 'pronta' && lista.length === 0 && <Text size="sm">Nenhum programa cadastrado.</Text>}
      {carga.tipo === 'pronta' && lista.length > 0 && (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Programa</Table.Th>
              <Table.Th>Pessoas</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {lista.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>{p.nome}</Table.Td>
                <Table.Td>{p.pessoas.map((x) => (x.papel ? `${x.nome} (${x.papel})` : x.nome)).join(', ')}</Table.Td>
                <Table.Td>
                  <Group gap="xs" justify="flex-end">
                    <Button size="xs" variant="default" aria-label={`Editar ${p.nome}`} onClick={() => setEditando(p)}>
                      Editar
                    </Button>
                    <Button size="xs" variant="default" aria-label={`Apagar ${p.nome}`} onClick={() => setApagando(p)}>
                      Apagar
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {editando && (
        <Formulario
          api={api}
          programa={editando === 'novo' ? null : editando}
          aoFechar={() => setEditando(null)}
          aoGravar={() => {
            setEditando(null)
            void carregar()
          }}
        />
      )}
      {apagando && (
        <Apagar
          api={api}
          programa={apagando}
          aoFechar={() => setApagando(null)}
          aoApagar={() => {
            setApagando(null)
            void carregar()
          }}
        />
      )}
    </Stack>
  )
}
