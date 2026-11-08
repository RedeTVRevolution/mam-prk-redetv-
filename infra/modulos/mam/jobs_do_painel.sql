-- Uma linha por Job para as abas Revisão e Custo do painel (#454). Roda de tempos em tempos
-- como consulta agendada (`jobs_do_painel.tf`) sobre os eventos de uso (#279): o `envio`
-- cria a linha (programa e dono) e o `fim_de_processamento` a fecha (estado, duração do
-- vídeo e dia do fim). O Job reprocessado traz um fim novo, que vale sobre o anterior. Os
-- Jobs anteriores aos eventos entram uma vez por `make preencher-jobs-do-painel`. A tabela
-- é criada pelo Terraform (particionada pelo dia de `criado_em` e agrupada por programa e
-- id); `${tabela}` é o nome inteiro desta tabela, `${tabela_de_eventos}` o nome inteiro
-- da tabela de eventos e `${inicio_da_janela}` o começo (TIMESTAMP) do período que pode ter
-- mudado. Os testes rodam este arquivo no SQLite, por isso só há SQL comum aos dois.
--
-- Cada rodada refaz só os Jobs com evento na janela. Os marcadores de purga são lidos
-- sem janela, para recusar também eventos atrasados de um vídeo já purgado.
-- Uma linha já gravada mantém o que a janela não traz (dono, criação, duração).
-- A purga grava o marcador e apaga a linha na mesma transação. A trava vem antes da
-- leitura: uma rodada concorrente falha em vez de reinserir uma fotografia anterior.
BEGIN TRANSACTION;
DELETE FROM `${tabela}` WHERE FALSE;

CREATE TEMP TABLE janela AS
SELECT id, quando, tipo, quem_tipo, quem_id, programa, estado, job_id, duracao_do_video_ms
FROM (
  SELECT
    u.*,
    ROW_NUMBER() OVER (PARTITION BY id ORDER BY quando) AS ordem
  FROM `${tabela_de_eventos}` AS u
  WHERE u.quando >= ${inicio_da_janela}
    AND u.tipo IN ('envio', 'fim_de_processamento')
    AND u.job_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM `${tabela_de_eventos}` AS p
      WHERE p.tipo = 'purga' AND p.job_id = u.job_id
    )
)
WHERE ordem = 1;

CREATE TEMP TABLE do_envio AS
SELECT job_id, quando, quem_tipo, quem_id, programa
FROM (
  SELECT
    job_id, quando, quem_tipo, quem_id, programa,
    ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY quando) AS vez
  FROM janela
  WHERE tipo = 'envio'
)
WHERE vez = 1;

-- O último fim de cada Job; a duração e o programa que ele não traz ficam com o que já havia.
CREATE TEMP TABLE do_fim AS
SELECT job_id, quando, quem_tipo, quem_id, programa, estado, duracao_do_video_ms
FROM (
  SELECT
    job_id, quando, quem_tipo, quem_id, programa, estado, duracao_do_video_ms,
    ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY quando DESC) AS vez
  FROM janela
  WHERE tipo = 'fim_de_processamento'
)
WHERE vez = 1;

CREATE TEMP TABLE novos AS
SELECT
  j.job_id AS id,
  COALESCE(e.programa, f.programa, a.programa) AS programa,
  COALESCE(f.duracao_do_video_ms, a.duracao_ms) AS duracao_ms,
  COALESCE(e.quem_tipo, a.quem_tipo, f.quem_tipo) AS quem_tipo,
  COALESCE(e.quem_id, a.quem_id, f.quem_id) AS quem_id,
  COALESCE(f.estado, a.estado, 'em_andamento') AS estado,
  COALESCE(a.criado_em, e.quando, f.quando) AS criado_em,
  COALESCE(f.quando, a.concluido_em) AS concluido_em,
  COALESCE(f.quando, e.quando, a.atualizado_em) AS atualizado_em
FROM (
  SELECT DISTINCT job_id
  FROM (
    SELECT job_id FROM do_envio
    UNION ALL
    SELECT job_id FROM do_fim
  )
) AS j
LEFT JOIN do_envio AS e ON e.job_id = j.job_id
LEFT JOIN do_fim AS f ON f.job_id = j.job_id
LEFT JOIN `${tabela}` AS a ON a.id = j.job_id;

-- Troca as linhas dos Jobs da rodada de uma vez, para o painel não ler a tabela pela metade.
DELETE FROM `${tabela}` WHERE id IN (SELECT id FROM novos);
INSERT INTO `${tabela}`
  (id, programa, duracao_ms, quem_tipo, quem_id, estado, criado_em, concluido_em, atualizado_em)
SELECT id, programa, duracao_ms, quem_tipo, quem_id, estado, criado_em, concluido_em, atualizado_em
FROM novos;
COMMIT TRANSACTION;
