import unittest
from unittest.mock import patch, MagicMock
from io import BytesIO
from Inz.wykres import app


class UploadTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
        self.client = self.app.test_client()

        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.app.config['SESSION_COOKIE_HTTPONLY'] = False
        self.app.config['SESSION_COOKIE_SAMESITE'] = None

    @patch('Inz.wykres.load_data')
    @patch('Inz.wykres.process_data_db')
    @patch('Inz.wykres.update_database')
    @patch('Inz.wykres.update_database_with_confirmation')
    def test_upload_success(self, mock_update_db_with_confirmation, mock_update_db, mock_process_data, mock_load_data):
        """Test poprawnego przesłania pliku i aktualizacji bazy"""
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        mock_load_data.return_value = (MagicMock(), None)
        mock_process_data.return_value = MagicMock()
        mock_update_db.return_value = False  # Brak istniejących rekordów

        data = {
            'file': (BytesIO(b'file_data'), 'file.xlsx')
        }

        response = self.client.post('/upload', data=data, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn('success', json_data)
        self.assertTrue(json_data['success'])

    def test_upload_missing_file(self):
        """Test przesłania bez pliku - powinien zwrócić błąd"""
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        response = self.client.post('/upload', data={}, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)  # Flask zwraca 200, ale z błędem w JSON
        json_data = response.get_json()
        self.assertIn('error', json_data)
        self.assertEqual(json_data['error'], "Nieprawidłowe dane wejściowe")

    def test_upload_missing_db_name(self):
        """Test przesłania pliku bez ustawionego `db_name` w sesji"""
        data = {
            'file': (BytesIO(b'file_data'), 'file.xlsx')
        }

        response = self.client.post('/upload', data=data, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn('error', json_data)
        self.assertEqual(json_data['error'],
                         "Brak przypisanej bazy danych. Proszę przypisać bazę danych przed przesłaniem pliku Excel.")

    @patch('Inz.wykres.load_data')
    def test_upload_processing_error(self, mock_load_data):
        """Test sytuacji, gdy przetwarzanie pliku kończy się błędem"""
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        mock_load_data.return_value = (None, "Błąd wczytywania pliku")

        data = {
            'file': (BytesIO(b'file_data'), 'file.xlsx')
        }

        response = self.client.post('/upload', data=data, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn('error', json_data)
        self.assertEqual(json_data['error'], "Błąd wczytywania pliku")

    @patch('Inz.wykres.load_data')
    @patch('Inz.wykres.process_data_db')
    @patch('Inz.wykres.update_database')
    @patch('Inz.wykres.create_temp_data_table')
    @patch('Inz.wykres.save_data_to_db')
    def test_upload_existing_records(self, mock_save_data, mock_create_table, mock_update_db, mock_process_data,
                                     mock_load_data):
        """Test gdy w bazie istnieją już rekordy i wymagane jest potwierdzenie"""
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        mock_load_data.return_value = (MagicMock(), None)
        mock_process_data.return_value = MagicMock()
        mock_update_db.return_value = True  # Istniejące rekordy
        mock_save_data.return_value = "temp_id_123"

        data = {
            'file': (BytesIO(b'file_data'), 'file.xlsx')
        }

        response = self.client.post('/upload', data=data, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn('message', json_data)
        self.assertEqual(json_data['message'], "Znaleziono istniejące rekordy. Czy chcesz je nadpisać?")
        self.assertTrue(json_data['requires_confirmation'])
        self.assertEqual(json_data['temp_id'], "temp_id_123")

    @patch('Inz.wykres.load_data')
    @patch('Inz.wykres.process_data_db')
    def test_upload_processing_exception(self, mock_process_data, mock_load_data):
        """Test gdy `process_data_db` rzuca wyjątek i aplikacja zwraca odpowiedni błąd"""
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        mock_load_data.return_value = (MagicMock(), None)
        mock_process_data.side_effect = Exception("Nieoczekiwany błąd przetwarzania danych")

        data = {
            'file': (BytesIO(b'file_data'), 'file.xlsx')
        }

        response = self.client.post('/upload', data=data, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)  # Flask zwraca 200, ale z błędem w JSON
        json_data = response.get_json()
        self.assertIn('error', json_data)
        self.assertTrue(json_data['error'].startswith("Błąd podczas przetwarzania danych: Nieoczekiwany błąd"))


class ConfirmOverwriteTestCase(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
        self.client = self.app.test_client()

        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.app.config['SESSION_COOKIE_HTTPONLY'] = False
        self.app.config['SESSION_COOKIE_SAMESITE'] = None

    @patch('Inz.wykres.get_data_from_db')
    @patch('Inz.wykres.update_database_with_confirmation')
    def test_confirm_overwrite_success(self, mock_update_db, mock_get_data):
        """Test poprawnego nadpisania danych w bazie"""
        mock_get_data.return_value = MagicMock()  # Symulujemy istnienie danych w bazie
        mock_update_db.return_value = None  # Brak błędów

        response = self.client.post('/confirm-overwrite', json={"temp_id": "temp_123", "overwrite_request": True})

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn('success', json_data)
        self.assertTrue(json_data['success'])

    @patch('Inz.wykres.get_data_from_db')
    def test_confirm_overwrite_no_data_found(self, mock_get_data):
        """Test gdy `temp_id` nie istnieje w bazie"""
        mock_get_data.return_value = None  # Brak danych w bazie

        response = self.client.post('/confirm-overwrite', json={"temp_id": "temp_123", "overwrite_request": True})

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn('error', json_data)
        self.assertEqual(json_data['error'], "Brak danych do przetworzenia.")

    @patch('Inz.wykres.get_data_from_db')
    @patch('Inz.wykres.update_database_with_confirmation')
    def test_confirm_overwrite_update_error(self, mock_update_db, mock_get_data):
        """Test gdy `update_database_with_confirmation` rzuca wyjątek"""
        mock_get_data.return_value = MagicMock()
        mock_update_db.side_effect = Exception("Błąd bazy danych")

        response = self.client.post('/confirm-overwrite', json={"temp_id": "temp_123", "overwrite_request": True})
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn('error', json_data)
        self.assertTrue(json_data['error'].startswith("Błąd podczas aktualizacji danych: Błąd bazy danych"))


class DisconnectDBTestCase(unittest.TestCase):

    def setUp(self):
        """Konfiguracja testowego klienta aplikacji"""
        self.app = app
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
        self.client = self.app.test_client()

    def test_disconnect_success(self):
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'  # Symulujemy aktywne połączenie

        response = self.client.post('/disconnect_db')

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(json_data['message'], 'Baza danych "test_db" została odłączona.')

    def test_disconnect_no_active_db(self):
        response = self.client.post('/disconnect_db')

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertFalse(json_data['success'])
        self.assertEqual(json_data['message'], 'Nie ma aktywnego połączenia z bazą danych.')
