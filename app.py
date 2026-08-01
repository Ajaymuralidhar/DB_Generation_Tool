import streamlit as st
import json
import logging
import tempfile
import os
from streamlit_ace import st_ace

from schema_manager import SchemaManager
from db_loader import DBLoader
from data_generator import DataGenerator
from schema_translator import SchemaTranslator
from config import logger

# --- Streamlit Page Config ---
st.set_page_config(page_title="Oracle Schema Builder", page_icon="🗄️", layout="wide")

# --- Startup Logic for PL/SQL Objects ---
def create_dummy_plsql_files():
    base_dir = "sql_objects"
    dirs = ["procedures", "functions", "triggers"]
    for d in dirs:
        os.makedirs(os.path.join(base_dir, d), exist_ok=True)
        
    dummy_proc = os.path.join(base_dir, "procedures", "calc_total.sql")
    if not os.path.exists(dummy_proc):
        with open(dummy_proc, 'w') as f:
            f.write("CREATE OR REPLACE PROCEDURE calc_total AS\nBEGIN\n    NULL;\nEND;\n/")
            
    dummy_func = os.path.join(base_dir, "functions", "get_user_status.sql")
    if not os.path.exists(dummy_func):
        with open(dummy_func, 'w') as f:
            f.write("CREATE OR REPLACE FUNCTION get_user_status RETURN VARCHAR2 AS\nBEGIN\n    RETURN 'ACTIVE';\nEND;\n/")
            
    dummy_trig = os.path.join(base_dir, "triggers", "trg_orders_audit.sql")
    if not os.path.exists(dummy_trig):
        with open(dummy_trig, 'w') as f:
            f.write("CREATE OR REPLACE TRIGGER trg_orders_audit\nBEFORE INSERT ON ORDERS\nFOR EACH ROW\nBEGIN\n    NULL;\nEND;\n/")

create_dummy_plsql_files()

# --- Custom Logging Handler ---
class StreamlitLogHandler(logging.Handler):
    def __init__(self, log_container):
        super().__init__()
        self.log_container = log_container
        self.log_text = ""
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        msg = self.format(record)
        self.log_text += msg + "\n"
        self.log_container.code(self.log_text, language="log")

# --- DB Connection Factory ---
def get_db_loader(user, password, dsn):
    loader = DBLoader()
    loader.connect(user=user, password=password, dsn=dsn)
    return loader

# --- App Layout ---
st.title("🗄️ Oracle DB Generator Dashboard")
st.markdown("Live Proof-of-Concept for automated schema generation and high-performance bulk data loading.")

# Sidebar Configuration
with st.sidebar:
    st.header("⚙️ Configuration")
    
    st.subheader("Database Credentials")
    db_user = st.text_input("System Username", value="system")
    db_password = st.text_input("System Password", value="DevPassword123", type="password")
    db_dsn = st.text_input("DSN (Host:Port/Service)", value="localhost:1521/FREEPDB1")
    
    st.subheader("Generation Settings")
    target_schema = st.text_input("Target Schema (Oracle User)", value="GEN_SCHEMA_1").upper()
    rows = st.number_input("Rows per Table", min_value=1, value=1000, step=100)
    batch_size = st.number_input("Batch Size", min_value=1, value=10000, step=100)
    force = st.checkbox("Force Recreate (Drop existing schema)", value=True)
    
    st.subheader("Integrations")
    gemini_api_key = st.text_input("Gemini API Key", type="password")
    
    run_btn = st.button("🚀 Run Generator", type="primary", use_container_width=True)

# Load default schema
if 'schema_json' not in st.session_state:
    try:
        with open("schema_example.json", "r") as f:
            st.session_state.schema_json = f.read()
    except FileNotFoundError:
        st.session_state.schema_json = "{}"

if 'editor_key' not in st.session_state:
    st.session_state.editor_key = 0

# Main content area
tab_gen, tab_explore = st.tabs(["⚙️ Generator", "📊 Data Explorer"])

with tab_gen:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📝 Schema Editor")
        st.markdown("Use AI to translate raw text, or edit the JSON manually.")
        
        raw_schema = st.text_area("✨ AI Translation: Raw Schema Input (Messy SQL / Text)", height=150)
        if st.button("Translate to JSON", use_container_width=True):
            if not gemini_api_key:
                st.error("Please provide a Gemini API Key in the sidebar.")
            elif not raw_schema.strip():
                st.warning("Please provide raw schema text to translate.")
            else:
                with st.spinner("Translating..."):
                    try:
                        translator = SchemaTranslator(gemini_api_key)
                        translated_json = translator.translate_to_json(raw_schema)
                        st.session_state.schema_json = translated_json
                        st.session_state.editor_key += 1
                        st.success("Translated successfully! Review the JSON below.")
                    except Exception as e:
                        st.error(str(e))
                        
        st.markdown("---")
        
        # st_ace editor
        edited_schema = st_ace(
            value=st.session_state.schema_json,
            language='json',
            theme='dracula',
            height=500,
            font_size=14,
            key=f"ace_editor_{st.session_state.editor_key}"
        )
        # Update session state with edited value
        if edited_schema != st.session_state.schema_json:
            st.session_state.schema_json = edited_schema

    with col2:
        st.subheader("🖥️ Execution Logs")
        log_container = st.empty()
        log_container.code("Ready to generate...", language="log")
        
        progress_bar = st.empty()
        status_text = st.empty()

    # --- Execution Logic ---
    if run_btn:
        # Set up custom logger for this run
        log_container.empty()
        sl_handler = StreamlitLogHandler(log_container)
        logger.addHandler(sl_handler)
        
        try:
            # Validate JSON
            try:
                schema_dict = json.loads(st.session_state.schema_json)
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON schema: {e}")
                st.stop()
                
            # Write temporary schema file for SchemaManager
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp_file:
                tmp_file.write(st.session_state.schema_json)
                tmp_schema_path = tmp_file.name
                
            status_text.info(f"Provisioning schema {target_schema}...")
            sys_db = DBLoader()
            sys_db.connect(user=db_user, password=db_password, dsn=db_dsn)
            
            if force:
                sys_db.drop_user(target_schema)
                
            sys_db.create_and_grant_user(target_schema, "GenPass123")
            sys_db.close()
            
            status_text.info(f"Connecting as {target_schema}...")
            db_loader = get_db_loader(target_schema, "GenPass123", db_dsn)
            
            schema_manager = SchemaManager(tmp_schema_path)
            data_generator = DataGenerator()
                    
            status_text.info("Creating tables...")
            creation_order = schema_manager.get_creation_order()
            for table_name in creation_order:
                ddl = schema_manager.generate_create_ddl(table_name)
                db_loader.execute_ddl(ddl, ignore_errors=[955] if not force else None)
                
            status_text.info("Creating indexes...")
            for table_name in creation_order:
                idx_ddls = schema_manager.generate_index_ddl(table_name)
                for ddl in idx_ddls:
                    db_loader.execute_ddl(ddl, ignore_errors=[955] if not force else None)
                
            sample_keys_dict = {}
            
            # Data Generation Loop
            for table_idx, table_name in enumerate(creation_order):
                status_text.info(f"Processing table: {table_name} ({table_idx+1}/{len(creation_order)})")
                table_schema = schema_manager.get_table_schema(table_name)
                
                rows_generated = 0
                pb = progress_bar.progress(0, text=f"Generating {table_name}...")
                
                while rows_generated < rows:
                    current_batch_size = min(batch_size, rows - rows_generated)
                    query, batch_data = data_generator.generate_batch(table_schema, sample_keys_dict, current_batch_size)
                    
                    if batch_data:
                        db_loader.execute_many(query, batch_data)
                        rows_generated += len(batch_data)
                        
                        # Update progress bar
                        progress_pct = min(1.0, rows_generated / rows)
                        pb.progress(progress_pct, text=f"[{table_name}] Inserted {rows_generated}/{rows}")
                    else:
                        break
                        
                pb.empty() # Clear progress bar for next table
                
                # Post-Insert Bounded Sampling
                # For composite primary keys, we sample the first column for FK lookups to avoid massive generator rewrite
                pk_cols = table_schema.get('primary_key_columns', [])
                if pk_cols:
                    pk_col = pk_cols[0]
                    sample_keys = db_loader.fetch_sample_keys(table_name, pk_col)
                    sample_keys_dict[table_name] = sample_keys
                    
            status_text.info("Applying Foreign Key Constraints...")
            for table_name in creation_order:
                fk_ddls = schema_manager.generate_fk_ddl(table_name)
                for ddl in fk_ddls:
                    db_loader.execute_ddl(ddl, ignore_errors=[2275])
                    
            # --- PL/SQL Compilation ---
            status_text.info("Compiling Procedures & Functions...")
            for proc in schema_manager.get_procedures():
                plsql_code = schema_manager.read_plsql_file(proc['file_path'])
                db_loader.execute_plsql(plsql_code, proc['name'], "PROCEDURE")
                
            for func in schema_manager.get_functions():
                plsql_code = schema_manager.read_plsql_file(func['file_path'])
                db_loader.execute_plsql(plsql_code, func['name'], "FUNCTION")
                
            status_text.info("Compiling Triggers...")
            for trg in schema_manager.get_triggers():
                plsql_code = schema_manager.read_plsql_file(trg['file_path'])
                db_loader.execute_plsql(plsql_code, trg['name'], "TRIGGER")
                    
            status_text.success("🎉 Process completed successfully!")
            
            # Cleanup
            os.remove(tmp_schema_path)
            
        except Exception as e:
            status_text.error(f"❌ Process failed: {e}")
            logger.error(f"Process failed: {e}")
        finally:
            logger.removeHandler(sl_handler)

with tab_explore:
    st.subheader("📊 Explore Generated Data")
    st.markdown("View tables generated in the current database.")
    
    try:
        explore_sys = get_db_loader(db_user, db_password, db_dsn)
        
        # Fetch all non-system schemas
        with explore_sys.connection.cursor() as cursor:
            cursor.execute("SELECT username FROM all_users WHERE oracle_maintained = 'N' ORDER BY username")
            schemas = [row[0] for row in cursor.fetchall()]
            
        if schemas:
            col_schema, col_del = st.columns([4, 1])
            with col_schema:
                selected_schema = st.selectbox("Select Schema", schemas)
            with col_del:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑️ Delete Entire Schema", type="primary"):
                    explore_sys.drop_user(selected_schema)
                    st.success(f"Deleted schema {selected_schema}!")
                    st.rerun()
                    
            if selected_schema:
                # Fetch tables for the selected schema
                with explore_sys.connection.cursor() as cursor:
                    cursor.execute(f"SELECT table_name FROM all_tables WHERE owner = '{selected_schema}' ORDER BY table_name")
                    tables = [row[0] for row in cursor.fetchall()]
                    
                if tables:
                    col_sel, col_btn = st.columns([4, 1])
                    with col_sel:
                        selected_table = st.selectbox("Select Table", tables)
                    with col_btn:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("🔄 Refresh Data"):
                            pass 
                            
                    if selected_table:
                        # Query table data using fully qualified name
                        import pandas as pd
                        query = f"SELECT * FROM {selected_schema}.{selected_table} FETCH FIRST 100 ROWS ONLY"
                        df = pd.read_sql(query, explore_sys.connection)
                        st.dataframe(df, use_container_width=True)
                        
                        # Show total row count
                        with explore_sys.connection.cursor() as cursor:
                            cursor.execute(f"SELECT COUNT(*) FROM {selected_schema}.{selected_table}")
                            total_rows = cursor.fetchone()[0]
                        st.info(f"Total rows in {selected_schema}.{selected_table}: {total_rows} (Showing top 100)")
                else:
                    st.info(f"No tables found in schema {selected_schema}.")
        else:
            st.info("No schemas found. Run the generator first!")
            
    except Exception as e:
        st.error(f"Could not connect to database or fetch data: {e}")
