import os

# Antes de qualquer import do gRPC (o Firestore o carrega): com o suporte a `fork` ligado o
# gRPC registra um handler que aborta o filho quando o ffmpeg sobe por `subprocess` num
# processo com o cliente aberto, e sob carga isso derruba o processo (#385). Quem define a
# variável por fora (um teste, a configuração do serviço) continua valendo.
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "false")
