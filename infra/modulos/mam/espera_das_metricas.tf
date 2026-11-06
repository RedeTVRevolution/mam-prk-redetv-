# O Monitoring recusa uma política de alerta sobre uma métrica de log que acabou de nascer
# ("Cannot find metric(s)"): a métrica leva um tempo para aparecer, e a referência ao nome só
# garante a ordem. As políticas dos sinais esperam 60 s depois das métricas delas, só quando
# alguma métrica é criada ou trocada.
resource "time_sleep" "metricas_dos_alertas" {
  create_duration = "60s"
  triggers = {
    metricas = join(",", concat(
      [for m in google_logging_metric.sinal_percentual : m.name],
      [
        google_logging_metric.respostas_fora_do_esquema.name,
        google_logging_metric.falhas_por_etapa.name,
        google_logging_metric.desvio_de_programa.name,
      ],
    ))
  }
}
