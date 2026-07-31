import oracledb
from config import DB_USER, DB_PASSWORD, DB_DSN, logger

class DBLoader:
    def __init__(self):
        self.connection = None

    def connect(self, user=None, password=None, dsn=None):
        try:
            self.connection = oracledb.connect(
                user=user or DB_USER,
                password=password or DB_PASSWORD,
                dsn=dsn or DB_DSN
            )
            logger.info("Successfully connected to Oracle Database.")
        except oracledb.Error as e:
            logger.error(f"Error connecting to database: {e}")
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
                logger.info(f"Executed: {ddl.strip().split(chr(10))[0]}...")
            except oracledb.DatabaseError as e:
                error, = e.args
                if error.code in ignore_errors:
                    logger.debug(f"Ignored expected error: {error.message}")
                else:
                    logger.error(f"Error executing DDL: {ddl}\n{e}")
                    raise

    def execute_many(self, query: str, data: list[tuple]):
        """Executes bulk inserts efficiently."""
        if not data:
            return
            
        with self.connection.cursor() as cursor:
            try:
                cursor.executemany(query, data)
                self.connection.commit()
            except oracledb.DatabaseError as e:
                logger.error(f"Bulk insert failed for query: {query}\nError: {e}")
                self.connection.rollback()
                raise

    def fetch_sample_keys(self, table_name: str, key_column: str, sample_size: int = 500000) -> list:
        """Fetches a sample of primary keys to be used for foreign key resolution."""
        query = f"SELECT {key_column} FROM {table_name} FETCH FIRST {sample_size} ROWS ONLY"
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            results = [row[0] for row in cursor.fetchall()]
        logger.info(f"Fetched {len(results)} sample keys from {table_name}.{key_column}")
        return results
