import random
from faker import Faker
from config import logger

class DataGenerator:
    def __init__(self):
        self.faker = Faker()

    def generate_batch(self, table_schema: dict, sample_keys_dict: dict, batch_size: int) -> tuple[str, list[tuple]]:
        """
        Generates a batch of synthetic data for a given table.
        Returns the INSERT query and the list of tuples (data).
        sample_keys_dict maps parent_table_name -> list of sample primary keys.
        """
        table_name = table_schema['name'].upper()
        columns_to_insert = []
        faker_methods = []
        fk_lookups = {}

        # Parse Foreign Keys for fast lookup
        for fk in table_schema.get('foreign_keys', []):
            ref_table = fk['references_table'].upper()
            fk_lookups[fk['column']] = ref_table

        for col in table_schema['columns']:
            # Skip auto-generated columns like Identity PKs
            if col.get('auto_generated', False):
                continue

            col_name = col['name']
            columns_to_insert.append(col_name)

            if col_name in fk_lookups:
                # It's a foreign key, we need to pick from sampled parent keys
                ref_table = fk_lookups[col_name]
                if ref_table not in sample_keys_dict or not sample_keys_dict[ref_table]:
                    raise ValueError(f"No sample keys available for parent table {ref_table} required by {table_name}.{col_name}")
                
                # We store a lambda that picks a random choice from the parent keys
                faker_methods.append(lambda t=ref_table: random.choice(sample_keys_dict[t]))
            elif 'faker' in col:
                # It's a faker column
                faker_func_name = col['faker']
                faker_kwargs = col.get('faker_kwargs', {})
                
                # Fetch the method from faker instance
                if hasattr(self.faker, faker_func_name):
                    faker_method = getattr(self.faker, faker_func_name)
                    # We wrap it in a lambda to pass kwargs lazily
                    faker_methods.append(lambda m=faker_method, kw=faker_kwargs: m(**kw))
                else:
                    logger.warning(f"Faker method {faker_func_name} not found, defaulting to word.")
                    faker_methods.append(lambda: self.faker.word())
            else:
                # Default fallback based on column type if no faker specified
                col_type = col.get('type', '').upper()
                if 'DATE' in col_type or 'TIMESTAMP' in col_type:
                    faker_methods.append(lambda: self.faker.date_time())
                elif 'NUMBER' in col_type or 'INT' in col_type or 'FLOAT' in col_type:
                    faker_methods.append(lambda: self.faker.random_int(min=1, max=10000))
                else:
                    faker_methods.append(lambda: self.faker.word())

        if not columns_to_insert:
            return "", []

        # Build the INSERT query
        placeholders = ", ".join([f":{i+1}" for i in range(len(columns_to_insert))])
        columns_str = ", ".join(columns_to_insert)
        query = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"

        # Generate data
        batch_data = []
        for _ in range(batch_size):
            row = tuple(method() for method in faker_methods)
            batch_data.append(row)

        return query, batch_data
