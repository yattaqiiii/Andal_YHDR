# app/routes.py
import os
from flask import (
    Blueprint, render_template, request, redirect, url_for, g, flash, session, current_app
)
from urllib.parse import urlparse
import datetime
from app.database import query_db, get_db, _init_db_internal # Pastikan _init_db_internal diimpor jika digunakan
from app.crawlers import WebCrawlerBFS, WebCrawlerDFS

bp = Blueprint('main', __name__)

def generate_db_name(institution_tag, crawl_method):
    return f"{institution_tag}_{crawl_method}.db"

@bp.before_app_request
def make_current_year_available():
    g.current_year = datetime.datetime.now().year

@bp.route('/', methods=['GET'])
def index():
    selected_institution_tag_from_arg = request.args.get('institution')
    keyword_prefili_from_arg = request.args.get('keyword', '')

    crawl_methods_cfg = current_app.config['CRAWL_METHODS']
    
    options_for_dropdown = []
    # Kunci: institution_tag (misal: "ipb_ac_id"), Nilai: nama tampilan (misal: "ipb.ac.id")
    discovered_tags_map = {} 

    instance_path = current_app.instance_path
    try:
        for filename in os.listdir(instance_path):
            if filename.endswith(".db"):
                base_name = filename[:-3] # Hapus .db
                parts = base_name.split('_')
                if len(parts) >= 2: # Minimal ada tag dan metode
                    potential_method_from_file = parts[-1]
                    if potential_method_from_file in crawl_methods_cfg:
                        institution_tag_from_file = '_'.join(parts[:-1])
                        
                        # Karena tidak ada AVAILABLE_INSTITUTIONS, semua tag dari DB adalah 'discovered'
                        # dan kita buat nama tampilannya dari tag file tersebut.
                        if institution_tag_from_file not in discovered_tags_map:
                            display_tag_processor = institution_tag_from_file
                            
                            # Hapus "www_" jika ada pada tag (dari file DB lama mungkin) untuk tampilan
                            if display_tag_processor.startswith("www_"):
                                display_tag_processor = display_tag_processor[len("www_"):]
                            
                            # Ganti underscore dengan titik untuk tampilan domain
                            display_domain_formatted = display_tag_processor.replace('_', '.')
                            
                            # Nama tampilan sekarang hanya domain bersih
                            discovered_tags_map[institution_tag_from_file] = display_domain_formatted
    except FileNotFoundError:
        current_app.logger.info(f"Folder instance '{instance_path}' tidak ditemukan. Ini normal jika belum ada DB.")
        pass 
    except Exception as e:
        current_app.logger.error(f"Error saat memindai folder instance: {e}")
        pass

    for tag, name in discovered_tags_map.items():
        options_for_dropdown.append({'tag': tag, 'name': name})
        
    options_for_dropdown.sort(key=lambda x: x['name']) # Urutkan berdasarkan nama
    
    final_selected_institution_tag = None
    if selected_institution_tag_from_arg and any(opt['tag'] == selected_institution_tag_from_arg for opt in options_for_dropdown):
        final_selected_institution_tag = selected_institution_tag_from_arg
    elif options_for_dropdown: # Jika arg tidak valid atau tidak ada, pilih yang pertama dari daftar
        final_selected_institution_tag = options_for_dropdown[0]['tag']

    return render_template('index.html',
                           project_name=current_app.config['PROJECT_NAME'],
                           targets_for_dropdown=options_for_dropdown,
                           selected_institution_tag=final_selected_institution_tag, 
                           max_depth_limit_default=current_app.config['MAX_DEPTH_LIMIT_DEFAULT'],
                           max_pages_default=current_app.config['MAX_PAGES_DEFAULT'],
                           crawl_methods=crawl_methods_cfg,
                           keyword_prefili=keyword_prefili_from_arg 
                           )

@bp.route('/initiate_action', methods=['POST'])
def initiate_action_route():
    keyword = request.form.get('keyword', '').strip()
    target_type = request.form.get('target_type', 'institution') 
    institution_tag_form = request.form.get('institution_tag') 
    manual_seed_url_form = request.form.get('manual_seed_url', '').strip()
    crawl_method_form = request.form.get('crawl_method', 'bfs')
    max_depth_from_form = request.form.get('max_depth', current_app.config['MAX_DEPTH_LIMIT_DEFAULT'], type=int)
    max_pages_from_form = request.form.get('max_pages', current_app.config['MAX_PAGES_DEFAULT'], type=int)
    clear_data_flag = request.form.get('clear_data_on_search_crawl') == 'yes'

    # Validasi Input
    if target_type == 'manual_url':
        if not manual_seed_url_form: # Untuk crawl baru, URL manual wajib
            flash("Seed URL manual baru wajib diisi untuk memulai crawling.", "danger")
            return redirect(url_for('main.index', institution=institution_tag_form, keyword=keyword))
        if not keyword and not clear_data_flag and max_pages_from_form <=0 : # Jika tidak ada keyword, dan bukan clear data, dan tidak ada halaman untuk di crawl
             flash("Untuk crawling URL manual baru, setidaknya masukkan kata kunci (untuk pencarian setelah crawl) atau pastikan Max Halaman > 0.", "warning")
             # Bisa tetap lanjut jika user hanya ingin crawl tanpa keyword awal
    elif target_type == 'institution':
        if not institution_tag_form: # Jika memilih dari dropdown tapi dropdown kosong
            flash("Tidak ada target tersimpan yang dipilih. Silakan crawl URL manual baru terlebih dahulu.", "danger")
            return redirect(url_for('main.index', keyword=keyword))
        if not keyword: # Jika memilih dari dropdown (target_type='institution'), keyword wajib untuk pencarian
            flash("Kata kunci wajib diisi untuk melakukan pencarian pada target tersimpan.", "danger")
            return redirect(url_for('main.index', institution=institution_tag_form))
            
    if crawl_method_form not in current_app.config['CRAWL_METHODS']:
        flash(f"Metode crawling '{crawl_method_form}' tidak valid.", "danger")
        return redirect(url_for('main.index', institution=institution_tag_form, keyword=keyword))
    
    if not (0 <= max_depth_from_form <= 5): 
        flash(f"Kedalaman maksimal harus antara 0 dan 5.", "danger")
        return redirect(url_for('main.index', institution=(institution_tag_form or ''), keyword=keyword))
    
    if not (1 <= max_pages_from_form <= 500) and target_type == 'manual_url': # Max pages relevan untuk crawling
        flash(f"Maksimal halaman dikunjungi (untuk crawling) harus antara 1 dan 500.", "danger")
        return redirect(url_for('main.index', institution=(institution_tag_form or ''), keyword=keyword, max_depth=max_depth_from_form))

    session['action_params'] = {
        'keyword': keyword,
        'target_type': target_type,
        'institution_tag': institution_tag_form,
        'manual_seed_url': manual_seed_url_form,
        'crawl_method': crawl_method_form,
        'max_depth': max_depth_from_form,
        'max_pages': max_pages_from_form,
        'clear_data': clear_data_flag
    }
    return redirect(url_for('main.process_crawling_route'))


@bp.route('/proses_crawling')
def process_crawling_route():
    action_params = session.get('action_params')
    if not action_params:
        flash("Parameter aksi tidak ditemukan.", "warning")
        return redirect(url_for('main.index'))

    keyword = action_params['keyword']
    target_type = action_params['target_type']
    institution_tag_from_dropdown = action_params['institution_tag'] 
    manual_seed_url_input = action_params['manual_seed_url']
    crawl_method = action_params['crawl_method']
    max_depth_to_crawl = action_params['max_depth']
    max_pages_to_crawl = action_params['max_pages']
    clear_data_before_crawl = action_params['clear_data']

    current_seed_url = None 
    current_domain = "" 
    current_institution_tag_for_db = "" 
    current_institution_name = "Tidak Diketahui"

    if target_type == 'institution':
        if not institution_tag_from_dropdown:
             flash("Tidak ada target tersimpan yang valid dipilih untuk diproses.", "danger")
             return redirect(url_for('main.index'))
        current_institution_tag_for_db = institution_tag_from_dropdown
        current_seed_url = None # PENTING: Tidak ada seed URL untuk target dari dropdown
        
        domain_display = institution_tag_from_dropdown
        if domain_display.startswith("www_"):
            domain_display = domain_display[len("www_"):]
        current_domain = domain_display.replace('_', '.')
        current_institution_name = current_domain 

        if (clear_data_before_crawl or max_pages_to_crawl > 0) and not keyword : # Ingin crawl/clear data, tapi ini dari dropdown
            flash(f"Aksi crawling/clear data tidak dapat dilakukan untuk '{current_institution_name}' yang dipilih dari target tersimpan karena Seed URL asli tidak diketahui. Gunakan tab 'URL Manual Baru' untuk crawling.", "warning")
            # Tetap lanjutkan jika ada keyword, karena itu berarti pencarian.
            # Jika tidak ada keyword dan ingin crawl, ini harusnya sudah dicegah di initiate_action
            # Tapi sebagai pengaman ganda:
            if not keyword:
                 return redirect(url_for('main.index', institution=institution_tag_from_dropdown))
    
    elif target_type == 'manual_url':
        if not manual_seed_url_input: 
            flash("Seed URL manual baru wajib diisi untuk crawling.", "danger")
            return redirect(url_for('main.index', keyword=keyword))
        try:
            parsed_url = urlparse(manual_seed_url_input)
            if not parsed_url.scheme or not parsed_url.netloc:
                raise ValueError("URL tidak valid atau tidak memiliki skema (http/https)")
            
            current_seed_url = manual_seed_url_input 
            domain_from_parser = parsed_url.netloc 
            
            cleaned_domain_for_tag_and_internal_use = domain_from_parser.lower()
            if cleaned_domain_for_tag_and_internal_use.startswith("www."):
                cleaned_domain_for_tag_and_internal_use = cleaned_domain_for_tag_and_internal_use[4:]
            
            current_domain = cleaned_domain_for_tag_and_internal_use
            current_institution_tag_for_db = cleaned_domain_for_tag_and_internal_use.replace('.', '_').replace('-', '_')
            current_institution_name = domain_from_parser # Nama tampilan tetap domain asli
                
        except ValueError as e:
            flash(f"Seed URL manual tidak valid: {e}", "danger")
            return redirect(url_for('main.index', keyword=keyword))
    else: 
        flash("Tipe target tidak valid.", "danger")
        return redirect(url_for('main.index'))

    if not current_institution_tag_for_db:
        flash("Target crawling/pencarian tidak dapat ditentukan.", "danger")
        return redirect(url_for('main.index'))

    # Jika tidak ada seed URL (misal dari dropdown) dan tidak ada keyword, tidak ada yang bisa dilakukan
    if not current_seed_url and not keyword:
        flash(f"Untuk target '{current_institution_name}', tidak ada Seed URL (tidak bisa crawl) dan tidak ada kata kunci (tidak bisa cari).", "warning")
        return redirect(url_for('main.index', institution=current_institution_tag_for_db))

    g.current_db_name = generate_db_name(current_institution_tag_for_db, crawl_method)
    db_path = os.path.join(current_app.instance_path, g.current_db_name)
    if not os.path.exists(db_path) and current_app.config.get('AUTO_INIT_DB', True):
         _init_db_internal(g.current_db_name, current_app) # Fungsi ini mencetak ke console

    self_log_for_template = [f"Database aktif: {g.current_db_name}"]
    
    if clear_data_before_crawl:
        if current_seed_url: # Hanya clear jika BISA crawl ulang (ada seed URL)
            try:
                db = get_db() 
                db.execute("DELETE FROM pages") 
                db.commit()
                self_log_for_template.append(f"Data lama dari '{g.current_db_name}' telah dihapus (akan dilakukan crawl baru).")
            except Exception as e:
                self_log_for_template.append(f"Gagal menghapus data lama dari '{g.current_db_name}': {e}")
        else: # Tidak bisa crawl ulang (tidak ada seed), jadi clear data tidak dilakukan
            self_log_for_template.append(f"Info: Opsi 'Hapus data lama' diabaikan untuk '{current_institution_name}' karena tidak ada Seed URL untuk crawl ulang dari pilihan ini.")

    crawl_log_messages = []
    crawl_summary = ""
    
    if current_seed_url and max_pages_to_crawl > 0: # Hanya crawl jika ada seed_url dan ada halaman yang diminta
        crawler_instance = None
        # current_domain sudah berisi domain bersih tanpa www
        if crawl_method == 'bfs':
            crawler_instance = WebCrawlerBFS(current_institution_tag_for_db, current_seed_url, current_domain, max_depth_to_crawl, max_pages_to_crawl)
        elif crawl_method == 'dfs':
            crawler_instance = WebCrawlerDFS(current_institution_tag_for_db, current_seed_url, current_domain, max_depth_to_crawl, max_pages_to_crawl)
        
        if crawler_instance:
            crawl_log_messages = crawler_instance.crawl()
            pages_added = sum(1 for msg in crawl_log_messages if 'SUKSES:' in msg)
            pages_updated = sum(1 for msg in crawl_log_messages if 'UPDATE:' in msg)
            visited_count = getattr(crawler_instance, 'pages_visited_count', 0)
            crawl_summary = f"Crawling ({crawl_method.upper()}) untuk '{current_institution_name}' selesai. DB: '{g.current_db_name}'. {pages_added} halaman baru, {pages_updated} diupdate. Dikunjungi: {visited_count}."
        else:
            crawl_summary = f"Metode crawling '{crawl_method}' tidak dikenal. Tidak ada crawling dilakukan."
            crawl_log_messages = [crawl_summary]
    elif keyword: # Tidak ada crawl (atau tidak ada seed_url), tapi ada keyword -> hanya pencarian
        crawl_summary = f"Tidak melakukan crawling untuk '{current_institution_name}' (Seed URL tidak tersedia/dipilih atau Max Halaman=0). Melakukan pencarian untuk '{keyword}'."
        if not current_seed_url and max_pages_to_crawl > 0 :
             crawl_summary = f"Tidak melakukan crawling untuk '{current_institution_name}' (Seed URL tidak tersedia dari pilihan ini). Melakukan pencarian untuk '{keyword}'."
        crawl_log_messages = [crawl_summary]
    else: # Tidak ada crawl dan tidak ada keyword
        crawl_summary = f"Tidak ada aksi (crawling atau pencarian) dilakukan untuk '{current_institution_name}'."
        crawl_log_messages = [crawl_summary]
    
    print(crawl_summary)

    final_log_for_template = self_log_for_template + crawl_log_messages
    
    session['search_params'] = {
        'keyword': keyword,
        'institution_tag': current_institution_tag_for_db,
        'institution_name': current_institution_name,
        'crawl_method': crawl_method
    }
    
    redirect_url_tree = url_for('main.view_crawl_tree_route', 
                                institution_tag=current_institution_tag_for_db, 
                                crawl_method=crawl_method)

    return render_template('proses_crawling.html',
                           project_name=current_app.config['PROJECT_NAME'],
                           keyword=keyword,
                           current_institution_name=current_institution_name,
                           crawl_log=final_log_for_template,
                           crawl_summary=crawl_summary,
                           redirect_url=url_for('main.show_search_results_route'),
                           redirect_url_tree=redirect_url_tree, 
                           db_name_used=g.current_db_name
                           )

@bp.route('/hasil_pencarian')
def show_search_results_route():
    search_params = session.get('search_params') # Ambil search_params, jangan pop dulu jika mau dipakai lagi
    if not search_params:
        flash("Parameter pencarian tidak ditemukan. Silakan coba lagi.", "warning")
        return redirect(url_for('main.index'))

    keyword = search_params['keyword']
    institution_tag = search_params['institution_tag']
    institution_name = search_params['institution_name']
    crawl_method = search_params.get('crawl_method') # !! Ambil crawl_method !!

    if not crawl_method:
        flash("Metode crawling tidak ditemukan dalam parameter pencarian.", "danger")
        return redirect(url_for('main.index'))

    g.current_db_name = generate_db_name(institution_tag, crawl_method)
    
    final_results = []
    error_message_search = None
    search_term_for_query = f"%{keyword}%"
    try:
        # Query tidak perlu 'WHERE institution_tag = ?' lagi karena DB sudah spesifik
        final_results = query_db("""
            SELECT url, title, content_preview, level, anchor_text, parent_url
            FROM pages
            WHERE (LOWER(title) LIKE LOWER(?) OR 
                   LOWER(content_preview) LIKE LOWER(?) OR 
                   LOWER(anchor_text) LIKE LOWER(?))
            ORDER BY level, title
        """, [search_term_for_query, search_term_for_query, search_term_for_query])
        
        if not final_results:
             error_message_search = f"Tidak ditemukan hasil yang cocok untuk '{keyword}' pada target '{institution_name}' (Metode: {crawl_method.upper()}, DB: {g.current_db_name})."

    except Exception as e:
        print(f"Error saat mengambil hasil pencarian dari {g.current_db_name}: {e}")
        error_message_search = f"Terjadi kesalahan saat mengambil hasil pencarian dari {g.current_db_name}."
    
    return render_template('hasil_pencarian.html', 
                           project_name=current_app.config['PROJECT_NAME'],
                           keyword=keyword,
                           institution_tag=institution_tag, # Untuk info saja
                           current_institution_name=institution_name,
                           crawl_method=crawl_method, # Untuk info
                           db_name_used=g.current_db_name, # Untuk info
                           results=final_results,
                           error_message=error_message_search)


@bp.route('/tree/<institution_tag>/<crawl_method>') # Tambahkan crawl_method ke URL
def view_crawl_tree_route(institution_tag, crawl_method):
    if crawl_method not in current_app.config['CRAWL_METHODS']:
        flash(f"Metode crawling '{crawl_method}' tidak valid untuk tree view.", "danger")
        return redirect(url_for('main.index'))

    g.current_db_name = generate_db_name(institution_tag, crawl_method)
    db_path = os.path.join(current_app.instance_path, g.current_db_name)

    if not os.path.exists(db_path):
        flash(f"Database '{g.current_db_name}' untuk tree view tidak ditemukan.", "warning")
        return redirect(url_for('main.index', institution=institution_tag))

    pages_from_db = []
    try:
        # Query tidak perlu 'WHERE institution_tag = ?' lagi
        pages_from_db = query_db("""
            SELECT id, url, title, level, parent_url, anchor_text 
            FROM pages 
            ORDER BY level, parent_url, id
        """) # Tidak ada argumen lagi untuk query ini
    except Exception as e:
        print(f"Error querying pages for tree view from {g.current_db_name}: {e}")
        flash(f"Tidak dapat mengambil data pohon untuk {institution_tag} ({crawl_method.upper()}). DB: {g.current_db_name}", "danger")

    # ... (Logika pembuatan tree_roots dari pages_from_db tetap sama) ...
    nodes_by_url = {} 
    for page_dict in pages_from_db:
        page = dict(page_dict)
        page['children'] = [] 
        nodes_by_url[page['url']] = page

    tree_roots = [] 
    for url, node in nodes_by_url.items():
        parent_url = node['parent_url']
        if parent_url and parent_url in nodes_by_url:
            nodes_by_url[parent_url]['children'].append(node)
        elif node['level'] == 0 : 
             tree_roots.append(node)
    
    for url, node in nodes_by_url.items():
        node['children'].sort(key=lambda x: (x.get('anchor_text', x['url']) or x['url']))
    
    current_institution_name_for_view = institution_tag 
    # ... (Logika penentuan current_institution_name_for_view tetap sama) ...
    available_institutions_cfg = current_app.config['AVAILABLE_INSTITUTIONS']
    if institution_tag in available_institutions_cfg:
        current_institution_name_for_view = available_institutions_cfg[institution_tag]['name']
    elif institution_tag.startswith("manual_"):
        try:
            domain_part = institution_tag.split("manual_", 1)[1]
            # Hapus potensi _bfs atau _dfs dari domain_part jika ada sebelum reconstruct
            domain_part_cleaned = domain_part.rsplit('_',1)[0] if domain_part.endswith(tuple(f"_{m}" for m in current_app.config['CRAWL_METHODS'])) else domain_part
            
            parts = domain_part_cleaned.split('_')
            reconstructed_domain = ".".join(parts)
            current_institution_name_for_view = f"Manual: {reconstructed_domain}"
        except Exception: # General exception
             current_institution_name_for_view = f"Manual Target: {institution_tag}"


    return render_template('crawl_tree_view.html',
                           project_name=current_app.config['PROJECT_NAME'],
                           institution_tag=institution_tag,
                           current_institution_name=current_institution_name_for_view,
                           crawl_method=crawl_method, # Kirim ke template
                           db_name_used=g.current_db_name, # Kirim ke template
                           tree_roots=tree_roots,
                           max_depth_limit=current_app.config['MAX_DEPTH_LIMIT_DEFAULT'])