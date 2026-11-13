"""Conexão com o PostgreSQL e execução dos arquivos .sql.

Credenciais nunca vão no código: variáveis de ambiente DB_HOST, DB_PORT, DB_NAME, DB_USER,
DB_PASSWORD (e DB_SCHEMA, opcional), ou um arquivo .env na raiz do repositório (veja .env.example).
"""
from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carregar_env() -> None:
    caminho = os.path.join(RAIZ, ".env")
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def conectar():
    import psycopg  # só exigido quando realmente vai ao banco

    carregar_env()
    faltando = [v for v in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if not os.environ.get(v)]
    if faltando:
        sys.exit(f"Defina as variáveis de ambiente {', '.join(faltando)} (ou crie o arquivo .env).")
    schema = os.environ.get("DB_SCHEMA")
    return psycopg.connect(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
                           dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                           password=os.environ["DB_PASSWORD"],
                           options=f"-c search_path={schema}" if schema else None)


def comandos_sql(caminho: str) -> list[str]:
    """Divide um arquivo .sql em comandos: tira linhas de comentário e corta no ';' de fim de linha."""
    comandos, atual = [], []
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            limpa = linha.strip()
            if not limpa or limpa.startswith("--"):
                continue
            if limpa.endswith(";"):
                atual.append(linha.rstrip().rstrip(";"))
                comandos.append("\n".join(atual).strip())
                atual = []
            else:
                atual.append(linha.rstrip())
    if any(l.strip() for l in atual):
        comandos.append("\n".join(atual).strip())
    return comandos


def executar_arquivo(cur, caminho: str) -> int:
    """Executa todos os comandos do arquivo. O 02_apagar usa IF EXISTS, então não precisa ignorar erro
    (no PostgreSQL um erro aborta a transação inteira, não dá para só pular o comando)."""
    n = 0
    for sql in comandos_sql(caminho):
        cur.execute(sql)
        n += 1
    return n


def tabelas_existentes(cur) -> set[str]:
    cur.execute("SELECT UPPER(table_name) FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name LIKE 'tmc\\_%'")
    return {t for (t,) in cur.fetchall()}
