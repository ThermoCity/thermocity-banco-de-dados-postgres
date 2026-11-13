"""Carga do clima (camada QUANDO): TMC_LIMIAR_NIVEL_CALOR, TMC_LEITURA_CLIMA,
TMC_RESUMO_DIARIO_CLIMA e TMC_NIVEL_CALOR, a partir da série unificada da estação INMET A707.

Lógica reaproveitada do repositório ThermoCity/Tratamento-de-Dados-PresidPrud-Python
(carregar_banco_clima.py), só com os nomes de tabela trocados para o prefixo TMC_.
O cálculo do índice de calor e dos limiares fica em analise_niveis_calor.py (mesma origem).

Carga idempotente: apaga só as observações do INMET e grava de novo.
"""

from __future__ import annotations

import csv
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from analise_niveis_calor import (ACOES, CSV_PADRAO, FUSO_LOCAL, JANELA_PICO,
                                  MIN_HORAS_DIA, MIN_HORAS_PICO, NOMES,
                                  REGRAS_PROPOSTAS, TEMP_MAX, TEMP_MIN, UR_MAX,
                                  UR_MIN, RegraNivel, definir_limiares,
                                  indice_calor, nivel_para_sequencia)

FONTE = "INMET"
TIPO = "OBSERVACAO"
VERSAO_LIMIAR = "A707-2003-2026-v1"
LOTE = 5000

# Coluna do CSV  ->  coluna em LEITURA_CLIMA
COLUNAS = [
    ("PRECIPITAÇÃO TOTAL, HORÁRIO (mm)", "PRECIPITACAO_MM"),
    ("PRESSAO ATMOSFERICA AO NIVEL DA ESTACAO, HORARIA (mB)", "PRESSAO_HPA"),
    ("PRESSÃO ATMOSFERICA MAX.NA HORA ANT. (AUT) (mB)", "PRESSAO_MAX_HORA_HPA"),
    ("PRESSÃO ATMOSFERICA MIN. NA HORA ANT. (AUT) (mB)", "PRESSAO_MIN_HORA_HPA"),
    ("RADIACAO GLOBAL (KJ/m²)", "RADIACAO_KJ_M2"),
    ("TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)", "TEMPERATURA_C"),
    ("TEMPERATURA DO PONTO DE ORVALHO (°C)", "PONTO_ORVALHO_C"),
    ("TEMPERATURA MÁXIMA NA HORA ANT. (AUT) (°C)", "TEMP_MAX_HORA_C"),
    ("TEMPERATURA MÍNIMA NA HORA ANT. (AUT) (°C)", "TEMP_MIN_HORA_C"),
    ("TEMPERATURA ORVALHO MAX. NA HORA ANT. (AUT) (°C)", "ORVALHO_MAX_HORA_C"),
    ("TEMPERATURA ORVALHO MIN. NA HORA ANT. (AUT) (°C)", "ORVALHO_MIN_HORA_C"),
    ("UMIDADE REL. MAX. NA HORA ANT. (AUT) (%)", "UMIDADE_MAX_HORA_PCT"),
    ("UMIDADE REL. MIN. NA HORA ANT. (AUT) (%)", "UMIDADE_MIN_HORA_PCT"),
    ("UMIDADE RELATIVA DO AR, HORARIA (%)", "UMIDADE_PCT"),
    ("VENTO, DIREÇÃO HORARIA (gr) (° (gr))", "VENTO_DIRECAO_GRAUS"),
    ("VENTO, RAJADA MAXIMA (m/s)", "VENTO_RAJADA_MS"),
    ("VENTO, VELOCIDADE HORARIA (m/s)", "VENTO_VELOCIDADE_MS"),
]
COLS_BD = [c for _, c in COLUNAS]

# --------------------------------------------------------------------------- #
# Leitura do CSV
# --------------------------------------------------------------------------- #
def _num(v: str) -> float | None:
    v = v.strip()
    if not v or v == "-9999":
        return None
    return float(v.replace(",", "."))


@dataclass
class Leitura:
    utc: datetime
    local: datetime
    valores: dict[str, float | None]
    ic: float | None
    qualidade: str


@dataclass
class ResumoDia:
    data: date
    leituras: list[Leitura] = field(default_factory=list)
    ic_max: float | None = None
    pico: Leitura | None = None
    valido: bool = False


def ler_csv(caminho: str):
    leituras: list[Leitura] = []
    descartes = Counter()
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f, delimiter=";")
        cab = next(r)
        i_data, i_hora = cab.index("DATA (YYYY-MM-DD)"), cab.index("HORA (UTC)")
        idx = [(cab.index(nome_csv), col) for nome_csv, col in COLUNAS]
        for linha in r:
            utc = datetime.strptime(f"{linha[i_data]} {linha[i_hora]}", "%Y-%m-%d %H:%M")
            local = utc + FUSO_LOCAL
            valores = {col: _num(linha[i]) for i, col in idx}
            if all(v is None for v in valores.values()):
                descartes[local.year] += 1          # linha totalmente vazia
                continue
            t, u = valores["TEMPERATURA_C"], valores["UMIDADE_PCT"]
            if t is None or u is None:
                qual, ic = "PARCIAL", None
            elif not (TEMP_MIN <= t <= TEMP_MAX and UR_MIN <= u <= UR_MAX):
                qual, ic = "FORA_FAIXA", None
            else:
                qual, ic = "OK", indice_calor(t, u)
            leituras.append(Leitura(utc, local, valores, ic, qual))
    return leituras, descartes


def resumir(leituras: list[Leitura]) -> list[ResumoDia]:
    dias: dict[date, ResumoDia] = {}
    for l in leituras:
        dias.setdefault(l.local.date(), ResumoDia(l.local.date())).leituras.append(l)
    for d in dias.values():
        ok = [l for l in d.leituras if l.qualidade == "OK"]
        pico_h = sum(1 for l in ok if l.local.hour in JANELA_PICO)
        d.valido = len(ok) >= MIN_HORAS_DIA and pico_h >= MIN_HORAS_PICO
        if ok:
            d.pico = max(ok, key=lambda l: l.ic)
            d.ic_max = d.pico.ic
    return [dias[k] for k in sorted(dias)]


# --------------------------------------------------------------------------- #
# Gravação
# --------------------------------------------------------------------------- #
def _r(x, n=2):
    return None if x is None else round(x, n)


def _media(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _min(vals):
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None


def _max(vals):
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def executar_em_lotes(cur, sql, linhas, rotulo):
    t0 = time.time()
    for i in range(0, len(linhas), LOTE):
        cur.executemany(sql, linhas[i:i + LOTE])
        print(f"\r  {rotulo}: {min(i + LOTE, len(linhas))}/{len(linhas)}", end="", flush=True)
    print(f"  ({time.time() - t0:.0f}s)")


def gravar_limiares(cur, regras: list[RegraNivel]) -> dict[tuple[int, int], int]:
    um_dia = {r.nivel: r.limiar for r in regras if r.dias_consecutivos == 1}
    linhas = [(1, NOMES[1], None, um_dia[2], 1, None,
               f"IC máx < {um_dia[2]} °C", ACOES[1])]
    for r in regras:
        ic_max = um_dia.get(r.nivel + 1) if r.dias_consecutivos == 1 else None
        regra = (f"IC máx ≥ {r.limiar} °C por {r.dias_consecutivos} dia(s) seguido(s) — "
                 f"{r.origem}")
        linhas.append((r.nivel, NOMES[r.nivel], r.limiar, ic_max, r.dias_consecutivos,
                       r.percentil, regra, ACOES[r.nivel]))
    cur.executemany("""
        INSERT INTO TMC_LIMIAR_NIVEL_CALOR (VERSAO_LIMIAR, NIVEL, NOME_NIVEL, IC_MIN_C, IC_MAX_C,
             DURACAO_DIAS, PERCENTIL, REGRA, ACAO_ESPERADA)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (VERSAO_LIMIAR, NIVEL, DURACAO_DIAS) DO UPDATE SET
             NOME_NIVEL = EXCLUDED.NOME_NIVEL, IC_MIN_C = EXCLUDED.IC_MIN_C,
             IC_MAX_C = EXCLUDED.IC_MAX_C, PERCENTIL = EXCLUDED.PERCENTIL, REGRA = EXCLUDED.REGRA,
             ACAO_ESPERADA = EXCLUDED.ACAO_ESPERADA, ATIVO = 'S'
    """, [(VERSAO_LIMIAR,) + l for l in linhas])
    # versões anteriores deixam de ser a ativa
    cur.execute("UPDATE TMC_LIMIAR_NIVEL_CALOR SET ATIVO = 'N' WHERE VERSAO_LIMIAR <> %s",
                (VERSAO_LIMIAR,))
    cur.execute("SELECT NIVEL, DURACAO_DIAS, ID_LIMIAR FROM TMC_LIMIAR_NIVEL_CALOR "
                "WHERE VERSAO_LIMIAR = %s", (VERSAO_LIMIAR,))
    return {(n, d): i for n, d, i in cur.fetchall()}


def gravar_leituras(cur, leituras: list[Leitura]) -> dict[datetime, int]:
    cols = ", ".join(COLS_BD)
    marcadores = ", ".join(["%s"] * (len(COLS_BD) + 6))
    sql = (f"INSERT INTO TMC_LEITURA_CLIMA (DATA_HORA_UTC, DATA_LOCAL, FONTE, TIPO, {cols}, "
           f"INDICE_CALOR_C, QUALIDADE) VALUES ({marcadores})")
    # DATA_HORA_UTC vai com fuso (UTC) explícito para o TIMESTAMPTZ não depender do fuso da sessão.
    linhas = [(l.utc.replace(tzinfo=timezone.utc), l.local.date(), FONTE, TIPO,
               *[l.valores[c] for c in COLS_BD], _r(l.ic), l.qualidade) for l in leituras]
    executar_em_lotes(cur, sql, linhas, "TMC_LEITURA_CLIMA")
    # Volta como hora UTC sem fuso, igual a Leitura.utc, para servir de chave do dicionário.
    cur.execute("""SELECT ID_LEITURA, DATA_HORA_UTC AT TIME ZONE 'UTC'
                   FROM TMC_LEITURA_CLIMA WHERE FONTE = %s AND TIPO = %s""", (FONTE, TIPO))
    return {dt: i for i, dt in cur.fetchall()}


def gravar_resumo_e_niveis(cur, dias: list[ResumoDia], regras, ids_leitura, ids_limiar):
    limiar_nc2 = next(r.limiar for r in regras if r.nivel == 2 and r.dias_consecutivos == 1)
    max_n = max(r.dias_consecutivos for r in regras)
    ic_valido = {d.data: d.ic_max for d in dias if d.valido}

    resumo, niveis, contagem = [], [], Counter()
    for d in dias:
        ls = d.leituras
        ok = [l for l in ls if l.qualidade == "OK"]
        v = lambda c: [l.valores[c] for l in ls]
        consec = 0
        if d.valido:
            k = d.data
            while ic_valido.get(k) is not None and ic_valido[k] >= limiar_nc2:
                consec += 1
                k -= timedelta(days=1)
        radiacao = [x for x in v("RADIACAO_KJ_M2") if x is not None and x > 0]
        chuva = [x for x in v("PRECIPITACAO_MM") if x is not None]
        resumo.append((
            d.data, FONTE, TIPO,
            _r(d.ic_max), d.pico.local.hour if d.pico else None,
            d.pico.valores["TEMPERATURA_C"] if d.pico else None,
            d.pico.valores["UMIDADE_PCT"] if d.pico else None,
            _r(_media([l.ic for l in ok])),
            sum(1 for l in ok if l.ic >= 35) if ok else None,
            sum(1 for l in ok if l.ic >= 36) if ok else None,
            _max(v("TEMPERATURA_C") + v("TEMP_MAX_HORA_C")),
            _min(v("TEMPERATURA_C") + v("TEMP_MIN_HORA_C")),
            _r(_media(v("TEMPERATURA_C")), 1),
            _min(v("UMIDADE_PCT") + v("UMIDADE_MIN_HORA_PCT")),
            _r(_media(v("UMIDADE_PCT")), 1),
            _r(sum(chuva), 1) if chuva else None,
            _r(sum(radiacao), 1) if radiacao else None,
            _r(_media(v("VENTO_VELOCIDADE_MS")), 1),
            _max(v("VENTO_RAJADA_MS")),
            consec if d.valido else None,
            len(ls), len(ok), "S" if d.valido else "N",
        ))
        if d.valido:
            seq = [ic_valido.get(d.data - timedelta(days=k)) for k in range(max_n - 1, -1, -1)]
            nivel, regra = nivel_para_sequencia(seq, regras)
            id_lim = ids_limiar[(regra.nivel, regra.dias_consecutivos)] if regra \
                else ids_limiar[(1, 1)]
            niveis.append((d.data, nivel, NOMES[nivel],
                           _r(d.ic_max), "OBSERVADO", FONTE, VERSAO_LIMIAR,
                           ids_leitura.get(d.pico.utc), id_lim))
            contagem[nivel] += 1

    executar_em_lotes(cur, """
        INSERT INTO TMC_RESUMO_DIARIO_CLIMA (DATA_LOCAL, FONTE, TIPO, IC_MAX_C, HORA_LOCAL_IC_MAX,
            TEMP_NO_PICO_C, UR_NO_PICO_PCT, IC_MEDIO_C, HORAS_IC_GE_35, HORAS_IC_GE_36,
            TEMP_MAX_C, TEMP_MIN_C, TEMP_MEDIA_C, UR_MIN_PCT, UR_MEDIA_PCT, CHUVA_TOTAL_MM,
            RADIACAO_TOTAL_KJ_M2, VENTO_MEDIO_MS, RAJADA_MAX_MS, DIAS_CONSEC_NC2,
            HORAS_COM_DADO, HORAS_VALIDAS, DIA_VALIDO)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, resumo, "TMC_RESUMO_DIARIO_CLIMA")
    executar_em_lotes(cur, """
        INSERT INTO TMC_NIVEL_CALOR (DATA_LOCAL, NIVEL, NOME_NIVEL, IC_MAX_C, ORIGEM, FONTE,
            VERSAO_LIMIAR, ID_LEITURA, ID_LIMIAR)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, niveis, "TMC_NIVEL_CALOR")
    return contagem


def apagar_carga_anterior(cur) -> None:
    cur.execute("DELETE FROM TMC_NIVEL_CALOR WHERE FONTE = %s AND ORIGEM = 'OBSERVADO'", (FONTE,))
    cur.execute("DELETE FROM TMC_RESUMO_DIARIO_CLIMA WHERE FONTE = %s AND TIPO = %s", (FONTE, TIPO))
    cur.execute("DELETE FROM TMC_LEITURA_CLIMA WHERE FONTE = %s AND TIPO = %s", (FONTE, TIPO))


def preparar(caminho_csv: str = CSV_PADRAO):
    """Lê a série e calcula limiares e dias, sem tocar no banco."""
    leituras, descartes = ler_csv(caminho_csv)
    dias = resumir(leituras)
    validos = [d for d in dias if d.valido]
    regras = [RegraNivel(**vars(r)) for r in REGRAS_PROPOSTAS]
    definir_limiares(validos, regras)
    print(f"  {len(leituras)} leituras com dado | {sum(descartes.values())} linhas vazias descartadas"
          f" | {len(dias)} dias ({len(validos)} válidos)")
    return leituras, descartes, dias, regras


def carregar(cur, leituras, dias, regras) -> Counter:
    apagar_carga_anterior(cur)
    ids_limiar = gravar_limiares(cur, regras)
    print(f"  TMC_LIMIAR_NIVEL_CALOR: {len(ids_limiar)} regras (versão {VERSAO_LIMIAR})")
    ids_leitura = gravar_leituras(cur, leituras)
    return gravar_resumo_e_niveis(cur, dias, regras, ids_leitura, ids_limiar)
