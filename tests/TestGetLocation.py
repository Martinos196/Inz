import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import json
from Inz.wykres import app


class TestGetLocationEndpoint(unittest.TestCase):
    def setUp(self):
        # Konfigurujemy testową instancję aplikacji Flask
        app.config['TESTING'] = True
        self.client = app.test_client()

    @patch('Inz.wykres.reverse_format_section')
    @patch('Inz.wykres.pd.ExcelFile')
    def test_missing_section_number(self, mock_excel_file, mock_reverse_format):
        """Test, gdy nie podano parametru section_number."""
        response = self.client.get('/get_location')
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
        self.assertEqual(data['error'], 'Nie podano numeru MR')

    @patch('Inz.wykres.reverse_format_section')
    @patch('Inz.wykres.pd.ExcelFile')
    def test_reverse_format_error(self, mock_excel_file, mock_reverse_format):
        """Test, gdy funkcja reverse_format_section zwraca błąd."""
        # Ustawiamy, że reverse_format_section zwraca błąd
        mock_reverse_format.return_value = (None, 'Błąd formatu')
        response = self.client.get('/get_location?section_number=145 (A1, km 300+430, Skoszewy)')
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
        self.assertEqual(data['error'], 'Błąd formatu')

    @patch('Inz.wykres.reverse_format_section')
    @patch('Inz.wykres.pd.read_excel')
    @patch('Inz.wykres.pd.ExcelFile')
    def test_location_found(self, mock_excel_file, mock_read_excel, mock_reverse_format):
        """Test, gdy lokalizacja zostanie znaleziona."""
        # Ustawiamy, że reverse_format_section zwraca przetworzony numer
        mock_reverse_format.return_value = ("145", None)

        # Przygotowujemy przykładowy DataFrame symulujący dane z arkusza
        df_found = pd.DataFrame({
            'id_mr': ['145'],
            'n_wgs84': [52.2297],
            'e_wgs84': [21.0122]
        })
        # Upewniamy się, że pd.read_excel zawsze zwraca nasz przykładowy DataFrame
        mock_read_excel.return_value = df_found

        # Tworzymy fałszywy obiekt ExcelFile z jedną nazwą arkusza
        fake_excel = MagicMock()
        fake_excel.sheet_names = ['Sheet1']
        mock_excel_file.return_value = fake_excel

        response = self.client.get('/get_location?section_number=145 (A1, km 300+430, Skoszewy)')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        # Sprawdzamy, czy zwrócone współrzędne są zgodne z naszymi danymi
        self.assertIn('N_wgs84', data)
        self.assertIn('E_wgs84', data)
        self.assertEqual(data['N_wgs84'], 52.2297)
        self.assertEqual(data['E_wgs84'], 21.0122)

    @patch('Inz.wykres.reverse_format_section')
    @patch('Inz.wykres.pd.read_excel')
    @patch('Inz.wykres.pd.ExcelFile')
    def test_location_not_found(self, mock_excel_file, mock_read_excel, mock_reverse_format):
        """Test, gdy lokalizacja dla podanego numeru MR nie zostanie znaleziona."""
        # Ustawiamy, że reverse_format_section zwraca numer, którego nie ma w danych
        mock_reverse_format.return_value = ("999", None)

        # Przygotowujemy DataFrame, w którym nie ma rekordu dla numeru "999"
        df_no_match = pd.DataFrame({
            'id_mr': ['145'],
            'n_wgs84': [52.2297],
            'e_wgs84': [21.0122]
        })
        mock_read_excel.return_value = df_no_match

        fake_excel = MagicMock()
        fake_excel.sheet_names = ['Sheet1']
        mock_excel_file.return_value = fake_excel

        response = self.client.get('/get_location?section_number=999 (A1, km 300+430, Skoszewy)')
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.data)
        self.assertIn('error', data)
        self.assertEqual(data['error'], 'Nie znaleziono lokalizacji dla podanego numeru MR')
