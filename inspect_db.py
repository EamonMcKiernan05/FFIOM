import sqlite3, json

p = r"C:\Users\Eamon\Desktop\FFIOM\fantasy_iom.db"
con = sqlite3.connect(p)
tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
print("TABLES:", tables)
for t in tables:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    cols = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
    print(f"\n{t}: {n} rows")
    print("  cols:", cols)
