
# migrate_prices_only.py - SAFE migration that preserves all data
import sqlite3
import os
import sys

def migrate_prices_only():
    print("\n" + "="*70)
    print("🔄 SAFE MIGRATION - UPDATING PRICES ONLY")
    print("="*70)
    print("⚠️  This will ONLY update service prices")
    print("✅ All other data (users, bookings, reviews) will be PRESERVED")
    print("="*70 + "\n")
    
    # Check if SQLite database exists
    sqlite_path = 'instance/simple_solimicrolink.db'
    if not os.path.exists(sqlite_path):
        print(f"❌ SQLite database not found at {sqlite_path}")
        return False
    
    print(f"✅ Found SQLite database with NEW prices")
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Get PostgreSQL URL from environment
    postgres_url = os.environ.get('DATABASE_URL')
    if not postgres_url:
        print("❌ DATABASE_URL not set - run this on Render Shell")
        return False
    
    if postgres_url.startswith('postgres://'):
        postgres_url = postgres_url.replace('postgres://', 'postgresql://', 1)
    
    try:
        import psycopg2
        pg_conn = psycopg2.connect(postgres_url)
        pg_cursor = pg_conn.cursor()
        print("✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return False
    
    # Get current prices from PostgreSQL (for verification)
    print("\n📊 CURRENT PRICES IN POSTGRESQL (LIVE SITE):")
    pg_cursor.execute("SELECT id, name, price FROM services WHERE category IN ('data', 'research', 'training') ORDER BY category, id")
    current_prices = pg_cursor.fetchall()
    for id, name, price in current_prices[:5]:
        print(f"  ID {id}: {name[:30]}... - ${price}")
    print(f"  ... and {len(current_prices)-5} more")
    
    # Get NEW prices from SQLite
    sqlite_cursor.execute("SELECT id, name, price, discounted_price FROM services")
    new_prices = sqlite_cursor.fetchall()
    print(f"\n📊 NEW PRICES FROM SQLITE:")
    for id, name, price, discounted in new_prices[:5]:
        print(f"  ID {id}: {name[:30]}... - ${price}")
    
    # Update prices one by one (safe, preserves all other data)
    print("\n🔄 UPDATING PRICES...")
    updated = 0
    for id, name, price, discounted in new_prices:
        try:
            pg_cursor.execute("""
                UPDATE services 
                SET price = %s, discounted_price = %s 
                WHERE id = %s
            """, (price, discounted, id))
            if pg_cursor.rowcount > 0:
                updated += 1
                if updated % 5 == 0:
                    print(f"  ✅ Updated {updated} services...")
        except Exception as e:
            print(f"  ❌ Failed to update ID {id} ({name}): {e}")
    
    pg_conn.commit()
    
    # Verify the update
    print("\n📊 VERIFYING UPDATES IN POSTGRESQL:")
    pg_cursor.execute("""
        SELECT category, COUNT(*), MIN(price), MAX(price), AVG(price)
        FROM services 
        WHERE category IN ('data', 'research', 'training')
        GROUP BY category
    """)
    
    for category, count, min_price, max_price, avg_price in pg_cursor.fetchall():
        print(f"  {category.upper()}: {count} courses | ${min_price:.0f} - ${max_price:.0f} | Avg: ${avg_price:.0f}")
    
    # Show sample of updated training prices
    print("\n📊 UPDATED TRAINING PRICES (should be $1499 each):")
    pg_cursor.execute("SELECT id, name, price FROM services WHERE category='training'")
    for id, name, price in pg_cursor.fetchall():
        print(f"  [{id}] {name}: ${price}")
    
    sqlite_conn.close()
    pg_conn.close()
    
    print(f"\n✅ Successfully updated {updated} service prices!")
    print("✅ All other data (users, bookings, reviews) was preserved!")
    return True

if __name__ == '__main__':
    success = migrate_prices_only()
    sys.exit(0 if success else 1)
