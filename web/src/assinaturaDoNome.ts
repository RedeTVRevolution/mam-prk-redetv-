/**
 * A assinatura de um nome (#544), a mesma regra de `api/assinatura_do_nome.py`: normaliza, separa as palavras, tira
 * as vazias, passa cada uma ao singular (até estabilizar), tira a que repete a cor do item e ordena.
 * `api/tests/assinatura_do_nome.json` é lida pelo teste daqui e pelo do Python, para as duas não divergirem.
 */

// Como `normalizar` de api/comparador.py: NFKD + casefold (toLowerCase, mais o único caso que difere: ß).
const normalizar = (t: string): string =>
  t.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/ß/g, 'ss').split(/\s+/).filter(Boolean).join(' ')

const PALAVRAS_VAZIAS = new Set(['de', 'da', 'do', 'das', 'dos', 'com', 'um', 'uma'])

// Espelho de `api/numero.py` (singular): as mesmas listas e a mesma ordem das regras.
const INVARIAVEIS = new Set([
  'mais', 'menos', 'seis', 'dois', 'três', 'tres', 'cais', 'deus', 'país',
  'lápis', 'lapis', 'ônibus', 'onibus', 'tênis', 'tenis', 'vírus', 'virus',
  'atlas', 'pires', 'simples', 'oásis', 'oasis', 'tórax', 'torax',
])
const IRREGULARES: Record<string, string> = {
  mães: 'mãe', maes: 'mãe', reis: 'rei', leis: 'lei', bois: 'boi',
  pais: 'pai', heróis: 'herói', herois: 'herói', meses: 'mês',
  países: 'país', paises: 'país', gases: 'gás',
}
const REGRAS: [string, string][] = [
  ['ões', 'ão'], ['ães', 'ão'], ['ãos', 'ão'], ['oes', 'ao'], ['ns', 'm'],
  ['éis', 'el'], ['eis', 'el'], ['óis', 'ol'], ['ois', 'ol'],
  ['ais', 'al'], ['uis', 'ul'], ['res', 'r'], ['zes', 'z'], ['s', ''],
]

function singular(palavra: string): string {
  const p = palavra.toLowerCase()
  if ([...p].length <= 3 || INVARIAVEIS.has(p)) return p
  const irregular = IRREGULARES[p]
  if (irregular !== undefined) return irregular
  for (const [fim, troca] of REGRAS) if (p.endsWith(fim)) return p.slice(0, p.length - fim.length) + troca
  return p
}

function singularEstavel(palavra: string): string {
  let atual = palavra
  for (;;) {
    const s = normalizar(singular(atual))
    if (s === atual) return atual
    atual = s
  }
}

function formasDaCor(cor: string): string[] {
  const base = singularEstavel(normalizar(cor))
  return base.endsWith('o') ? [base, `${base.slice(0, -1)}a`] : [base]
}

export function assinatura(nome: string, cores: readonly string[] = []): string {
  const palavras = (normalizar(nome).match(/[\p{L}\p{N}]+(?:-[\p{L}\p{N}]+)*/gu) ?? [])
    .filter((p) => !PALAVRAS_VAZIAS.has(p))
    .map(singularEstavel)
  const cor = new Set(cores.flatMap(formasDaCor))
  const semCor = palavras.filter((p) => !cor.has(p))
  return [...new Set(semCor.length > 0 ? semCor : palavras)].sort().join(' ')
}
