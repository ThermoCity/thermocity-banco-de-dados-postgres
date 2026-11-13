"""
ThermoCity — Feature "Clima em Tempo Real e Níveis de Calor" (camada QUANDO)

Cópia do repositório ThermoCity/Tratamento-de-Dados-PresidPrud-Python, sem mudança na
lógica. Só o caminho do CSV mudou para dados/clima/.

Analisa a série horária da estação INMET A707 (Presidente Prudente, 2003–2026)
e define os limiares NC1–NC5 do índice de calor para responder:
    "Hoje está quente o suficiente para agir? Em que nível?"

Segue os Passos 1–3 do roteiro:
  1. Lê a série, mantém data/hora/temperatura/umidade, descarta ausentes e conta
     os descartes por ano.
  2. Calcula o índice de calor (Rothfusz/NWS, em °F, convertido para °C; abaixo de
     80 °F o índice é igual à temperatura).
  3. Calcula o índice de calor MÁXIMO de cada dia, mede a frequência das faixas do
     protocolo do Rio em Prudente e deriva limiares próprios por percentis da série,
     com regra de persistência (dias consecutivos).

Só usa a biblioteca padrão do Python (3.9+). Não precisa instalar nada.

Uso:
    python analise_niveis_calor.py                       # análise completa
    python analise_niveis_calor.py --leitura 36.5 45     # IC de uma leitura (T °C, UR %)
    python analise_niveis_calor.py --classificar 35.2 36.4 37.1
        # classifica HOJE a partir do IC máximo dos últimos dias (o último valor é hoje)

Saídas (pasta resultados_niveis_calor/):
    qualidade_por_ano.csv       horas e dias descartados por ano
    ic_diario.csv               IC máximo de cada dia + nível NC atribuído
    faixas_rio_por_ano.csv      dias por faixa do protocolo do Rio em Prudente
    limiares_nc_prudente.csv    tabela de limiares (formato da tabela LIMIAR_NIVEL_CALOR)
    niveis_por_ano.csv          quantos dias cada nível teria ocorrido por ano
    episodios_nc4_nc5.csv       episódios históricos que chegariam a NC4/NC5
    relatorio_niveis_calor.md   resumo para o grupo revisar
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
PASTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PADRAO = os.path.join(PASTA_BASE, "dados", "clima",
                          "INMET_A707_PRESIDENTE_PRUDENTE_2003-2026.csv")
PASTA_SAIDA = os.path.join(PASTA_BASE, "resultados_niveis_calor")

COL_DATA = "DATA (YYYY-MM-DD)"
COL_HORA = "HORA (UTC)"
COL_TEMP = "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)"
COL_UR = "UMIDADE RELATIVA DO AR, HORARIA (%)"

# Fuso: a série do INMET está em UTC. Prudente = UTC−3 (horário padrão).
# Até 2019 havia horário de verão; ele só desloca em 1 h o limite da meia-noite,
# o que não afeta o máximo diário (que ocorre à tarde).
FUSO_LOCAL = timedelta(hours=-3)

# Faixas físicas plausíveis para descartar leituras com erro de sensor.
TEMP_MIN, TEMP_MAX = -5.0, 48.0
UR_MIN, UR_MAX = 1.0, 100.0

# Critério de dia válido: o máximo só é confiável se o dia tiver cobertura
# suficiente, principalmente à tarde (quando o calor atinge o pico).
MIN_HORAS_DIA = 18
JANELA_PICO = range(12, 18)      # 12h–17h locais
MIN_HORAS_PICO = 4

# Faixas do protocolo do Rio (índice de calor, °C), segundo o roteiro / Agência
# Pública: NC2–NC3 entre 36 e 40, NC4 entre 40 e 44, NC5 acima. A duração exigida
# em cada nível deve ser conferida no decreto oficial do Rio.
FAIXAS_RIO = [("< 36", -math.inf, 36.0), ("36–40 (NC2/NC3 Rio)", 36.0, 40.0),
              ("40–44 (NC4 Rio)", 40.0, 44.0), ("≥ 44 (NC5 Rio)", 44.0, math.inf)]


@dataclass
class RegraNivel:
    """Uma regra de entrada no nível: IC máx diário ≥ limiar por N dias seguidos."""
    nivel: int
    percentil: float | None   # percentil da série que define o limiar (None = fixo)
    limiar: float | None      # preenchido após calcular os percentis (°C)
    dias_consecutivos: int
    origem: str


# Regra proposta (decisão a ser validada pelo grupo):
#   - Limiares = percentis do IC máximo diário da própria A707 (arredondados a 0,5 °C).
#   - Um nível é atingido por um dia muito quente OU por calor um pouco menor
#     que persiste — o calor prolongado é o que mais afeta idosos.
#   - O nível do dia é o MAIOR nível cuja regra é satisfeita.
REGRAS_PROPOSTAS = [
    RegraNivel(2, 90.0, None, 1, "P90 — dia quente acima do habitual"),
    RegraNivel(3, 95.0, None, 1, "P95 — ~ início da faixa do Rio (36 °C)"),
    RegraNivel(3, 90.0, None, 3, "P90 por 3 dias seguidos (calor persistente)"),
    RegraNivel(4, 98.0, None, 1, "P98 — calor extremo para Prudente"),
    RegraNivel(4, 95.0, None, 3, "P95 por 3 dias seguidos (onda de calor)"),
    RegraNivel(5, 99.5, None, 1, "P99,5 — calor excepcional para Prudente"),
    RegraNivel(5, 98.0, None, 3, "P98 por 3 dias seguidos (onda de calor extrema)"),
]

ACOES = {
    1: "Rotina. Sem acionamento; painel apenas monitora.",
    2: "Atenção. Alerta no painel e comunicação preventiva (hidratação, horários) "
       "para os idosos cadastrados.",
    3: "Alerta. Inicia busca ativa: contato com idosos 70+ nos setores de IPVS 5–6; "
       "divulgar refúgios mais próximos.",
    4: "Alto risco. Busca ativa ampliada a todos os 60+ dos setores IPVS 4–6; "
       "UBS em alerta; refúgios abertos.",
    5: "Emergência. Busca ativa em toda a cidade com visita presencial aos "
       "prioritários; refúgios em horário estendido.",
}
NOMES = {1: "Normal", 2: "Atenção", 3: "Alerta", 4: "Alto risco", 5: "Emergência"}


# --------------------------------------------------------------------------- #
# Passo 2 — Índice de calor
# --------------------------------------------------------------------------- #
def indice_calor(temp_c: float, ur: float) -> float:
    """Índice de calor (°C) pela regressão de Rothfusz (NWS/NOAA).

    A fórmula usa T em °F e UR em %. Abaixo de 80 °F (~26,7 °C) ela não vale e o
    índice é considerado igual à temperatura, como define o roteiro. É a mesma
    função que a clima-api deve aplicar às leituras da OpenWeather (temp + humidity),
    para que os números sejam comparáveis com os limiares.
    """
    t = temp_c * 9.0 / 5.0 + 32.0
    if t < 80.0:
        return temp_c
    r = ur
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * r - 0.22475541 * t * r
          - 0.00683783 * t * t - 0.05481717 * r * r + 0.00122874 * t * t * r
          + 0.00085282 * t * r * r - 0.00000199 * t * t * r * r)
    return (hi - 32.0) * 5.0 / 9.0


# --------------------------------------------------------------------------- #
# Passo 1 — Leitura e limpeza
# --------------------------------------------------------------------------- #
def _num(valor: str) -> float | None:
    valor = valor.strip()
    if not valor or valor == "-9999":
        return None
    return float(valor.replace(",", "."))


def ler_serie(caminho: str):
    """Retorna (leituras_por_dia_local, qualidade_por_ano)."""
    por_dia: dict[date, list[tuple[int, float, float, float]]] = defaultdict(list)
    qualidade = defaultdict(Counter)

    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.reader(f, delimiter=";")
        cab = next(leitor)
        i_data, i_hora = cab.index(COL_DATA), cab.index(COL_HORA)
        i_temp, i_ur = cab.index(COL_TEMP), cab.index(COL_UR)

        for linha in leitor:
            utc = datetime.strptime(f"{linha[i_data]} {linha[i_hora]}", "%Y-%m-%d %H:%M")
            local = utc + FUSO_LOCAL
            q = qualidade[local.year]
            q["horas_total"] += 1

            temp, ur = _num(linha[i_temp]), _num(linha[i_ur])
            if temp is None:
                q["descartadas_temp_ausente"] += 1
                continue
            if ur is None:
                q["descartadas_ur_ausente"] += 1
                continue
            if not (TEMP_MIN <= temp <= TEMP_MAX and UR_MIN <= ur <= UR_MAX):
                q["descartadas_fora_faixa"] += 1
                continue
            q["horas_validas"] += 1
            por_dia[local.date()].append((local.hour, temp, ur, indice_calor(temp, ur)))

    return por_dia, qualidade


# --------------------------------------------------------------------------- #
# Passo 3 — IC máximo diário, faixas do Rio e limiares por percentil
# --------------------------------------------------------------------------- #
@dataclass
class Dia:
    data: date
    ic_max: float
    hora_ic_max: int
    temp_no_pico: float
    ur_no_pico: float
    temp_max: float
    horas_validas: int
    nivel: int = 1


def resumir_dias(por_dia, qualidade) -> list[Dia]:
    dias = []
    for d, leituras in sorted(por_dia.items()):
        horas_pico = sum(1 for h, *_ in leituras if h in JANELA_PICO)
        if len(leituras) < MIN_HORAS_DIA or horas_pico < MIN_HORAS_PICO:
            qualidade[d.year]["dias_descartados_cobertura"] += 1
            continue
        h, t, u, ic = max(leituras, key=lambda x: x[3])
        dias.append(Dia(d, ic, h, t, u, max(x[1] for x in leituras), len(leituras)))
        qualidade[d.year]["dias_validos"] += 1
    return dias


def percentil(valores_ordenados: list[float], p: float) -> float:
    """Percentil com interpolação linear (mesmo método padrão do numpy)."""
    k = (len(valores_ordenados) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return valores_ordenados[lo]
    return valores_ordenados[lo] + (valores_ordenados[hi] - valores_ordenados[lo]) * (k - lo)


def arred_meio(x: float) -> float:
    return round(x * 2) / 2


def definir_limiares(dias: list[Dia], regras: list[RegraNivel]) -> dict[float, float]:
    valores = sorted(d.ic_max for d in dias)
    pcts = {}
    for r in regras:
        if r.percentil is not None:
            pcts[r.percentil] = percentil(valores, r.percentil)
            r.limiar = arred_meio(pcts[r.percentil])
    return pcts


def nivel_para_sequencia(ic_max_ultimos_dias: list[float | None],
                         regras: list[RegraNivel]) -> tuple[int, RegraNivel | None]:
    """Nível de HOJE dado o IC máx dos dias anteriores (o último elemento é hoje).

    None em um dia (sem dado) quebra a sequência de persistência.
    """
    nivel, motivo = 1, None
    for r in regras:
        janela = ic_max_ultimos_dias[-r.dias_consecutivos:]
        if len(janela) < r.dias_consecutivos:
            continue
        if all(v is not None and v >= r.limiar for v in janela) and r.nivel > nivel:
            nivel, motivo = r.nivel, r
    return nivel, motivo


def classificar_historico(dias: list[Dia], regras: list[RegraNivel]) -> None:
    max_n = max(r.dias_consecutivos for r in regras)
    por_data = {d.data: d.ic_max for d in dias}
    for d in dias:
        seq = [por_data.get(d.data - timedelta(days=k)) for k in range(max_n - 1, -1, -1)]
        d.nivel, _ = nivel_para_sequencia(seq, regras)


# --------------------------------------------------------------------------- #
# Saídas
# --------------------------------------------------------------------------- #
def _fmt(x: float, n: int = 1) -> str:
    return f"{x:.{n}f}".replace(".", ",")


def escrever_csv(nome: str, cabecalho: list[str], linhas: list[list]) -> str:
    caminho = os.path.join(PASTA_SAIDA, nome)
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cabecalho)
        w.writerows(linhas)
    return caminho


def tabela_limiares(regras: list[RegraNivel]) -> list[list]:
    """Uma linha por nível: limiar de 1 dia (faixa) + regra de persistência."""
    linhas = [[1, NOMES[1], "", "", "", "Abaixo do limiar de NC2", ACOES[1]]]
    for n in range(2, 6):
        rs = [r for r in regras if r.nivel == n]
        um_dia = next(r for r in rs if r.dias_consecutivos == 1)
        prox = [r for r in regras if r.nivel == n + 1 and r.dias_consecutivos == 1]
        faixa_max = _fmt(prox[0].limiar) if prox else ""
        persist = [r for r in rs if r.dias_consecutivos > 1]
        regra_txt = f"IC máx ≥ {_fmt(um_dia.limiar)} °C em 1 dia ({um_dia.origem})"
        for r in persist:
            regra_txt += f" OU IC máx ≥ {_fmt(r.limiar)} °C por {r.dias_consecutivos} dias seguidos"
        linhas.append([n, NOMES[n], _fmt(um_dia.limiar), faixa_max,
                       max((r.dias_consecutivos for r in persist), default=1),
                       regra_txt, ACOES[n]])
    return linhas


def episodios(dias: list[Dia], nivel_min: int) -> list[list]:
    eps, atual = [], []
    for d in dias:
        if d.nivel >= nivel_min and atual and (d.data - atual[-1].data).days == 1:
            atual.append(d)
        elif d.nivel >= nivel_min:
            if atual:
                eps.append(atual)
            atual = [d]
    if atual:
        eps.append(atual)
    return [[e[0].data.isoformat(), e[-1].data.isoformat(), len(e),
             f"NC{max(x.nivel for x in e)}", _fmt(max(x.ic_max for x in e)),
             _fmt(max(x.temp_max for x in e))] for e in eps]


def analisar(caminho_csv: str) -> None:
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    print(f"Lendo {caminho_csv}")
    por_dia, qualidade = ler_serie(caminho_csv)
    dias = resumir_dias(por_dia, qualidade)
    anos = sorted(qualidade)
    n_dias = len(dias)
    n_anos = n_dias / 365.25
    print(f"{n_dias} dias válidos (~{n_anos:.1f} anos de dados)")

    # ---- Qualidade
    campos_q = ["horas_total", "horas_validas", "descartadas_temp_ausente",
                "descartadas_ur_ausente", "descartadas_fora_faixa",
                "dias_validos", "dias_descartados_cobertura"]
    escrever_csv("qualidade_por_ano.csv", ["ano"] + campos_q,
                 [[a] + [qualidade[a][c] for c in campos_q] for a in anos])

    # ---- Distribuição e percentis
    valores = sorted(d.ic_max for d in dias)
    ps = [50, 75, 90, 95, 97.5, 98, 99, 99.5, 99.9]
    dist = {p: percentil(valores, p) for p in ps}

    # ---- Faixas do Rio aplicadas a Prudente
    faixa_ano = defaultdict(Counter)
    for d in dias:
        for nome, lo, hi in FAIXAS_RIO:
            if lo <= d.ic_max < hi:
                faixa_ano[d.data.year][nome] += 1
    total_faixa = Counter()
    for c in faixa_ano.values():
        total_faixa.update(c)
    escrever_csv("faixas_rio_por_ano.csv", ["ano", "dias_validos"] + [f[0] for f in FAIXAS_RIO],
                 [[a, qualidade[a]["dias_validos"]] + [faixa_ano[a][f[0]] for f in FAIXAS_RIO]
                  for a in anos])

    # ---- Limiares propostos e classificação do histórico
    regras = [RegraNivel(**vars(r)) for r in REGRAS_PROPOSTAS]
    definir_limiares(dias, regras)
    classificar_historico(dias, regras)

    lim = tabela_limiares(regras)
    escrever_csv("limiares_nc_prudente.csv",
                 ["nivel", "nome", "ic_min_c", "ic_max_c", "duracao_dias", "regra", "acao_esperada"],
                 lim)

    escrever_csv("ic_diario.csv",
                 ["data", "ic_max_c", "hora_local_ic_max", "temp_no_pico_c", "ur_no_pico_pct",
                  "temp_max_c", "horas_validas", "nivel"],
                 [[d.data.isoformat(), _fmt(d.ic_max, 2), d.hora_ic_max, _fmt(d.temp_no_pico),
                   _fmt(d.ur_no_pico, 0), _fmt(d.temp_max), d.horas_validas, f"NC{d.nivel}"]
                  for d in dias])

    niv_ano = defaultdict(Counter)
    for d in dias:
        niv_ano[d.data.year][d.nivel] += 1
    escrever_csv("niveis_por_ano.csv", ["ano", "dias_validos"] + [f"NC{n}" for n in range(1, 6)],
                 [[a, qualidade[a]["dias_validos"]] + [niv_ano[a][n] for n in range(1, 6)]
                  for a in anos])
    total_niv = Counter(d.nivel for d in dias)

    eps = episodios(dias, 4)
    escrever_csv("episodios_nc4_nc5.csv",
                 ["inicio", "fim", "dias", "nivel_maximo", "ic_max_c", "temp_max_c"], eps)

    # ---- Relatório
    r = []
    r.append("# Níveis de calor NC1–NC5 — Presidente Prudente (INMET A707)\n")
    r.append(f"Gerado em {datetime.now():%Y-%m-%d %H:%M} por `analise_niveis_calor.py`.\n")
    r.append("## Dados\n")
    r.append(f"- Série horária de {dias[0].data:%d/%m/%Y} a {dias[-1].data:%d/%m/%Y} "
             f"(horários convertidos de UTC para UTC−3).")
    r.append(f"- **{n_dias} dias válidos** (≥ {MIN_HORAS_DIA} h com temperatura e umidade, "
             f"e ≥ {MIN_HORAS_PICO} h entre 12h e 17h). Descartes por ano em "
             f"`qualidade_por_ano.csv`.")
    r.append("- Índice de calor: Rothfusz (NWS), T em °F e UR em %, convertido para °C; "
             "abaixo de 80 °F, IC = temperatura.")
    r.append("- Métrica diária: **IC máximo do dia** (maior IC horário).\n")
    r.append("## Distribuição do IC máximo diário\n")
    r.append("| Percentil | " + " | ".join(f"P{_fmt(p, 1).rstrip('0').rstrip(',')}" for p in ps)
             + " | Máx |")
    r.append("|" + "---|" * (len(ps) + 2))
    r.append("| IC (°C) | " + " | ".join(_fmt(dist[p]) for p in ps) + f" | {_fmt(valores[-1])} |\n")
    r.append("## Faixas do Rio aplicadas a Prudente\n")
    r.append("| Faixa de IC máx | Dias | % dos dias | Dias/ano |")
    r.append("|---|---|---|---|")
    for nome, *_ in FAIXAS_RIO:
        n = total_faixa[nome]
        r.append(f"| {nome} | {n} | {_fmt(100 * n / n_dias, 2)}% | {_fmt(n / n_anos)} |")
    r.append("\nAs faixas de NC4 e NC5 do Rio quase nunca ocorrem em Prudente. Com elas, "
             "os níveis mais graves ficariam sem uso, por isso os limiares são ajustados "
             "à série local por percentis.\n")
    r.append("## Limiares propostos para Prudente\n")
    r.append("Regra: o nível do dia é o **maior** nível cuja condição é atendida. Cada nível "
             "pode ser atingido por um dia muito quente **ou** por calor um pouco menor que "
             "se repete por 3 dias seguidos (calor persistente afeta mais os idosos). "
             "Limiares = percentis do IC máximo diário da A707, arredondados a 0,5 °C.\n")
    r.append("| Nível | Nome | Regra | Ação esperada (proposta) |")
    r.append("|---|---|---|---|")
    for n, nome, _, _, _, regra, acao in lim:
        r.append(f"| NC{n} | {nome} | {regra} | {acao} |")
    r.append("\n## Frequência histórica com a regra proposta\n")
    r.append("| Nível | Dias | % dos dias | Dias/ano (média) |")
    r.append("|---|---|---|---|")
    for n in range(1, 6):
        r.append(f"| NC{n} | {total_niv[n]} | {_fmt(100 * total_niv[n] / n_dias, 2)}% | "
                 f"{_fmt(total_niv[n] / n_anos)} |")
    r.append(f"\nEpisódios que chegaram a NC4 ou NC5: {len(eps)} "
             f"(lista em `episodios_nc4_nc5.csv`).\n")
    r.append("## Pendências para o grupo\n")
    r.append("- Conferir as durações exigidas no decreto oficial do protocolo do Rio e citá-lo.")
    r.append("- Validar as ações por nível (são proposta, não norma).")
    r.append("- Os limiares vêm de percentis de 2003–2026; anos recentes (2023–2024) foram "
             "bem mais quentes. Reavaliar a base periodicamente.")
    caminho_rel = os.path.join(PASTA_SAIDA, "relatorio_niveis_calor.md")
    with open(caminho_rel, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")

    # ---- Console
    print("\nPercentis do IC máximo diário (°C):")
    print("  " + "  ".join(f"P{p}={dist[p]:.1f}" for p in ps) + f"  máx={valores[-1]:.1f}")
    print("\nFaixas do Rio em Prudente:")
    for nome, *_ in FAIXAS_RIO:
        n = total_faixa[nome]
        print(f"  {nome:<22} {n:>5} dias  {100 * n / n_dias:6.2f}%  {n / n_anos:5.1f}/ano")
    print("\nLimiares propostos:")
    for n, nome, _, _, _, regra, _ in lim:
        print(f"  NC{n} {nome:<11} {regra}")
    print("\nFrequência histórica com a regra proposta:")
    for n in range(1, 6):
        print(f"  NC{n}: {total_niv[n]:>5} dias  {100 * total_niv[n] / n_dias:6.2f}%  "
              f"{total_niv[n] / n_anos:5.1f}/ano")
    print(f"\nEpisódios NC4+: {len(eps)}")
    print(f"\nArquivos gerados em: {PASTA_SAIDA}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # console do Windows (cp1252)
    ap =argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=CSV_PADRAO, help="CSV unificado da A707")
    ap.add_argument("--leitura", nargs=2, type=float, metavar=("TEMP_C", "UR"),
                    help="calcula o índice de calor de uma leitura")
    ap.add_argument("--classificar", nargs="+", type=float, metavar="IC_MAX",
                    help="IC máximo dos últimos dias (último = hoje); devolve o nível de hoje")
    args = ap.parse_args()

    if args.leitura:
        t, u = args.leitura
        print(f"T = {t} °C, UR = {u}% → índice de calor = {indice_calor(t, u):.1f} °C")
        return

    if args.classificar:
        por_dia, qualidade = ler_serie(args.csv)
        regras = [RegraNivel(**vars(r)) for r in REGRAS_PROPOSTAS]
        definir_limiares(resumir_dias(por_dia, qualidade), regras)
        nivel, motivo = nivel_para_sequencia(args.classificar, regras)
        print(f"Nível de hoje: NC{nivel} — {NOMES[nivel]}")
        if motivo:
            print(f"Motivo: IC máx ≥ {motivo.limiar:.1f} °C por {motivo.dias_consecutivos} "
                  f"dia(s) ({motivo.origem})")
        print(f"Ação: {ACOES[nivel]}")
        print(f"Agir? {'SIM' if nivel >= 3 else 'Não — só monitorar' if nivel == 2 else 'Não'}")
        return

    analisar(args.csv)


if __name__ == "__main__":
    main()
