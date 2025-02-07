import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import datetime
from Inz.wykres import update_database_with_confirmation  # Załóżmy, że funkcja jest w myapp.py


class TestUpdateDatabaseWithConfirmation(unittest.TestCase):

    @patch('Inz.wykres.connect_db')  # Mockowanie funkcji connect_db
    def test_update_database_with_confirmation_overwrite(self, mock_connect_db):
        # Mockowanie połączenia z bazą danych
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Przygotowanie przykładowych danych
        data = {
            'Data 15min': [datetime(2025, 1, 20, 12, 0)],
            'Numer odcinka': ['12345'],
            'Średnia przestrzeń między pojazdem': [2.5],
            'Liczba samochodów jadąca pod prąd': [5],
            'Liczba na pasie 1': [10],
            'Liczba samochodów H Pas 1': [3],
            'Średnia prędkość H Pas 1': [60],
            'Średnia długość H Pas 1': [450],
            'Liczba samochodów L Pas 1': [4],
            'Średnia prędkość L Pas 1': [55],
            'Średnia długość L Pas 1': [400],
            'Liczba na pasie 2': [12],
            'Liczba samochodów H Pas 2': [6],
            'Średnia prędkość H Pas 2': [70],
            'Średnia długość H Pas 2': [460],
            'Liczba samochodów L Pas 2': [7],
            'Średnia prędkość L Pas 2': [65],
            'Średnia długość L Pas 2': [420]
        }
        df = pd.DataFrame(data)

        # Wywołanie funkcji z overwrite_request=True
        update_database_with_confirmation(df, overwrite_request=True)

        # Sprawdzenie, czy wykonano odpowiednią liczbę zapytań SQL
        self.assertEqual(mock_cursor.execute.call_count, 1)
        # Sprawdzanie, czy zapytanie zawiera "ON CONFLICT" (co oznacza nadpisanie)
        args, kwargs = mock_cursor.execute.call_args
        self.assertIn('ON CONFLICT (data_15min, numer_odcinka) DO UPDATE SET', args[0])

    @patch('Inz.wykres.connect_db')  # Mockowanie funkcji connect_db
    def test_update_database_with_confirmation_no_overwrite(self, mock_connect_db):
        # Mockowanie połączenia z bazą danych
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Przygotowanie przykładowych danych
        data = {
            'Data 15min': [datetime(2025, 1, 20, 12, 0)],
            'Numer odcinka': ['12345'],
            'Średnia przestrzeń między pojazdem': [2.5],
            'Liczba samochodów jadąca pod prąd': [5],
            'Liczba na pasie 1': [10],
            'Liczba samochodów H Pas 1': [3],
            'Średnia prędkość H Pas 1': [60],
            'Średnia długość H Pas 1': [450],
            'Liczba samochodów L Pas 1': [4],
            'Średnia prędkość L Pas 1': [55],
            'Średnia długość L Pas 1': [400],
            'Liczba na pasie 2': [12],
            'Liczba samochodów H Pas 2': [6],
            'Średnia prędkość H Pas 2': [70],
            'Średnia długość H Pas 2': [460],
            'Liczba samochodów L Pas 2': [7],
            'Średnia prędkość L Pas 2': [65],
            'Średnia długość L Pas 2': [420]
        }
        df = pd.DataFrame(data)

        # Wywołanie funkcji z overwrite_request=False
        update_database_with_confirmation(df, overwrite_request=False)

        # Sprawdzenie, czy wykonano odpowiednią liczbę zapytań SQL
        self.assertEqual(mock_cursor.execute.call_count, 1)
        # Sprawdzanie, czy zapytanie zawiera "DO NOTHING" (co oznacza brak nadpisania)
        args, kwargs = mock_cursor.execute.call_args
        self.assertIn('ON CONFLICT (data_15min, numer_odcinka) DO NOTHING', args[0])
