import unittest
from unittest.mock import patch, MagicMock
from flask import session, url_for
from cryptography.fernet import Fernet
from psycopg2 import OperationalError
from Inz.wykres import connect_db, app
key = Fernet.generate_key()
cipher = Fernet(key)


class TestDatabaseConnection(unittest.TestCase):
    def setUp(self):
        # Tworzymy testową aplikację Flask
        self.app = app
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
        self.client = self.app.test_client()

        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.app.config['SESSION_COOKIE_HTTPONLY'] = False
        self.app.config['SESSION_COOKIE_SAMESITE'] = None

    @patch("psycopg2.connect")
    @patch("Inz.wykres.cipher.decrypt", return_value=b"test_password")
    def test_connect_db_encrypt(self, mock_decrypt, mock_connect):
        with self.app.test_request_context():
            session['db_name'] = "test_db"
            session['db_user'] = "test_user"
            # Symulujemy szyfrowanie hasła, jak w rzeczywistej aplikacji
            session['db_password'] = cipher.encrypt(b"test_password").decode()
            session['db_host'] = "localhost"
            session['db_port'] = "5432"

            mock_connection = MagicMock()
            mock_connect.return_value = mock_connection

            conn = connect_db()

            # Sprawdzamy, czy połączenie zostało wykonane z odpowiednimi parametrami
            self.assertEqual(conn, mock_connection)
            mock_connect.assert_called_once_with(
                dbname=session['db_name'],
                user=session['db_user'],
                password=cipher.decrypt(session['db_password'].encode()).decode(),  # Hasło, które zostało odszyfrowane
                host=session['db_host'],
                port=session['db_port']
            )

    def test_connect_failure(self):
        with self.app.test_request_context():
            session.clear()  # Brak wymaganych kluczy w sesji
            response = connect_db()

            # Sprawdzamy, czy przekierowanie nastąpiło do strony 'index'
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, url_for('index', _external=False))

    @patch("Inz.wykres.psycopg2.connect")
    def test_connect_db_success(self, mock_connect):
        # Mockujemy błąd przy połączeniu

        with self.app.app_context():
            response = self.client.post('/connect', data={
                'db_name': 'test_db',
                'db_user': 'test_user',
                'db_password': 'test_password',
                'db_host': 'localhost',
                'db_port': '5432',

            })
            self.assertEqual(response.status_code, 200)

            response_json = response.get_json()
            self.assertIn("Połączenie z bazą danych powiodło się!", response_json["message"])

            mock_connect.assert_called_once()

    @patch("Inz.wykres.psycopg2.connect")
    def test_connect_db_failure(self, mock_connect):
        # Mockujemy błąd przy połączeniu
        mock_connect.side_effect = OperationalError("Database connection failed")
        with self.app.app_context():
            response = self.client.post('/connect', data={
                'db_name': 'test_db',
                'db_user': 'test_user',
                'db_password': 'test_password',
                'db_host': 'localhost',
                'db_port': '5432',

            })
            self.assertEqual(response.status_code, 200)

            response_json = response.get_json()
            self.assertIn("Nie udało się połączyć z bazą danych!", response_json["message"])

            mock_connect.assert_called_once()

    @patch("Inz.wykres.psycopg2.connect")
    def test_missing_parameters(self, mock_connect):
        # Mockujemy błąd przy połączeniu

        with self.app.app_context():
            response = self.client.post('/connect', data={
                'db_name': 'test_db',
                'db_user': 'test_user',
                'db_password': 'test_password',
            })
            self.assertEqual(response.status_code, 200)

            response_json = response.get_json()
            self.assertIn("Połączenie z bazą danych powiodło się!", response_json["message"])

            mock_connect.assert_called_once()
