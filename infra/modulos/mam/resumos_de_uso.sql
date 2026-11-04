-- Tabelas resumidas do painel da diretoria (#280, E9). Roda de tempos em tempos como
-- consulta agendada (`resumos_de_uso.tf`) e refaz as quatro tabelas a partir dos eventos de
-- uso (#279). `${p}` é o prefixo `projeto.dataset.` (vazio nos testes, que rodam este arquivo
-- no SQLite: por isso só há SQL comum aos dois, salvo a data com fuso e o CREATE OR REPLACE TABLE).
--
-- Eventos repetidos (o mesmo `id`) valem uma vez. O dia é o de São Paulo. As horas vêm da
-- duração que a cópia dos momentos guarda (`momentos.duracao_do_video_ms`); vídeo ainda não
-- copiado conta como 0 hora.
CREATE TEMP TABLE eventos AS
SELECT
  e.dia, e.quando, e.tipo, e.quem_tipo, e.quem_id, e.programa, e.estado,
  COALESCE(d.horas, 0) AS horas
FROM (
  SELECT
    id, quando, tipo, quem_tipo, quem_id, programa, estado, job_id,
    DATE(quando, 'America/Sao_Paulo') AS dia,
    ROW_NUMBER() OVER (PARTITION BY id ORDER BY quando) AS ordem
  FROM `${p}eventos_de_uso`
) AS e
LEFT JOIN (
  SELECT job_id, MAX(duracao_do_video_ms) / 3600000.0 AS horas
  FROM `${p}momentos`
  GROUP BY job_id
) AS d ON d.job_id = e.job_id
WHERE e.ordem = 1;

-- Um dia, um usuário (ou sistema).
CREATE OR REPLACE TABLE `${p}uso_por_dia_e_usuario` AS
SELECT
  dia, quem_tipo, quem_id,
  COUNT(CASE WHEN tipo = 'login' THEN 1 END) AS acessos,
  COUNT(CASE WHEN tipo = 'envio' THEN 1 END) AS videos_enviados,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN 1 END) AS videos_concluidos,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'falhou' THEN 1 END) AS videos_falhos,
  COALESCE(SUM(CASE WHEN tipo = 'envio' THEN horas END), 0) AS horas_enviadas,
  COALESCE(SUM(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN horas END), 0) AS horas_concluidas,
  COUNT(CASE WHEN tipo = 'busca' THEN 1 END) AS buscas,
  COUNT(CASE WHEN tipo = 'correcao' THEN 1 END) AS correcoes,
  COUNT(CASE WHEN tipo = 'chamada_de_api' THEN 1 END) AS chamadas_de_api
FROM eventos
GROUP BY dia, quem_tipo, quem_id;

-- Um dia, todos juntos. `usuarios_ativos` são só as pessoas, não os sistemas.
CREATE OR REPLACE TABLE `${p}uso_por_dia` AS
SELECT
  dia,
  COUNT(DISTINCT CASE WHEN quem_tipo = 'usuario' THEN quem_id END) AS usuarios_ativos,
  COUNT(CASE WHEN tipo = 'login' THEN 1 END) AS acessos,
  COUNT(CASE WHEN tipo = 'envio' THEN 1 END) AS videos_enviados,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN 1 END) AS videos_concluidos,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'falhou' THEN 1 END) AS videos_falhos,
  COALESCE(SUM(CASE WHEN tipo = 'envio' THEN horas END), 0) AS horas_enviadas,
  COALESCE(SUM(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN horas END), 0) AS horas_concluidas,
  COUNT(CASE WHEN tipo = 'busca' THEN 1 END) AS buscas,
  COUNT(CASE WHEN tipo = 'correcao' THEN 1 END) AS correcoes,
  COUNT(CASE WHEN tipo = 'chamada_de_api' THEN 1 END) AS chamadas_de_api
FROM eventos
GROUP BY dia;

-- Um usuário (ou sistema), o histórico todo.
CREATE OR REPLACE TABLE `${p}uso_por_usuario` AS
SELECT
  quem_tipo, quem_id,
  COUNT(DISTINCT dia) AS dias_ativos,
  MAX(CASE WHEN tipo = 'login' THEN quando END) AS ultimo_acesso,
  COUNT(CASE WHEN tipo = 'login' THEN 1 END) AS acessos,
  COUNT(CASE WHEN tipo = 'envio' THEN 1 END) AS videos_enviados,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN 1 END) AS videos_concluidos,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'falhou' THEN 1 END) AS videos_falhos,
  COALESCE(SUM(CASE WHEN tipo = 'envio' THEN horas END), 0) AS horas_enviadas,
  COALESCE(SUM(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN horas END), 0) AS horas_concluidas,
  COUNT(CASE WHEN tipo = 'busca' THEN 1 END) AS buscas,
  COUNT(CASE WHEN tipo = 'correcao' THEN 1 END) AS correcoes,
  COUNT(CASE WHEN tipo = 'chamada_de_api' THEN 1 END) AS chamadas_de_api
FROM eventos
GROUP BY quem_tipo, quem_id;

-- Um dia, um programa. O login não tem programa; o evento sem programa fica de fora.
CREATE OR REPLACE TABLE `${p}uso_por_dia_e_programa` AS
SELECT
  dia, programa,
  COUNT(CASE WHEN tipo = 'envio' THEN 1 END) AS videos_enviados,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN 1 END) AS videos_concluidos,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'falhou' THEN 1 END) AS videos_falhos,
  COALESCE(SUM(CASE WHEN tipo = 'envio' THEN horas END), 0) AS horas_enviadas,
  COALESCE(SUM(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN horas END), 0) AS horas_concluidas,
  COUNT(CASE WHEN tipo = 'busca' THEN 1 END) AS buscas,
  COUNT(CASE WHEN tipo = 'correcao' THEN 1 END) AS correcoes,
  COUNT(CASE WHEN tipo = 'chamada_de_api' THEN 1 END) AS chamadas_de_api
FROM eventos
WHERE programa IS NOT NULL
GROUP BY dia, programa;
