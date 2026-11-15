# thermocity-banco-de-dados-postgres

> Versão **PostgreSQL** do `thermocity-banco-de-dados` (original em Oracle). Mesmas tabelas, mesmos
> dados e mesma carga; só muda o dialeto SQL e o driver (`psycopg` no lugar de `oracledb`).

Banco de dados do **ThermoCity** num lugar só: o script que **cria as tabelas** e os scripts e arquivos
que **populam** todas elas. Com este repositório dá para montar o banco do zero em qualquer banco
PostgreSQL em poucos minutos.

## Tabelas

| Camada | Tabela | Linhas | O que guarda | De onde vem |
|---|---|---|---|---|
| ONDE | `TMC_SETOR` | 420 | Setores censitários com população 60–69 e 70+ (Censo 2022) e IPVS 2022 | `dados/territorio/tmc_setor.csv` |
| ONDE | `TMC_SERVICO` | 191 | 36 UBS (CNES) e 155 possíveis refúgios (OpenStreetMap) | `dados/territorio/tmc_servico.csv` |
| ONDE | `TMC_CALOR_SETOR` | 420 | Nota de calor 1–5 por setor (Landsat, 08/01/2024) | `dados/territorio/tmc_calor_setor.csv` |
| QUEM | `TMC_PESSOA_SINTETICA` | — | Pessoas 60+ **fictícias** para testar a busca ativa | gerada pela `base-territorial-api` |
| QUANDO | `TMC_LIMIAR_NIVEL_CALOR` | 8 | Regras NC1–NC5 (versão `A707-2003-2026-v1`) | calculada da série do INMET |
| QUANDO | `TMC_LEITURA_CLIMA` | 188.498 | Leituras horárias da estação INMET A707 (2003–2026) + índice de calor | `dados/clima/INMET_A707_…csv` |
| QUANDO | `TMC_RESUMO_DIARIO_CLIMA` | 8.010 | Resumo de cada dia (IC máximo, temperaturas, chuva…) | calculada da série |
| QUANDO | `TMC_NIVEL_CALOR` | 7.498 | Nível NC1–NC5 de cada dia válido | calculada da série |
| GÊMEO | `TMC_SIMULACAO` | — | Cenários de simulação enviados pelo gestor (onda de calor, refúgios, agentes, fator k) | gravada pela `base-territorial-api` |
| GÊMEO | `TMC_SIMULACAO_DIA` | — | Nível NC e totais da busca ativa de cada dia simulado | gravada pela `base-territorial-api` |
| GÊMEO | `TMC_SIMULACAO_RESULTADO` | — | Resultado da simulação por dia e por setor | gravada pela `base-territorial-api` |

> As tabelas do gêmeo ficam separadas das reais: rodar uma simulação não altera nenhum dado real.
> Num banco que já existe (ex.: o do Azure), crie só as três com `sql/04_criar_tabelas_simulacao.sql` (pode rodar mais de uma vez).


## Como montar o banco

Requisitos: Python 3.9+ e acesso a um banco PostgreSQL 12+.

```powershell
py -m pip install -r requirements.txt
copy .env.example .env          # preencher DB_HOST, DB_PORT, DB_NAME, DB_USER e DB_PASSWORD
py carga\carregar.py --simular  # confere os arquivos sem conectar
py carga\carregar.py            # cria as tabelas que faltarem e carrega tudo (~2 a 5 min)
```

Depois, para ter pessoas sintéticas, suba a `base-territorial-api` apontando para o mesmo banco
(`jdbc:postgresql://...` e driver `org.postgresql:postgresql` no lugar do Oracle) e
chame `POST /admin/sinteticos` com `{ "quantidade": 5000, "semente": 42 }`.

| Comando | O que faz |
|---|---|
| `py carga\carregar.py` | cria as tabelas `TMC_` se não existirem e carrega território e clima |
| `py carga\carregar.py --somente territorio` | só setores, serviços e calor |
| `py carga\carregar.py --somente clima` | só leituras, resumo, limiares e níveis |
| `py carga\carregar.py --recriar` | **apaga** todas as tabelas `TMC_` e cria de novo (perde as pessoas sintéticas) |
| `py carga\carregar.py --simular` | só lê e confere os arquivos |

- **Pode rodar de novo:** o território usa `INSERT ... ON CONFLICT` (atualiza sem duplicar) e o clima apaga e grava
  de novo só as observações do INMET.
- **Erro no meio:** cada bloco é uma transação. Se falhar, nada daquele bloco fica gravado.
- **Credenciais:** só no `.env` ou em variáveis de ambiente. O `.env` está no `.gitignore` e **não** vai
  para o GitHub.
- **Sem Python:** dá para criar as tabelas rodando `sql/01_criar_tabelas.sql` no pgAdmin, DBeaver ou
  `psql -f sql/01_criar_tabelas.sql`.
  Os dados, porém, precisam do script.

## Diferenças em relação à versão Oracle

| Oracle | PostgreSQL |
|---|---|
| `VARCHAR2`, `BINARY_DOUBLE`, `CLOB` | `VARCHAR`, `DOUBLE PRECISION`, `TEXT` |
| `NUMBER(p)` / `NUMBER(p,s)` | `SMALLINT`/`INTEGER`/`BIGINT` / `NUMERIC(p,s)` |
| `TIMESTAMP WITH TIME ZONE`, `SYSTIMESTAMP` | `TIMESTAMPTZ`, `CURRENT_TIMESTAMP` |
| Campos 0/1 de `TMC_PESSOA_SINTETICA` (`NUMBER(1)` + CHECK) | `BOOLEAN` (é o que o Hibernate espera para `boolean`) |
| Índice único com `SYS_EXTRACT_UTC` em `TMC_LEITURA_CLIMA` | Índice único com `COALESCE(DATA_EMISSAO_PREVISAO, '-infinity')`, para `NULL` contar como igual |
| `MERGE ... USING DUAL` | `INSERT ... ON CONFLICT DO UPDATE` |
| `DROP TABLE ... CASCADE CONSTRAINTS PURGE` | `DROP TABLE IF EXISTS ... CASCADE` |
| `AT TIME ZONE '-03:00'` | `AT TIME ZONE 'America/Sao_Paulo'` (no PostgreSQL `'-03:00'` seria lido como UTC+3) |
| DDL confirma sozinho | DDL é transacional: o `carregar.py` faz `commit` depois de criar as tabelas |

Os nomes ficam sem aspas, então o PostgreSQL guarda tudo em minúsculas (`tmc_setor`), e consultas em
maiúsculas continuam funcionando.

## Estrutura

```
sql/
  01_criar_tabelas.sql      DDL: 8 tabelas, chaves, checks, índices e comentários
  02_apagar_tabelas.sql     apaga tudo (ordem inversa das chaves estrangeiras)
  03_consultas_exemplo.sql  contagens e consultas de ONDE e QUANDO
carga/
  carregar.py               ponto de entrada (cria tabelas e carrega)
  territorio.py             TMC_SETOR, TMC_SERVICO, TMC_CALOR_SETOR
  clima.py                  TMC_LIMIAR_NIVEL_CALOR, TMC_LEITURA_CLIMA, TMC_RESUMO_DIARIO_CLIMA, TMC_NIVEL_CALOR
  analise_niveis_calor.py   índice de calor (Rothfusz) e limiares NC1–NC5
  conexao.py                conexão (psycopg) e execução dos .sql
dados/
  territorio/               CSVs prontos, no formato das tabelas
  clima/                    série unificada da A707 (2003-02-04 a 2026-10-31)
testes/                     testes sem banco (DDL, arquivos e índice de calor)
```

Testes: `py -m unittest discover -s testes -v`

## Fontes dos dados

| Dado | Fonte | Onde baixar | Usado em |
|---|---|---|---|
| Malha de setores censitários 2022 (polígonos) | IBGE | [Malhas de setores censitários](https://www.ibge.gov.br/geociencias/organizacao-do-territorio/malhas-territoriais/26565-malhasde-setores-censitarios-divisoes-intramunicipais.html) | `TMC_SETOR` (geometria, códigos e nomes) |
| População por idade, Censo 2022 | IBGE | [Agregados por Setores Censitários (FTP)](https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/) | `TMC_SETOR` (`POP_*`) |
| Índice Paulista de Vulnerabilidade Social 2022 | Fundação Seade | [IPVS versão 2022 (Dados Abertos SP)](https://dadosabertos.sp.gov.br/dataset/seade-ipvs-versao-2022) · [principais resultados (PDF)](https://ipvs.seade.gov.br/wp-content/uploads/2026/01/IPVS-2022-principais-resultados.pdf) | `TMC_SETOR` (`IPVS_*`) |
| UBS | Ministério da Saúde, CNES | [API CNES (OpenDataSUS)](https://opendatasus.saude.gov.br/dataset/40a0d093-b12f-44a4-bdc7-bae8eb54dd04/resource/4f0c6f3f-cc21-4148-bb98-fe821fb9db12) | `TMC_SERVICO` (tipo `UBS`) |
| Possíveis refúgios | OpenStreetMap | [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) | `TMC_SERVICO` (tipo `REFUGIO`), revisados à mão |
| Temperatura de superfície, cor e infravermelho | USGS/NASA, Landsat 8 Collection 2 Level-2 | [EarthExplorer](https://earthexplorer.usgs.gov/) · [sobre o produto de temperatura de superfície](https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-temperature) | `TMC_CALOR_SETOR` |
| Altitude | USGS, SRTM 1 Arc-Second Global | [catálogo USGS](https://data.usgs.gov/datacatalog/data/USGS:EROS5e83a3ee1af480c5) | `TMC_CALOR_SETOR.TA_ESTIMADA_C` |
| Modelo de temperatura do ar de Presidente Prudente | Amorim, Dubreuil e Cardoso (2015), Revista Brasileira de Climatologia, v. 16 | [artigo (PDF)](https://revistas.ufpr.br/revistaabclima/article/download/40585/25983) | `TMC_CALOR_SETOR.TA_ESTIMADA_C` |
| Série horária da estação A707 (2003–2026) | INMET | [Dados Históricos](https://portal.inmet.gov.br/dadoshistoricos) | `TMC_LEITURA_CLIMA`, `TMC_RESUMO_DIARIO_CLIMA`, `TMC_NIVEL_CALOR`, `TMC_LIMIAR_NIVEL_CALOR` |
| Fórmula do índice de calor (Rothfusz) | NOAA/NWS | [The Heat Index Equation](https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml) | `TMC_LEITURA_CLIMA.INDICE_CALOR_C` |

Como cada dado foi preparado:

- **Setores, IPVS e serviços:** juntados no QGIS (`prudente_setores_final.gpkg`) e importados pela
  `base-territorial-api`.
  - `LAT/LON_REFERENCIA` (ponto interior) e o `SETOR_CODIGO` de cada serviço (ponto dentro do polígono)
    foram calculados pela API e exportados do banco.
  - `STATUS_CENSO`: 390 `OK`, 21 `SUPRIMIDO` (sigilo do IBGE) e 9 `SEM_REGISTRO`.
  - `IPVS_STATUS`: 392 `OK` e 28 `SEM_DADO`.
- **Calor:** cena `LC08_L2SP_222075_20240108_20240122_02_T1`, processada no QGIS (`landsat/setores_calor.gpkg`).
  A `CLASSE_CALOR` são quintis da temperatura de superfície, com 84 setores por classe. Ela **não** é o
  nível NC: mede o chão e os telhados às 10h20 e serve para comparar setores.
- **Clima:** série baixada e unificada no repositório
  [ThermoCity/Tratamento-de-Dados-PresidPrud-Python](https://github.com/ThermoCity/Tratamento-de-Dados-PresidPrud-Python).
  O cálculo (índice de calor, dia válido, limiares por percentil, regra de 3 dias) é o mesmo daquele
  repositório, e o README de lá explica cada decisão.

## Glossário dos campos

Convenções:
- Ausente é sempre `NULL`, nunca zero nem `-9999`.
- Coordenadas em graus, SIRGAS 2000 (EPSG:4674).
- Horários do clima em UTC; o "dia local" é UTC−3.

### TMC_SETOR — setor censitário

| Campo | Tipo | Significado |
|---|---|---|
| `CODIGO` | texto(15) | **Chave.** Código do setor no IBGE (`CD_SETOR`). Liga todas as tabelas do território |
| `SITUACAO` | texto | Urbana ou Rural |
| `CD_SITUACAO` | texto(5) | Código da situação no IBGE |
| `CD_TIPO` | texto(5) | Código do tipo de setor no IBGE |
| `AREA_KM2` | decimal | Área do setor em km² |
| `CD_MUNICIPIO` / `NM_MUNICIPIO` | texto | Código e nome do município (3541406 = Presidente Prudente) |
| `CD_DISTRITO` / `NM_DISTRITO` | texto | Código e nome do distrito |
| `CD_SUBDISTRITO` / `NM_SUBDISTRITO` | texto | Código e nome do subdistrito |
| `CD_BAIRRO` / `NM_BAIRRO` | texto | Código e nome do bairro (muitas vezes vazio em Prudente) |
| `POP_TOTAL` | inteiro | Moradores do setor (Censo 2022) |
| `POP_60_69` | inteiro | Moradores de 60 a 69 anos |
| `POP_70_MAIS` | inteiro | Moradores de 70 anos ou mais |
| `STATUS_CENSO` | texto | `OK`, `SUPRIMIDO` (IBGE omitiu por sigilo), `SEM_REGISTRO` (setor fora da tabela) ou `SEM_DADO` |
| `IPVS_GRUPO` | inteiro 1–6 | Grupo do IPVS: 1 = baixíssima, 2 = muito baixa, 3 = baixa, 4 = média e 5 = alta vulnerabilidade. Em Prudente só aparecem os grupos 1 a 5 |
| `IPVS_NOME` | texto | Nome do grupo do IPVS |
| `IPVS_EDICAO` | texto | Edição do IPVS (2022) |
| `IPVS_STATUS` | texto | `OK` ou `SEM_DADO` (Seade não classificou o setor) |
| `LAT_REFERENCIA` / `LON_REFERENCIA` | decimal | Ponto garantidamente dentro do setor, usado para medir distâncias |
| `GEOMETRIA_WKT` | TEXT | Polígono do setor em texto WKT |
| `ATUALIZADO_EM` | data/hora | Quando a linha foi gravada |

### TMC_SERVICO — UBS e refúgios

| Campo | Tipo | Significado |
|---|---|---|
| `ID` | texto(40) | **Chave.** `CNES-<código>` para UBS e `OSM-<node/way>-<id>` para refúgios |
| `NOME` | texto | Nome do estabelecimento (`Sem nome (OSM)` quando o mapa não tem) |
| `TIPO` | texto | `UBS` ou `REFUGIO` |
| `CATEGORIA` | texto | Tipo de lugar: biblioteca, templo religioso, centro comunitário etc. |
| `ENDERECO` / `BAIRRO` | texto | Endereço e bairro, quando a fonte informa |
| `LAT` / `LON` | decimal | Coordenada do lugar |
| `FONTE` | texto | `CNES` ou `OpenStreetMap` |
| `ID_FONTE` | texto | Identificador original na fonte |
| `SETOR_CODIGO` | texto(15) | **FK → `TMC_SETOR`.** Setor onde o ponto está |
| `COORD_STATUS` | texto | `OK`, `SEM_COORDENADA` ou `FORA_MUNICIPIO` |
| `REVISAO` | texto | Só refúgios. `manter` = público confirmado (sugerido sempre). `potencial` = templos e shoppings (sugerido se pedido). `revisar` e `remover` = nunca sugeridos. `publico_alvo` = lugar que abriga idosos, não refúgio |
| `MOTIVO_REVISAO` | texto | Por que o refúgio recebeu essa revisão |

### TMC_CALOR_SETOR — calor relativo do setor

| Campo | Tipo | Significado |
|---|---|---|
| `CODIGO_SETOR` | texto(15) | **Chave e FK → `TMC_SETOR`** |
| `LST_VERAO_C` | decimal | Temperatura média da **superfície** (chão e telhados) no setor, em °C, às 10h20 do dia da cena. Não é temperatura do ar |
| `NDVI_MEDIO` | decimal | Índice de vegetação médio (−1 a 1; quanto maior, mais verde) |
| `PCT_CONSTRUCOES` | decimal | % de construções numa janela de 990 m (variável C1 do modelo da Unesp) |
| `PCT_VEGETACAO_DENSA` | decimal | % de vegetação densa numa janela de 990 m (variável C3) |
| `TA_ESTIMADA_C` | decimal | Temperatura do ar estimada pelo modelo da Unesp. Ficou ~9 °C acima das medições de campo: use só para comparar setores |
| `CLASSE_CALOR` | inteiro 1–5 | Nota de calor: quintis de `LST_VERAO_C`. 1 = 20% mais frescos, 5 = 20% mais quentes |
| `PIXELS_VALIDOS` | inteiro | Quantos pixels de 30 m × 30 m sem nuvem entraram na média |
| `CENA_LANDSAT` | texto | Identificador da cena do satélite |
| `DATA_CENA` | data | Dia da passagem do satélite (08/01/2024) |
| `STATUS` | texto | `OK` ou `SEM_DADO` (setor coberto por nuvem) |
| `ATUALIZADO_EM` | data/hora | Quando a linha foi gravada |

### TMC_PESSOA_SINTETICA — idoso fictício

| Campo | Tipo | Significado |
|---|---|---|
| `ID` | inteiro | **Chave.** Gerada pela sequência `TMC_SEQ_PESSOA_SINTETICA` |
| `NOME` | texto | Nome fictício |
| `IDADE` | inteiro | Idade (60 a 95) |
| `FAIXA_ETARIA` | texto | `60-69` ou `70+` |
| `SEXO` | texto | `F` ou `M` |
| `SETOR_CODIGO` | texto(15) | **FK → `TMC_SETOR`.** Setor onde a pessoa mora |
| `LAT` / `LON` | decimal | Ponto sorteado dentro do setor |
| `MORA_SOZINHO` | booleano | Mora sozinho (taxa PROVISÓRIA) |
| `MOBILIDADE_REDUZIDA` | booleano | Tem mobilidade reduzida (taxa PROVISÓRIA) |
| `CONDICAO_CRONICA` | booleano | Tem condição crônica de saúde (taxa PROVISÓRIA) |
| `TELEFONE` | texto | Telefone fictício `+55 18 0000-XXXX`, não discável |
| `CONTATO_REF_NOME` / `CONTATO_REF_TELEFONE` | texto | Contato de referência fictício |
| `UBS_REF_ID` | texto | **FK → `TMC_SERVICO`.** UBS mais próxima do ponto |
| `UBS_REF_NOME` | texto | Nome dessa UBS |
| `CONSENTIMENTO_LGPD` / `CONSENTIMENTO_EM` | booleano, data/hora | Consentimento simulado |
| `SINTETICO` | booleano | Sempre `true`: deixa claro que o registro é fictício |
| `SEMENTE` | inteiro | Semente do sorteio (mesma semente = mesmo cadastro) |
| `GERADO_EM` | data/hora | Quando o cadastro foi gerado |

### TMC_LIMIAR_NIVEL_CALOR — regras NC1–NC5

| Campo | Tipo | Significado |
|---|---|---|
| `ID_LIMIAR` | inteiro | **Chave** |
| `VERSAO_LIMIAR` | texto | Versão das regras (`A707-2003-2026-v1`). Uma revisão dos limiares vira uma versão nova |
| `NIVEL` | 1–5 | Nível que a regra atribui |
| `NOME_NIVEL` | texto | Normal, Atenção, Alerta, Alto risco ou Emergência |
| `IC_MIN_C` | decimal | Índice de calor máximo do dia a partir do qual a regra vale (°C) |
| `IC_MAX_C` | decimal | Limite de cima da faixa, só informativo |
| `DURACAO_DIAS` | inteiro | Dias seguidos exigidos (1 = um dia basta; 3 = calor persistente) |
| `PERCENTIL` | decimal | Percentil da série 2003–2026 que gerou o limiar (P90, P95…) |
| `REGRA` | texto | A regra escrita por extenso |
| `ACAO_ESPERADA` | texto | O que a busca ativa deve fazer nesse nível |
| `ATIVO` | S/N | `S` na versão em uso |
| `CRIADO_EM` | data/hora | Quando a regra foi gravada |

### TMC_LEITURA_CLIMA — leitura horária

| Campo | Tipo | Significado |
|---|---|---|
| `ID_LEITURA` | inteiro | **Chave** |
| `DATA_HORA_UTC` | data/hora com fuso | Hora da medição, em UTC |
| `DATA_LOCAL` | data | Dia da medição no horário de Prudente (UTC−3) |
| `FONTE` | texto | `INMET` (estação A707). `OPENWEATHER` fica reservado |
| `TIPO` | texto | `OBSERVACAO` (medido) ou `PREVISAO` |
| `DATA_EMISSAO_PREVISAO` / `HORIZONTE_H` | data/hora, inteiro | Só para previsões: quando foi emitida e quantas horas à frente |
| `PRECIPITACAO_MM` | decimal | Chuva na hora (mm) |
| `PRESSAO_HPA`, `PRESSAO_MAX_HORA_HPA`, `PRESSAO_MIN_HORA_HPA` | decimal | Pressão atmosférica na estação e máx./mín. na hora anterior (hPa) |
| `RADIACAO_KJ_M2` | decimal | Radiação solar global (kJ/m²) |
| `TEMPERATURA_C` | decimal | Temperatura do ar (°C) |
| `PONTO_ORVALHO_C` | decimal | Temperatura do ponto de orvalho (°C) |
| `TEMP_MAX_HORA_C` / `TEMP_MIN_HORA_C` | decimal | Máxima e mínima na hora anterior (°C) |
| `ORVALHO_MAX_HORA_C` / `ORVALHO_MIN_HORA_C` | decimal | Ponto de orvalho máx./mín. na hora anterior (°C) |
| `UMIDADE_PCT` | inteiro | Umidade relativa do ar (%) |
| `UMIDADE_MAX_HORA_PCT` / `UMIDADE_MIN_HORA_PCT` | inteiro | Umidade máx./mín. na hora anterior (%) |
| `VENTO_DIRECAO_GRAUS` | inteiro | Direção do vento (graus) |
| `VENTO_VELOCIDADE_MS` / `VENTO_RAJADA_MS` | decimal | Velocidade média e rajada máxima do vento (m/s) |
| `INDICE_CALOR_C` | decimal | Índice de calor (sensação térmica pela fórmula de Rothfusz). Abaixo de 26,7 °C é igual à temperatura |
| `QUALIDADE` | texto | `OK` (tem temperatura e umidade), `PARCIAL` (falta uma delas, sem índice) ou `FORA_FAIXA` (valor implausível) |

### TMC_RESUMO_DIARIO_CLIMA — resumo do dia

| Campo | Tipo | Significado |
|---|---|---|
| `DATA_LOCAL` + `FONTE` + `TIPO` | data, texto | **Chave** |
| `IC_MAX_C` | decimal | Maior índice de calor do dia (é o que define o nível NC) |
| `HORA_LOCAL_IC_MAX` | inteiro | Hora local em que ocorreu o pico |
| `TEMP_NO_PICO_C` / `UR_NO_PICO_PCT` | decimal | Temperatura e umidade na hora do pico |
| `IC_MEDIO_C` | decimal | Índice de calor médio do dia |
| `HORAS_IC_GE_35` / `HORAS_IC_GE_36` | inteiro | Horas com índice de calor ≥ 35 °C e ≥ 36 °C |
| `TEMP_MAX_C`, `TEMP_MIN_C`, `TEMP_MEDIA_C` | decimal | Temperatura máxima, mínima e média do dia |
| `UR_MIN_PCT` / `UR_MEDIA_PCT` | decimal | Umidade mínima e média |
| `CHUVA_TOTAL_MM` | decimal | Chuva acumulada no dia |
| `RADIACAO_TOTAL_KJ_M2` | decimal | Radiação solar acumulada |
| `VENTO_MEDIO_MS` / `RAJADA_MAX_MS` | decimal | Vento médio e maior rajada |
| `DIAS_CONSEC_NC2` | inteiro | Dias seguidos (até hoje) com índice de calor no nível de Atenção ou acima |
| `HORAS_COM_DADO` / `HORAS_VALIDAS` | inteiro | Horas com alguma medição e horas com temperatura e umidade válidas |
| `DIA_VALIDO` | S/N | `S` se tiver ≥ 18 h válidas e ≥ 4 h válidas entre 12h e 17h. Só dias válidos recebem nível |

### TMC_NIVEL_CALOR — nível do dia

| Campo | Tipo | Significado |
|---|---|---|
| `ID_NIVEL` | inteiro | **Chave** |
| `DATA_LOCAL` | data | Dia (horário de Prudente) |
| `NIVEL` / `NOME_NIVEL` | 1–5, texto | Nível NC atribuído ao dia |
| `IC_MAX_C` | decimal | Índice de calor máximo do dia |
| `ORIGEM` | texto | `OBSERVADO` (medido) ou `PREVISTO` |
| `FONTE` | texto | Fonte dos dados (`INMET`) |
| `VERSAO_LIMIAR` | texto | Versão das regras usada no cálculo |
| `ID_LEITURA` | inteiro | **FK → `TMC_LEITURA_CLIMA`.** Leitura em que ocorreu o pico |
| `ID_LIMIAR` | inteiro | **FK → `TMC_LIMIAR_NIVEL_CALOR`.** Regra que definiu o nível |
| `CALCULADO_EM` | data/hora | Quando o nível foi calculado |

## Se os dados mudarem

- **Território:** gere de novo o CSV correspondente em `dados/territorio` com as mesmas colunas e
  rode `--somente territorio`.
- **Série do INMET:** troque o CSV em `dados/clima` e rode `--somente clima`. Os limiares são
  recalculados.
- **Tabela nova:** coloque o `CREATE TABLE` em `sql/01_criar_tabelas.sql` com o prefixo `TMC_` e o
  `DROP` em `sql/02_apagar_tabelas.sql`. Os testes conferem os dois.
