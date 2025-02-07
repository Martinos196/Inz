import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import pandas as pd
from io import BytesIO
from datetime import timedelta
from Inz.wykres import load_data, process_data_db, update_database


class TestDataProcessing(unittest.TestCase):
    def setUp(self):
        self.valid_file_name = "114_A_145_2025-01-20_POJAZDY.xlsx"
        self.invalid_file_name = "invalid_file.xlsx"
        self.valid_data = {
            'Id': [1, 2],
            'Data': ['2024-01-01 12:00:00', '2024-01-01 12:15:00'],
            'Kategoria': ['H', 'L'],
            'Pas ruchu': [1, 2],
            'Prędkość': [50, 60],
            'Przestrzeń między poprzedzającym pojazdem w dziesiętnych częściach sekundy': [1, 2],
            'Długość pojazdu w cm': [400, 450],
            'Kierunek pod prąd': [0, 1],
        }
        self.df_valid = pd.DataFrame(self.valid_data)
        self.df_valid['Data'] = pd.to_datetime(self.df_valid['Data'])

    def test_load_data_valid_file_name(self):
        file_mock = BytesIO()
        self.df_valid.to_excel(file_mock, index=False, engine='openpyxl')
        file_mock.seek(0)
        file_mock.filename = self.valid_file_name

        df, error = load_data(file_mock)
        self.assertIsNotNone(df)
        self.assertIsNone(error)

    def test_load_data_invalid_file_name(self):
        file_mock = BytesIO()
        self.df_valid.to_excel(file_mock, index=False, engine='openpyxl')
        file_mock.seek(0)
        file_mock.filename = self.invalid_file_name

        df, error = load_data(file_mock)
        self.assertIsNone(df)
        self.assertIsNotNone(error)
        self.assertIn("Niepoprawny schemat nazwy pliku", error)

    def test_load_data_missing_columns(self):
        file_mock = BytesIO()
        df_invalid = self.df_valid.drop(columns=['Kategoria'])
        df_invalid.to_excel(file_mock, index=False, engine='openpyxl')
        file_mock.seek(0)
        file_mock.filename = self.valid_file_name

        df, error = load_data(file_mock)
        self.assertIsNone(df)
        self.assertIsNotNone(error)
        self.assertIn("Brakujące kolumny", error)

    @patch("Inz.wykres.pd.to_datetime")
    def test_load_data_date_conversion_exception(self, mock_to_datetime):
        # Przygotowanie pliku z poprawną nazwą i danymi
        file_mock = BytesIO()
        self.df_valid.to_excel(file_mock, index=False, engine='openpyxl')
        file_mock.seek(0)
        file_mock.filename = self.valid_file_name

        # Wymuszenie wyjątku podczas konwersji daty
        mock_to_datetime.side_effect = Exception("Test conversion error")

        df, error = load_data(file_mock)

        # W przypadku wyjątku oczekujemy, że funkcja zwróci (None, "Błąd podczas konwersji daty.")
        self.assertIsNone(df)
        self.assertEqual(error, "Błąd podczas konwersji daty.")

    def test_load_data_extra_columns(self):
        df_invalid = self.df_valid.copy()
        df_invalid['Dodatkowa kolumna'] = 'wartość domyślna'
        file_mock = BytesIO()
        df_invalid.to_excel(file_mock, index=False, engine='openpyxl')
        file_mock.seek(0)
        file_mock.filename = self.valid_file_name

        df, error = load_data(file_mock)
        self.assertIsNone(df)
        self.assertIsNotNone(error)
        self.assertIn("Niepotrzebne kolumny", error)

    def test_process_data_db_valid(self):
        self.df_valid["Data 15min"] = self.df_valid["Data"].apply(
            lambda x: x - timedelta(minutes=x.minute % 15, seconds=x.second, microseconds=x.microsecond))
        self.df_valid['Numer odcinka'] = '123_MR'
        df_processed = process_data_db(self.df_valid)
        self.assertIsInstance(df_processed, pd.DataFrame)
        self.assertFalse(df_processed.empty)
        self.assertIn("Liczba na pasie 1", df_processed.columns)
        self.assertIn("Średnia prędkość H Pas 1", df_processed.columns)

    def test_process_data_db_empty_dataframe(self):
        df_empty = pd.DataFrame()
        with self.assertRaises(ValueError) as context:
            process_data_db(df_empty)
        self.assertEqual(str(context.exception), "DataFrame jest pusty.")

    def test_process_data_db_invalid_type(self):
        with self.assertRaises(ValueError) as context:
            process_data_db("invalid input")
        self.assertEqual(str(context.exception), "Oczekiwano obiektu DataFrame.")

    @patch("Inz.wykres.connect_db")
    @patch("Inz.wykres.connect")
    def test_update_database_existing_record(self, mock_cursor, mock_connect_db):
        # Mocking database connection and cursor
        mock_conn = MagicMock()
        mock_cursor.return_value = mock_conn.cursor.return_value
        mock_cursor.return_value.fetchone.return_value = {'data_15min': '2025-01-30 12:00:00', 'numer_odcinka': '12345'}

        df = pd.DataFrame({
            'Data 15min': [datetime(2025, 1, 30, 12, 0)],
            'Numer odcinka': ['12345'],
            'Średnia przestrzeń między pojazdem': [1.5]
        })

        existing_records = update_database(df)

        # Ensure existing_records is True since the record exists
        self.assertTrue(existing_records)
