import pyodbc
c = pyodbc.connect('Driver={SQL Server};Server=127.0.0.1,1433;Database=master;UID=sa;PWD=YourStrong@Passw0rd', autocommit=True)
cr = c.cursor()
cr.execute("SELECT name, OBJECT_SCHEMA_NAME(object_id), OBJECT_SCHEMA_NAME(parent_object_id), OBJECT_NAME(parent_object_id) FROM sys.foreign_keys WHERE name = 'FK_CUSTOMER_KYC_CUSTOMER_ID_0'")
for row in cr.fetchall():
    print(row)
