import { Button, Group, Loader, Modal, Stack, Text, TextInput } from '@mantine/core'
import { useEffect, useState } from 'react'
import { SessaoExpirada, type ClienteDaApi } from './api.ts'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { falhaDaAcao, type Falha } from './falhaDaAcao.ts'
import type { Job } from './jobs.ts'
import { frasesDoImpacto } from './lixeira.ts'

/** Montado só enquanto aberto: mostra o que vai junto, pede o motivo e manda com um clique. */
export default function MandarParaLixeira({
  api,
  job,
  aoFechar,
  aoMandar,
}: {
  api: ClienteDaApi
  job: Job
  aoFechar: () => void
  aoMandar: () => void
}) {
  const [frases, setFrases] = useState<string[] | null>(null)
  const [motivo, setMotivo] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)

  useEffect(() => {
    let ativo = true
    api.lixeira.impacto('video', job.id).then(
      (i) => ativo && setFrases(frasesDoImpacto('video', i)),
      (erro: unknown) => {
        if (ativo && !(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível calcular o que vai junto. Tente de novo.'))
      },
    )
    return () => {
      ativo = false
    }
  }, [api, job.id])

  async function mandar() {
    setEnviando(true)
    setFalha(null)
    try {
      await api.lixeira.enviar('video', job.id, motivo.trim())
      aoMandar()
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível mandar ${job.nome} para a lixeira. Tente de novo.`))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Modal
      opened
      onClose={enviando ? () => {} : aoFechar}
      title={`Mandar ${job.nome} para a lixeira`}
      closeOnEscape={!enviando}
      closeOnClickOutside={!enviando}
      withCloseButton={!enviando}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (motivo.trim() !== '' && !enviando) void mandar()
        }}
      >
        <Stack gap="sm">
          {frases === null && !falha && <Loader size="sm" role="status" aria-label="Calculando o que vai junto" />}
          {frases?.map((f) => (
            <Text key={f} size="sm">
              {f}
            </Text>
          ))}
          <Text size="sm">Sai da busca, do acervo e dos relatórios na hora. Nada é destruído: dá para restaurar em até 30 dias.</Text>
          <TextInput label="Motivo" required value={motivo} onChange={(e) => setMotivo(e.currentTarget.value)} data-autofocus />
          {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
          <Group justify="flex-end">
            <Button type="button" variant="default" onClick={aoFechar} disabled={enviando}>
              Cancelar
            </Button>
            <Button type="submit" disabled={motivo.trim() === ''} loading={enviando}>
              Mandar para a lixeira
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}
