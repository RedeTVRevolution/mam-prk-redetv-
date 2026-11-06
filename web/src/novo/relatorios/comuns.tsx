import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import type { UseQueryResult } from "@tanstack/react-query";
import { cn } from "cn";
import type { ReactNode } from "react";
import { codigoDoErro } from "../../api.ts";
import type { FiltrosDoRelatorio } from "../../tempoDeTela.ts";
import { Falha } from "../comum/Falha.tsx";
import { CAMPO, mensagemDoErro } from "../comum/relatorio.ts";
import { Campo } from "../comum/relatorio.tsx";
import { useProgramas } from "../consultas.ts";
import { Button } from "../ui/button.tsx";

// O que o Tempo de tela e as Marcas têm em comum na tela: os filtros do período, a paginação da
// tabela, a barrinha de proporção, o botão que abre a linha e o aviso da consulta.

/** Programa e período de exibição; `children` são os filtros próprios do relatório. */
export function FiltrosDoPeriodo({
  filtros,
  aoMudar,
  children,
}: {
  filtros: FiltrosDoRelatorio;
  aoMudar: (parte: Partial<FiltrosDoRelatorio>) => void;
  children?: ReactNode;
}) {
  const programas = useProgramas();
  return (
    <>
      <Campo rotulo="Programa">
        {(id) => (
          <select
            id={id}
            className={cn(CAMPO, "w-48")}
            value={filtros.programa}
            onChange={(e) => aoMudar({ programa: e.target.value })}
          >
            <option value="">Todos os programas</option>
            {/* O programa do endereço que não está na lista continua escolhido. */}
            {filtros.programa && !programas.includes(filtros.programa) && (
              <option value={filtros.programa}>{filtros.programa}</option>
            )}
            {programas.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        )}
      </Campo>
      <Campo rotulo="Exibido de">
        {(id) => (
          <input
            id={id}
            type="date"
            className={CAMPO}
            value={filtros.de}
            onChange={(e) => aoMudar({ de: e.target.value })}
          />
        )}
      </Campo>
      <Campo rotulo="Exibido até">
        {(id) => (
          <input
            id={id}
            type="date"
            className={CAMPO}
            value={filtros.ate}
            onChange={(e) => aoMudar({ ate: e.target.value })}
          />
        )}
      </Campo>
      {children}
    </>
  );
}

/** Anterior e Próxima: a tabela mostra uma página por vez, então ocupa sempre a mesma memória. */
export function Paginacao({
  pagina,
  temProxima,
  aoVoltar,
  aoAvancar,
}: {
  pagina: number;
  temProxima: boolean;
  aoVoltar: () => void;
  aoAvancar: () => void;
}) {
  return (
    <nav aria-label="Páginas da tabela" className="flex items-center justify-end gap-2 pt-3">
      <Button type="button" variant="secondary" size="sm" disabled={pagina === 1} onClick={aoVoltar}>
        Anterior
      </Button>
      <span className="text-xs text-muted-foreground">Página {pagina}</span>
      <Button type="button" variant="secondary" size="sm" disabled={!temProxima} onClick={aoAvancar}>
        Próxima
      </Button>
    </nav>
  );
}

/** O valor com uma barrinha de até 48 px, proporcional ao maior da página. */
export function ComBarra({ valor, maximo, children }: { valor: number; maximo: number; children: ReactNode }) {
  const largura = maximo > 0 && valor > 0 ? Math.max(2, Math.round((48 * valor) / maximo)) : 0;
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span aria-hidden className="h-1.5 rounded-xs bg-primary" style={{ width: largura }} />
      {children}
    </span>
  );
}

/** O nome da linha como botão que abre e fecha o detalhe. */
export function BotaoDaLinha({
  id,
  aberta,
  aoAlternar,
  children,
}: {
  id: string;
  aberta: boolean;
  aoAlternar: () => void;
  children: ReactNode;
}) {
  const Icone = aberta ? IconChevronDown : IconChevronRight;
  return (
    <button
      type="button"
      id={id}
      aria-expanded={aberta}
      onClick={aoAlternar}
      className="-ml-1 flex items-center gap-1 rounded-xs px-1 text-left hover:text-link"
    >
      <Icone size={14} stroke={1.75} className="shrink-0 text-muted-foreground" aria-hidden />
      {children}
    </button>
  );
}

/** O que a consulta mostra enquanto não tem dados: a espera ou a falha, com a nova tentativa. */
export function AvisoDaConsulta({ consulta, espera }: { consulta: UseQueryResult<unknown, unknown>; espera: string }) {
  if (consulta.isError) {
    return (
      <Falha
        mensagem={mensagemDoErro(consulta.error)}
        codigo={codigoDoErro(consulta.error)}
        aoTentar={() => void consulta.refetch()}
      />
    );
  }
  if (!consulta.isPending) return null;
  return (
    <p role="status" aria-label={espera} className="py-6 text-center text-sm text-muted-foreground">
      {espera}…
    </p>
  );
}
