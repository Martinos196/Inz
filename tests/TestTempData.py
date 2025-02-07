import unittest
from unittest.mock import patch, MagicMock
import pickle
import pandas as pd
from Inz.wykres import create_temp_data_table, save_data_to_db, get_data_from_db


class TestDatabaseFunctions(unittest.TestCase):

    @patch("Inz.wykres.connect_db")
    def test_create_temp_data_table(self, mock_connect_db):
        # Przygotowanie mocka połączenia i kursora
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Uruchomienie funkcji, która wykonuje zapytania SQL
        create_temp_data_table()

        # Sprawdzenie, czy wśród wywołań execute pojawiło się zapytanie CREATE TABLE
        create_table_called = any(
            "CREATE TABLE IF NOT EXISTS temp_data" in call_arg[0]
            for call_arg in (call[0] for call in mock_cursor.execute.call_args_list)
        )
        self.assertTrue(create_table_called, "CREATE TABLE query was not called")

        # Sprawdzenie, czy zapytanie usuwania przeterminowanych rekordów zostało wykonane
        mock_cursor.execute.assert_any_call(
            "DELETE FROM temp_data WHERE expiration < CURRENT_TIMESTAMP - INTERVAL '5 minutes'"
        )

        # Sprawdzenie, czy commit został wykonany
        mock_conn.commit.assert_called_once()

        # Sprawdzenie, czy kursor oraz połączenie zostały zamknięte
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("Inz.wykres.connect_db")
    def test_save_data_to_db(self, mock_connect_db):
        mock_conn = MagicMock()
        mock_cursor = mock_conn.cursor.return_value
        mock_connect_db.return_value = mock_conn
        mock_cursor.fetchone.return_value = [1]  # ID zwrócone z INSERT

        df = pd.DataFrame({"col1": [1, 2, 3]})
        temp_id = save_data_to_db(df)

        mock_cursor.execute.assert_called_once()
        self.assertEqual(temp_id, 1)
        mock_conn.commit.assert_called()
        mock_cursor.close.assert_called()
        mock_conn.close.assert_called()

    @patch("Inz.wykres.connect_db")
    def test_get_data_from_db(self, mock_connect_db):
        mock_conn = MagicMock()
        mock_cursor = mock_conn.cursor.return_value
        mock_connect_db.return_value = mock_conn
        df = pd.DataFrame({"col1": [1, 2, 3]})
        serialized_df = pickle.dumps(df)
        mock_cursor.fetchone.return_value = [serialized_df]

        result_df = get_data_from_db(1)
        self.assertTrue(result_df.equals(df))

        mock_cursor.execute.assert_called_once_with("SELECT data FROM temp_data WHERE id = %s", (1,))
        mock_cursor.close.assert_called()
        mock_conn.close.assert_called()

    @patch("Inz.wykres.connect_db")
    def test_get_data_from_db_no_row(self, mock_connect_db):
        # Utworzenie symulowanego połączenia oraz kursora
        mock_conn = MagicMock()
        mock_cursor = mock_conn.cursor.return_value
        mock_connect_db.return_value = mock_conn

        # Symulacja sytuacji, gdy zapytanie nie zwraca żadnego wiersza
        mock_cursor.fetchone.return_value = None

        # Wywołanie testowanej funkcji
        result_df = get_data_from_db(1)

        # Sprawdzamy, że funkcja zwraca None, gdy nie ma danych
        self.assertIsNone(result_df)

        # Weryfikacja, czy zapytanie SQL zostało wykonane z odpowiednimi parametrami
        mock_cursor.execute.assert_called_once_with("SELECT data FROM temp_data WHERE id = %s", (1,))
        # Sprawdzamy, czy kursor i połączenie zostały zamknięte
        mock_cursor.close.assert_called()
        mock_conn.close.assert_called()
