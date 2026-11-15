"""
ThermoCity — cria as tabelas TMC_ e carrega todos os dados no PostgreSQL.

Uso (na raiz do repositório):
    py -m pip install -r requirements.txt
    copy .env.example .env                       # preencher DB_HOST, DB_NAME, DB_USER e DB_PASSWORD
    py carga/carregar.py                          # cria as tabelas que faltarem e carrega tudo
    py carga/carregar.py --somente territorio     # só setores, serviços e calor
    py carga/carregar.py --somente clima          # só a série do INMET e os níveis NC
    py carga/carregar.py --recriar                # APAGA as tabelas TMC_ e cria de novo
    py carga/carregar.py --simular                # lê e confere os arquivos, sem conectar

Tudo roda numa transação por bloco: se der erro, nada daquele bloco fica gravado.
As pessoas sintéticas (TMC_PESSOA_SINTETICA) são geradas pela base-territorial-api
(POST /admin/sinteticos) e não são apagadas por esta carga, exceto com --recriar.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clima  # noqa: E402
import territorio  # noqa: E402
from conexao import RAIZ, conectar, executar_arquivo, tabelas_existentes  # noqa: E402

SQL_CRIAR = os.path.join(RAIZ, "sql", "01_criar_tabelas.sql")
SQL_APAGAR = os.path.join(RAIZ, "sql", "02_apagar_tabelas.sql")
TODAS = {"TMC_SETOR", "TMC_SERVICO", "TMC_CALOR_SETOR", "TMC_PESSOA_SINTETICA",
         "TMC_LIMIAR_NIVEL_CALOR", "TMC_LEITURA_CLIMA", "TMC_RESUMO_DIARIO_CLIMA", "TMC_NIVEL_CALOR"}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--somente", choices=["territorio", "clima"], help="carrega só um dos blocos")
    ap.add_argument("--recriar", action="store_true", help="apaga e recria todas as tabelas TMC_ (perde tudo)")
    ap.add_argument("--simular", action="store_true", help="só lê e confere os arquivos, sem banco")
    ap.add_argument("--csv-clima", default=clima.CSV_PADRAO, help="série unificada da A707")
    args = ap.parse_args()
    t0 = time.time()

    blocos = [args.somente] if args.somente else ["territorio", "clima"]
    dados_terr = dados_clima = None
    if "territorio" in blocos:
        print("Território: lendo dados/territorio")
        dados_terr = {t: territorio.ler(t) for t in territorio.ORDEM}
        for t, (_, linhas) in dados_terr.items():
            print(f"  {t}: {len(linhas)} linhas")
        problemas = territorio.validar(dados_terr)
        if problemas:
            sys.exit("Arquivos com problema, nada foi gravado:\n  " + "\n  ".join(problemas))
    if "clima" in blocos:
        print(f"Clima: lendo {os.path.relpath(args.csv_clima, RAIZ)}")
        dados_clima = clima.preparar(args.csv_clima)

    if args.simular:
        print("Simulação concluída: arquivos lidos e conferidos, nada foi gravado.")
        return

    with conectar() as con:
        v = con.info.server_version
        print(f"Conectado ao PostgreSQL {v // 10000}.{v % 10000} como {con.info.user}")
        cur = con.cursor()
        existentes = tabelas_existentes(cur)
        if args.recriar and existentes:
            executar_arquivo(cur, SQL_APAGAR)
            print(f"  {len(existentes)} tabelas TMC_ apagadas")
            existentes = set()
        if not existentes:
            n = executar_arquivo(cur, SQL_CRIAR)
            con.commit()  # no Oracle o DDL já se confirma sozinho; aqui é transacional
            print(f"  sql/01_criar_tabelas.sql: {n} comandos executados")
        elif TODAS - existentes:  # tabelas a mais (orientação, simulação) não atrapalham a carga
            sys.exit(f"Faltam tabelas TMC_: {sorted(TODAS - existentes)}. "
                     "Rode com --recriar ou crie as que faltam pelo sql/01_criar_tabelas.sql.")

        if dados_terr:
            print("Gravando território")
            try:
                territorio.carregar(cur, dados_terr)
                con.commit()
            except Exception:
                con.rollback()
                print("Erro — nada do território foi gravado (rollback).")
                raise
        if dados_clima:
            print("Gravando clima")
            leituras, descartes, dias, regras = dados_clima
            try:
                contagem = clima.carregar(cur, leituras, dias, regras)
                con.commit()
            except Exception:
                con.rollback()
                print("\nErro — nada do clima foi gravado (rollback).")
                raise
            print("  Dias por nível: " + "  ".join(f"NC{n}: {contagem[n]}" for n in range(1, 6)))

        print("\nLinhas por tabela:")
        for t in sorted(TODAS):
            (n,) = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
            print(f"  {t:<26} {n:>8}")
    print(f"Carga concluída em {time.time() - t0:.0f}s.")


if __name__ == "__main__":
    main()
