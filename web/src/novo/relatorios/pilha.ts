import { useState } from "react";

interface Estado {
  chave: string;
  cursores: string[];
  aberta: string | null;
}

const COMECO = (chave: string): Estado => ({ chave, cursores: [""], aberta: null });

/**
 * A página da tabela e a linha aberta. A página é a pilha dos cursores já percorridos (o do topo
 * é o da página atual, "" a primeira), então voltar não guarda nada além disso. Quando a `chave`
 * (os filtros) muda, tudo recomeça, sem efeito: o estado de outra chave nem é lido.
 */
export function useTabelaPaginada(chave: string) {
  const [estado, definir] = useState<Estado>(COMECO(chave));
  const atual = estado.chave === chave ? estado : COMECO(chave);
  return {
    cursor: atual.cursores[atual.cursores.length - 1],
    pagina: atual.cursores.length,
    aberta: atual.aberta,
    avancar: (proximo: string) => definir({ ...atual, cursores: [...atual.cursores, proximo], aberta: null }),
    voltar: () => definir({ ...atual, cursores: atual.cursores.slice(0, -1), aberta: null }),
    abrir: (id: string | null) => definir({ ...atual, aberta: id }),
    /** Do gráfico: a linha está na primeira página, que é de onde o gráfico tira as barras. */
    mostrarNaPrimeira: (id: string) => definir({ ...atual, cursores: [""], aberta: id }),
  };
}
