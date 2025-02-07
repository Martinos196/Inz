from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_wtf.csrf import CSRFProtect
from cryptography.fernet import Fernet
import pandas as pd
from pandas.io.sql import DatabaseError
import io
import time
import pickle
import csv
import re
import os
import warnings
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
from psycopg2 import OperationalError
from psycopg2.extras import RealDictCursor

warnings.filterwarnings("ignore", category=UserWarning, message="pandas only supports SQLAlchemy connectable")

load_dotenv()

DATABASE_NAME = None

app = Flask(__name__, template_folder='templates')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Klucz tajny aplikacji przechowywany w zmiennej środowiskowej
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'fallback-key')

csrf = CSRFProtect(app)
# Klucz szyfrujący do przechowywania wrażliwych danych
FERNET_KEY = os.getenv('FERNET_KEY', Fernet.generate_key())
cipher = Fernet(FERNET_KEY)


def connect_db():
    """Łączy się z bazą danych za pomocą danych z sesji."""
    global DATABASE_NAME
    if not all(key in session for key in ['db_name', 'db_user', 'db_password', 'db_host', 'db_port']):
        DATABASE_NAME = None
        return redirect(url_for('index'))
    DATABASE_NAME = session['db_name']
    conn = psycopg2.connect(
        dbname=session['db_name'],
        user=session['db_user'],
        password=cipher.decrypt(session['db_password'].encode()).decode(),
        host=session['db_host'],
        port=session['db_port']
    )
    return conn


def create_temp_data_table():
    conn = connect_db()
    cursor = conn.cursor()

    # Zapytanie tworzące tabelę (jeśli jeszcze nie istnieje)
    create_table_query = """
    CREATE TABLE IF NOT EXISTS temp_data (
        id SERIAL PRIMARY KEY,
        data BYTEA,
        expiration TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    cursor.execute(create_table_query)

    # Usuwanie przeterminowanych rekordów
    cursor.execute("DELETE FROM temp_data WHERE expiration < CURRENT_TIMESTAMP - INTERVAL '5 minutes'")
    conn.commit()
    cursor.close()
    conn.close()


def save_data_to_db(processed_df):
    # Serializujemy dane DataFrame
    serialized_df = pickle.dumps(processed_df)

    conn = connect_db()
    cursor = conn.cursor()

    # Wstawiamy dane do tabeli temp_data
    cursor.execute("""
        INSERT INTO temp_data (data, expiration) 
        VALUES (%s, %s) RETURNING id
    """, (serialized_df, datetime.now()))

    conn.commit()

    # Pobieramy ID wstawionego rekordu
    temp_id = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return temp_id


def get_data_from_db(temp_id):
    conn = connect_db()
    cursor = conn.cursor()

    # Pobieramy dane z tabeli temp_data na podstawie temp_id
    cursor.execute("SELECT data FROM temp_data WHERE id = %s", (temp_id,))
    row = cursor.fetchone()

    if row:
        # Deserializujemy dane z formatu binarnego
        processed_df = pickle.loads(row[0])

        conn.commit()

        cursor.close()
        conn.close()

        return processed_df
    else:
        cursor.close()
        conn.close()
        return None


def resource_path_mr_number_info():
    return os.path.join(BASE_DIR, 'WK_1000_A1M-5000_A2E.xlsx')


# Load data from excel file
def load_data(file_name):
    # start_time = time.perf_counter()  # Zapisz czas rozpoczęcia
    file = file_name.filename
    if not re.search(r'_(\d+)_\d{4}-\d{2}-\d{2}_POJAZDY\.(xlsx|csv)$', file):
        return None, "Niepoprawny schemat nazwy pliku. Oczekiwany format to NUMER_MR_RRRR-MM-DD_POJAZDY."
    df = pd.read_excel(file_name, engine='calamine')

    # List of required columns
    required_columns = {'Id', 'Data', 'Kategoria', 'Pas ruchu', 'Prędkość',
                        'Przestrzeń między poprzedzającym pojazdem w dziesiętnych częściach sekundy',
                        'Długość pojazdu w cm', 'Kierunek pod prąd'}

    df_columns = set(df.columns)
    missing_columns = required_columns - df_columns
    extra_columns = df_columns - required_columns

    # Check for the presence of required columns
    if missing_columns:
        return None, f"Brakujące kolumny: {', '.join(missing_columns)}"

    # Check for the presence of additional columns
    if extra_columns:
        return None, f"Niepotrzebne kolumny: {', '.join(extra_columns)}"

    try:
        df["Data"] = pd.to_datetime(df["Data"], format='%Y-%m-%d %H:%M:%S', errors='coerce')
        df["Data"] = df["Data"] + timedelta(hours=1)
    except Exception as e:
        print(f"Błąd podczas konwersji daty: {e}")
        return None, "Błąd podczas konwersji daty."

    df["Data 15min"] = df["Data"].apply(lambda x: x - timedelta(minutes=x.minute % 15, seconds=x.second,
                                                                microseconds=x.microsecond) if pd.notnull(x) else None)
    # Extracting the mr number from the file name
    match = re.search(r'([^\\]+)(?=_\d{4}-\d{2}-\d{2}_POJAZDY\.(xlsx|csv)$)', file)
    odcinek = match.group(1) if match else None
    df['Numer odcinka'] = odcinek
    # end_time = time.perf_counter()  # Zapisz czas zakończenia
    # elapsed_time = end_time - start_time  # Oblicz czas wykonania
    # print(f"Czas wykonania load_data: {elapsed_time:.2f} sekundy")
    return df, None


def process_data_db(df):
    if not isinstance(df, pd.DataFrame):
        raise ValueError("Oczekiwano obiektu DataFrame.")

    if df.empty:
        raise ValueError("DataFrame jest pusty.")

    # Maski dla pasów ruchu i kategorii
    mask_pas_1 = df['Pas ruchu'] == 1
    mask_pas_2 = df['Pas ruchu'] == 2

    mask_h = df['Kategoria'] == 'H'
    mask_l = df['Kategoria'] == 'L'

    # Liczba pojazdów na pasach
    df['Liczba na pasie 1'] = mask_pas_1.astype(int)
    df['Liczba na pasie 2'] = mask_pas_2.astype(int)

    df['Liczba samochodów H Pas 1'] = (mask_pas_1 & mask_h).astype(int)
    df['Średnia prędkość H Pas 1'] = df['Prędkość'].where(mask_pas_1 & mask_h)
    df['Średnia długość H Pas 1'] = df['Długość pojazdu w cm'].where(mask_pas_1 & mask_h)

    df['Liczba samochodów L Pas 1'] = (mask_pas_1 & mask_l).astype(int)
    df['Średnia prędkość L Pas 1'] = df['Prędkość'].where(mask_pas_1 & mask_l)
    df['Średnia długość L Pas 1'] = df['Długość pojazdu w cm'].where(mask_pas_1 & mask_l)

    df['Liczba samochodów H Pas 2'] = (mask_pas_2 & mask_h).astype(int)
    df['Średnia prędkość H Pas 2'] = df['Prędkość'].where(mask_pas_2 & mask_h)
    df['Średnia długość H Pas 2'] = df['Długość pojazdu w cm'].where(mask_pas_2 & mask_h)

    df['Liczba samochodów L Pas 2'] = (mask_pas_2 & mask_l).astype(int)
    df['Średnia prędkość L Pas 2'] = df['Prędkość'].where(mask_pas_2 & mask_l)
    df['Średnia długość L Pas 2'] = df['Długość pojazdu w cm'].where(mask_pas_2 & mask_l)

    aggregated_data = df.groupby(["Data 15min", "Numer odcinka"]).agg({
        "Przestrzeń między poprzedzającym pojazdem w dziesiętnych częściach sekundy": "mean",
        "Kierunek pod prąd": "sum",
        "Liczba na pasie 1": "sum",
        "Liczba samochodów H Pas 1": "sum",
        "Średnia prędkość H Pas 1": "mean",
        "Średnia długość H Pas 1": "mean",
        "Liczba samochodów L Pas 1": "sum",
        "Średnia prędkość L Pas 1": "mean",
        "Średnia długość L Pas 1": "mean",
        "Liczba na pasie 2": "sum",
        "Liczba samochodów H Pas 2": "sum",
        "Średnia prędkość H Pas 2": "mean",
        "Średnia długość H Pas 2": "mean",
        "Liczba samochodów L Pas 2": "sum",
        "Średnia prędkość L Pas 2": "mean",
        "Średnia długość L Pas 2": "mean"
    }).reset_index()

    # Zaokrąglanie tylko wymaganych kolumn
    columns_to_round = [
        "Przestrzeń między poprzedzającym pojazdem w dziesiętnych częściach sekundy",
        "Średnia prędkość H Pas 1", "Średnia długość H Pas 1",
        "Średnia prędkość L Pas 1", "Średnia długość L Pas 1",
        "Średnia prędkość H Pas 2", "Średnia długość H Pas 2",
        "Średnia prędkość L Pas 2", "Średnia długość L Pas 2"
    ]

    aggregated_data[columns_to_round] = aggregated_data[columns_to_round].round(1)
    aggregated_data.columns = [
        "Data 15min", "Numer odcinka", "Średnia przestrzeń między pojazdem", "Liczba samochodów jadąca pod prąd",
        "Liczba na pasie 1", "Liczba samochodów H Pas 1", "Średnia prędkość H Pas 1",
        "Średnia długość H Pas 1", "Liczba samochodów L Pas 1", "Średnia prędkość L Pas 1",
        "Średnia długość L Pas 1", "Liczba na pasie 2", "Liczba samochodów H Pas 2",
        "Średnia prędkość H Pas 2", "Średnia długość H Pas 2", "Liczba samochodów L Pas 2",
        "Średnia prędkość L Pas 2", "Średnia długość L Pas 2"
    ]

    return aggregated_data


# Search if there is existing record to update
def update_database(df):
    conn = connect_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)  # Kursor zwracający słowniki

    # Tworzenie tabeli (jeśli nie istnieje) w PostgreSQL
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pojazdy (
        data_15min TIMESTAMP,
        numer_odcinka TEXT,
        srednia_przestrzen_pomiedzy_pojazdami NUMERIC,
        liczba_samochodow_jadaca_pod_prad INTEGER,
        liczba_na_pasie_1 INTEGER,
        liczba_samochodow_h_pas_1 INTEGER,
        srednia_predkosc_h_pas_1 NUMERIC,
        srednia_dlugosc_h_pas_1 NUMERIC,
        liczba_samochodow_l_pas_1 INTEGER,
        srednia_predkosc_l_pas_1 NUMERIC,
        srednia_dlugosc_l_pas_1 NUMERIC,
        liczba_na_pasie_2 INTEGER,
        liczba_samochodow_h_pas_2 INTEGER,
        srednia_predkosc_h_pas_2 NUMERIC,
        srednia_dlugosc_h_pas_2 NUMERIC,
        liczba_samochodow_l_pas_2 INTEGER,
        srednia_predkosc_l_pas_2 NUMERIC,
        srednia_dlugosc_l_pas_2 NUMERIC,
        PRIMARY KEY (data_15min, numer_odcinka)
    );
    """)

    existing_records = False

    for _, row in df.iterrows():
        # Sprawdzenie, czy rekord już istnieje
        cursor.execute("""
            SELECT * FROM pojazdy WHERE data_15min = %s AND numer_odcinka = %s
        """, (row['Data 15min'].to_pydatetime(), row['Numer odcinka']))

        record = cursor.fetchone()

        # Jeśli rekord istnieje, dodajemy do listy
        if record:
            existing_records = True
            break

    conn.commit()
    cursor.close()
    conn.close()

    return existing_records


def fetch_data_from_db(start_date=None, end_date=None, section_number=None):
    try:
        conn = connect_db()
    except psycopg2.Error as e:
        return None, str(e)

    query = "SELECT * FROM pojazdy"

    conditions = []
    if start_date and end_date:
        conditions.append(f"data_15min BETWEEN '{start_date} 00:00:00' AND '{end_date} 23:59:59'")
    if section_number:
        conditions.append(f"numer_odcinka = '{section_number}'")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY data_15min"

    try:
        df = pd.read_sql_query(query, conn)
    except pd.io.sql.DatabaseError as e:
        conn.close()
        return None, str(e)

    conn.close()
    return df, None


def get_sections(excel_path):
    if not os.path.isfile(excel_path):
        return None, f"Excel file does not exist at {excel_path}"

    try:
        # Connect to the database and fetch the sections
        conn = connect_db()
        query = 'SELECT DISTINCT numer_odcinka FROM pojazdy ORDER BY numer_odcinka'
        df_db = pd.read_sql_query(query, conn)
        conn.close()

        # Read all sheets from the Excel file
        excel_info = {}
        try:
            xls = pd.ExcelFile(excel_path, engine='calamine')
            try:
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(xls, sheet_name=sheet_name)

                    if 'ID_MR' in df.columns:
                        # Normalize column names
                        df.columns = df.columns.str.strip().str.lower()
                        df.rename(columns={
                            'id_mr': 'ID_MR',
                            'pikieta': 'pikietaż'
                        }, inplace=True)

                        # Add data from the current sheet to the excel_info dictionary
                        df_filtered = df[['ID_MR', 'droga', 'pikietaż', 'lokalizacja']].dropna(subset=['ID_MR'])
                        for _, row in df_filtered.iterrows():
                            excel_info[row['ID_MR']] = {
                                'droga': row.get('droga', ''),
                                'pikietaż': row.get('pikietaż', ''),
                                'lokalizacja': row.get('lokalizacja', '')
                            }
            finally:
                xls.close()
        except Exception as e:
            return None, f"Error reading Excel file: {str(e)}"

        if not excel_info:
            return None, "Column 'ID_MR' not found in any sheet of Excel file."

        # Create a list of sections with additional info
        sections_with_info = []
        for section in df_db['numer_odcinka']:
            section_info = excel_info.get(section, {})
            additional_info = (f"{section_info.get('droga', '')}, km {section_info.get('pikietaż', '')}, "
                               f"{section_info.get('lokalizacja')}")
            sections_with_info.append(f"{section.split('_')[-1]} ({additional_info})")

        return sections_with_info, None
    except Exception as e:
        return None, str(e)


def reverse_format_section(excel_path, formatted_section):
    if not os.path.isfile(excel_path):
        return None, f"Excel file does not exist at {excel_path}"

    try:
        # Read all sheets from the Excel file
        excel_info = {}
        try:
            xls = pd.ExcelFile(excel_path, engine='calamine')
            try:
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(xls, sheet_name=sheet_name)

                    if 'ID_MR' in df.columns:
                        # Normalize column names
                        df.columns = df.columns.str.strip().str.lower()
                        df.rename(columns={
                            'id_mr': 'ID_MR',
                            'pikieta': 'pikietaż'
                        }, inplace=True)

                        # Add data from the current sheet to the excel_info dictionary
                        df_filtered = df[['ID_MR', 'droga', 'pikietaż', 'lokalizacja']].dropna(subset=['ID_MR'])
                        for _, row in df_filtered.iterrows():
                            excel_info[str(row['ID_MR']).strip()] = {
                                'droga': str(row.get('droga', '')).strip(),
                                'pikietaż': str(row.get('pikietaż', '')).strip(),
                                'lokalizacja': str(row.get('lokalizacja', '')).strip()
                            }
            finally:
                xls.close()
        except Exception as e:
            return None, f"Error reading Excel file: {str(e)}"

        # Parse the formatted_section string
        pattern = re.compile(r'(\d+)\s*\(([^,]+),\s*km\s*([\d+]+(?:\d*)?),\s*([^)]*)\)')
        match = pattern.match(formatted_section)

        if not match:
            return None, "Formatted section does not match expected pattern."

        # Extract the relevant parts
        id_mr_part = match.group(1).strip()
        droga = match.group(2).strip()
        pikietaz = match.group(3).strip()
        lokalizacja = match.group(4).strip()

        # Check if the part matches any entry
        matching_id_mr = None
        for key, value in excel_info.items():
            if value['droga'] == droga and value['pikietaż'] == pikietaz and value['lokalizacja'] == lokalizacja:

                # Extract last three digits of ID_MR
                if key.endswith(id_mr_part):
                    matching_id_mr = key
                    break

        if matching_id_mr:
            return matching_id_mr, None
        else:
            return None, "No matching ID_MR found in the Excel data."

    except Exception as e:
        return None, str(e)


@app.route('/get_location', methods=['GET'])
def get_location():
    section_number = request.args.get('section_number')
    if not section_number:
        return jsonify({'error': 'Nie podano numeru MR'}), 400

        # Wywołaj reverse_format_section tylko raz
    section_reverse, error = reverse_format_section(resource_path_mr_number_info(), section_number)
    if error:
        return jsonify({'error': error}), 400

    # Wczytaj wszystkie arkusze na raz
    xls = pd.ExcelFile(resource_path_mr_number_info(), engine='calamine')
    try:
        sheets_dict = {sheet: pd.read_excel(xls, sheet_name=sheet) for sheet in xls.sheet_names}
    finally:
        xls.close()

    location_info = None
    for sheet_name, df in sheets_dict.items():
        # Ujednolicenie nazw kolumn
        df.columns = df.columns.str.strip().str.lower()
        # Sprawdzenie, czy wymagane kolumny istnieją
        if 'id_mr' in df.columns and 'n_wgs84' in df.columns and 'e_wgs84' in df.columns:
            df.rename(columns={'id_mr': 'ID_MR'}, inplace=True)
            # Filtracja po numerze MR
            row = df[df['ID_MR'] == section_reverse]
            if not row.empty:
                n_wgs84 = row.iloc[0]['n_wgs84']
                e_wgs84 = row.iloc[0]['e_wgs84']
                location_info = {'N_wgs84': n_wgs84, 'E_wgs84': e_wgs84}
                break

    if location_info:
        return jsonify(location_info)
    else:
        return jsonify({'error': 'Nie znaleziono lokalizacji dla podanego numeru MR'}), 404


@app.route('/get_sections', methods=['GET'])
def get_sections_endpoint():
    sections, error = get_sections(resource_path_mr_number_info())
    if error:
        return jsonify({"error": error})
    return jsonify(sections)


def process_data(df, car_type, day_of_week=None):
    try:
        if car_type == 'H':
            df['Liczba samochodów'] = df['liczba_samochodow_h_pas_1'] + df['liczba_samochodow_h_pas_2']
        elif car_type == 'L':
            df['Liczba samochodów'] = df['liczba_samochodow_l_pas_1'] + df['liczba_samochodow_l_pas_2']
        else:  # oba
            df['Liczba samochodów'] = df['liczba_na_pasie_1'] + df['liczba_na_pasie_2']

        df['data_15min'] = pd.to_datetime(df['data_15min'], errors='coerce')
        df = df.dropna(subset=['data_15min'])
        df.set_index('data_15min', inplace=True)

        df['Liczba samochodów'] = pd.to_numeric(df['Liczba samochodów'], errors='coerce')
        df = df.dropna(subset=['Liczba samochodów'])

        if day_of_week:
            day_of_week_map = {
                'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
                'Friday': 4, 'Saturday': 5, 'Sunday': 6
            }
            day_num = day_of_week_map.get(day_of_week)
            if day_num is not None:
                df = df[df.index.dayofweek == day_num]

        df['Hour'] = df.index.floor('h')
        df_hourly = df.groupby('Hour').sum()

    except Exception as e:
        return None, str(e)

    return df_hourly, None


@app.route('/')
def index():
    connect_db()
    db_message = f"Obecnie używana baza danych: {DATABASE_NAME}" if DATABASE_NAME else "Baza danych nie jest przypisana"
    return render_template('index.html', db_message=db_message)


@app.route('/connect', methods=['POST'])
def connect():
    try:
        # Próbujemy połączyć się z bazą danych
        conn = psycopg2.connect(
            dbname=request.form.get('db_name'),
            user=request.form.get('db_user'),
            password=request.form.get('db_password'),
            host=request.form.get('db_host', 'localhost'),
            port=request.form.get('db_port', '5432')
        )
        conn.close()

        # Zapisujemy dane w sesji
        session['db_name'] = request.form.get('db_name')
        session['db_user'] = request.form.get('db_user')
        session['db_password'] = cipher.encrypt(request.form.get('db_password').encode()).decode()
        session['db_host'] = request.form.get('db_host', 'localhost')
        session['db_port'] = request.form.get('db_port', '5432')

        return jsonify({'success': True, 'message': 'Połączenie z bazą danych powiodło się!'})

    except OperationalError:
        return jsonify({'success': False, 'message': f'Nie udało się połączyć z bazą danych!'})


def update_database_with_confirmation(df, overwrite_request):
    conn = connect_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)  # Wygenerowanie kursorów zwracających słowniki

    for _, row in df.iterrows():
        values = (
            row['Data 15min'].to_pydatetime(), row['Numer odcinka'], row['Średnia przestrzeń między pojazdem'],
            row['Liczba samochodów jadąca pod prąd'], row['Liczba na pasie 1'],
            row['Liczba samochodów H Pas 1'], row['Średnia prędkość H Pas 1'], row['Średnia długość H Pas 1'],
            row['Liczba samochodów L Pas 1'], row['Średnia prędkość L Pas 1'], row['Średnia długość L Pas 1'],
            row['Liczba na pasie 2'], row['Liczba samochodów H Pas 2'], row['Średnia prędkość H Pas 2'],
            row['Średnia długość H Pas 2'], row['Liczba samochodów L Pas 2'], row['Średnia prędkość L Pas 2'],
            row['Średnia długość L Pas 2']
        )

        if overwrite_request:
            cursor.execute("""
            INSERT INTO pojazdy (data_15min, numer_odcinka, srednia_przestrzen_pomiedzy_pojazdami, 
            liczba_samochodow_jadaca_pod_prad, liczba_na_pasie_1, liczba_samochodow_h_pas_1, srednia_predkosc_h_pas_1, 
            srednia_dlugosc_h_pas_1, liczba_samochodow_l_pas_1, srednia_predkosc_l_pas_1, srednia_dlugosc_l_pas_1, 
            liczba_na_pasie_2, liczba_samochodow_h_pas_2, srednia_predkosc_h_pas_2, srednia_dlugosc_h_pas_2, 
            liczba_samochodow_l_pas_2, srednia_predkosc_l_pas_2, srednia_dlugosc_l_pas_2)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (data_15min, numer_odcinka) DO UPDATE SET
            srednia_przestrzen_pomiedzy_pojazdami = EXCLUDED.srednia_przestrzen_pomiedzy_pojazdami,
            liczba_samochodow_jadaca_pod_prad = EXCLUDED.liczba_samochodow_jadaca_pod_prad,
            liczba_na_pasie_1 = EXCLUDED.liczba_na_pasie_1,
            liczba_samochodow_h_pas_1 = EXCLUDED.liczba_samochodow_h_pas_1,
            srednia_predkosc_h_pas_1 = EXCLUDED.srednia_predkosc_h_pas_1,
            srednia_dlugosc_h_pas_1 = EXCLUDED.srednia_dlugosc_h_pas_1,
            liczba_samochodow_l_pas_1 = EXCLUDED.liczba_samochodow_l_pas_1,
            srednia_predkosc_l_pas_1 = EXCLUDED.srednia_predkosc_l_pas_1,
            srednia_dlugosc_l_pas_1 = EXCLUDED.srednia_dlugosc_l_pas_1,
            liczba_na_pasie_2 = EXCLUDED.liczba_na_pasie_2,
            liczba_samochodow_h_pas_2 = EXCLUDED.liczba_samochodow_h_pas_2,
            srednia_predkosc_h_pas_2 = EXCLUDED.srednia_predkosc_h_pas_2,
            srednia_dlugosc_h_pas_2 = EXCLUDED.srednia_dlugosc_h_pas_2,
            liczba_samochodow_l_pas_2 = EXCLUDED.liczba_samochodow_l_pas_2,
            srednia_predkosc_l_pas_2 = EXCLUDED.srednia_predkosc_l_pas_2,
            srednia_dlugosc_l_pas_2 = EXCLUDED.srednia_dlugosc_l_pas_2
            """, values)
        else:
            # Jeśli overwrite_request jest False, to wykonujemy tylko INSERT
            cursor.execute("""
            INSERT INTO pojazdy (data_15min, numer_odcinka, srednia_przestrzen_pomiedzy_pojazdami, 
            liczba_samochodow_jadaca_pod_prad, liczba_na_pasie_1, liczba_samochodow_h_pas_1, srednia_predkosc_h_pas_1, 
            srednia_dlugosc_h_pas_1, liczba_samochodow_l_pas_1, srednia_predkosc_l_pas_1, srednia_dlugosc_l_pas_1, 
            liczba_na_pasie_2, liczba_samochodow_h_pas_2, srednia_predkosc_h_pas_2, srednia_dlugosc_h_pas_2, 
            liczba_samochodow_l_pas_2, srednia_predkosc_l_pas_2, srednia_dlugosc_l_pas_2)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (data_15min, numer_odcinka) DO NOTHING
            """, values)

    conn.commit()
    cursor.close()
    conn.close()


# Upload file from excel or database
@app.route('/upload', methods=['POST'])
def upload():
    if 'db_name' not in session:
        error_message = "Brak przypisanej bazy danych. Proszę przypisać bazę danych przed przesłaniem pliku Excel."
        return jsonify(error=error_message)
    # xlsx or csv file
    if 'file' in request.files:
        file = request.files['file']
        df, error = load_data(file)
        if error:
            return jsonify(error=error)
        try:
            processed_df = process_data_db(df)
        except Exception as e:
            return jsonify(error=f"Błąd podczas przetwarzania danych: {e}")

        # Sprawdzamy, czy istnieją rekordy w bazie danych
        existing_records = update_database(processed_df)
        if existing_records:
            # Sprawdzamy, czy tabela istnieje, jeśli nie, to ją tworzymy
            create_temp_data_table()

            # Zapisujemy dane do bazy
            temp_id = save_data_to_db(processed_df)

            return jsonify({
                "message": "Znaleziono istniejące rekordy. Czy chcesz je nadpisać?",
                "requires_confirmation": True,
                "temp_id": temp_id
            })

        # Jeśli brak istniejących rekordów, wykonujemy aktualizację
        update_database_with_confirmation(processed_df, overwrite_request=False)
        return jsonify(success=True)

    return jsonify(error="Nieprawidłowe dane wejściowe")


@app.route('/confirm-overwrite', methods=['POST'])
def confirm_overwrite():
    temp_id = request.json.get("temp_id")
    overwrite_request = request.json.get("overwrite_request", False)

    # Pobieramy dane z bazy
    processed_df = get_data_from_db(temp_id)

    if processed_df is None:
        return jsonify(error="Brak danych do przetworzenia.")

    # Wykonujemy aktualizację bazy danych
    try:
        update_database_with_confirmation(processed_df, overwrite_request=overwrite_request)
        return jsonify(success=True)
    except Exception as e:
        return jsonify(error=f"Błąd podczas aktualizacji danych: {e}")


@app.route('/disconnect_db', methods=['POST'])
def disconnect():
    if 'db_name' in session:
        db_name = session.pop('db_name', None)
        session.clear()

        return jsonify({'success': True, 'message': f'Baza danych "{db_name}" została odłączona.'})
    else:
        return jsonify({'success': False, 'message': 'Nie ma aktywnego połączenia z bazą danych.'})


@app.route('/plot', methods=['POST'])
def plot():
    if 'db_name' not in session:
        return jsonify(error="Brak przypisanej bazy danych. Proszę przypisać bazę danych przed wygenerowaniem wykresu.")
    start_date_1 = request.form.get('start_date_1')
    end_date_1 = request.form.get('end_date_1')
    start_date_2 = request.form.get('start_date_2')
    end_date_2 = request.form.get('end_date_2')
    car_type = request.form['car_type']
    day_of_week = request.form.get('day_of_week')
    section_number = request.form.get('section_number')

    days_of_week_translation = {
        'Monday': 'Poniedziałek',
        'Tuesday': 'Wtorek',
        'Wednesday': 'Środa',
        'Thursday': 'Czwartek',
        'Friday': 'Piątek',
        'Saturday': 'Sobota',
        'Sunday': 'Niedziela'
    }

    car_type_translation = {
        'both': 'Oba',
    }

    # Walidacja dat wejściowych
    try:
        for date in [start_date_1, end_date_1, start_date_2, end_date_2]:
            if date:
                datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        return jsonify(error="Nieprawidłowy format daty. Użyj formatu RRRR-MM-DD.")

    section_reverse, error = reverse_format_section(resource_path_mr_number_info(), section_number)

    df1, error1 = fetch_data_from_db(start_date_1, end_date_1, section_reverse)
    df2, error2 = fetch_data_from_db(start_date_2, end_date_2, section_reverse) if start_date_2 and end_date_2 else (
        None, None)

    if df1 is None or df1.empty:
        return jsonify(error="Brak danych do wyświetlenia.")

    df1_hourly, error1 = process_data(df1, car_type, day_of_week)
    df2_hourly, error2 = process_data(df2, car_type, day_of_week) if df2 is not None else (None, None)
    if error1 or (error2 and df2 is not None):
        return jsonify(error=f"Błąd przetwarzania danych: {error1 or error2}")

    # Pobranie numeru odcinka drogi z danych
    odcinek_numer = df1['numer_odcinka'].iloc[0] if 'numer_odcinka' in df1.columns else "N/A"

    df1_hourly = df1_hourly[['Liczba samochodów']].groupby(df1_hourly.index.time).mean().reset_index()
    df1_hourly['Liczba samochodów'] = df1_hourly['Liczba samochodów'].round(1)
    df1_hourly.columns = ['Czas', 'Liczba samochodów']
    if df2_hourly is not None:
        df2_hourly = df2_hourly[['Liczba samochodów']].groupby(df2_hourly.index.time).mean().reset_index()
        df2_hourly['Liczba samochodów'] = df2_hourly['Liczba samochodów'].round(1)
        df2_hourly.columns = ['Czas', 'Liczba samochodów']
    title = f"Średnia liczba samochodów"
    if day_of_week:
        polish_day_of_week = days_of_week_translation.get(day_of_week, day_of_week)
        title += f"<br>Dzień tygodnia: {polish_day_of_week}"
    car_type_translation = car_type_translation.get(car_type, car_type)
    title += f"<br>Typ samochodu: {car_type_translation}"
    title += f"<br>Numer MR: {odcinek_numer}"
    chart_data = {
        "x": df1_hourly['Czas'].astype(str).tolist(),  # Convert to string for JSON
        "y1": df1_hourly['Liczba samochodów'].tolist(),
        "labels": {
            "xaxis": "Czas",
            "yaxis": "Liczba samochodów"
        },
        "start_date_1": start_date_1,
        "end_date_1": end_date_1
    }

    if df2_hourly is not None:
        chart_data.update({
            "y2": df2_hourly['Liczba samochodów'].fillna(0).tolist(),  # Handle missing data in df2
            "labels": {
                "title": title,
                "xaxis": "Czas",
                "yaxis": "Liczba samochodów"
            },
            "start_date_2": start_date_2,
            "end_date_2": end_date_2
        })
    else:
        chart_data["labels"].update({
            "title": title
        })

    # Eksport danych do CSV
    csv_output = io.StringIO()
    csv_writer = csv.writer(csv_output)
    csv_writer.writerow([
        'Okres', 'Data początkowa', 'Data końcowa', 'Czas', 'Średnia liczba samochodów',
        'Typ samochodu', 'Numer MR'
    ])

    # Pętla iterująca przez dane z obu okresów
    for df, (start_date, end_date), period in zip(
            [df1_hourly, df2_hourly],
            [(start_date_1, end_date_1), (start_date_2, end_date_2)],
            ['Okres 1', 'Okres 2']
    ):
        if df is not None:
            for _, row in df.iterrows():
                csv_writer.writerow([
                    period, start_date, end_date, row['Czas'], row['Liczba samochodów'],
                    car_type_translation, odcinek_numer
                ])

    csv_data = csv_output.getvalue()

    return jsonify(chart_data=chart_data, csv_data=csv_data)


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)  # pragma: no cover
