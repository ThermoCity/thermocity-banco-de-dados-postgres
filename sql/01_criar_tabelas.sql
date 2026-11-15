-- =============================================================================
-- ThermoCity — criação das tabelas (PostgreSQL 12+)
-- Prefixo TMC_ = ThermoCity. Rode conectado no banco/schema que vai guardar os dados.
-- Nomes sem aspas: o PostgreSQL guarda tudo em minúsculas (tmc_setor), e as consultas
-- em maiúsculas (TMC_SETOR) continuam funcionando.
--
-- Ordem: território (ONDE) -> pessoas (QUEM) -> clima (QUANDO).
-- Para apagar tudo: 02_apagar_tabelas.sql
-- Cada comando termina em ";" no fim da linha (o carregar.py usa isso para dividir o arquivo).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- ONDE — território de Presidente Prudente
-- -----------------------------------------------------------------------------

-- Setor censitário do IBGE (Censo 2022) com população idosa e IPVS 2022 (Seade).
CREATE TABLE TMC_SETOR (
    CODIGO           VARCHAR(15)    NOT NULL,
    SITUACAO         VARCHAR(255),
    CD_SITUACAO      VARCHAR(5),
    CD_TIPO          VARCHAR(5),
    AREA_KM2         DOUBLE PRECISION,
    CD_MUNICIPIO     VARCHAR(7),
    NM_MUNICIPIO     VARCHAR(255),
    CD_DISTRITO      VARCHAR(9),
    NM_DISTRITO      VARCHAR(255),
    CD_SUBDISTRITO   VARCHAR(11),
    NM_SUBDISTRITO   VARCHAR(255),
    CD_BAIRRO        VARCHAR(255),
    NM_BAIRRO        VARCHAR(255),
    POP_TOTAL        INTEGER,
    POP_60_69        INTEGER,
    POP_70_MAIS      INTEGER,
    STATUS_CENSO     VARCHAR(15),
    IPVS_GRUPO       INTEGER,
    IPVS_NOME        VARCHAR(255),
    IPVS_EDICAO      VARCHAR(10),
    IPVS_STATUS      VARCHAR(15),
    LAT_REFERENCIA   DOUBLE PRECISION,
    LON_REFERENCIA   DOUBLE PRECISION,
    GEOMETRIA_WKT    TEXT,
    ATUALIZADO_EM    TIMESTAMPTZ(6) DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT PK_TMC_SETOR PRIMARY KEY (CODIGO),
    CONSTRAINT CK_TMC_SETOR_STATUS_CENSO CHECK (STATUS_CENSO IN ('OK','SUPRIMIDO','SEM_REGISTRO','SEM_DADO')),
    CONSTRAINT CK_TMC_SETOR_IPVS_GRUPO CHECK (IPVS_GRUPO BETWEEN 1 AND 6),
    CONSTRAINT CK_TMC_SETOR_IPVS_STATUS CHECK (IPVS_STATUS IN ('OK','SUPRIMIDO','SEM_REGISTRO','SEM_DADO'))
);

COMMENT ON TABLE TMC_SETOR IS 'Setores censitarios de Presidente Prudente (IBGE, Censo 2022) com populacao 60+ e IPVS 2022';
COMMENT ON COLUMN TMC_SETOR.STATUS_CENSO IS 'OK, SUPRIMIDO (sigilo do IBGE) ou SEM_REGISTRO. Ausente nunca vira zero';
COMMENT ON COLUMN TMC_SETOR.LAT_REFERENCIA IS 'Ponto garantidamente dentro do setor, usado para medir distancias';
COMMENT ON COLUMN TMC_SETOR.GEOMETRIA_WKT IS 'Poligono do setor em WKT, SIRGAS 2000 (EPSG:4674)';

-- UBS (CNES) e possíveis refúgios climáticos (OpenStreetMap).
CREATE TABLE TMC_SERVICO (
    ID               VARCHAR(40)    NOT NULL,
    NOME             VARCHAR(300),
    TIPO             VARCHAR(10)    NOT NULL,
    CATEGORIA        VARCHAR(255),
    ENDERECO         VARCHAR(300),
    BAIRRO           VARCHAR(255),
    LAT              DOUBLE PRECISION,
    LON              DOUBLE PRECISION,
    FONTE            VARCHAR(30),
    ID_FONTE         VARCHAR(40),
    SETOR_CODIGO     VARCHAR(15),
    COORD_STATUS     VARCHAR(20),
    REVISAO          VARCHAR(20),
    MOTIVO_REVISAO   VARCHAR(500),
    CONSTRAINT PK_TMC_SERVICO PRIMARY KEY (ID),
    CONSTRAINT FK_TMC_SERVICO_SETOR FOREIGN KEY (SETOR_CODIGO) REFERENCES TMC_SETOR (CODIGO),
    CONSTRAINT CK_TMC_SERVICO_TIPO CHECK (TIPO IN ('UBS','REFUGIO')),
    CONSTRAINT CK_TMC_SERVICO_COORD CHECK (COORD_STATUS IN ('OK','SEM_COORDENADA','FORA_MUNICIPIO')),
    CONSTRAINT CK_TMC_SERVICO_REVISAO CHECK (REVISAO IN ('manter','potencial','revisar','remover','publico_alvo'))
);

CREATE INDEX IX_TMC_SERVICO_SETOR ON TMC_SERVICO (SETOR_CODIGO);
COMMENT ON TABLE TMC_SERVICO IS 'UBS (CNES) e possiveis refugios climaticos (OpenStreetMap) de Presidente Prudente';
COMMENT ON COLUMN TMC_SERVICO.REVISAO IS 'So refugios. manter = publico confirmado. potencial = templos e shoppings. revisar e remover nunca sao sugeridos';

-- Calor relativo de cada setor (Landsat 8, cena de verão), feature "Mapa de Calor por Setor".
CREATE TABLE TMC_CALOR_SETOR (
    CODIGO_SETOR         VARCHAR(15)    NOT NULL,
    LST_VERAO_C          DOUBLE PRECISION,
    NDVI_MEDIO           DOUBLE PRECISION,
    PCT_CONSTRUCOES      DOUBLE PRECISION,
    PCT_VEGETACAO_DENSA  DOUBLE PRECISION,
    TA_ESTIMADA_C        DOUBLE PRECISION,
    CLASSE_CALOR         INTEGER,
    PIXELS_VALIDOS       INTEGER,
    CENA_LANDSAT         VARCHAR(60),
    DATA_CENA            DATE,
    STATUS               VARCHAR(15),
    ATUALIZADO_EM        TIMESTAMPTZ(6) DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT PK_TMC_CALOR_SETOR PRIMARY KEY (CODIGO_SETOR),
    CONSTRAINT FK_TMC_CALOR_SETOR_SETOR FOREIGN KEY (CODIGO_SETOR) REFERENCES TMC_SETOR (CODIGO),
    CONSTRAINT CK_TMC_CALOR_CLASSE CHECK (CLASSE_CALOR BETWEEN 1 AND 5),
    CONSTRAINT CK_TMC_CALOR_STATUS CHECK (STATUS IN ('OK','SEM_DADO'))
);

COMMENT ON TABLE TMC_CALOR_SETOR IS 'Calor relativo por setor a partir da temperatura de superficie do Landsat (cena de verao)';
COMMENT ON COLUMN TMC_CALOR_SETOR.CLASSE_CALOR IS 'Quintis da temperatura de superficie: 1 = 20% mais frescos, 5 = 20% mais quentes. Nao e nivel NC';
COMMENT ON COLUMN TMC_CALOR_SETOR.LST_VERAO_C IS 'Temperatura media da SUPERFICIE (chao e telhados) as 10h20 do dia da cena. Nao e temperatura do ar';
COMMENT ON COLUMN TMC_CALOR_SETOR.TA_ESTIMADA_C IS 'Temperatura do ar pelo modelo Amorim, Dubreuil e Cardoso (2015). So para comparar setores';


-- -----------------------------------------------------------------------------
-- QUEM — cadastro FICTÍCIO de pessoas 60+ (gerado pela base-territorial-api)
-- -----------------------------------------------------------------------------

-- Incremento 50 = allocationSize do Hibernate na entidade PessoaSintetica.
CREATE SEQUENCE TMC_SEQ_PESSOA_SINTETICA START WITH 1 INCREMENT BY 50;

-- Os campos sim/não são BOOLEAN (no Oracle eram NUMBER(1) 0/1): é o tipo que o Hibernate
-- espera para os campos boolean da entidade PessoaSintetica no PostgreSQL.
CREATE TABLE TMC_PESSOA_SINTETICA (
    ID                    BIGINT         NOT NULL,
    NOME                  VARCHAR(120)   NOT NULL,
    IDADE                 INTEGER,
    FAIXA_ETARIA          VARCHAR(10),
    SEXO                  VARCHAR(1),
    SETOR_CODIGO          VARCHAR(15)    NOT NULL,
    LAT                   DOUBLE PRECISION,
    LON                   DOUBLE PRECISION,
    MORA_SOZINHO          BOOLEAN        DEFAULT FALSE NOT NULL,
    MOBILIDADE_REDUZIDA   BOOLEAN        DEFAULT FALSE NOT NULL,
    CONDICAO_CRONICA      BOOLEAN        DEFAULT FALSE NOT NULL,
    TELEFONE              VARCHAR(30),
    CONTATO_REF_NOME      VARCHAR(120),
    CONTATO_REF_TELEFONE  VARCHAR(30),
    UBS_REF_ID            VARCHAR(40),
    UBS_REF_NOME          VARCHAR(300),
    CONSENTIMENTO_LGPD    BOOLEAN        DEFAULT FALSE NOT NULL,
    CONSENTIMENTO_EM      TIMESTAMPTZ(6),
    SINTETICO             BOOLEAN        DEFAULT TRUE NOT NULL,
    SEMENTE               BIGINT,
    GERADO_EM             TIMESTAMPTZ(6),
    CONSTRAINT PK_TMC_PESSOA_SINTETICA PRIMARY KEY (ID),
    CONSTRAINT FK_TMC_PESSOA_SETOR FOREIGN KEY (SETOR_CODIGO) REFERENCES TMC_SETOR (CODIGO),
    CONSTRAINT FK_TMC_PESSOA_UBS FOREIGN KEY (UBS_REF_ID) REFERENCES TMC_SERVICO (ID),
    CONSTRAINT CK_TMC_PESSOA_SEXO CHECK (SEXO IN ('F','M')),
    CONSTRAINT CK_TMC_PESSOA_FAIXA CHECK (FAIXA_ETARIA IN ('60-69','70+'))
);

CREATE INDEX IX_TMC_PESSOA_SETOR ON TMC_PESSOA_SINTETICA (SETOR_CODIGO);
CREATE INDEX IX_TMC_PESSOA_UBS ON TMC_PESSOA_SINTETICA (UBS_REF_ID);
COMMENT ON TABLE TMC_PESSOA_SINTETICA IS 'Pessoas 60+ FICTICIAS para testar a busca ativa. Taxas de vulnerabilidade PROVISORIAS';


-- -----------------------------------------------------------------------------
-- QUANDO — clima da estação INMET A707 e níveis de calor NC1–NC5
-- -----------------------------------------------------------------------------

-- Regras NC1–NC5 versionadas.
CREATE TABLE TMC_LIMIAR_NIVEL_CALOR (
    ID_LIMIAR       BIGINT GENERATED BY DEFAULT AS IDENTITY,
    VERSAO_LIMIAR   VARCHAR(40)    NOT NULL,
    NIVEL           SMALLINT       NOT NULL,
    NOME_NIVEL      VARCHAR(20)    NOT NULL,
    IC_MIN_C        NUMERIC(5,2),
    IC_MAX_C        NUMERIC(5,2),
    DURACAO_DIAS    SMALLINT       NOT NULL,
    PERCENTIL       NUMERIC(5,2),
    REGRA           VARCHAR(300)   NOT NULL,
    ACAO_ESPERADA   VARCHAR(400)   NOT NULL,
    ATIVO           CHAR(1)        DEFAULT 'S' NOT NULL,
    CRIADO_EM       TIMESTAMPTZ    DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_TMC_LIMIAR_NIVEL_CALOR PRIMARY KEY (ID_LIMIAR),
    CONSTRAINT UK_TMC_LIMIAR_NC UNIQUE (VERSAO_LIMIAR, NIVEL, DURACAO_DIAS),
    CONSTRAINT CK_TMC_LIMIAR_NIVEL CHECK (NIVEL BETWEEN 1 AND 5),
    CONSTRAINT CK_TMC_LIMIAR_ATIVO CHECK (ATIVO IN ('S','N'))
);

COMMENT ON TABLE TMC_LIMIAR_NIVEL_CALOR IS 'Regras NC1-NC5 do indice de calor maximo diario, versionadas, com a acao esperada';

-- Leituras horárias (observação) e previsões.
CREATE TABLE TMC_LEITURA_CLIMA (
    ID_LEITURA             BIGINT GENERATED BY DEFAULT AS IDENTITY,
    DATA_HORA_UTC          TIMESTAMPTZ   NOT NULL,
    DATA_LOCAL             DATE          NOT NULL,
    FONTE                  VARCHAR(20)   NOT NULL,
    TIPO                   VARCHAR(10)   NOT NULL,
    DATA_EMISSAO_PREVISAO  TIMESTAMPTZ,
    HORIZONTE_H            SMALLINT,
    PRECIPITACAO_MM        NUMERIC(6,2),
    PRESSAO_HPA            NUMERIC(6,1),
    PRESSAO_MAX_HORA_HPA   NUMERIC(6,1),
    PRESSAO_MIN_HORA_HPA   NUMERIC(6,1),
    RADIACAO_KJ_M2         NUMERIC(8,1),
    TEMPERATURA_C          NUMERIC(4,1),
    PONTO_ORVALHO_C        NUMERIC(4,1),
    TEMP_MAX_HORA_C        NUMERIC(4,1),
    TEMP_MIN_HORA_C        NUMERIC(4,1),
    ORVALHO_MAX_HORA_C     NUMERIC(4,1),
    ORVALHO_MIN_HORA_C     NUMERIC(4,1),
    UMIDADE_MAX_HORA_PCT   SMALLINT,
    UMIDADE_MIN_HORA_PCT   SMALLINT,
    UMIDADE_PCT            SMALLINT,
    VENTO_DIRECAO_GRAUS    SMALLINT,
    VENTO_RAJADA_MS        NUMERIC(5,1),
    VENTO_VELOCIDADE_MS    NUMERIC(5,1),
    INDICE_CALOR_C         NUMERIC(5,2),
    QUALIDADE              VARCHAR(12)   NOT NULL,
    CONSTRAINT PK_TMC_LEITURA_CLIMA PRIMARY KEY (ID_LEITURA),
    CONSTRAINT CK_TMC_LEITURA_FONTE CHECK (FONTE IN ('INMET','OPENWEATHER')),
    CONSTRAINT CK_TMC_LEITURA_TIPO CHECK (TIPO IN ('OBSERVACAO','PREVISAO')),
    CONSTRAINT CK_TMC_LEITURA_QUALIDADE CHECK (QUALIDADE IN ('OK','PARCIAL','FORA_FAIXA'))
);

-- No PostgreSQL um UNIQUE comum deixaria repetir observações (DATA_EMISSAO_PREVISAO é NULL e
-- NULL nunca é igual a NULL). O COALESCE trata NULL como um valor, igual ao índice do Oracle.
CREATE UNIQUE INDEX UK_TMC_LEITURA_CLIMA ON TMC_LEITURA_CLIMA (FONTE, TIPO, DATA_HORA_UTC, COALESCE(DATA_EMISSAO_PREVISAO, '-infinity'::TIMESTAMPTZ));
CREATE INDEX IX_TMC_LEITURA_CLIMA_DATA ON TMC_LEITURA_CLIMA (DATA_LOCAL, FONTE, TIPO);
COMMENT ON TABLE TMC_LEITURA_CLIMA IS 'Leituras horarias da estacao INMET A707 e previsoes. Ausente = NULL, nunca -9999';
COMMENT ON COLUMN TMC_LEITURA_CLIMA.INDICE_CALOR_C IS 'Rothfusz (NWS) a partir de TEMPERATURA_C e UMIDADE_PCT. Abaixo de 80 F = temperatura';
COMMENT ON COLUMN TMC_LEITURA_CLIMA.QUALIDADE IS 'OK = temperatura e umidade validas. PARCIAL = falta temperatura ou umidade. FORA_FAIXA = valor implausivel';

-- Agregados diários (dia local, UTC-3) para análise e ML.
CREATE TABLE TMC_RESUMO_DIARIO_CLIMA (
    DATA_LOCAL            DATE          NOT NULL,
    FONTE                 VARCHAR(20)   NOT NULL,
    TIPO                  VARCHAR(10)   NOT NULL,
    IC_MAX_C              NUMERIC(5,2),
    HORA_LOCAL_IC_MAX     SMALLINT,
    TEMP_NO_PICO_C        NUMERIC(4,1),
    UR_NO_PICO_PCT        SMALLINT,
    IC_MEDIO_C            NUMERIC(5,2),
    HORAS_IC_GE_35        SMALLINT,
    HORAS_IC_GE_36        SMALLINT,
    TEMP_MAX_C            NUMERIC(4,1),
    TEMP_MIN_C            NUMERIC(4,1),
    TEMP_MEDIA_C          NUMERIC(4,1),
    UR_MIN_PCT            SMALLINT,
    UR_MEDIA_PCT          NUMERIC(4,1),
    CHUVA_TOTAL_MM        NUMERIC(6,1),
    RADIACAO_TOTAL_KJ_M2  NUMERIC(9,1),
    VENTO_MEDIO_MS        NUMERIC(4,1),
    RAJADA_MAX_MS         NUMERIC(5,1),
    DIAS_CONSEC_NC2       SMALLINT,
    HORAS_COM_DADO        SMALLINT      NOT NULL,
    HORAS_VALIDAS         SMALLINT      NOT NULL,
    DIA_VALIDO            CHAR(1)       NOT NULL,
    CONSTRAINT PK_TMC_RESUMO_DIARIO_CLIMA PRIMARY KEY (DATA_LOCAL, FONTE, TIPO),
    CONSTRAINT CK_TMC_RESUMO_DIA_VALIDO CHECK (DIA_VALIDO IN ('S','N'))
);

COMMENT ON TABLE TMC_RESUMO_DIARIO_CLIMA IS 'Agregados diarios (dia local UTC-3) para analise e ML';
COMMENT ON COLUMN TMC_RESUMO_DIARIO_CLIMA.DIA_VALIDO IS 'S se tiver pelo menos 18 h validas e 4 h validas entre 12h e 17h locais';

-- Nível NC1–NC5 de cada dia válido.
CREATE TABLE TMC_NIVEL_CALOR (
    ID_NIVEL        BIGINT GENERATED BY DEFAULT AS IDENTITY,
    DATA_LOCAL      DATE          NOT NULL,
    NIVEL           SMALLINT      NOT NULL,
    NOME_NIVEL      VARCHAR(20)   NOT NULL,
    IC_MAX_C        NUMERIC(5,2)  NOT NULL,
    ORIGEM          VARCHAR(10)   NOT NULL,
    FONTE           VARCHAR(20)   NOT NULL,
    VERSAO_LIMIAR   VARCHAR(40)   NOT NULL,
    ID_LEITURA      BIGINT,
    ID_LIMIAR       BIGINT,
    CALCULADO_EM    TIMESTAMPTZ   DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_TMC_NIVEL_CALOR PRIMARY KEY (ID_NIVEL),
    CONSTRAINT UK_TMC_NIVEL_CALOR UNIQUE (DATA_LOCAL, ORIGEM, FONTE, VERSAO_LIMIAR),
    CONSTRAINT FK_TMC_NIVEL_LEITURA FOREIGN KEY (ID_LEITURA) REFERENCES TMC_LEITURA_CLIMA (ID_LEITURA),
    CONSTRAINT FK_TMC_NIVEL_LIMIAR FOREIGN KEY (ID_LIMIAR) REFERENCES TMC_LIMIAR_NIVEL_CALOR (ID_LIMIAR),
    CONSTRAINT CK_TMC_NIVEL_NIVEL CHECK (NIVEL BETWEEN 1 AND 5),
    CONSTRAINT CK_TMC_NIVEL_ORIGEM CHECK (ORIGEM IN ('OBSERVADO','PREVISTO'))
);

CREATE INDEX IX_TMC_NIVEL_CALOR_DATA ON TMC_NIVEL_CALOR (DATA_LOCAL);
CREATE INDEX IX_TMC_NIVEL_LEITURA ON TMC_NIVEL_CALOR (ID_LEITURA);
CREATE INDEX IX_TMC_NIVEL_LIMIAR ON TMC_NIVEL_CALOR (ID_LIMIAR);
COMMENT ON TABLE TMC_NIVEL_CALOR IS 'Nivel NC1-NC5 por dia, calculado pelos limiares da VERSAO_LIMIAR';

CREATE TABLE IF NOT EXISTS tmc_orientacao_contato (
    id                   BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    pessoa_id            BIGINT           NOT NULL,
    data_lista           DATE             NOT NULL,
    nivel_calor          INTEGER          CHECK (nivel_calor BETWEEN 1 AND 5),
    ic_previsto_c        DOUBLE PRECISION,
    roteiro              TEXT,
    sinais_alerta        TEXT,
    refugio_nome         VARCHAR(300),
    refugio_endereco     VARCHAR(300),
    refugio_distancia_m  INTEGER,
    fontes               TEXT,
    modelo               VARCHAR(60),
    gerado_em            TIMESTAMP(6) WITH TIME ZONE,
    CONSTRAINT uk_tmc_orientacao_pessoa_dia UNIQUE (pessoa_id, data_lista)
);

COMMENT ON TABLE tmc_orientacao_contato IS 'Roteiro de contato gerado por IA (RAG) para cada pessoa da lista do dia. Guardado para não chamar o modelo de novo';
COMMENT ON COLUMN tmc_orientacao_contato.fontes IS 'Guias oficiais usados, um por linha';
COMMENT ON COLUMN tmc_orientacao_contato.pessoa_id IS 'Id da pessoa (tmc_pessoa_sintetica). Nenhum dado identificador é enviado ao modelo';

-- -----------------------------------------------------------------------------
-- GÊMEO DIGITAL — simulação de cenários (base-territorial-api)
-- Tudo da simulação fica nestas tabelas: rodar um cenário não altera nenhuma tabela real.
-- -----------------------------------------------------------------------------

-- Cenário enviado pelo gestor (POST /simulacoes) e situação da execução.
CREATE TABLE TMC_SIMULACAO (
    ID_SIMULACAO             BIGINT GENERATED BY DEFAULT AS IDENTITY,
    NOME                     VARCHAR(120)   NOT NULL,
    STATUS                   VARCHAR(15)    NOT NULL,
    MODELO_ID                VARCHAR(40),
    DATA_INICIO              DATE,
    QTD_DIAS                 SMALLINT       NOT NULL,
    REFUGIOS                 VARCHAR(10)    NOT NULL,
    AGENTES_POR_UBS          SMALLINT       NOT NULL,
    CONTATOS_POR_AGENTE_DIA  SMALLINT       NOT NULL,
    FATOR_K                  NUMERIC(3,2)   NOT NULL,
    DISTRITO                 VARCHAR(255),
    VERSAO_LIMIAR            VARCHAR(40)    NOT NULL,
    NIVEL_MAXIMO             SMALLINT       NOT NULL,
    MAX_HISTORICO_IC_C       NUMERIC(5,2),
    DIAS_EXTRAPOLADOS        SMALLINT       NOT NULL,
    CRIADO_POR               VARCHAR(120)   NOT NULL,
    CRIADO_EM                TIMESTAMPTZ    NOT NULL,
    CONCLUIDO_EM             TIMESTAMPTZ,
    CONSTRAINT PK_TMC_SIMULACAO PRIMARY KEY (ID_SIMULACAO),
    CONSTRAINT CK_TMC_SIMULACAO_STATUS CHECK (STATUS IN ('PROCESSANDO','CONCLUIDA','ERRO')),
    CONSTRAINT CK_TMC_SIMULACAO_DIAS CHECK (QTD_DIAS BETWEEN 1 AND 15),
    CONSTRAINT CK_TMC_SIMULACAO_REFUGIOS CHECK (REFUGIOS IN ('TODOS','PUBLICOS','NENHUM')),
    CONSTRAINT CK_TMC_SIMULACAO_AGENTES CHECK (AGENTES_POR_UBS > 0 AND CONTATOS_POR_AGENTE_DIA > 0),
    CONSTRAINT CK_TMC_SIMULACAO_K CHECK (FATOR_K BETWEEN 0.10 AND 0.50)
);

CREATE INDEX IX_TMC_SIMULACAO_CRIADO_EM ON TMC_SIMULACAO (CRIADO_EM);
COMMENT ON TABLE TMC_SIMULACAO IS 'Cenario hipotetico do gemeo digital (onda de calor, refugios, agentes). Separado das tabelas reais';
COMMENT ON COLUMN TMC_SIMULACAO.FATOR_K IS 'Estimativa: quanto da diferenca de temperatura de superficie (Landsat) vira diferenca de ar entre setores';
COMMENT ON COLUMN TMC_SIMULACAO.MAX_HISTORICO_IC_C IS 'Maior IC maximo diario da A707 no momento da simulacao; acima dele o dia e extrapolacao';

-- Resultado de cada dia do cenário. Os totais da busca ativa são preenchidos pelo motor dia a dia.
CREATE TABLE TMC_SIMULACAO_DIA (
    ID_SIMULACAO      BIGINT         NOT NULL,
    DIA               SMALLINT       NOT NULL,
    DATA_LOCAL        DATE,
    IC_MAX_C          NUMERIC(5,2)   NOT NULL,
    NIVEL             SMALLINT       NOT NULL,
    NOME_NIVEL        VARCHAR(20)    NOT NULL,
    REGRA             VARCHAR(300)   NOT NULL,
    EXTRAPOLACAO      CHAR(1)        NOT NULL,
    PESSOAS_LISTA     INTEGER,
    CONTATADAS        INTEGER,
    PENDENTES         INTEGER,
    SEM_REFUGIO_800M  INTEGER,
    CONSTRAINT PK_TMC_SIMULACAO_DIA PRIMARY KEY (ID_SIMULACAO, DIA),
    CONSTRAINT FK_TMC_SIM_DIA_SIMULACAO FOREIGN KEY (ID_SIMULACAO) REFERENCES TMC_SIMULACAO (ID_SIMULACAO) ON DELETE CASCADE,
    CONSTRAINT CK_TMC_SIM_DIA_NIVEL CHECK (NIVEL BETWEEN 1 AND 5),
    CONSTRAINT CK_TMC_SIM_DIA_EXTRAP CHECK (EXTRAPOLACAO IN ('S','N'))
);

COMMENT ON TABLE TMC_SIMULACAO_DIA IS 'Nivel NC e totais da busca ativa de cada dia da simulacao';

-- Resultado de cada setor em cada dia (preenchido pelo motor dia a dia).
CREATE TABLE TMC_SIMULACAO_RESULTADO (
    ID_SIMULACAO      BIGINT         NOT NULL,
    DIA               SMALLINT       NOT NULL,
    CODIGO_SETOR      VARCHAR(15)    NOT NULL,
    PESSOAS_LISTA     INTEGER        NOT NULL,
    CONTATADAS        INTEGER        NOT NULL,
    PENDENTES         INTEGER        NOT NULL,
    SEM_REFUGIO_800M  INTEGER        NOT NULL,
    CONSTRAINT PK_TMC_SIMULACAO_RESULTADO PRIMARY KEY (ID_SIMULACAO, DIA, CODIGO_SETOR),
    CONSTRAINT FK_TMC_SIM_RES_DIA FOREIGN KEY (ID_SIMULACAO, DIA) REFERENCES TMC_SIMULACAO_DIA (ID_SIMULACAO, DIA) ON DELETE CASCADE,
    CONSTRAINT FK_TMC_SIM_RES_SETOR FOREIGN KEY (CODIGO_SETOR) REFERENCES TMC_SETOR (CODIGO)
);

CREATE INDEX IX_TMC_SIM_RES_SETOR ON TMC_SIMULACAO_RESULTADO (CODIGO_SETOR);
COMMENT ON TABLE TMC_SIMULACAO_RESULTADO IS 'Resultado da simulacao por dia e por setor censitario';
