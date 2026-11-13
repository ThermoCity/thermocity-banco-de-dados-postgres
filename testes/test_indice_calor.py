"""Testes do índice de calor e da classificação NC.

Valores de referência: tabela de índice de calor do NWS/NOAA
(https://www.weather.gov/ama/heatindex), que traz o IC em °F para T (°F) e UR (%).
A tabela é arredondada ao grau inteiro, por isso a tolerância é de 1 °F.

Rodar (na raiz):  py -m unittest discover -s testes -v
"""
import unittest

from analise_niveis_calor import RegraNivel, indice_calor, nivel_para_sequencia


def f_para_c(f):
    return (f - 32) * 5 / 9


def c_para_f(c):
    return c * 9 / 5 + 32


class TestIndiceCalor(unittest.TestCase):
    TOL_F = 1.0

    def _confere(self, temp_f, ur, esperado_f):
        obtido_f = c_para_f(indice_calor(f_para_c(temp_f), ur))
        self.assertAlmostEqual(obtido_f, esperado_f, delta=self.TOL_F,
                               msg=f"T={temp_f}°F UR={ur}%")

    def test_tabela_nws_90f_50(self):
        self._confere(90, 50, 95)    # 32,2 °C / 50% → ~35 °C

    def test_tabela_nws_96f_40(self):
        self._confere(96, 40, 101)   # 35,6 °C / 40% → ~38,3 °C

    def test_tabela_nws_86f_80(self):
        self._confere(86, 80, 100)   # 30 °C / 80% → ~37,8 °C

    def test_abaixo_de_80f_ic_igual_temperatura(self):
        self.assertEqual(indice_calor(25.0, 90.0), 25.0)


class TestClassificacao(unittest.TestCase):
    def setUp(self):
        self.regras = [
            RegraNivel(2, None, 35.0, 1, ""),
            RegraNivel(3, None, 36.0, 1, ""),
            RegraNivel(3, None, 35.0, 3, ""),
            RegraNivel(4, None, 37.0, 1, ""),
            RegraNivel(4, None, 36.0, 3, ""),
            RegraNivel(5, None, 38.5, 1, ""),
            RegraNivel(5, None, 37.0, 3, ""),
        ]

    def nivel(self, seq):
        return nivel_para_sequencia(seq, self.regras)[0]

    def test_dia_ameno_nc1(self):
        self.assertEqual(self.nivel([30.0]), 1)

    def test_um_dia_quente_nc2(self):
        self.assertEqual(self.nivel([30.0, 30.0, 35.5]), 2)

    def test_persistencia_sobe_para_nc3(self):
        self.assertEqual(self.nivel([35.2, 35.4, 35.5]), 3)

    def test_dia_sem_dado_quebra_persistencia(self):
        self.assertEqual(self.nivel([35.2, None, 35.5]), 2)

    def test_onda_de_calor_extrema_nc5(self):
        self.assertEqual(self.nivel([37.2, 37.5, 37.8]), 5)

    def test_pico_isolado_nc5(self):
        self.assertEqual(self.nivel([30.0, 30.0, 39.0]), 5)


if __name__ == "__main__":
    unittest.main()
