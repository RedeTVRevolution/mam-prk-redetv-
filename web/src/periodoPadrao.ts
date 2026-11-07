// O período padrão dos relatórios (#462): os últimos 7 dias, de hoje − 6 até hoje, no dia de
// São Paulo. A API usa a mesma conta (`api/periodo_padrao.py`) quando o pedido não traz datas.
//
// Na URL, `de` e `ate` ausentes valem o padrão; presentes e vazios (`?de=&ate=`) são o histórico
// inteiro, que a pessoa pode escolher.

export const DIAS_DO_PERIODO_PADRAO = 7

const DIA_EM_SAO_PAULO = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/Sao_Paulo',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function diaDeSaoPaulo(instante: Date): string {
  return DIA_EM_SAO_PAULO.format(instante)
}

/** `{ de, ate }` em `AAAA-MM-DD`; `agora` é o relógio que o teste troca. */
export function periodoPadrao(agora: Date = new Date()): { de: string; ate: string } {
  const ate = diaDeSaoPaulo(agora)
  const [ano, mes, dia] = ate.split('-').map(Number) as [number, number, number]
  const inicio = new Date(Date.UTC(ano, mes - 1, dia - (DIAS_DO_PERIODO_PADRAO - 1)))
  return { de: inicio.toISOString().slice(0, 10), ate }
}

const DATA = /^\d{4}-\d{2}-\d{2}$/

/** O período do endereço: sem `de` nem `ate`, o padrão; com algum (mesmo vazio), o que veio, e data malformada sai. */
export function periodoDoEndereco(p: URLSearchParams, agora?: Date): { de: string; ate: string } {
  if (!p.has('de') && !p.has('ate')) return periodoPadrao(agora)
  const data = (nome: string) => (DATA.test(p.get(nome) ?? '') ? p.get(nome)! : '')
  return { de: data('de'), ate: data('ate') }
}

/** Grava o período no endereço: vazio entra como `de=&ate=`, senão a tela voltaria ao padrão. */
export function poePeriodoNoEndereco(p: URLSearchParams, f: { de: string; ate: string }): void {
  p.set('de', f.de)
  p.set('ate', f.ate)
}

/** Grava o período na query da API: sem datas, `desde=&ate=` vazios pedem o histórico inteiro. */
export function poePeriodoNaConsulta(p: URLSearchParams, f: { de: string; ate: string }): void {
  p.set('desde', f.de)
  p.set('ate', f.ate)
}
