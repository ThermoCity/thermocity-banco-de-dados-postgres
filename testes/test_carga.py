"""Testes da carga que não precisam de banco: DDL, arquivos de dados e consistência entre eles.

Rodar (na raiz):  py -m unittest discover -s testes -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "carga"))

import territorio  # noqa: E402
from conexao import RAIZ, comandos_sql  # noqa: E402

CRIAR = os.path.join(RAIZ, "sql", "01_criar_tabelas.sql")
APAGAR = os.path.join(RAIZ, "sql", "02_apagar_tabelas.sql")


class TestDdl(unittest.TestCase):
    def setUp(self):
        self.comandos = comandos_sql(CRIAR)
        self.texto = "\n".join(self.comandos)

    def test_todas_as_tabelas_tem_prefixo_tmc(self):
        tabelas = re.findall(r"CREATE TABLE (\w+)", self.texto)
        self.assertEqual(len(tabelas), 8)
        self.assertTrue(all(t.startswith("TMC_") for t in tabelas), tabelas)

    def test_chaves_estrangeiras(self):
        fks = set(re.findall(r"CONSTRAINT (FK_\w+) FOREIGN KEY", self.texto))
        self.assertEqual(fks, {"FK_TMC_SERVICO_SETOR", "FK_TMC_CALOR_SETOR_SETOR", "FK_TMC_PESSOA_SETOR",
                               "FK_TMC_PESSOA_UBS", "FK_TMC_NIVEL_LEITURA", "FK_TMC_NIVEL_LIMIAR"})

    def test_tabela_referenciada_e_criada_antes(self):
        criadas = []
        for c in self.comandos:
            m = re.match(r"CREATE TABLE (\w+)", c)
            if m:
                for ref in re.findall(r"REFERENCES (\w+)", c):
                    self.assertIn(ref, criadas, f"{m.group(1)} referencia {ref} antes de ela existir")
                criadas.append(m.group(1))

    def test_nenhum_comando_vazio_nem_com_ponto_e_virgula_sobrando(self):
        for c in self.comandos:
            self.assertTrue(c)
            self.assertFalse(c.rstrip().endswith(";"), c[:60])

    def test_apagar_cobre_todas_as_tabelas(self):
        criadas = set(re.findall(r"CREATE TABLE (\w+)", self.texto))
        apagadas = set(re.findall(r"DROP TABLE (?:IF EXISTS )?(\w+)", "\n".join(comandos_sql(APAGAR))))
        self.assertEqual(criadas, apagadas)

    def test_colunas_dos_csvs_existem_na_ddl(self):
        for tabela in territorio.ORDEM:
            bloco = next(c for c in self.comandos if c.startswith(f"CREATE TABLE {tabela} "))
            colunas, _ = territorio.ler(tabela)
            for col in colunas:
                self.assertRegex(bloco, rf"\n\s+{col}\s", f"{tabela}.{col} não está na DDL")


class TestDadosTerritorio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dados = {t: territorio.ler(t) for t in territorio.ORDEM}

    def test_quantidades(self):
        self.assertEqual(len(self.dados["TMC_SETOR"][1]), 420)
        self.assertEqual(len(self.dados["TMC_SERVICO"][1]), 191)
        self.assertEqual(len(self.dados["TMC_CALOR_SETOR"][1]), 420)

    def test_sem_problemas_de_chave_ou_referencia(self):
        self.assertEqual(territorio.validar(self.dados), [])

    def test_cinco_classes_de_calor_com_84_setores(self):
        colunas, linhas = self.dados["TMC_CALOR_SETOR"]
        i = colunas.index("CLASSE_CALOR")
        for classe in range(1, 6):
            self.assertEqual(sum(1 for l in linhas if l[i] == classe), 84)

    def test_validacao_pega_setor_inexistente(self):
        dados = dict(self.dados)
        colunas, linhas = dados["TMC_CALOR_SETOR"]
        dados["TMC_CALOR_SETOR"] = (colunas, linhas + [("999999999999999",) + linhas[0][1:]])
        self.assertTrue(any("999999999999999" in p for p in territorio.validar(dados)))


if __name__ == "__main__":
    unittest.main()
