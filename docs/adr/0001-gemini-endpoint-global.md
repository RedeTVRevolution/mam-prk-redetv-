# Gemini no endpoint global, com o resto em São Paulo

> **Região substituída em 09/11/2026 pela [ADR 0019](0019-tudo-em-us-east4.md):** todo o MAM, dados incluídos, passa a ficar em `us-east4`. O que esta ADR diz sobre guardar dados no Brasil ou sobre a região dos buckets, do Firestore e do BigQuery deixou de valer.

Toda a aplicação e os dados guardados ficam em `southamerica-east1`, mas as chamadas ao Gemini usam o endpoint global, porque o modo Flex (50% de desconto) só existe nele. Por isso o vídeo é processado pelo modelo fora do Brasil, embora fique armazenado em São Paulo. A RedeTV já autorizou esse envio. Um endpoint regional exigiria o modo Standard, pelo dobro do preço, e só se o modelo estiver disponível na região.
