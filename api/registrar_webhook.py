"""`registrar-webhook <sistema> <url>` (E7): registra o webhook de um sistema.

Falta o adaptador do Cofre real (Secret Manager com CMEK, outro ticket): sem ele o
comando não tem onde guardar o segredo e se recusa a rodar.
"""

import sys

if __name__ == "__main__":
    sys.exit("o cofre do segredo (Secret Manager) ainda não foi ligado")
