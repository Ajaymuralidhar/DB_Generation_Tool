import json
import networkx as nx
from config import logger

class SchemaManager:
    def __init__(self, schema_file: str):
        self.schema_file = schema_file
        self.schema_data = self._load_schema()
        self.dag = self._build_dag()

    def _load_schema(self) -> dict:
        with open(self.schema_file, 'r') as f:
            return json.load(f)

    def _build_dag(self) -> nx.DiGraph:
        """
        Builds a Directed Acyclic Graph (DAG) where nodes are tables
        and edges represent foreign key dependencies.
        """
        dag = nx.DiGraph()
        for table in self.schema_data.get('tables', []):
            table_name = table['name'].upper()
            dag.add_node(table_name, **table)

            for fk in table.get('foreign_keys', []):
                ref_table = fk['references_table'].upper()
                # Edge from parent to child means parent must come before child
                dag.add_edge(ref_table, table_name) 

        if not nx.is_directed_acyclic_graph(dag):
            raise ValueError("Schema contains cyclic foreign key dependencies!")
        return dag

    def get_creation_order(self) -> list[str]:
        """Returns table names in topological order (parents first)."""
        return list(nx.topological_sort(self.dag))

    def get_drop_order(self) -> list[str]:
        """Returns table names in reverse topological order (children first)."""
        return list(reversed(self.get_creation_order()))

    def get_table_schema(self, table_name: str) -> dict:
        return self.dag.nodes[table_name.upper()]

    def generate_drop_ddl(self, table_name: str) -> str:
        return f"DROP TABLE {table_name.upper()} CASCADE CONSTRAINTS"

    def generate_create_ddl(self, table_name: str) -> str:
        table_def = self.get_table_schema(table_name)
        columns_ddl = []
        
        for col in table_def['columns']:
            col_ddl = f"{col['name']} {col['type']}"
            columns_ddl.append(col_ddl)
            
        if 'primary_key_columns' in table_def and table_def['primary_key_columns']:
            pk_cols = ", ".join(table_def['primary_key_columns'])
            columns_ddl.append(f"CONSTRAINT PK_{table_name.upper()} PRIMARY KEY ({pk_cols})")
            
        columns_str = ",\n    ".join(columns_ddl)
        ddl = f"CREATE TABLE {table_name.upper()} (\n    {columns_str}\n)"
        return ddl
        
    def generate_fk_ddl(self, table_name: str) -> list[str]:
        table_def = self.get_table_schema(table_name)
        fk_ddls = []
        for fk in table_def.get('foreign_keys', []):
            fk_name = f"fk_{table_name}_{fk['column']}".lower()
            # truncate name to 30 chars for older oracle versions (just in case), or let oracle handle it for 12c+
            fk_name = fk_name[:30]
            ddl = (f"ALTER TABLE {table_name.upper()} "
                   f"ADD CONSTRAINT {fk_name} "
                   f"FOREIGN KEY ({fk['column']}) "
                   f"REFERENCES {fk['references_table'].upper()}({fk['references_column']})")
            fk_ddls.append(ddl)
        return fk_ddls

    def generate_index_ddl(self, table_name: str) -> list[str]:
        table_def = self.get_table_schema(table_name)
        idx_ddls = []
        for idx in table_def.get('indexes', []):
            idx_name = idx['name'].upper()
            idx_cols = ", ".join(idx['columns'])
            ddl = f"CREATE INDEX {idx_name} ON {table_name.upper()} ({idx_cols})"
            idx_ddls.append(ddl)
        return idx_ddls

    def read_plsql_file(self, file_path: str) -> str:
        with open(file_path, 'r') as f:
            content = f.read()
        return content.strip().rstrip('/').strip()

    def get_procedures(self) -> list[dict]:
        return self.schema_data.get('procedures', [])

    def get_functions(self) -> list[dict]:
        return self.schema_data.get('functions', [])

    def get_triggers(self) -> list[dict]:
        return self.schema_data.get('triggers', [])
