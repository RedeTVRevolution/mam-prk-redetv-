// A escala sequencial da matriz marca × tipo (MAM_DESIGN_SYSTEM 2.6): cinco passos do azul de foco.

export type Passo = 100 | 250 | 400 | 500 | 600;

/** Do menor ao maior quinto; no escuro o maior valor é o mais claro. */
const PASSOS: Passo[] = [600, 500, 400, 250, 100];

/** O passo do valor numa escala só para a matriz inteira; sem valor (ou sem máximo) não há cor, a célula é a própria superfície. */
export function passoDaEscala(valor: number, maximo: number): Passo | null {
  if (valor <= 0 || maximo <= 0) return null;
  return PASSOS[Math.min(PASSOS.length - 1, Math.ceil((valor / maximo) * PASSOS.length) - 1)];
}
