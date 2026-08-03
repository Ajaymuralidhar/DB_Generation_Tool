import oracledb
import psycopg2
import psycopg2.extras
import pyodbc
from config import DB_USER, DB_PASSWORD, DB_DSN, logger

class DBLoader:
    def __init__(self):
        self.connection = None
        self.dialect = "Oracle"

    def connect(self, dialect="Oracle", user=None, password=None, dsn=None):
        self.dialect = dialect
        try:
            if dialect == "Oracle":
                self.connection = oracledb.connect(
                    user=user or DB_USER,
                    password=password or DB_PASSWORD,
                    dsn=dsn or DB_DSN
                )
            elif dialect == "PostgreSQL":
                # dsn format: host:port/dbname
                host, port_db = (dsn or DB_DSN).split(':')
                port, dbname = port_db.split('/')
                self.connection = psycopg2.connect(
                    user=user or DB_USER,
                    password=password or DB_PASSWORD,
                    host=host,
                    port=port,
                    dbname=dbname
                )
            elif dialect == "MSSQL":
                # dsn format: host:port/dbname
                host, port_db = (dsn or DB_DSN).split(':')
                port, dbname = port_db.split('/')
                conn_str = (
                    "Driver={SQL Server};"
                    f"Server={host},{port};"
                    f"Database={dbname};"
                    f"UID={user or DB_USER};"
                    f"PWD={password or DB_PASSWORD};"
                )
                self.connection = pyodbc.connect(conn_str)
            logger.info(f"Successfully connected to {dialect} Database.")
        except Exception as e:
            logger.error(f"Error connecting to {dialect} database: {e}")
            raise

    def close(self):
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed.")

    def execute_ddl(self, ddl: str, ignore_errors: list[int] = None):
        """Executes a single DDL statement."""
        ignore_errors = ignore_errors or []
        with self.connection.cursor() as cursor:
            try:
                cursor.execute(ddl)
                if self.dialect != "Oracle":
                    self.connection.commit()
                logger.info(f"Executed: {ddl.strip().split(chr(10))[0]}...")
            except Exception as e:
                # Basic error ignoring for non-Oracle (mostly for drops)
                if self.dialect == "Oracle" and isinstance(e, oracledb.DatabaseError):
                    error, = e.args
                    if error.code in ignore_errors:
                        logger.debug(f"Ignored expected error: {error.message}")
                        return
                elif self.dialect != "Oracle" and ignore_errors:
                    # Generic ignore for MSSQL/Postgres (e.g., if object exists)
                    logger.debug(f"Ignored potential error: {e}")
                    self.connection.rollback()
                    return
                logger.error(f"Error executing DDL: {ddl}\n{e}")
                if self.dialect != "Oracle": self.connection.rollback()
                raise

    def execute_many(self, query: str, data: list[tuple]):
        """Executes bulk inserts efficiently using dialect-specific optimizations."""
        if not data:
            return
            
        with self.connection.cursor() as cursor:
            try:
                if self.dialect == "PostgreSQL":
                    psycopg2.extras.execute_values(cursor, query, data)
                elif self.dialect == "MSSQL":
                    cursor.fast_executemany = True
                    cursor.executemany(query, data)
                else: # Oracle
                    cursor.executemany(query, data)
                self.connection.commit()
            except Exception as e:
                logger.error(f"Bulk insert failed for query: {query}\nError: {e}")
                self.connection.rollback()
                raise

    def fetch_sample_keys(self, table_name: str, key_column: str, sample_size: int = 500000, target_schema: str = None) -> list:
        """Fetches a sample of primary keys to be used for foreign key resolution."""
        fqn = f"{target_schema}.{table_name}" if target_schema else table_name
        if self.dialect == "Oracle":
            query = f"SELECT {key_column} FROM {fqn} FETCH FIRST {sample_size} ROWS ONLY"
        elif self.dialect == "MSSQL":
            query = f"SELECT TOP ({sample_size}) {key_column} FROM {fqn}"
        else: # PostgreSQL
            query = f"SELECT {key_column} FROM {fqn} LIMIT {sample_size}"
            
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            results = [row[0] for row in cursor.fetchall()]
        logger.info(f"Fetched {len(results)} sample keys from {table_name}.{key_column}")
        return results

    def execute_plsql(self, plsql_code: str, object_name: str, object_type: str):
        """Executes PL/SQL block. Only applicable for Oracle."""
        if self.dialect != "Oracle":
            logger.info(f"Skipping PL/SQL compilation for {self.dialect}: {object_name}")
            return
            
        with self.connection.cursor() as cursor:
            try:
                cursor.execute(plsql_code)
                cursor.execute(
                    "SELECT line, position, text FROM user_errors WHERE name = :1 AND type = :2 ORDER BY sequence",
                    [object_name.upper(), object_type.upper()]
                )
                errors = cursor.fetchall()
                if errors:
                    error_msgs = "\n".join([f"Line {e[0]},{e[1]}: {e[2]}" for e in errors])
                    logger.error(f"Compilation errors for {object_type} {object_name}:\n{error_msgs}")
                    raise ValueError(f"PL/SQL Compilation failed for {object_name}")
                logger.info(f"Successfully compiled {object_type}: {object_name}")
            except Exception as e:
                logger.error(f"Error executing PL/SQL for {object_name}: {e}")
                raise

    def drop_user(self, target_user: str):
        """Drops a user/schema/database and all their objects CASCADE."""
        with self.connection.cursor() as cursor:
            try:
                if self.dialect == "Oracle":
                    try:
                        cursor.execute(f"SELECT sid, serial# FROM v$session WHERE username = '{target_user.upper()}'")
                        sessions = cursor.fetchall()
                        for sid, serial in sessions:
                            cursor.execute(f"ALTER SYSTEM KILL SESSION '{sid},{serial}' IMMEDIATE")
                    except Exception as e:
                        pass
                    cursor.execute(f"DROP USER {target_user} CASCADE")
                elif self.dialect == "PostgreSQL":
                    self.connection.commit()
                    self.connection.autocommit = True
                    cursor.execute(f"DROP SCHEMA IF EXISTS {target_user} CASCADE")
                    self.connection.autocommit = False
                elif self.dialect == "MSSQL":
                    self.connection.commit()
                    self.connection.autocommit = True
                    # Drop all foreign keys in the schema
                    cursor.execute(f"""
                        DECLARE @Sql NVARCHAR(MAX) = '';
                        SELECT @Sql += 'ALTER TABLE ' + QUOTENAME(s.name) + '.' + QUOTENAME(t.name) + ' DROP CONSTRAINT ' + QUOTENAME(fk.name) + ';'
                        FROM sys.foreign_keys fk
                        JOIN sys.tables t ON fk.parent_object_id = t.object_id
                        JOIN sys.schemas s ON t.schema_id = s.schema_id
                        WHERE s.name = '{target_user}';
                        EXEC sp_executesql @Sql;
                    """)
                    # Drop all tables in the schema
                    cursor.execute(f"""
                        DECLARE @Sql NVARCHAR(MAX) = '';
                        SELECT @Sql += 'DROP TABLE ' + QUOTENAME(s.name) + '.' + QUOTENAME(t.name) + ';'
                        FROM sys.tables t
                        JOIN sys.schemas s ON t.schema_id = s.schema_id
                        WHERE s.name = '{target_user}';
                        EXEC sp_executesql @Sql;
                    """)
                    # Drop the schema itself
                    cursor.execute(f"IF EXISTS (SELECT * FROM sys.schemas WHERE name = '{target_user}') DROP SCHEMA {target_user}")
                    self.connection.autocommit = False
                logger.info(f"Successfully dropped schema {target_user}.")
            except Exception as e:
                logger.info(f"Skipping drop or error occurred: {e}")

    def create_and_grant_user(self, new_user: str, new_password: str):
        """Creates a new user/schema and grants necessary privileges."""
        with self.connection.cursor() as cursor:
            try:
                if self.dialect == "Oracle":
                    cursor.execute(f"CREATE USER {new_user} IDENTIFIED BY \"{new_password}\"")
                    cursor.execute(f"GRANT CONNECT, RESOURCE, CREATE VIEW, CREATE PROCEDURE, CREATE TRIGGER TO {new_user}")
                    cursor.execute(f"GRANT UNLIMITED TABLESPACE TO {new_user}")
                elif self.dialect == "PostgreSQL":
                    self.connection.commit()
                    self.connection.autocommit = True
                    cursor.execute(f"CREATE SCHEMA {new_user}")
                    self.connection.autocommit = False
                elif self.dialect == "MSSQL":
                    self.connection.commit()
                    self.connection.autocommit = True
                    cursor.execute(f"CREATE SCHEMA {new_user}")
                    self.connection.autocommit = False
                logger.info(f"Successfully created schema/user {new_user}.")
            except Exception as e:
                logger.error(f"Error creating schema {new_user}: {e}")
                raise
