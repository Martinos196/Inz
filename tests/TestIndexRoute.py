import unittest
from unittest.mock import patch
from Inz.wykres import app  # Załóżmy, że aplikacja jest w pliku myapp.py


class TestIndexRoute(unittest.TestCase):

    @patch('Inz.wykres.connect_db')  # Mockowanie funkcji connect_db
    def test_index_route(self, mock_connect_db):
        # Zamockowanie funkcji connect_db, by nie wykonywała rzeczywistego połączenia z bazą danych
        mock_connect_db.return_value = None

        # Mockowanie zmiennej DATABASE_NAME, aby testować różne przypadki
        with patch('Inz.wykres.DATABASE_NAME', 'test_db'):
            # Symulowanie żądania GET do aplikacji
            with app.test_client() as client:
                response = client.get('/')  # Wysłanie zapytania GET na stronę główną

            # Sprawdzanie, czy odpowiedź ma kod statusu 200 (OK)
            self.assertEqual(response.status_code, 200)

            # Sprawdzanie, czy odpowiedź zawiera oczekiwany komunikat z nazwą bazy danych
            self.assertIn("Obecnie używana baza danych: test_db", response.data.decode())

        # Testowanie przypadku, gdy DATABASE_NAME jest pusty
        with patch('Inz.wykres.DATABASE_NAME', None):
            with app.test_client() as client:
                response = client.get('/')  # Wysłanie zapytania GET na stronę główną

            # Sprawdzamy, czy odpowiedź zawiera komunikat o braku przypisanej bazy danych
            self.assertEqual(response.status_code, 200)
            self.assertIn("Baza danych nie jest przypisana", response.data.decode())
