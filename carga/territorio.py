"""Carga do território (camada ONDE): TMC_SETOR, TMC_SERVICO e TMC_CALOR_SETOR.

Os CSVs de dados/territorio já estão no formato das tabelas (uma coluna por coluna da tabela),
separados por ';', UTF-8, ponto como separador decimal e vazio = NULL.
A carga usa INSERT ... ON CONFLICT (upsert): rodar de novo atualiza as linhas sem duplicar e sem apagar pessoas sintéticas.
"""
from __future__ import annotations

import csv
import os
from datetime import date

from conexao import RAIZ

PASTA = os.path.join(RAIZ, "dados", "territorio")

# tabela -> (arquivo, chave, {coluna: tipo})  tipos: s=texto, f=decimal, i=inteiro, d=data, c=clob
TABELAS = {
    "TMC_SETOR": ("tmc_setor.csv", "CODIGO", {
        "AREA_KM2": "f", "POP_TOTAL": "i", "POP_60_69": "i", "POP_70_MAIS": "i", "IPVS_GRUPO": "i",
        "LAT_REFERENCIA": "f", "LON_REFERENCIA": "f", "GEOMETRIA_WKT": "c"}),
    "TMC_SERVICO": ("tmc_servico.csv", "ID", {"LAT": "f", "LON": "f"}),
    "TMC_CALOR_SETOR": ("tmc_calor_setor.csv", "CODIGO_SETOR", {
        "LST_VERAO_C": "f", "NDVI_MEDIO": "f", "PCT_CONSTRUCOES": "f", "PCT_VEGETACAO_DENSA": "f",
        "TA_ESTIMADA_C": "f", "CLASSE_CALOR": "i", "PIXELS_VALIDOS": "i", "DATA_CENA": "d"}),
}
ORDEM = ["TMC_SETOR", "TMC_SERVICO", "TMC_CALOR_SETOR"]


def _converter(valor: str, tipo: str):
    valor = valor.strip()
    if valor == "":
        return None
    if tipo == "f":
        return float(valor)
    if tipo == "i":
        return int(float(valor))
    if tipo == "d":
        return date.fromisoformat(valor)
    return valor


def ler(tabela: str) -> tuple[list[str], list[tuple]]:
    arquivo, _, tipos = TABELAS[tabela]
    with open(os.path.join(PASTA, arquivo), encoding="utf-8-sig", newline="") as f:
        leitor = csv.reader(f, delimiter=";")
        colunas = next(leitor)
        linhas = [tuple(_converter(v, tipos.get(c, "s")) for c, v in zip(colunas, l)) for l in leitor]
    return colunas, linhas


def validar(dados: dict[str, tuple[list[str], list[tuple]]]) -> list[str]:
    """Confere chaves e referências antes de ir ao banco. Devolve a lista de problemas."""
    problemas = []
    for tabela, (colunas, linhas) in dados.items():
        chave = TABELAS[tabela][1]
        i = colunas.index(chave)
        vistos = [l[i] for l in linhas]
        if len(vistos) != len(set(vistos)):
            problemas.append(f"{tabela}: chave {chave} repetida")
    setores = {l[0] for l in dados["TMC_SETOR"][1]}
    cs, ls = dados["TMC_SERVICO"]
    i = cs.index("SETOR_CODIGO")
    problemas += [f"TMC_SERVICO {l[0]}: setor {l[i]} não existe" for l in ls if l[i] and l[i] not in setores]
    cc, lc = dados["TMC_CALOR_SETOR"]
    problemas += [f"TMC_CALOR_SETOR: setor {l[0]} não existe" for l in lc if l[0] not in setores]
    i = cc.index("CLASSE_CALOR")
    problemas += [f"TMC_CALOR_SETOR {l[0]}: classe {l[i]} fora de 1-5" for l in lc if l[i] is not None and not 1 <= l[i] <= 5]
    return problemas


def _upsert(tabela: str, colunas: list[str], chave: str) -> str:
    marcadores = ", ".join(["%s"] * len(colunas))
    upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in colunas if c != chave)
    extra = ", ATUALIZADO_EM = CURRENT_TIMESTAMP" if tabela != "TMC_SERVICO" else ""
    return (f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({marcadores}) "
            f"ON CONFLICT ({chave}) DO UPDATE SET {upd}{extra}")


def carregar(cur, dados) -> dict[str, int]:
    contagem = {}
    for tabela in ORDEM:
        colunas, linhas = dados[tabela]
        cur.executemany(_upsert(tabela, colunas, TABELAS[tabela][1]), linhas)
        contagem[tabela] = len(linhas)
        print(f"  {tabela}: {len(linhas)} linhas")
    return contagem
