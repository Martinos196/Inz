import unittest
import os
import pandas as pd
from unittest.mock import patch, MagicMock
import psycopg2
from Inz.wykres import process_data, fetch_data_from_db, get_sections, reverse_format_section, resource_path_mr_number_info, BASE_DIR, app


class PlotRouteTestCase(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
        self.client = self.app.test_client()

    def test_no_database_assigned(self):
        """Test braku przypisanej bazy danych"""
        response = self.client.post('/plot', data={})
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn("error", json_data)
        self.assertEqual(json_data["error"], "Brak przypisanej bazy danych. Proszę przypisać bazę danych przed wygenerowaniem wykresu.")

    def test_invalid_date_format(self):
        """Test nieprawidłowego formatu daty"""
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        response = self.client.post('/plot', data={
            'start_date_1': '2023-13-01',  # Nieprawidłowy miesiąc
            'end_date_1': '2023-12-31',
            'car_type': 'both'
        })
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn("error", json_data)
        self.assertEqual(json_data["error"], "Nieprawidłowy format daty. Użyj formatu RRRR-MM-DD.")

    @patch('Inz.wykres.fetch_data_from_db', return_value=(None, None))
    def test_no_data_found(self, mock_fetch_data):
        """Test przypadku, gdy brak danych w bazie"""
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        response = self.client.post('/plot', data={
            'start_date_1': '2023-01-01',
            'end_date_1': '2023-12-31',
            'car_type': 'both'
        })
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn("error", json_data)
        self.assertEqual(json_data["error"], "Brak danych do wyświetlenia.")

    @patch('Inz.wykres.fetch_data_from_db', return_value=(pd.DataFrame(), None))
    @patch('Inz.wykres.process_data', return_value=(None, "Błąd testowy"))
    def test_processing_error(self, mock_process_data, mock_fetch_data):
        """Test obsługi błędów przetwarzania danych"""

        mock_df1 = pd.DataFrame({
            'Czas': ['2023-01-01 08:00:00', '2023-01-01 09:00:00'],
            'Liczba samochodów': [50, 60]
        })
        mock_df1['Czas'] = pd.to_datetime(mock_df1['Czas'])
        mock_df1 = mock_df1.set_index('Czas')

        # Symulacja błędów w przetwarzaniu danych
        mock_fetch_data.return_value = (mock_df1, None)
        mock_process_data.return_value = (mock_df1, "Błąd przetwarzania danych")

        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        response = self.client.post('/plot', data={
            'start_date_1': '2023-01-01',
            'end_date_1': '2023-12-31',
            'car_type': 'both',
            'day_of_week': 'Monday'
        })

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn("error", json_data)
        self.assertEqual(json_data["error"], "Błąd przetwarzania danych: Błąd przetwarzania danych")

    @patch('Inz.wykres.fetch_data_from_db')
    @patch('Inz.wykres.process_data')
    def test_successful_plot(self, mock_process_data, mock_fetch_data):
        """Test poprawnego generowania wykresu"""

        # ✅ Tworzymy poprawny DataFrame z indeksami datetime
        mock_df = pd.DataFrame({
            'Czas': ['2023-01-01 08:00:00', '2023-01-01 09:00:00'],
            'Liczba samochodów': [50, 60]
        })
        mock_df['Czas'] = pd.to_datetime(mock_df['Czas'])  # ✅ Konwersja na datetime
        mock_df = mock_df.set_index('Czas')  # ✅ Ustawienie indeksu jako DatetimeIndex

        mock_fetch_data.return_value = (mock_df, None)
        mock_process_data.return_value = (mock_df, None)

        # Ustawienie sesji
        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        # Wysłanie zapytania
        response = self.client.post('/plot', data={
            'start_date_1': '2023-01-01',
            'end_date_1': '2023-12-31',
            'car_type': 'both'
        })

        # **🟢 Sprawdzamy, czy odpowiedź jest poprawna**
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()

        # **🟢 Sprawdzamy, czy odpowiedź zawiera dane wykresu**
        self.assertIn("chart_data", json_data)
        self.assertIn("csv_data", json_data)

        # **🟢 Sprawdzamy, czy dane wykresu są poprawne**
        self.assertIn("x", json_data["chart_data"])
        self.assertIn("y1", json_data["chart_data"])
        self.assertEqual(len(json_data["chart_data"]["x"]), 2)  # Powinny być 2 wartości
        self.assertEqual(json_data["chart_data"]["y1"], [50, 60])  # Powinny zgadzać się wartości

    @patch('Inz.wykres.fetch_data_from_db')
    @patch('Inz.wykres.process_data')
    def test_df2_hourly_processing(self, mock_process_data, mock_fetch_data):
        """Test przetwarzania df2_hourly"""

        # Mockowanie danych dla df1 i df2
        mock_df1 = pd.DataFrame({
            'Czas': ['2023-01-01 08:00:00', '2023-01-01 09:00:00'],
            'Liczba samochodów': [50, 60]
        })
        mock_df1['Czas'] = pd.to_datetime(mock_df1['Czas'])
        mock_df1 = mock_df1.set_index('Czas')

        mock_df2 = pd.DataFrame({
            'Czas': ['2023-01-01 08:00:00', '2023-01-01 09:00:00'],
            'Liczba samochodów': [30, 40]
        })
        mock_df2['Czas'] = pd.to_datetime(mock_df2['Czas'])
        mock_df2 = mock_df2.set_index('Czas')

        mock_fetch_data.return_value = (mock_df1, None)
        mock_process_data.return_value = (mock_df2, None)

        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        response = self.client.post('/plot', data={
            'start_date_1': '2023-01-01',
            'end_date_1': '2023-12-31',
            'start_date_2': '2023-01-01',
            'end_date_2': '2023-12-31',
            'car_type': 'both'
        })

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn("chart_data", json_data)
        self.assertIn("y2", json_data["chart_data"])

    @patch('Inz.wykres.fetch_data_from_db')
    @patch('Inz.wykres.process_data')
    def test_day_of_week_translation(self, mock_process_data, mock_fetch_data):
        """Test tłumaczenia dnia tygodnia"""

        mock_df1 = pd.DataFrame({
            'Czas': ['2023-01-01 08:00:00', '2023-01-01 09:00:00'],
            'Liczba samochodów': [50, 60]
        })
        mock_df1['Czas'] = pd.to_datetime(mock_df1['Czas'])
        mock_df1 = mock_df1.set_index('Czas')

        mock_fetch_data.return_value = (mock_df1, None)
        mock_process_data.return_value = (mock_df1, None)

        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        response = self.client.post('/plot', data={
            'start_date_1': '2023-01-01',
            'end_date_1': '2023-12-31',
            'car_type': 'both',
            'day_of_week': 'Monday'
        })

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn("chart_data", json_data)
        self.assertIn("labels", json_data["chart_data"])
        self.assertIn("title", json_data["chart_data"]["labels"])

        # Sprawdzamy, czy tytuł zawiera przetłumaczony dzień tygodnia
        self.assertIn("Dzień tygodnia: Poniedziałek", json_data["chart_data"]["labels"]["title"])

    @patch('Inz.wykres.fetch_data_from_db')
    @patch('Inz.wykres.process_data')
    def test_matching_x_axis(self, mock_process_data, mock_fetch_data):
        """Test dopasowania osi X dla df1 i df2"""

        mock_df1 = pd.DataFrame({
            'Czas': ['2023-01-01 08:00:00', '2023-01-01 09:00:00'],
            'Liczba samochodów': [50, 60]
        })
        mock_df1['Czas'] = pd.to_datetime(mock_df1['Czas'])
        mock_df1 = mock_df1.set_index('Czas')

        mock_df2 = pd.DataFrame({
            'Czas': ['2023-01-01 08:00:00', '2023-01-01 09:00:00'],
            'Liczba samochodów': [30, 40]
        })
        mock_df2['Czas'] = pd.to_datetime(mock_df2['Czas'])
        mock_df2 = mock_df2.set_index('Czas')

        mock_fetch_data.return_value = (mock_df1, None)
        mock_process_data.return_value = (mock_df2, None)

        with self.client.session_transaction() as sess:
            sess['db_name'] = 'test_db'

        response = self.client.post('/plot', data={
            'start_date_1': '2023-01-01',
            'end_date_1': '2023-12-31',
            'start_date_2': '2023-01-01',
            'end_date_2': '2023-12-31',
            'car_type': 'both'
        })

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn("chart_data", json_data)
        self.assertIn("y2", json_data["chart_data"])
        self.assertTrue(json_data["chart_data"]["y2"])  # Sprawdzamy, czy y2 zawiera dane



class TestProcessDataPlot(unittest.TestCase):

    def setUp(self):
        # Przygotowanie przykładowych danych
        self.valid_data = {
            'data_15min': ['2025-01-20 12:00:00', '2025-01-20 12:15:00', '2025-01-20 13:00:00'],
            'liczba_samochodow_h_pas_1': [5, 6, 7],
            'liczba_samochodow_h_pas_2': [3, 4, 5],
            'liczba_samochodow_l_pas_1': [1, 2, 5],
            'liczba_samochodow_l_pas_2': [1, 2, 5],
            'liczba_na_pasie_1': [6, 8, 12],
            'liczba_na_pasie_2': [4, 6, 10],
        }

        self.df_valid = pd.DataFrame(self.valid_data)
        self.df_valid['data_15min'] = pd.to_datetime(self.df_valid['data_15min'])

    def test_process_data_H(self):
        # Sprawdzamy, czy liczba samochodów jest poprawnie sumowana dla typu 'H'
        df_processed, error = process_data(self.df_valid, 'H')

        self.assertIsNone(error)
        self.assertTrue('Liczba samochodów' in df_processed.columns)
        self.assertEqual(df_processed['Liczba samochodów'].iloc[0], 18)  # 5+3+6+4
        self.assertEqual(df_processed['Liczba samochodów'].iloc[1], 12)  # 7+5

    def test_process_data_L(self):
        # Sprawdzamy, czy liczba samochodów jest poprawnie sumowana dla typu 'L'
        df_processed, error = process_data(self.df_valid, 'L')

        self.assertIsNone(error)
        self.assertTrue('Liczba samochodów' in df_processed.columns)
        self.assertEqual(df_processed['Liczba samochodów'].iloc[0], 6)  # 1+2+1+2
        self.assertEqual(df_processed['Liczba samochodów'].iloc[1], 10)  # 5+5

    def test_process_data_both(self):
        # Sprawdzamy, czy liczba samochodów jest poprawnie sumowana dla obu typów
        df_processed, error = process_data(self.df_valid, 'oba')

        self.assertIsNone(error)
        self.assertTrue('Liczba samochodów' in df_processed.columns)
        self.assertEqual(df_processed['Liczba samochodów'].iloc[0], 24)  # 6+4+8+6
        self.assertEqual(df_processed['Liczba samochodów'].iloc[1], 22)  # 12+10

    def test_process_data_with_day_of_week(self):
        # Sprawdzamy, czy filtracja po dniu tygodnia działa poprawnie
        df_processed, error = process_data(self.df_valid, 'H', day_of_week='Monday')

        self.assertIsNone(error)
        self.assertEqual(len(df_processed), 2)
        df_processed, error = process_data(self.df_valid, 'H', day_of_week='Sunday')

        self.assertIsNone(error)
        self.assertEqual(len(df_processed), 0)  # Brak danych na niedzielę

    def test_process_data_invalid_data(self):
        # Testujemy, co się stanie, gdy dane wejściowe są nieprawidłowe (np. NaT w 'data_15min')
        df_invalid = self.df_valid.copy()
        df_invalid['data_15min'] = pd.to_datetime(['invalid', '2025-01-20 12:15:00', '2025-01-20 13:00:00'],
                                                  errors='coerce')

        df_processed, error = process_data(df_invalid, 'H')

        self.assertIsNone(error)
        self.assertEqual(len(df_processed), 2)  # Powinna pozostać tylko jedna poprawna wartość

    def test_process_data_empty_df(self):
        # Testujemy, co się stanie, gdy DataFrame jest pusty
        df_empty = pd.DataFrame(columns=self.df_valid.columns)

        df_processed, error = process_data(df_empty, 'H')

        self.assertIsNone(error)
        self.assertEqual(len(df_processed), 0)  # Wynikowy DataFrame powinien być pusty

    def test_process_data_non_numeric(self):
        # Przygotowanie danych z błędnymi wartościami (np. tekstami w kolumnach, które powinny być liczbami)
        df_invalid = self.df_valid.copy()
        df_invalid['liczba_samochodow_h_pas_1'] = ['a', 'b', 'c']

        # Wywołanie funkcji z niepoprawnymi danymi
        df_processed, error = process_data(df_invalid, 'H')

        # Sprawdzamy, czy został zwrócony komunikat o błędzie
        self.assertIsNone(df_processed)  # Oczekujemy None, ponieważ wystąpił błąd
        self.assertIsInstance(error, str)  # Oczekujemy, że error to string
        self.assertIn('can only concatenate str (not "int") to str', error)  # Błąd związany z niepoprawnymi danymi


class TestFetchDataFromDB(unittest.TestCase):

    @patch("Inz.wykres.connect_db")
    @patch("Inz.wykres.pd.read_sql_query")
    def test_fetch_data_from_db_success(self, mock_read_sql, mock_connect_db):
        # Przygotowanie fałszywego połączenia i DataFrame'a
        mock_conn = MagicMock()
        mock_connect_db.return_value = mock_conn

        df_fake = pd.DataFrame({
            "data_15min": ["2025-01-01 00:00:00"],
            "numer_odcinka": ["section1"]
        })
        mock_read_sql.return_value = df_fake

        # Wywołanie funkcji z podaniem warunków
        df, error = fetch_data_from_db(start_date="2025-01-01",
                                       end_date="2025-01-02",
                                       section_number="section1")

        # Weryfikacja, czy zapytanie SQL zawiera oczekiwane warunki
        args, _ = mock_read_sql.call_args
        query_arg = args[0]
        self.assertIn("data_15min BETWEEN '2025-01-01 00:00:00' AND '2025-01-02 23:59:59'", query_arg)
        self.assertIn("numer_odcinka = 'section1'", query_arg)
        self.assertIn("ORDER BY data_15min", query_arg)

        self.assertIsNone(error)
        self.assertTrue(df.equals(df_fake))
        # Sprawdzamy, czy połączenie zostało zamknięte
        mock_conn.close.assert_called_once()

    @patch("Inz.wykres.connect_db")
    def test_fetch_data_from_db_connection_error(self, mock_connect_db):
        # Symulacja błędu połączenia (psycopg2.Error)
        mock_connect_db.side_effect = psycopg2.Error("Connection failed")
        df, error = fetch_data_from_db()
        self.assertIsNone(df)
        self.assertEqual(error, "Connection failed")

    @patch("Inz.wykres.connect_db")
    @patch("Inz.wykres.pd.read_sql_query")
    def test_fetch_data_from_db_sql_error(self, mock_read_sql, mock_connect_db):
        # Przygotowanie fałszywego połączenia
        mock_conn = MagicMock()
        mock_connect_db.return_value = mock_conn
        # Wymuszenie błędu podczas wykonywania zapytania SQL
        mock_read_sql.side_effect = pd.io.sql.DatabaseError("SQL error occurred")
        df, error = fetch_data_from_db()
        self.assertIsNone(df)
        self.assertEqual(error, "SQL error occurred")
        # Sprawdzamy, czy połączenie zostało zamknięte
        mock_conn.close.assert_called_once()


class TestGetSections(unittest.TestCase):

    @patch("Inz.wykres.os.path.isfile")
    def test_get_sections_file_not_exists(self, mock_isfile):
        mock_isfile.return_value = False
        sections, error = get_sections("dummy.xlsx")
        self.assertIsNone(sections)
        self.assertIn("Excel file does not exist", error)

    @patch("Inz.wykres.connect_db")
    @patch("Inz.wykres.pd.read_sql_query")
    @patch("Inz.wykres.pd.ExcelFile")
    @patch("Inz.wykres.os.path.isfile")
    def test_get_sections_missing_id_mr(self, mock_isfile, mock_excelfile, mock_read_sql, mock_connect_db):
        # Plik istnieje
        mock_isfile.return_value = True

        # Symulacja zapytania do bazy zwracającego kolumnę numer_odcinka
        df_db = pd.DataFrame({"numer_odcinka": ["section1", "section2"]})
        mock_read_sql.return_value = df_db
        mock_conn = MagicMock()
        mock_connect_db.return_value = mock_conn

        # Symulacja pliku Excel – arkusz nie zawiera kolumny 'ID_MR'
        fake_excel = MagicMock()
        fake_excel.sheet_names = ["Sheet1"]
        mock_excelfile.return_value = fake_excel

        with patch("Inz.wykres.pd.read_excel", return_value=pd.DataFrame({"OtherColumn": [1, 2]})):
            sections, error = get_sections("dummy.xlsx")
            self.assertIsNone(sections)
            self.assertIn("Column 'ID_MR' not found", error)

    @patch("Inz.wykres.connect_db")
    @patch("Inz.wykres.pd.read_sql_query")
    @patch("Inz.wykres.pd.ExcelFile")
    @patch("Inz.wykres.os.path.isfile")
    def test_get_sections_success(self, mock_isfile, mock_excelfile, mock_read_sql, mock_connect_db):
        mock_isfile.return_value = True

        # Symulacja zwróconych sekcji z bazy danych
        df_db = pd.DataFrame({"numer_odcinka": ["section_001", "section_002"]})
        mock_read_sql.return_value = df_db
        mock_conn = MagicMock()
        mock_connect_db.return_value = mock_conn

        # Przygotowanie fałszywego pliku Excel zawierającego arkusz z danymi
        fake_excel = MagicMock()
        fake_excel.sheet_names = ["Sheet1"]
        mock_excelfile.return_value = fake_excel

        # DataFrame zawierający wymagane kolumny
        df_excel = pd.DataFrame({
            "ID_MR": ["section_001", "section_002"],
            "droga": ["road1", "road2"],
            "pikieta": ["10", "20"],
            "lokalizacja": ["loc1", "loc2"]
        })
        with patch("Inz.wykres.pd.read_excel", return_value=df_excel):
            sections, error = get_sections("dummy.xlsx")
            self.assertIsNone(error)
            # Dla "section_001" spodziewamy się formatu "001 (road1, km 10, loc1)"
            expected_section1 = "001 (road1, km 10, loc1)"
            expected_section2 = "002 (road2, km 20, loc2)"
            self.assertIn(expected_section1, sections)
            self.assertIn(expected_section2, sections)

    @patch("Inz.wykres.os.path.isfile")
    @patch("Inz.wykres.connect_db")
    def test_get_sections_outer_exception(self, mock_connect_db, mock_isfile):
        # Test symulujący wyjątek w zewnętrznym bloku try (np. przy łączeniu z bazą)
        mock_isfile.return_value = True
        mock_connect_db.side_effect = Exception("DB connection failed")
        sections, error = get_sections("dummy.xlsx")
        self.assertIsNone(sections)
        self.assertEqual(error, "DB connection failed")

    @patch("Inz.wykres.os.path.isfile")
    @patch("Inz.wykres.pd.ExcelFile")
    @patch("Inz.wykres.connect_db")
    @patch("Inz.wykres.pd.read_sql_query")
    def test_get_sections_excel_read_error(self, mock_read_sql, mock_connect_db, mock_excelfile, mock_isfile):
        # Symulujemy, że plik istnieje
        mock_isfile.return_value = True

        # Przygotowujemy zwracane dane z bazy
        df_db = pd.DataFrame({"numer_odcinka": ["section1"]})
        mock_read_sql.return_value = df_db
        mock_conn = MagicMock()
        mock_connect_db.return_value = mock_conn

        # Wymuszamy wyjątek przy próbie utworzenia obiektu ExcelFile
        mock_excelfile.side_effect = Exception("Test Excel error")

        sections, error = get_sections("dummy.xlsx")
        self.assertIsNone(sections)
        self.assertEqual(error, "Error reading Excel file: Test Excel error")


class TestReverseFormatSection(unittest.TestCase):

    @patch("Inz.wykres.os.path.isfile")
    def test_reverse_format_section_file_not_exists(self, mock_isfile):
        mock_isfile.return_value = False
        id_mr, error = reverse_format_section("dummy.xlsx", "123 (road, km 10, loc)")
        self.assertIsNone(id_mr)
        self.assertIn("Excel file does not exist", error)

    @patch("Inz.wykres.os.path.isfile")
    @patch("Inz.wykres.pd.ExcelFile")
    def test_reverse_format_section_excel_error(self, mock_excelfile, mock_isfile):
        mock_isfile.return_value = True
        # Wymuszenie wyjątku przy otwieraniu pliku Excel
        mock_excelfile.side_effect = Exception("Excel read error")
        id_mr, error = reverse_format_section("dummy.xlsx", "123 (road, km 10, loc)")
        self.assertIsNone(id_mr)
        self.assertIn("Error reading Excel file", error)

    @patch("Inz.wykres.os.path.isfile")
    @patch("Inz.wykres.pd.ExcelFile")
    def test_reverse_format_section_invalid_format(self, mock_excelfile, mock_isfile):
        mock_isfile.return_value = True
        # Aby funkcja nie przerwała się wcześniej, symulujemy pustą listę arkuszy
        fake_excel = MagicMock()
        fake_excel.sheet_names = []
        mock_excelfile.return_value = fake_excel

        id_mr, error = reverse_format_section("dummy.xlsx", "invalid format string")
        self.assertIsNone(id_mr)
        self.assertEqual(error, "Formatted section does not match expected pattern.")

    @patch("Inz.wykres.os.path.isfile")
    @patch("Inz.wykres.pd.ExcelFile")
    def test_reverse_format_section_no_matching_id(self, mock_excelfile, mock_isfile):
        mock_isfile.return_value = True

        fake_excel = MagicMock()
        fake_excel.sheet_names = ["Sheet1"]
        mock_excelfile.return_value = fake_excel

        # Dane w arkuszu, które nie będą pasowały do wzorca
        df_excel = pd.DataFrame({
            "ID_MR": ["1001"],
            "droga": ["roadX"],
            "pikieta": ["10"],
            "lokalizacja": ["locX"]
        })
        with patch("Inz.wykres.pd.read_excel", return_value=df_excel):
            # Podajemy sformatowany string, który nie odpowiada danym z Excel
            id_mr, error = reverse_format_section("dummy.xlsx", "999 (road, km 10, loc)")
            self.assertIsNone(id_mr)
            self.assertEqual(error, "No matching ID_MR found in the Excel data.")

    @patch("Inz.wykres.os.path.isfile")
    @patch("Inz.wykres.pd.ExcelFile")
    def test_reverse_format_section_success(self, mock_excelfile, mock_isfile):
        mock_isfile.return_value = True

        fake_excel = MagicMock()
        fake_excel.sheet_names = ["Sheet1"]
        mock_excelfile.return_value = fake_excel

        # Przygotowanie arkusza z danymi odpowiadającymi wzorcowi
        df_excel = pd.DataFrame({
            "ID_MR": ["1001"],
            "droga": ["road"],
            "pikieta": ["10"],
            "lokalizacja": ["loc"]
        })
        with patch("Inz.wykres.pd.read_excel", return_value=df_excel):
            # Formatowany string – regex w funkcji wyłuskuje część "001"; ponieważ "1001" kończy się "001", powinno być dopasowanie.
            id_mr, error = reverse_format_section("dummy.xlsx", "001 (road, km 10, loc)")
            self.assertIsNone(error)
            self.assertEqual(id_mr, "1001")

    @patch("Inz.wykres.os.path.isfile")
    @patch("Inz.wykres.pd.ExcelFile")
    def test_reverse_format_section_outer_exception(self, mock_excelfile, mock_isfile):
        # Test dla ostatniego except w reverse_format_section – symulujemy błąd w dalszej części funkcji.
        mock_isfile.return_value = True

        # Przygotowanie poprawnego obiektu Excel, by ominąć wewnętrzny try/except
        fake_excel = MagicMock()
        fake_excel.sheet_names = ["Sheet1"]
        mock_excelfile.return_value = fake_excel

        # Zwracamy poprawny DataFrame przy czytaniu arkusza
        df_excel = pd.DataFrame({
            "ID_MR": ["1001"],
            "droga": ["road"],
            "pikieta": ["10"],
            "lokalizacja": ["loc"]
        })
        with patch("Inz.wykres.pd.read_excel", return_value=df_excel):
            # Patchujemy np. funkcję re.compile tak, aby rzuciła wyjątek podczas przetwarzania sformatowanego stringa.
            with patch("Inz.wykres.re.compile", side_effect=Exception("Regex error")):
                id_mr, error = reverse_format_section("dummy.xlsx", "001 (road, km 10, loc)")
                self.assertIsNone(id_mr)
                self.assertEqual(error, "Regex error")


class TestGetSectionsEndpoint(unittest.TestCase):

    def setUp(self):
        # Konfiguracja testowa Flask
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("Inz.wykres.get_sections")
    @patch("Inz.wykres.resource_path_mr_number_info")
    def test_get_sections_endpoint_success(self, mock_resource_path, mock_get_sections):
        # Symulujemy poprawne działanie get_sections – zwraca listę sekcji i None jako error.
        mock_resource_path.return_value = "dummy.xlsx"
        mock_get_sections.return_value = (["001 (road, km 10, loc)"], None)

        response = self.client.get("/get_sections")
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIsInstance(json_data, list)
        self.assertIn("001 (road, km 10, loc)", json_data)

    @patch("Inz.wykres.get_sections")
    @patch("Inz.wykres.resource_path_mr_number_info")
    def test_get_sections_endpoint_error(self, mock_resource_path, mock_get_sections):
        # Symulujemy sytuację błędną – get_sections zwraca None oraz komunikat błędu.
        mock_resource_path.return_value = "dummy.xlsx"
        mock_get_sections.return_value = (None, "Test error")

        response = self.client.get("/get_sections")
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIsInstance(json_data, dict)
        self.assertIn("error", json_data)
        self.assertEqual(json_data["error"], "Test error")


class TestResourcePathMrNumberInfo(unittest.TestCase):
    def test_resource_path_mr_number_info(self):
        expected_path = os.path.join(BASE_DIR, 'WK_1000_A1M-5000_A2E.xlsx')
        actual_path = resource_path_mr_number_info()
        self.assertEqual(actual_path, expected_path)