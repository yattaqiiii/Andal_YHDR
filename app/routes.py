# app/routes.py
import os
from flask import (
    Blueprint, render_template, request, redirect, url_for, g, flash, session, current_app
)
from urllib.parse import urlparse, quote, unquote
import datetime
from app.database import query_db, get_db, _init_db_internal
from app.crawlers import WebCrawlerBFS, WebCrawlerDFS

bp = Blueprint('main', __name__)

def get_display_name_for_tag(tag_to_display):
    if not tag_to_display:
        return "Tidak Diketahui"
    processed_tag = tag_to_display
    if processed_tag.startswith("manual_"):
        processed_tag = processed_tag[len("manual_"):]
    if processed_tag.startswith("www_"):
        processed_tag = processed_tag[len("www_"):]
    return processed_tag.replace('_', '.')

def generate_db_name(institution_tag, crawl_method):
    # Helper ini mungkin tidak banyak berubah, tapi pastikan konsisten
    return f"{institution_tag}_{crawl_method}.db"

def parse_db_filename(db_filename):
    """ Parses institution_tag and crawl_method from a db_filename. """
    if not db_filename.endswith(".db"):
        return None, None
    base_name = db_filename[:-3]
    parts = base_name.split('_')
    if len(parts) >= 2:
        method = parts[-1]
        tag = '_'.join(parts[:-1])
        # Validasi sederhana, bisa diperkuat jika CRAWL_METHODS lebih dinamis
        if method in current_app.config.get('CRAWL_METHODS', ['bfs', 'dfs']) and tag:
            return tag, method
    return None, None

@bp.before_app_request
def make_current_year_available():
    g.current_year = datetime.datetime.now().year

@bp.route('/', methods=['GET'])
def index():
    # selected_db_file_from_arg akan menampung nama file DB jika ada argumen 'db_target'
    selected_db_file_from_arg = request.args.get('db_target')
    keyword_prefili_from_arg = request.args.get('keyword', '')

    crawl_methods_cfg = current_app.config.get('CRAWL_METHODS', ['bfs', 'dfs'])
    max_depth_cfg = current_app.config.get('MAX_DEPTH_LIMIT_DEFAULT', 2)
    max_pages_cfg = current_app.config.get('MAX_PAGES_DEFAULT', 50)
    
    # options_for_dropdown sekarang akan berisi daftar database file
    # format: {'value': 'itb_ac_id_bfs.db', 'name': 'itb.ac.id (BFS)'}
    options_for_dropdown = []
    instance_path = current_app.instance_path
    try:
        if not os.path.exists(instance_path):
            current_app.logger.info(f"Folder instance '{instance_path}' tidak ditemukan, akan dibuat.")
            os.makedirs(instance_path, exist_ok=True)
            
        for filename in os.listdir(instance_path):
            if filename.endswith(".db"):
                institution_tag_from_file, method_from_file = parse_db_filename(filename)
                if institution_tag_from_file and method_from_file in crawl_methods_cfg:
                    display_name = get_display_name_for_tag(institution_tag_from_file)
                    options_for_dropdown.append({
                        'value': filename, # Value adalah nama file DB nya
                        'name': f"{display_name} ({method_from_file.upper()})"
                    })
                            
    except Exception as e:
        current_app.logger.error(f"Error saat memindai folder instance untuk DB: {e}")
        
    options_for_dropdown.sort(key=lambda x: x['name']) # Urutkan berdasarkan nama tampilan
    
    final_selected_db_target = None
    if selected_db_file_from_arg and any(opt['value'] == selected_db_file_from_arg for opt in options_for_dropdown):
        final_selected_db_target = selected_db_file_from_arg
    elif options_for_dropdown: 
        final_selected_db_target = options_for_dropdown[0]['value'] # Pilih yang pertama jika ada

    # 'selected_institution_tag' diubah menjadi 'selected_db_target_for_view'
    # 'targets_for_dropdown' sekarang berisi daftar DB
    return render_template('index.html',
                           project_name=current_app.config.get('PROJECT_NAME', 'Doksli Mint'),
                           db_targets_for_dropdown=options_for_dropdown, # Ganti nama variabel
                           selected_db_target=final_selected_db_target, # Ganti nama variabel
                           max_depth_limit_default=max_depth_cfg,
                           max_pages_default=max_pages_cfg,
                           crawl_methods=crawl_methods_cfg,
                           keyword_prefili=keyword_prefili_from_arg
                           )

@bp.route('/initiate_action', methods=['POST'])
def initiate_action_route():
    keyword = request.form.get('keyword', '').strip()
    target_type = request.form.get('target_type', 'institution')
    
    final_institution_tag = None
    final_crawl_method = None
    default_max_depth = current_app.config.get('MAX_DEPTH_LIMIT_DEFAULT', 2)
    default_max_pages = current_app.config.get('MAX_PAGES_DEFAULT', 50) # Default untuk scraping
    max_depth_from_form = default_max_depth
    max_pages_from_form = default_max_pages 
    clear_data_flag = False
    manual_seed_url_to_pass = None

    if target_type == 'institution':
        selected_db_file = request.form.get('selected_db_file') 
        if not selected_db_file:
            flash("Tidak ada target database tersimpan yang dipilih.", "danger")
            return redirect(url_for('main.index', keyword=keyword))
        tag_from_db, method_from_db = parse_db_filename(selected_db_file)
        if not tag_from_db or not method_from_db:
            flash(f"Format file database '{selected_db_file}' tidak valid.", "danger")
            return redirect(url_for('main.index', keyword=keyword))
        final_institution_tag = tag_from_db
        final_crawl_method = method_from_db
        if not keyword: 
             flash("Kata kunci wajib diisi untuk melakukan pencarian pada target tersimpan.", "danger")
             return redirect(url_for('main.index', db_target=selected_db_file))
        # Untuk 'institution', max_pages, max_depth, clear_data diabaikan (default)
        # karena hanya search, keyword sudah divalidasi.
        max_pages_from_form = 0 # Eksplisit set 0 karena tidak ada crawl

    elif target_type == 'manual_url':
        manual_seed_url_form = request.form.get('manual_seed_url', '').strip()
        manual_seed_url_to_pass = manual_seed_url_form
        final_crawl_method = request.form.get('crawl_method', 'bfs') 
        clear_data_flag = request.form.get('clear_data_on_search_crawl') == 'yes'
        keyword = "" # Keyword diabaikan/dikosongkan untuk mode scraping murni

        if not manual_seed_url_form:
            flash("Seed URL manual baru wajib diisi untuk scraping.", "danger")
            return redirect(url_for('main.index'))
        try:
            # ... (validasi URL dan pembuatan final_institution_tag seperti sebelumnya) ...
            parsed_url_val = urlparse(manual_seed_url_form)
            if not parsed_url_val.scheme or not parsed_url_val.netloc or parsed_url_val.scheme not in ['http', 'https']:
                raise ValueError("URL tidak valid atau skema bukan http/https.")
            domain_from_parser = parsed_url_val.netloc 
            cleaned_domain = domain_from_parser.lower().replace("www.", "")
            final_institution_tag = cleaned_domain.replace('.', '_').replace('-', '_')
        except ValueError as e_val:
            flash(f"Seed URL manual tidak valid: {e_val}", "danger")
            return redirect(url_for('main.index'))
        
        try: 
            max_depth_str = request.form.get('max_depth', str(default_max_depth))
            max_depth_from_form = int(max_depth_str) if max_depth_str.strip() else default_max_depth
            
            max_pages_str = request.form.get('max_pages', str(default_max_pages))
            # Untuk manual_url, max_pages harus > 0
            max_pages_from_form = int(max_pages_str) if max_pages_str.strip() else 0 # Default ke 0 jika kosong, validasi di bawah
        except ValueError:
            flash("Nilai kedalaman atau maks halaman harus berupa angka.", "danger")
            return redirect(url_for('main.index', manual_seed_url=manual_seed_url_form))

        # Validasi khusus untuk scraping dari URL Manual
        if not (1 <= max_pages_from_form <= 500): # Harus 1-500
            flash(f"Maksimal halaman (untuk scraping) harus antara 1 dan 500.", "danger")
            return redirect(url_for('main.index', manual_seed_url=manual_seed_url_form))
        if not (0 <= max_depth_from_form <= 5): 
            flash(f"Kedalaman maksimal (untuk scraping) harus antara 0 dan 5.", "danger")
            return redirect(url_for('main.index', manual_seed_url=manual_seed_url_form))
    else: 
        flash("Tipe target tidak valid.", "danger")
        return redirect(url_for('main.index'))

    if final_crawl_method not in current_app.config.get('CRAWL_METHODS', ['bfs', 'dfs']):
        flash(f"Metode '{final_crawl_method}' tidak valid.", "danger")
        return redirect(url_for('main.index', keyword=keyword))
    
    session['action_params'] = {
        'keyword': keyword, # Akan kosong jika manual_url
        'target_type': target_type, 
        'institution_tag': final_institution_tag, 
        'crawl_method': final_crawl_method,       
        'manual_seed_url': manual_seed_url_to_pass,
        'max_depth': max_depth_from_form,
        'max_pages': max_pages_from_form, # Akan >0 jika manual_url, 0 jika institution
        'clear_data': clear_data_flag
    }
    return redirect(url_for('main.process_crawling_route'))

@bp.route('/proses_crawling')
def process_crawling_route():
    action_params = session.get('action_params')
    if not action_params:
        flash("Parameter aksi tidak ditemukan.", "warning")
        return redirect(url_for('main.index'))

    keyword = action_params.get('keyword','') # Akan kosong jika target_type 'manual_url'
    target_type = action_params.get('target_type') 
    current_institution_tag_for_db = action_params.get('institution_tag')
    crawl_method = action_params.get('crawl_method','bfs') 
    manual_seed_url_input = action_params.get('manual_seed_url')
    max_depth_to_crawl = action_params.get('max_depth')
    max_pages_to_crawl = action_params.get('max_pages') # Ini akan > 0 untuk manual_url (scraping)
    clear_data_before_crawl = action_params.get('clear_data', False)

    current_seed_url = None # Reset
    current_domain = ""
    current_institution_name = get_display_name_for_tag(current_institution_tag_for_db) # Nama default
    self_log_for_template = []

    if not current_institution_tag_for_db: # Validasi dasar
        flash("Tag institusi untuk target tidak ditemukan dalam parameter.", "danger")
        return redirect(url_for('main.index'))

    # Dapatkan nama institusi untuk tampilan
    current_institution_name = get_display_name_for_tag(current_institution_tag_for_db)
    if target_type == 'manual_url' and manual_seed_url_input:
        try: # Jika manual URL, nama bisa lebih spesifik dari domain inputan asli
            parsed_url = urlparse(manual_seed_url_input)
            current_institution_name = parsed_url.netloc # Ambil dari URL asli
            current_seed_url = manual_seed_url_input # Hanya set seed_url jika manual
            current_domain = current_institution_tag_for_db.replace('_', '.') # Domain dasar untuk crawler
        except Exception:
            pass # Biarkan current_institution_name dari get_display_name_for_tag
    
    # Jika target_type 'institution', tidak ada crawling, jadi pastikan max_pages_to_crawl = 0
    if target_type == 'institution':
        max_pages_to_crawl = 0 
        clear_data_before_crawl = False # Tidak relevan
        if not keyword: # Seharusnya sudah divalidasi di initiate_action
            flash(f"Kata kunci diperlukan untuk mencari di target tersimpan '{current_institution_name}'.", "warning")
            return redirect(url_for('main.index', db_target=generate_db_name(current_institution_tag_for_db, crawl_method)))
        self_log_for_template.append(f"Info: Mode 'Pilih Target Tersimpan'. Hanya pencarian untuk '{keyword}' akan dilakukan pada {current_institution_name} ({crawl_method.upper()}).")

    elif target_type == 'manual_url':
        if not manual_seed_url_input: # Seharusnya sudah divalidasi
            flash("Seed URL manual tidak ada untuk tipe target manual.", "danger")
            return redirect(url_for('main.index', keyword=keyword))
        if not keyword and max_pages_to_crawl <= 0: # Tidak ada aksi
            flash(f"Tidak ada kata kunci untuk dicari dan tidak ada crawling (Maks Halaman <= 0) untuk '{current_institution_name}'.", "warning")
            return redirect(url_for('main.index', keyword=keyword, manual_seed_url=manual_seed_url_input))
    
    g.current_db_name = generate_db_name(current_institution_tag_for_db, crawl_method)
    db_path_for_action = os.path.join(current_app.instance_path, g.current_db_name)
    db_existed_before_init = os.path.exists(db_path_for_action)
    db_was_newly_created_this_request = False

    # Logika Clear DB jika manual_url dan diminta
    if target_type == 'manual_url' and current_seed_url and clear_data_before_crawl and db_existed_before_init:
        try:
            # ... (hapus DB, self_log_for_template, db_existed_before_init = False) ...
            if hasattr(g, 'db') and g.db is not None: g.db.close(); g.db = None
            os.remove(db_path_for_action)
            self_log_for_template.append(f"INFO: Data lama dari '{g.current_db_name}' telah dihapus.")
            db_existed_before_init = False
        except Exception as e_del:
            self_log_for_template.append(f"GAGAL: Tidak bisa menghapus data lama '{g.current_db_name}': {e_del}")
            current_app.logger.error(f"Gagal clear DB {g.current_db_name}: {e_del}")
            # Jika gagal clear, mungkin lebih baik tidak lanjut crawling jika clear itu penting
            # flash(f"Gagal menghapus data lama untuk '{g.current_db_name}'. Proses dihentikan.", "danger")
            # return redirect(url_for('main.index'))

    # Logika Inisialisasi DB jika belum ada dan diperlukan
    should_create_db_flag = not db_existed_before_init and \
                           (keyword or (target_type == 'manual_url' and current_seed_url and max_pages_to_crawl > 0))
    if should_create_db_flag:
        if current_app.config.get('AUTO_INIT_DB', True):
            try:
                _init_db_internal(g.current_db_name, current_app)
                db_was_newly_created_this_request = True
                self_log_for_template.append(f"Database '{g.current_db_name}' diinisialisasi/dibuat.")
            except Exception as e_init:
                self_log_for_template.append(f"Database '{g.current_db_name}' tidak ada dan AUTO_INIT_DB false.")
                g.current_db_name = None
                db_path_for_action = None
    elif db_existed_before_init:
         self_log_for_template.append(f"Database '{g.current_db_name}' sudah ada, akan digunakan.")

    pages_added = 0
    crawl_failed_flag = False
    crawl_log_messages = []
    
    if current_seed_url and max_pages_to_crawl > 0 and target_type == 'manual_url': # Crawl hanya untuk manual_url
        if not g.current_db_name or not os.path.exists(db_path_for_action):
            flash(f"GAGAL SCRAPING: Persiapan database untuk '{current_institution_name}' bermasalah.", "danger")
            crawl_summary = f"Crawling dibatalkan: Database '{g.current_db_name or 'Target DB'}' tidak ditemukan atau gagal diinisialisasi."
            crawl_log_messages.append(crawl_summary)
            return redirect(url_for('main.index', manual_seed_url=manual_seed_url_input))
        else:
            # Logika crawler instance (BFS/DFS) ... (sama seperti sebelumnya)
            crawler_instance = None
            if crawl_method == 'bfs':
                crawler_instance = WebCrawlerBFS(current_institution_tag_for_db, current_seed_url, current_domain, max_depth_to_crawl, max_pages_to_crawl)
            elif crawl_method == 'dfs':
                crawler_instance = WebCrawlerDFS(current_institution_tag_for_db, current_seed_url, current_domain, max_depth_to_crawl, max_pages_to_crawl)
            
            if crawler_instance:
                crawl_log_messages = crawler_instance.crawl() 
                pages_added = sum(1 for msg in crawl_log_messages if 'SUKSES:' in msg) 
                pages_updated = sum(1 for msg in crawl_log_messages if 'UPDATE:' in msg)
                visited_count = getattr(crawler_instance, 'pages_visited_count', 0)
                
                if (pages_added == 0 | pages_added == 1) and db_was_newly_created_this_request:
                    # Logika penghapusan DB baru yang kosong (sama seperti sebelumnya)
                    self_log_for_template.append(f"PERINGATAN: Crawling untuk '{current_institution_name}' tidak menghasilkan data baru.")
                    try:
                        if hasattr(g, 'db') and g.db is not None:
                            app_db = get_db(); # Ini akan mendapatkan g.db
                            if app_db: app_db.close()
                            g.db = None; 
                        if os.path.exists(db_path_for_action):
                           os.remove(db_path_for_action)
                           self_log_for_template.append(f"Database baru '{g.current_db_name}' yang kosong telah dihapus.")
                           current_app.logger.info(f"Database baru dan kosong {g.current_db_name} dihapus.")
                           crawl_summary = f"Crawling '{current_institution_name}' selesai, tidak ada halaman baru. DB baru kosong dihapus."
                           g.current_db_name = None 
                           db_path_for_action = None
                        else:
                           crawl_summary = f"Crawling '{current_institution_name}' selesai, tidak ada halaman baru. DB baru sudah tidak ada."
                        flash(f"Website '{current_institution_name}' tidak bisa melakukan crawling", "danger")
                        return redirect(url_for('main.index'))
                    except Exception as e_del_empty:
                        self_log_for_template.append(f"ERROR: Gagal hapus DB baru kosong '{g.current_db_name or 'DB'}': {e_del_empty}")
                        crawl_summary = f"Crawling '{current_institution_name}' selesai, tidak ada halaman baru. Gagal hapus DB baru kosong."
                else:
                    crawl_summary = f"Crawling ({crawl_method.upper()}) '{current_institution_name}' selesai. DB: '{g.current_db_name}'. {pages_added} baru, {pages_updated} update. Dikunjungi: {visited_count}."
            else: # crawler_instance tidak ada
                crawl_summary = f"Metode crawling '{crawl_method}' tidak dikenal. Tidak ada crawling."
                crawl_log_messages.append(crawl_summary)
    elif keyword: 
        db_name_info = g.current_db_name if g.current_db_name and os.path.exists(db_path_for_action) else "tidak ada/valid"
        crawl_summary = f"Tidak melakukan crawling untuk '{current_institution_name}'. Akan dilakukan pencarian untuk '{keyword}' di DB: {db_name_info} jika ada."
        if target_type == 'manual_url' and max_pages_to_crawl > 0 and not current_seed_url: # Seharusnya tidak terjadi jika validasi benar
            crawl_summary = f"Tidak ada crawling (URL seed tidak valid?). Mencari '{keyword}' di DB: {db_name_info}."
        crawl_log_messages.append(crawl_summary)
    else: # Tidak ada keyword dan tidak crawl
        crawl_summary = f"Tidak ada aksi (crawling atau pencarian) dilakukan untuk '{current_institution_name}'."
        crawl_log_messages.append(crawl_summary)
    
    current_app.logger.info(crawl_summary)
    self_log_for_template.extend(crawl_log_messages)
    
    session['search_params'] = {
        'keyword': keyword,
        'institution_tag': current_institution_tag_for_db, # Tag asli untuk identifikasi
        'institution_name': current_institution_name,      # Nama tampilan
        'crawl_method': crawl_method,                      # Metode yang terkait dengan DB
        'db_name_for_search': g.current_db_name if g.current_db_name and os.path.exists(db_path_for_action or "") else None 
    }
    
    redirect_url_tree = None
    if current_institution_tag_for_db and crawl_method and db_path_for_action and os.path.exists(db_path_for_action) : 
        redirect_url_tree = url_for('main.view_crawl_tree_route', 
                                    institution_tag=current_institution_tag_for_db, 
                                    crawl_method=crawl_method)

    if target_type == 'manual_url' :
        flash(f"Website '{current_institution_name}' sudah berhasil di crawling", "success")
        return redirect(url_for('main.index'))
    elif target_type == 'institution' :
        return redirect(url_for('main.show_search_results_route'))
    
@bp.route('/hasil_pencarian')
def show_search_results_route():
    search_params = session.get('search_params') 
    if not search_params:
        flash("Parameter pencarian tidak ditemukan.", "warning")
        return redirect(url_for('main.index'))

    keyword = search_params.get('keyword','')
    # institution_tag di sini adalah tag asli, bukan nama file DB
    institution_tag_param = search_params.get('institution_tag') 
    institution_name_param = search_params.get('institution_name', 'Tidak Diketahui')
    crawl_method_param = search_params.get('crawl_method', 'bfs')
    db_name_to_search = search_params.get('db_name_for_search') # Ini adalah nama file DB yang valid dari proses_crawling
    
    final_results = []
    error_message_search = None
    # g.current_db_name akan di-set jika db_name_to_search valid
    # g.current_db_name = None # Reset, akan di-set jika DB valid (baris ini bisa dihapus jika g tidak dipakai lintas request selain sesi)

    if not db_name_to_search:
        error_message_search = f"Database untuk '{institution_name_param}' ({crawl_method_param.upper()}) tidak tersedia."
        if not institution_tag_param : # jika tag juga tidak ada
             error_message_search = "Target pencarian (tag/db) tidak valid."

    elif not keyword:
        error_message_search = "Masukkan kata kunci untuk memulai pencarian."
    else:
        g.current_db_name = db_name_to_search 
        db_path = os.path.join(current_app.instance_path, g.current_db_name)

        if not os.path.exists(db_path): # Cek sekali lagi untuk keamanan
            error_message_search = f"Database '{g.current_db_name}' untuk target '{institution_name_param}' tidak ditemukan."
        else:
            search_term_for_query = f"%{keyword}%"
            try:
                raw_results = query_db("""
                    SELECT url, title, content_preview, level, anchor_text, parent_url
                    FROM pages
                    WHERE (LOWER(title) LIKE LOWER(?) OR 
                           LOWER(content_preview) LIKE LOWER(?) OR 
                           LOWER(anchor_text) LIKE LOWER(?))
                    ORDER BY level, title
                """, [search_term_for_query, search_term_for_query, search_term_for_query])
                final_results = [dict(r) for r in raw_results]
                if not final_results:
                    error_message_search = f"Tidak ditemukan hasil untuk '{keyword}' pada '{institution_name_param}' (DB: {g.current_db_name})."
            except Exception as e:
                current_app.logger.error(f"Error query DB {g.current_db_name} di hasil_pencarian: {e}")
                error_message_search = f"Kesalahan saat query database '{g.current_db_name}'."

    return render_template('search_results.html', 
                           project_name=current_app.config.get('PROJECT_NAME','Doksli Mint'),
                           keyword=keyword,
                           current_institution_name=institution_name_param,
                           results=final_results,
                           error_message=error_message_search,
                           crawl_method_searched=crawl_method_param, # Untuk info di template
                           db_name_used=(db_name_to_search if db_name_to_search else 'N/A'),
                           # 'institution_tag' di sini adalah tag asli, bukan nama file DB
                           # digunakan untuk link kembali ke form pencarian awal.
                           institution_tag=institution_tag_param 
                           )


# view_crawl_tree_route sudah menggunakan institution_tag dan crawl_method, jadi seharusnya OK
@bp.route('/tree/<institution_tag>/<crawl_method>')
def view_crawl_tree_route(institution_tag, crawl_method):
    # ... (kode sama seperti sebelumnya, sudah baik)
    if not institution_tag or not crawl_method :
        flash("Parameter tag institusi atau metode crawl tidak lengkap.", "danger")
        return redirect(url_for('main.index'))

    if crawl_method not in current_app.config.get('CRAWL_METHODS', ['bfs','dfs']):
        flash(f"Metode crawling '{crawl_method}' tidak valid.", "danger")
        # Redirect kembali dengan db_target jika memungkinkan, atau hanya tag
        # Untuk tree view, kita punya tag dan method, jadi bisa buat db_target jika ada
        # db_target_val = generate_db_name(institution_tag, crawl_method)
        return redirect(url_for('main.index', db_target=generate_db_name(institution_tag, crawl_method) if institution_tag else None))


    g.current_db_name = generate_db_name(institution_tag, crawl_method)
    db_path = os.path.join(current_app.instance_path, g.current_db_name)

    if not os.path.exists(db_path):
        flash(f"Database '{g.current_db_name}' untuk tree view tidak ditemukan.", "warning")
        return redirect(url_for('main.index', db_target=g.current_db_name))

    # ... (sisa kode untuk membangun tree sama)
    pages_from_db = []
    try:
        pages_from_db = query_db("SELECT id, url, title, level, parent_url, anchor_text FROM pages ORDER BY level, parent_url, id") 
    except Exception as e:
        current_app.logger.error(f"Error query pages for tree view from {g.current_db_name}: {e}")
        flash(f"Tidak dapat mengambil data pohon untuk {institution_tag} ({crawl_method.upper()}). DB: {g.current_db_name}", "danger")

    nodes_by_url = {} 
    for page_row in pages_from_db: 
        page = dict(page_row) 
        page['children'] = [] 
        nodes_by_url[page['url']] = page

    tree_roots = [] 
    for url, node in nodes_by_url.items():
        parent_url = node.get('parent_url') 
        if parent_url and parent_url in nodes_by_url:
            if parent_url != url:
                 nodes_by_url[parent_url]['children'].append(node)
            elif node.get('level') == 0 : 
                 tree_roots.append(node)
        elif node.get('level') == 0 : 
             tree_roots.append(node)
    
    if not tree_roots and nodes_by_url: # Heuristik jika tidak ada root eksplisit
        min_level_nodes = [node for node in nodes_by_url.values() if node.get('level') == 0]
        if not min_level_nodes:
            if pages_from_db:
                min_level = min(node.get('level', float('inf')) for node in nodes_by_url.values())
                min_level_nodes = [node for node in nodes_by_url.values() if node.get('level') == min_level and not (node.get('parent_url') and node.get('parent_url') in nodes_by_url)]
        for node in min_level_nodes:
            is_child_elsewhere = any(node in parent_candidate['children'] for parent_candidate in nodes_by_url.values() if 'children' in parent_candidate)
            if not is_child_elsewhere:
                tree_roots.append(node)

    for url, node in nodes_by_url.items():
        if 'children' in node:
            node['children'].sort(key=lambda x: (x.get('anchor_text', x.get('url', '') or '').lower(), x.get('url', '').lower()))
    tree_roots.sort(key=lambda x: (x.get('anchor_text', x.get('url', '') or '').lower(), x.get('url', '').lower()))

    current_institution_name_for_view = get_display_name_for_tag(institution_tag)

    return render_template('crawl_tree_view.html',
                           project_name=current_app.config.get('PROJECT_NAME','Doksli Mint'),
                           institution_tag=institution_tag, 
                           current_institution_name=current_institution_name_for_view, 
                           crawl_method=crawl_method, 
                           db_name_used=g.current_db_name, 
                           tree_roots=tree_roots,
                           max_depth_limit=current_app.config.get('MAX_DEPTH_LIMIT_DEFAULT',2) 
                           )

# Fungsi helper untuk mengambil data halaman dari DB (sudah ada dari contoh sebelumnya)
def get_page_data_from_db(url_to_find):
    if not hasattr(g, 'current_db_name') or not g.current_db_name:
        current_app.logger.error("get_page_data_from_db: g.current_db_name tidak di-set.")
        return None
    try:
        results = query_db("SELECT url, title, parent_url, anchor_text, level FROM pages WHERE url = ?", [url_to_find], one=True)
        return dict(results) if results else None
    except Exception as e:
        current_app.logger.error(f"Error di get_page_data_from_db untuk URL {url_to_find} di DB {g.current_db_name}: {e}")
        return None

# Mengubah route ini untuk me-render template, bukan JSON
@bp.route('/link_path/<institution_tag>/<crawl_method>/<path:target_url_encoded>')
def show_link_path_page(institution_tag, crawl_method, target_url_encoded):
    try:
        target_url = unquote(target_url_encoded)
    except Exception as e:
        current_app.logger.error(f"Gagal unquote target_url_encoded '{target_url_encoded}': {e}")
        flash("URL target tidak valid.", "danger")
        return redirect(url_for('main.index')) # Atau ke halaman error

    if not institution_tag or not crawl_method:
        flash("Parameter institusi atau metode tidak lengkap untuk melihat rute link.", "warning")
        return redirect(request.referrer or url_for('main.index')) # Kembali ke halaman sebelumnya atau index

    # Set g.current_db_name untuk query_db
    g.current_db_name = generate_db_name(institution_tag, crawl_method)
    db_path = os.path.join(current_app.instance_path, g.current_db_name)
    error_message_page = None # Untuk pesan error di template link_route_page

    if not os.path.exists(db_path):
        current_app.logger.error(f"Database '{g.current_db_name}' tidak ditemukan untuk rute link.")
        error_message_page = f"Database '{g.current_db_name}' tidak ditemukan."
        # Render template dengan pesan error daripada flash dan redirect langsung
        return render_template('link_route_page.html',
                               project_name=current_app.config.get('PROJECT_NAME','Doksli Mint'),
                               error_message=error_message_page,
                               target_url=target_url, # Kirim target_url agar template tahu apa yang dicari
                               current_institution_name=get_display_name_for_tag(institution_tag),
                               path_data=[])


    link_path = []
    current_url_in_path = target_url
    # Ambil max_depth dari config, default ke 5, tambah buffer sedikit
    # Ini untuk mencegah loop tak berujung jika ada data parent_url yang siklik/rusak
    max_steps = current_app.config.get('MAX_DEPTH_LIMIT_DEFAULT', 5) + 3 

    for i in range(max_steps):
        page_info = get_page_data_from_db(current_url_in_path)
        
        if not page_info:
            if current_url_in_path == target_url and i == 0 : # Jika URL target awal tidak ditemukan
                error_message_page = f"Halaman target '{target_url}' tidak ditemukan di database '{g.current_db_name}'."
                current_app.logger.warning(error_message_page)
            else: # Jika parent_url mengarah ke URL yang tidak ada di DB
                error_message_page = f"Rute tidak lengkap, halaman '{current_url_in_path}' (parent dari langkah sebelumnya) tidak ditemukan di database."
                current_app.logger.warning(error_message_page)
            break 
        
        link_path.append({
            'url': page_info['url'],
            'title': page_info['title'],
            'anchor_text': page_info['anchor_text'],
            'level': page_info['level']
        })

        if page_info['level'] == 0 or not page_info['parent_url']:
            break 
        
        current_url_in_path = page_info['parent_url']
        if i == max_steps - 1: # Jika loop mencapai batas maksimum
             error_message_page = "Rute terlalu panjang atau terdeteksi loop, tampilan rute dihentikan."
             current_app.logger.warning(f"Rute untuk {target_url} di {g.current_db_name} mencapai max_steps.")


    if not link_path and not error_message_page:
        error_message_page = f"Tidak dapat membangun rute untuk '{target_url}'. Halaman mungkin tidak ada atau data tidak lengkap."

    # Ambil keyword dari sesi jika ada, untuk link "Kembali ke Hasil Pencarian"
    session_search_params = session.get('search_params', {})
    keyword_for_backlink = session_search_params.get('keyword', '')
    # db_target untuk preselect dropdown jika kembali ke index
    db_target_for_backlink = session_search_params.get('db_name_for_search', g.current_db_name)


    return render_template('link_route_page.html',
                           project_name=current_app.config.get('PROJECT_NAME','Doksli Mint'),
                           path_data=list(reversed(link_path)), # Balik urutan
                           target_url=target_url,
                           current_institution_name=get_display_name_for_tag(institution_tag),
                           db_name_used=g.current_db_name,
                           error_message=error_message_page,
                           keyword_for_backlink=keyword_for_backlink,
                           db_target_for_backlink=db_target_for_backlink # Untuk link kembali ke index
                           )