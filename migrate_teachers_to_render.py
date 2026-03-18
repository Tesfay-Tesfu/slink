import sqlite3
import psycopg2

# Local SQLite database (with your teachers data)
SQLITE_PATH = '/Users/mahdermuez/Documents/Soli_Website_Final/instance/simple_solimicrolink.db'

# Render PostgreSQL
PG_CONNECTION = "postgresql://slink_db_user:kR1r9mtFfCsPu4geyaRp2TZ6nqiK7OVv@dpg-d6sg8b7fte5s73f7hmcg-a.oregon-postgres.render.com/slink_db?sslmode=require"

print("🔄 Connecting to databases...")

# Connect to SQLite
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row
sqlite_cursor = sqlite_conn.cursor()

# Check teachers in SQLite
sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='teachers'")
if not sqlite_cursor.fetchone():
    print("❌ Teachers table not found in SQLite!")
    exit(1)

sqlite_cursor.execute("SELECT COUNT(*) FROM teachers")
teacher_count = sqlite_cursor.fetchone()[0]
print(f"✅ SQLite has {teacher_count} teachers")

if teacher_count == 0:
    print("❌ No teachers to migrate!")
    exit(0)

# Connect to PostgreSQL
pg_conn = psycopg2.connect(PG_CONNECTION)
pg_cursor = pg_conn.cursor()
print("✅ Connected to PostgreSQL")

# Clear existing teachers
print("\n🗑️ Clearing existing teachers...")
try:
    pg_cursor.execute("DELETE FROM teachers;")
    print("  Cleared teachers table")
except Exception as e:
    print(f"  Could not clear teachers: {e}")

# Get all teachers from SQLite
sqlite_cursor.execute("SELECT * FROM teachers ORDER BY id")
teachers = sqlite_cursor.fetchall()

# Get column names
sqlite_cursor.execute("PRAGMA table_info(teachers)")
columns = [col[1] for col in sqlite_cursor.fetchall()]
print(f"\nColumns: {columns}")

# Migrate teachers
print("\n📊 Migrating teachers...")
success_count = 0

for row in teachers:
    try:
        teacher_dict = dict(zip(columns, row))
        
        # Handle boolean values
        is_active = 'TRUE' if teacher_dict.get('is_active', 1) == 1 else 'FALSE'
        
        # Handle NULL values
        photo_url = f"'{teacher_dict['photo_url']}'" if teacher_dict.get('photo_url') else 'NULL'
        bio = f"'{teacher_dict['bio']}'" if teacher_dict.get('bio') else 'NULL'
        
        insert_sql = f"""
            INSERT INTO teachers (
                id, name, subject, department, rating, reviews_count,
                bio, photo_url, is_active, created_at
            ) VALUES (
                {teacher_dict['id']},
                '{teacher_dict['name']}',
                '{teacher_dict['subject']}',
                '{teacher_dict['department']}',
                {teacher_dict.get('rating', 0)},
                {teacher_dict.get('reviews_count', 0)},
                {bio},
                {photo_url},
                {is_active}::boolean,
                '{teacher_dict['created_at']}'
            )
        """
        
        pg_cursor.execute(insert_sql)
        print(f"  ✅ {teacher_dict['name']}")
        success_count += 1
        
    except Exception as e:
        print(f"  ❌ {teacher_dict.get('name', 'Unknown')}: {e}")
        pg_conn.rollback()
        pg_cursor = pg_conn.cursor()

# Commit
if success_count > 0:
    pg_conn.commit()
    print(f"\n✅ Successfully migrated {success_count} teachers to PostgreSQL!")
else:
    print("\n❌ No teachers were migrated")
    pg_conn.rollback()

# Verify
try:
    pg_cursor.execute("SELECT COUNT(*) FROM teachers")
    pg_count = pg_cursor.fetchone()[0]
    print(f"📊 PostgreSQL now has {pg_count} teachers")
    
    if pg_count > 0:
        pg_cursor.execute("SELECT id, name, subject FROM teachers LIMIT 5")
        print("\nSample teachers in PostgreSQL:")
        for row in pg_cursor.fetchall():
            print(f"  - {row[1]} ({row[2]})")
except Exception as e:
    print(f"❌ Could not verify: {e}")

# Close connections
sqlite_conn.close()
pg_conn.close()
