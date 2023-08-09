import sys
import os
import sqlite3
import signal
import argparse

# Variable to track if Ctrl+C has been pressed
ctrl_c_pressed = False

# Function to handle Ctrl+C


def signal_handler(sig, frame):
    global ctrl_c_pressed
    print("\nCtrl+C detected. Exiting gracefully.")
    ctrl_c_pressed = True
    sys.exit(0)


# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)

# Constants for MySQL table options
MYSQL_ENGINE = 'InnoDB'
MYSQL_CHARSET = 'utf8mb4'
MYSQL_COLLATE = 'utf8mb4_unicode_ci'

# Function to convert SQLite data types to MySQL data types


def sqlite_to_mysql_type(sqlite_type, max_length=None, nullable=False, max_value=None):
    mapping = {
        'TEXT': 'TEXT',
        'INTEGER': 'INT',
        'REAL': 'DOUBLE',
        'BLOB': 'LONGBLOB',
        'NULL': 'NULL',
    }
    if sqlite_type == 'TEXT' and max_length is not None:
        if max_length > 255:
            return 'LONGTEXT' if nullable else 'LONGTEXT NOT NULL'
        elif max_length > 0:
            return f'VARCHAR({max_length})' if nullable else f'VARCHAR({max_length}) NOT NULL'

    elif sqlite_type == 'INTEGER' and max_value is not None:
        if -2147483648 <= max_value <= 2147483647:
            return 'INT' if nullable else 'INT NOT NULL'
        elif -9223372036854775808 <= max_value <= 9223372036854775807:
            return 'BIGINT' if nullable else 'BIGINT NOT NULL'

    return mapping.get(sqlite_type, sqlite_type) + (' DEFAULT NULL' if nullable else ' NOT NULL')

# Function to create the SQL dump file for MySQL


def create_sql_dump(db_file, dump_file, drop_table=True):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Get the list of tables from the SQLite database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [table[0] for table in cursor.fetchall()]
    total_tables = len(tables)

    print("Exporting from SQLite to MySQL:")

    for idx, table in enumerate(tables, 1):
        # Skip the 'sqlite_sequence' table
        if table == 'sqlite_sequence':
            continue

        print(f"\nReading table: {table} ({idx}/{total_tables})")

        # Retrieve the table structure
        cursor.execute(f"PRAGMA table_info({table});")
        columns_info = cursor.fetchall()

        print("Checking the length of columns and nullability...")
        # Analyze the data to determine the max length of TEXT columns and check nullability
        max_lengths = {}
        nullability = {}
        max_values = {}
        for col_info in columns_info:
            col_name, col_type = col_info[1], col_info[2]
            nullable = False
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col_name} IS NULL OR {col_name} = '';")
            null_count = cursor.fetchone()[0]
            if null_count > 0:
                nullable = True
            else:
                col_value = None
                if col_type == 'TEXT':
                    cursor.execute(
                        f"SELECT MAX(LENGTH({col_name})) FROM {table};")
                    max_length = cursor.fetchone()[0]
                    max_lengths[col_name] = max(
                        max_lengths.get(col_name, 0), max_length)
                elif col_type == 'INTEGER':
                    cursor.execute(f"SELECT MAX({col_name}) FROM {table};")
                    max_value = cursor.fetchone()[0]
                    max_values[col_name] = max(
                        max_values.get(col_name, 0), max_value)
            nullability[col_name] = nullable

        # Write the table structures and data to the SQL dump file
        with open(dump_file, 'a') as f:
            if drop_table:
                f.write(f"\n\n-- Drop table if exists {table}\n")
                f.write(f"DROP TABLE IF EXISTS {table};")

            columns = ', '.join([
                f"{col[1]} {sqlite_to_mysql_type(col[2], max_lengths.get(col[1]), nullability.get(col[1]), max_values.get(col[1]))}"
                for col in columns_info
            ])
            table_create_query = f"\n\n-- Table structure for {table}\n"
            table_create_query += f"CREATE TABLE {table} ({columns}) ENGINE={MYSQL_ENGINE} DEFAULT CHARSET={MYSQL_CHARSET} COLLATE={MYSQL_COLLATE};"
            f.write(table_create_query)

            # Retrieve the data from the table
            cursor.execute(f"SELECT * FROM {table};")
            data = cursor.fetchall()

            total_rows = len(data)
            print(f"Exporting {total_rows} rows from {table}...")
            # Write the data insertion queries to the dump file
            for row_num, row in enumerate(data, 1):
                # Convert None to NULL in the data
                row = [col if col is not None and col !=
                       '' else 'NULL' for col in row]

                # Check if Ctrl+C has been pressed
                if ctrl_c_pressed:
                    print("\nCtrl+C detected. Exiting gracefully.")
                    sys.exit(0)

                # columns = ', '.join(repr(col) for col in row)
                columns = ', '.join(
                    'NULL' if col is None or col == '' else repr(col) for col in row)
                # Replace 'NULL' with NULL
                columns = columns.replace("'NULL'", "NULL")

                f.write(f"\nINSERT INTO {table} VALUES ({columns});")

                # Print progress for each row
                print(
                    f"Progress: {row_num}/{total_rows} rows exported.", end='\r')

        # Print progress for the table
        print(f"\nTable {table} exported successfully.")

    conn.close()
    # Add extra spaces to overwrite the loading indicator
    print("\nExport completed.                            ")


def display_help():
    print(
        "Usage: python sqlite_to_mysql.py <sqlite_db_file> [mysql_dump_file] [--no-drop]")
    print("Parameters:")
    print("  sqlite_db_file: Path to the SQLite database file.")
    print("  mysql_dump_file: (Optional) Path to the output MySQL SQL dump file.")
    print("                   If not provided, the SQLite database with .sql extension will be used as the default.")
    print("  --no-drop: (Optional) Prevents adding 'DROP TABLE IF EXISTS' statement in the SQL dump.")
    print("             By default, the statement will be included unless this parameter is specified.")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="SQLite to MySQL SQL dump converter")
    parser.add_argument("sqlite_db_file", type=str,
                        help="Path to the SQLite database file.")
    parser.add_argument("mysql_dump_file", type=str, nargs="?", default=None,
                        help="(Optional) Path to the output MySQL SQL dump file. "
                             "If not provided, the SQLite database with .sql extension will be used as the default.")
    parser.add_argument("--no-drop", action="store_true",
                        help="Prevents adding 'DROP TABLE IF EXISTS' statement in the SQL dump.")

    return parser.parse_args()


# Main code block
if __name__ == '__main__':
    args = parse_arguments()
    sqlite_db_file = args.sqlite_db_file

    # If mysql_dump_file is not provided, use sqlite_db_file with .sql extension as default
    mysql_dump_file = args.mysql_dump_file if args.mysql_dump_file else os.path.splitext(
        sqlite_db_file)[0] + '.sql'

    # Check if the user passed the "--no-drop" parameter
    drop_table = not args.no_drop

    # Call the create_sql_dump function for exporting SQLite to MySQL
    create_sql_dump(sqlite_db_file, mysql_dump_file, drop_table)

    if ctrl_c_pressed:
        print("Process terminated by user.")
        sys.exit(0)
