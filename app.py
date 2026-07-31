import streamlit as st
import json
import logging
import tempfile
import os
from streamlit_ace import st_ace

from schema_manager import SchemaManager
from db_loader import DBLoader
from data_generator import DataGenerator
from config import logger

# --- Streamlit Page Config ---
st.set_page_config(page_title="Oracle Schema Builder", page_icon="🗄️", layout="wide")

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

# --- DB Connection Caching ---
@st.cache_resource
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
    db_user = st.text_input("Username", value="system")
    db_password = st.text_input("Password", value="DevPassword123", type="password")
    db_dsn = st.text_input("DSN (Host:Port/Service)", value="localhost:1521/FREEPDB1")
    
    st.subheader("Generation Settings")
    rows = st.number_input("Rows per Table", min_value=1, value=1000, step=100)
    batch_size = st.number_input("Batch Size", min_value=1, value=10000, step=100)
    force = st.checkbox("Force Recreate (Drop existing)", value=True)
    
    run_btn = st.button("🚀 Run Generator", type="primary", use_container_width=True)

# Load default schema
if 'schema_json' not in st.session_state:
    try:
        with open("schema_example.json", "r") as f:
            st.session_state.schema_json = f.read()
    except FileNotFoundError:
        st.session_state.schema_json = "{}"

# Main content area
tab_gen, tab_explore = st.tabs(["⚙️ Generator", "📊 Data Explorer"])

with tab_gen:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📝 Schema Editor")
        st.markdown("Edit the JSON schema below. Changes are saved automatically.")
        
        # st_ace editor
        edited_schema = st_ace(
            value=st.session_state.schema_json,
            language='json',
            theme='dracula',
            height=500,
            font_size=14,
            key="ace_editor"
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
                
            status_text.info("Connecting to Database...")
            db_loader = get_db_loader(db_user, db_password, db_dsn)
            
            schema_manager = SchemaManager(tmp_schema_path)
            data_generator = DataGenerator()
            
            if force:
                status_text.info("Dropping existing tables...")
                for table_name in schema_manager.get_drop_order():
                    ddl = schema_manager.generate_drop_ddl(table_name)
                    db_loader.execute_ddl(ddl, ignore_errors=[942])
                    
            status_text.info("Creating tables...")
            creation_order = schema_manager.get_creation_order()
            for table_name in creation_order:
                ddl = schema_manager.generate_create_ddl(table_name)
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
                pk_col = next((col['name'] for col in table_schema['columns'] if col.get('primary_key')), None)
                if pk_col:
                    sample_keys = db_loader.fetch_sample_keys(table_name, pk_col)
                    sample_keys_dict[table_name] = sample_keys
                    
            status_text.info("Applying Foreign Key Constraints...")
            for table_name in creation_order:
                fk_ddls = schema_manager.generate_fk_ddl(table_name)
                for ddl in fk_ddls:
                    db_loader.execute_ddl(ddl, ignore_errors=[2275])
                    
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
        explore_db = get_db_loader(db_user, db_password, db_dsn)
        
        # Fetch all user tables, filtering out Oracle internal system tables (which usually contain '$' or '#')
        with explore_db.connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM user_tables WHERE table_name NOT LIKE '%$%' AND table_name NOT LIKE '%#%' ORDER BY table_name")
            tables = [row[0] for row in cursor.fetchall()]
            
        if tables:
            col_sel, col_btn = st.columns([4, 1])
            with col_sel:
                selected_table = st.selectbox("Select Table", tables)
            with col_btn:
                st.markdown("<br>", unsafe_allow_html=True) # padding
                if st.button("🔄 Refresh Data"):
                    pass # Just reruns
                    
            if selected_table:
                # Query table data
                import pandas as pd
                query = f"SELECT * FROM {selected_table} FETCH FIRST 100 ROWS ONLY"
                df = pd.read_sql(query, explore_db.connection)
                st.dataframe(df, use_container_width=True)
                
                # Show total row count
                with explore_db.connection.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) FROM {selected_table}")
                    total_rows = cursor.fetchone()[0]
                st.info(f"Total rows in {selected_table}: {total_rows} (Showing top 100)")
        else:
            st.info("No tables found. Run the generator first!")
            
    except Exception as e:
        st.error(f"Could not connect to database or fetch data: {e}")
