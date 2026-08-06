import json
import requests
import time
import re

class SchemaTranslator:
    def __init__(self, api_key: str, dialect: str):
        self.api_key = api_key
        self.dialect = dialect
        self.endpoint = "https://api.sarvam.ai/v1/chat/completions"

    def _get_system_prompt(self) -> str:
        dialect = self.dialect.upper()

        # ==========================================
        # COMMON RULES (Applies to both dialects)
        # ==========================================
        common_rules = """
5. PROCEDURES, FUNCTIONS & TRIGGERS (EMBEDDED DDL):
  * You MUST generate the FULL, valid DDL statement including headers (e.g., `CREATE OR REPLACE...` or `CREATE OR ALTER...`).
  * DO NOT generate headless or anonymous `BEGIN...END` blocks without the CREATE header.
  * Place the generated code directly into the `"sql_body"` field.

6. NULLABILITY & CONSTRAINTS (CRITICAL):
  * You MUST strictly obey the `nullable` field to prevent NOT NULL constraint violations.
  * Faker providers MUST NOT generate duplicates for Primary Key or Unique columns.

7. STRICT JSON KEYS & RELATIONSHIPS (CRITICAL):
  * Use EXACTLY the keys shown in the template below. 
  * For foreign_keys: Use ONLY `"column"`, `"references_table"`, and `"references_column"`.
  * EXACT SPELLING: The `"references_table"` MUST exactly match the spelled name of a table defined in the `"tables"` array to prevent invalid identifier or object mapping errors.

EXPECTED JSON SCHEMA TEMPLATE:
{
  "tables": [
    {
      "name": "VALID_TABLE_NAME",
      "columns": [
        {"name": "VALID_COL_NAME", "type": "DIALECT_TYPE_WITH_SIZE", "nullable": false, "auto_generated": false, "faker": "safe_faker_provider"}
      ],
      "primary_key_columns": ["VALID_COL_NAME"],
      "indexes": [
        {"name": "IDX_NAME", "columns": ["VALID_COL_NAME"]}
      ],
      "foreign_keys": [
        {"column": "LOCAL_COL", "references_table": "TARGET_TABLE", "references_column": "TARGET_COL"}
      ]
    }
  ],
  "procedures": [],
  "functions": [],
  "triggers": []
}

OUTPUT FORMAT:
- Output ONLY valid JSON matching the template exactly.
- NO markdown blocks (e.g. ```json).
- NO conversational text.
"""

        # ==========================================
        # ISOLATED MSSQL PROMPT
        # ==========================================
        if dialect == "MSSQL":
            return f"""You are a strict, enterprise-grade database schema translation engine. 
Your ONLY purpose is to translate unstructured text into a perfectly formatted JSON schema that strictly adheres to Microsoft SQL Server documentation.

CRITICAL RULES FOR MSSQL (PYODBC FAST_EXECUTEMANY SAFE MODE):
1. DATA TYPE MAPPING (PREVENT 22003 & 8115 OVERFLOWS):
  * Numeric: Convert ALL integers (INT, SMALLINT) to `INT`. Large integers to `BIGINT`. Decimals/Numerics to `FLOAT`. 
  * STRICT SIZING: You MUST strip all size/precision modifiers from numerics. Output exact strings `INT`, `BIGINT`, or `FLOAT`. Never output `FLOAT(18,4)` or `INT(10)` to prevent PyODBC out of range exceptions.
  * Booleans: Convert BIT/BOOLEAN to `TINYINT`.
  * Strings: Convert VARCHAR/TEXT to `NVARCHAR(255)` to prevent string truncation (8152/2628).
  * Dates/Times: Convert ALL date/time types to `VARCHAR(50)`. NEVER output `DATETIME2` or `DATETIME`. This entirely bypasses invalid datetime (22007) and invalid character cast (22018) errors during fast_executemany bulk inserts.
  * UUIDs/GUIDs: Convert UUID/GUID to `VARCHAR(50)` and set `"auto_generated": false` to prevent invalid GUID (8169) and cast (22018) errors.

2. AUTO-INCREMENT:
  * You MUST physically append `IDENTITY(1,1)` to the string in the type field for INT or BIGINT Primary Keys (e.g., `"type": "BIGINT IDENTITY(1,1)"`), AND set `"auto_generated": true`.

3. STRICT FAKER MATRIX (MEMORY ALIGNMENT):
  * `INT` or `BIGINT` -> MUST use "random_int".
  * `FLOAT` -> MUST use "pyfloat". 
  * `TINYINT` -> MUST use "random_digit" to stay strictly within the 0-255 bounds.
  * `VARCHAR(50)` acting as Date/Time -> MUST use "iso8601".
  * `VARCHAR(50)` acting as UUID -> MUST use "uuid4".
  * `NVARCHAR(255)` -> MUST use a text provider ("word", "sentence", "name", "email").

4. IDENTIFIER NAMING: Replace ANY spaces with underscores. Append "_val" to SQL reserved words to prevent syntax (102) and invalid column (207) errors.
{common_rules}
"""

        # ==========================================
        # ISOLATED ORACLE PROMPT
        # ==========================================
        elif dialect == "ORACLE":
            return f"""You are a strict, enterprise-grade database schema translation engine. 
Your ONLY purpose is to translate unstructured text into a perfectly formatted JSON schema that strictly adheres to Oracle 19c/23c documentation.

CRITICAL RULES FOR ORACLE (NATIVE DRIVER SAFE MODE):
1. DATA TYPE MAPPING:
  * Numeric: Convert INT, BIGINT, FLOAT, DECIMAL to `NUMBER`.
  * Strings: Convert VARCHAR, TEXT, NVARCHAR to `VARCHAR2(255)`.
  * Dates/Times: Convert DATETIME, TIME, DATE to `TIMESTAMP`.
  * UUIDs/GUIDs: Convert to `VARCHAR2(50)` and set `"auto_generated": false`.

2. AUTO-INCREMENT:
  * ONLY if a column is a NUMERIC Primary Key, use `NUMBER GENERATED BY DEFAULT AS IDENTITY` and set `"auto_generated": true`.

3. STRICT FAKER MATRIX (PREVENT ORA-01858 & TYPE CRASHES):
  * `NUMBER` (for IDs/Counters) -> MUST use "random_int". NEVER assign a text provider to a NUMBER column.
  * `NUMBER` (for Currency/Floats) -> MUST use "pyfloat".
  * `TIMESTAMP` -> MUST use "date_time". (CRITICAL: Oracle strictly requires native python datetime objects. NEVER use "iso8601" or string dates, as this triggers ORA-01858 invalid month parsing errors).
  * `VARCHAR2(50)` acting as UUID -> MUST use "uuid4".
  * `VARCHAR2(255)` -> MUST use a text provider ("word", "sentence", "name", "email").

4. IDENTIFIER NAMING: Replace ANY spaces with underscores. Append "_val" to SQL reserved words to prevent invalid identifier exceptions.
{common_rules}
"""

        else:
            raise ValueError(f"Unsupported dialect passed to prompt builder: {{dialect}}")

    def _sanitize_json_output(self, raw_str: str) -> str:
        if not raw_str:
            return "{}"
            
        # 1. Strip markdown formatting
        clean_str = re.sub(r'^```(?:json)?\s*', '', raw_str.strip(), flags=re.MULTILINE | re.IGNORECASE)
        clean_str = re.sub(r'```\s*$', '', clean_str).strip()
        
        # 2. Extract strictly the JSON object bounds
        start_idx = clean_str.find('{')
        end_idx = clean_str.rfind('}')
        
        if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
            return clean_str[start_idx:end_idx + 1]
            
        return clean_str

    def translate_to_json(self, raw_text: str) -> str:
        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "sarvam-105b",
            "messages": [
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": f"Translate this schema directly to JSON without any reasoning or conversational text:\n\n{raw_text}"}
            ],
            "temperature": 0.0,
            "max_tokens": 4096,
            "reasoning_effort": None  # Disables the chain-of-thought processing
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.endpoint, 
                    headers=headers, 
                    json=payload, 
                    timeout=120  # Safe timeout limit
                )
                
                # Check for 400 Bad Request or 500 errors
                response.raise_for_status()
                response_data = response.json()
                
                # Safe JSON Extraction
                try:
                    content = response_data['choices'][0]['message']['content']
                    if not content:
                        raise ValueError("Content returned from API is None.")
                        
                    sanitized_json = self._sanitize_json_output(content)
                    
                    # Validate JSON parses correctly before returning to UI
                    json.loads(sanitized_json)
                    return sanitized_json
                    
                except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
                    print(f"JSON Parsing failed. Raw API Response: {response_data}")
                    raise RuntimeError(f"The API returned an invalid structure. Error: {str(e)}")
                    
            except requests.exceptions.RequestException as e:
                print(f"API Request failed on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2)