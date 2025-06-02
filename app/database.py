# app/database.py
import sqlite3
import os
from flask import g, current_app, has_app_context
import click

def get_current_db_name():
    """Helper untuk mendapatkan nama DB saat ini dari g atau error jika tidak diset."""
    if not hasattr(g, 'current_db_name') or not g.current_db_name:
        # Jika dalam konteks CLI dan tidak diset, mungkin tidak masalah.
        # Tapi jika dalam konteks request, ini masalah.
        if has_app_context() and not current_app.config.get('TESTING', False): # Jangan error saat testing jika tidak diset
             raise RuntimeError("Database name (g.current_db_name) not set for the current context.")
        return None # Atau nama default jika ada, tapi untuk kasus ini lebih baik None
    return g.current_db_name

def _init_db_internal(db_name, app_context):
    if not db_name:
        click.echo("Nama database tidak valid untuk inisialisasi.")
        return

    db_path = os.path.join(app_context.instance_path, db_name)
    os.makedirs(app_context.instance_path, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    try:
        # Pastikan path ke schema.sql benar relatif terhadap app_context.root_path atau current_app.root_path
        # Jika schema.sql ada di root proyek, dan app_context adalah 'app'
        schema_path = os.path.join(app_context.root_path, '..', 'schema.sql')
        with app_context.open_resource(schema_path) as f:
            conn.executescript(f.read().decode('utf8'))
        conn.commit()
        click.echo(f"Database '{db_name}' telah diinisialisasi di '{app_context.instance_path}'.")
    except Exception as e:
        click.echo(f"Error saat inisialisasi database '{db_name}': {e}")
    finally:
        conn.close()

def get_db():
    """Mendapatkan koneksi database untuk db_name yang ada di g.current_db_name."""
    db_name = get_current_db_name()
    if not db_name: # Bisa terjadi jika dipanggil di luar konteks request yang tepat
        return None 

    # Cek apakah kita sudah punya koneksi ke DB yang benar di 'g'
    if 'db' not in g or g.get('_active_db_name') != db_name:
        db_path = os.path.join(current_app.instance_path, db_name)
        
        # Inisialisasi DB jika belum ada
        if not os.path.exists(db_path) and current_app.config.get('AUTO_INIT_DB', True):
            click.echo(f"Database '{db_name}' tidak ditemukan. Melakukan inisialisasi otomatis...")
            _init_db_internal(db_name, current_app) # Gunakan current_app untuk konteks

        g.db = sqlite3.connect(
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
        g._active_db_name = db_name # Simpan nama DB yang koneksinya aktif
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
    g.pop('_active_db_name', None) # Hapus juga penanda nama DB aktif

def query_db(query, args=(), one=False):
    db = get_db()
    if not db:
        # Ini bisa terjadi jika dipanggil di luar konteks yang benar,
        # atau jika get_current_db_name() mengembalikan None.
        raise RuntimeError("Tidak dapat melakukan query, koneksi database tidak tersedia.")
    cur = db.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

@click.command('init-db')
@click.option('--institution', default=None, help="Tag target (misal, ipb_ac_id).")
@click.option('--method', default=None, help="Metode crawling (misal, bfs).")
def init_db_command(institution, method): 
    """Menginisialisasi database spesifik secara manual (jarang diperlukan)."""
    app_ctx = current_app._get_current_object() # Dapatkan app object untuk open_resource
    
    if institution and method: 
        db_name = f"{institution}_{method}.db"
        _init_db_internal(db_name, app_ctx)
    else:
        click.echo("Gunakan '--institution <tag_target>' dan '--method <metode>' untuk inisialisasi manual.")
        click.echo("Normalnya, aplikasi akan auto-inisialisasi DB saat crawling pertama untuk target baru.")

def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.config.setdefault('AUTO_INIT_DB', True)