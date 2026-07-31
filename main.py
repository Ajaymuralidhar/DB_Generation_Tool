import argparse
from config import logger
from schema_manager import SchemaManager
from db_loader import DBLoader
from data_generator import DataGenerator

def main():
    parser = argparse.ArgumentParser(description="Automated Schema Builder and Synthetic Bulk Data Generator for Oracle.")
    parser.add_argument("--schema", type=str, default="schema_example.json", help="Path to JSON schema file")
    parser.add_argument("--rows", type=int, default=1000, help="Number of rows to generate per table")
    parser.add_argument("--batch-size", type=int, default=10000, help="Batch size for insertion")
    parser.add_argument("--force", action="store_true", help="Drop tables if they exist")
    args = parser.parse_args()

    schema_manager = SchemaManager(args.schema)
    db_loader = DBLoader()
    data_generator = DataGenerator()

    try:
        db_loader.connect()

        if args.force:
            logger.info("Force flag is set. Dropping existing tables...")
            for table_name in schema_manager.get_drop_order():
                ddl = schema_manager.generate_drop_ddl(table_name)
                # 942 is table or view does not exist
                db_loader.execute_ddl(ddl, ignore_errors=[942])

        logger.info("Creating tables (without Foreign Key constraints initially)...")
        creation_order = schema_manager.get_creation_order()
        for table_name in creation_order:
            ddl = schema_manager.generate_create_ddl(table_name)
            # 955 is name is already used by an existing object
            db_loader.execute_ddl(ddl, ignore_errors=[955] if not args.force else None)

        logger.info("Generating and loading data...")
        sample_keys_dict = {}

        for table_name in creation_order:
            table_schema = schema_manager.get_table_schema(table_name)
            
            logger.info(f"Processing table: {table_name} ({args.rows} rows target)")
            
            rows_generated = 0
            while rows_generated < args.rows:
                current_batch_size = min(args.batch_size, args.rows - rows_generated)
                query, batch_data = data_generator.generate_batch(table_schema, sample_keys_dict, current_batch_size)
                
                if batch_data:
                    db_loader.execute_many(query, batch_data)
                    rows_generated += len(batch_data)
                    logger.info(f"[{table_name}] Inserted {rows_generated}/{args.rows} rows")
                else:
                    # Table has only auto-generated columns or nothing to insert
                    logger.info(f"[{table_name}] No columns to insert manually.")
                    break
            
            # Post-Insert Bounded Sampling: fetch primary keys for children to use
            # Find the primary key column
            pk_col = next((col['name'] for col in table_schema['columns'] if col.get('primary_key')), None)
            if pk_col:
                sample_keys = db_loader.fetch_sample_keys(table_name, pk_col)
                sample_keys_dict[table_name] = sample_keys
            else:
                logger.warning(f"No primary key found for {table_name}, cannot sample for child tables.")

        logger.info("Applying Foreign Key Constraints...")
        for table_name in creation_order:
            fk_ddls = schema_manager.generate_fk_ddl(table_name)
            for ddl in fk_ddls:
                # 2275 is such a referential constraint already exists in the table
                db_loader.execute_ddl(ddl, ignore_errors=[2275])
                
        logger.info("Process completed successfully.")

    except Exception as e:
        logger.error(f"Process failed: {e}")
    finally:
        db_loader.close()

if __name__ == "__main__":
    main()
