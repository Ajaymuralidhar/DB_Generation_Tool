import random
from faker import Faker
from config import logger

class DataGenerator:
    def __init__(self):
        self.faker = Faker()
        self.fk_pools = {}
        self.pk_counters = {}

    def generate_batch(self, table_schema: dict, sample_keys_dict: dict, batch_size: int, dialect: str = "Oracle", target_schema: str = None) -> tuple[str, list[tuple]]:
        """
        Generates a batch of synthetic data for a given table.
        Returns the INSERT query and the list of tuples (data).
        sample_keys_dict maps parent_table_name -> list of sample primary keys.
        """
        table_name = table_schema['name'].upper()
        columns_to_insert = []
        faker_methods = []
        fk_lookups = {}
        
        pk_cols = table_schema.get('primary_key_columns', [])

        # Parse Foreign Keys for fast lookup
        for fk in table_schema.get('foreign_keys', []):
            ref_table = fk['references_table'].upper()
            fk_col = fk.get('column')
            if not fk_col and fk.get('columns'):
                fk_col = fk.get('columns')[0]
            if fk_col:
                fk_lookups[fk_col] = ref_table

        for col in table_schema['columns']:
            # Skip auto-generated columns like Identity PKs
            if col.get('auto_generated', False):
                continue

            col_name = col['name']
            columns_to_insert.append(col_name)
            is_pk = col_name in pk_cols

            if col_name in fk_lookups:
                # It's a foreign key, we need to pick from sampled parent keys
                ref_table = fk_lookups[col_name]
                if ref_table not in sample_keys_dict or not sample_keys_dict[ref_table]:
                    raise ValueError(f"No sample keys available for parent table {ref_table} required by {table_name}.{col_name}")
                
                if is_pk:
                    # PK + FK: must be unique!
                    pool_key = f"{table_name}.{col_name}"
                    if pool_key not in self.fk_pools:
                        self.fk_pools[pool_key] = list(set(sample_keys_dict[ref_table]))
                        random.shuffle(self.fk_pools[pool_key])
                        
                    def get_unique_fk(pk=pool_key, rt=ref_table):
                        if not self.fk_pools[pk]:
                            return random.choice(sample_keys_dict[rt])
                        return self.fk_pools[pk].pop()
                        
                    faker_methods.append(get_unique_fk)
                else:
                    # We store a lambda that picks a random choice from the parent keys
                    faker_methods.append(lambda t=ref_table: random.choice(sample_keys_dict[t]))
            else:
                col_type = col.get('type', '').upper()
                is_numeric = any(t in col_type for t in ['NUMBER', 'INT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC', 'REAL'])
                is_date = 'DATE' in col_type or 'TIMESTAMP' in col_type
                
                if is_pk:
                    # Uniqueness guarantee without Faker collision issues
                    pool_key = f"{table_name}.{col_name}"
                    if pool_key not in self.pk_counters:
                        self.pk_counters[pool_key] = 1
                        
                    if is_numeric:
                        def get_unique_pk(pk=pool_key):
                            val = self.pk_counters[pk]
                            self.pk_counters[pk] += 1
                            return val
                    else:
                        def get_unique_pk(pk=pool_key):
                            val = f"ID_{self.pk_counters[pk]}"
                            self.pk_counters[pk] += 1
                            return val
                    faker_methods.append(get_unique_pk)
                else:
                    f_instance = self.faker

                    if 'faker' in col:
                        faker_func_name = col['faker']
                        faker_kwargs = col.get('faker_kwargs', {})
                        
                        if hasattr(f_instance, faker_func_name):
                            faker_method = getattr(f_instance, faker_func_name)
                            
                            # Prevent ORA-01722 and MSSQL SMALLINT overflows
                            if is_numeric and faker_func_name not in ['random_int', 'random_number', 'pyfloat', 'pyint', 'random_digit']:
                                logger.warning(f"Overriding incompatible faker '{faker_func_name}' for numeric column {col_name}")
                                faker_methods.append(lambda inst=f_instance: inst.random_int(min=1, max=9999))
                            else:
                                faker_methods.append(lambda m=faker_method, kw=faker_kwargs: m(**kw))
                        else:
                            logger.warning(f"Faker method {faker_func_name} not found, defaulting based on type.")
                            if is_date:
                                faker_methods.append(lambda inst=f_instance: inst.date_time())
                            elif is_numeric:
                                faker_methods.append(lambda inst=f_instance: inst.random_int(min=1, max=9999))
                            else:
                                faker_methods.append(lambda inst=f_instance: inst.word())
                    else:
                        if is_date:
                            faker_methods.append(lambda inst=f_instance: inst.date_time())
                        elif is_numeric:
                            faker_methods.append(lambda inst=f_instance: inst.random_int(min=1, max=9999))
                        else:
                            faker_methods.append(lambda inst=f_instance: inst.word())

        if not columns_to_insert:
            return "", []

        # Build the INSERT query with dialect-specific placeholders
        fqn = f"{target_schema}.{table_name}" if target_schema else table_name
        columns_str = ", ".join(columns_to_insert)
        
        if dialect == "MSSQL":
            placeholders = ", ".join(["?" for _ in range(len(columns_to_insert))])
            query = f"INSERT INTO {fqn} ({columns_str}) VALUES ({placeholders})"
        else: # Oracle
            placeholders = ", ".join([f":{i+1}" for i in range(len(columns_to_insert))])
            query = f"INSERT INTO {fqn} ({columns_str}) VALUES ({placeholders})"

        # Generate data
        batch_data = []
        for _ in range(batch_size):
            row = tuple(method() for method in faker_methods)
            batch_data.append(row)

        return query, batch_data
