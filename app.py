import sqlite3
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque # Untuk BFS
# Stack untuk DFS bisa diimplementasikan dengan list Python (append dan pop)
from flask import Flask, render_template, request, redirect, url_for, g, flash, session
import os 
import time 
import datetime 

# --- Konfigurasi Aplikasi ---
DATABASE = 'doksli_mint.db'
PROJECT_NAME = "doksli mint"

AVAILABLE_INSTITUTIONS = {
    "itb_ac_id": {"name": "Institut Teknologi Bandung", "seed": "https://www.itb.ac.id", "domain": "itb.ac.id"},
    "upi_edu": {"name": "Universitas Pendidikan Indonesia", "seed": "https://www.upi.edu", "domain": "upi.edu"},
    # "ui_ac_id": {"name": "Universitas Indonesia", "seed": "https://www.ui.ac.id", "domain": "ui.ac.id"},
}
DEFAULT_INSTITUTION_TAG = "itb_ac_id" 
MAX_DEPTH_LIMIT_DEFAULT = 2 # Kedalaman maksimal crawling default
MAX_PAGES_DEFAULT = 50 # Maksimal halaman default yang dikunjungi

app = Flask(__name__)
app.config['DATABASE'] = DATABASE
app.secret_key = 'kunci_rahasia_super_untuk_doksli_mint_!@#$%^_V8_lebih_aman_lagi' 

# --- Fungsi Helper Database (Sama seperti V7) ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()
    print("Database 'doksli_mint.db' telah diinisialisasi.")

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

# --- Kelas Crawler Dasar (untuk shared methods) ---
class BaseCrawler:
    def __init__(self, institution_tag, seed_url, domain, max_depth, max_pages):
        self.institution_tag = institution_tag
        self.seed_url = seed_url
        self.domain = domain
        self.max_depth = max_depth
        self.max_pages_to_visit = max_pages # Batas total halaman yang akan dikunjungi/diproses
        self.crawl_log = []
        self.pages_visited_count = 0 # Penghitung halaman yang telah diproses/dikunjungi
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 DoksliMintBot/1.0 (+https://github.com/yourusername/dokslimint)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9,id-ID;q=0.8,id;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'DNT': '1',
        }

    def _log(self, message):
        print(message) 
        self.crawl_log.append(message) 

    def _is_valid_url_for_domain(self, url_to_check):
        try:
            parsed_url = urlparse(url_to_check)
            if parsed_url.scheme not in ['http', 'https']: return False
            if not parsed_url.netloc: return False
            return (parsed_url.netloc == self.domain or parsed_url.netloc.endswith("." + self.domain))
        except Exception: return False

    def _process_page_content(self, db, current_url, level, parent_url_db, anchor_text, response_text):
        """Memproses konten halaman dan menyimpannya ke DB. Mengembalikan True jika halaman baru/diupdate."""
        soup = BeautifulSoup(response_text, 'html.parser')
        title_from_web = soup.title.string.strip() if soup.title and soup.title.string else "Tidak Ada Judul"
        content_text = soup.get_text(separator=' ', strip=True)
        content_preview = (content_text[:300] + '...') if len(content_text) > 300 else content_text

        existing_page_in_db = query_db("SELECT id, title, content_preview FROM pages WHERE url = ? AND institution_tag = ?",
                                       [current_url, self.institution_tag], one=True)
        page_processed_flag = False

        if not existing_page_in_db:
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO pages (url, title, content_preview, level, parent_url, anchor_text, institution_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (current_url, title_from_web, content_preview, level, parent_url_db, anchor_text, self.institution_tag))
            db.commit()
            page_id_in_db = cursor.lastrowid
            self._log(f"    SUKSES: Halaman '{title_from_web[:50]}...' disimpan ke DB (ID: {page_id_in_db}).")
            page_processed_flag = True
        elif title_from_web != existing_page_in_db['title'] or \
             (existing_page_in_db['content_preview'] and content_preview[:150] != existing_page_in_db['content_preview'][:150]):
            cursor = db.cursor()
            cursor.execute("""
                UPDATE pages SET title = ?, content_preview = ?, crawled_at = CURRENT_TIMESTAMP, level = ?, parent_url = ?, anchor_text = ?
                WHERE id = ?
            """, (title_from_web, content_preview, level, parent_url_db, anchor_text, existing_page_in_db['id']))
            db.commit()
            self._log(f"    UPDATE: Info untuk {current_url} (ID: {existing_page_in_db['id']}) diupdate di DB.")
            page_processed_flag = True
        
        return page_processed_flag, soup # Kembalikan soup untuk ekstraksi link

    def crawl(self):
        raise NotImplementedError("Metode crawl harus diimplementasikan oleh subclass (BFS/DFS)")


# --- Kelas WebCrawlerBFS ---
class WebCrawlerBFS(BaseCrawler):
    def crawl(self):
        self.crawl_log = [] 
        self._log(f"Memulai crawling BFS untuk [{self.institution_tag}] dari {self.seed_url} (depth: {self.max_depth}, max pages: {self.max_pages_to_visit})")
        db = get_db()
        queue = deque()
        # session_visited_urls_levels: untuk menghindari memasukkan (url, level) yang sama ke antrian berkali-kali dalam satu sesi crawl
        session_visited_urls_levels = set() 

        queue.append((self.seed_url, 0, None, "Seed URL"))
        session_visited_urls_levels.add((self.seed_url, 0))
        self._log(f"Seed URL {self.seed_url} ditambahkan ke antrian.")

        pages_added_this_session = 0
        pages_updated_this_session = 0
        self.pages_visited_count = 0


        while queue and self.pages_visited_count < self.max_pages_to_visit:
            current_url, level, parent_url_db, anchor_text = queue.popleft()

            if level > self.max_depth:
                self._log(f"  L{level}: Melebihi kedalaman maksimal ({self.max_depth}) untuk {current_url}. Menghentikan cabang ini.")
                continue

            # Cek apakah URL ini sudah pernah diproses kontennya (bukan hanya masuk antrian)
            # Ini penting agar tidak memproses ulang halaman yang sama jika ditemukan dari path berbeda
            # Untuk BFS, kita bisa mengandalkan `session_visited_urls_levels` untuk antrian,
            # dan pengecekan `existing_page_in_db` untuk konten.
            # Atau, tambahkan set visited_content_urls. Untuk BFS, karena kita proses per level,
            # pengecekan di DB sudah cukup.

            self._log(f"  L{level}: Memproses (BFS) {current_url} ({self.pages_visited_count + 1}/{self.max_pages_to_visit})")
            
            current_headers = self.headers.copy()
            current_headers['Referer'] = parent_url_db if parent_url_db else self.seed_url

            try:
                try:
                    time.sleep(0.25) 
                    response = requests.get(current_url, timeout=15, headers=current_headers, allow_redirects=True)
                    response.raise_for_status()
                except requests.exceptions.RequestException as e:
                    self._log(f"    Error saat mengambil {current_url}: {e}")
                    continue

                if 'text/html' not in response.headers.get('Content-Type', '').lower():
                    self._log(f"    Konten bukan HTML di {current_url}. Skip.")
                    continue
                
                self.pages_visited_count += 1 # Tambah HANYA jika halaman berhasil diambil dan akan diproses kontennya
                
                processed_flag, soup = self._process_page_content(db, current_url, level, parent_url_db, anchor_text, response.text)
                if processed_flag and query_db("SELECT id FROM pages WHERE url = ? AND institution_tag = ?", [current_url, self.institution_tag], one=True): # Cek apakah masuk DB
                    if not query_db("SELECT id FROM pages WHERE url = ? AND institution_tag = ? AND title IS NOT NULL", [current_url, self.institution_tag], one=True): # Jika baru
                         pages_added_this_session +=1
                    else: # Jika update
                         pages_updated_this_session +=1


                if level < self.max_depth and self.pages_visited_count < self.max_pages_to_visit:
                    links_found_on_page_for_queue = 0
                    for link_tag in soup.find_all('a', href=True):
                        href_value = link_tag['href']
                        if not href_value or href_value.startswith('#') or href_value.lower().startswith('mailto:') or href_value.lower().startswith('javascript:'):
                            continue 
                        
                        absolute_link = urljoin(current_url, href_value)
                        parsed_link = urlparse(absolute_link)
                        normalized_link = parsed_link._replace(fragment="").geturl()

                        if self._is_valid_url_for_domain(normalized_link):
                            if (normalized_link, level + 1) not in session_visited_urls_levels:
                                link_anchor_text_from_tag = link_tag.string.strip() if link_tag.string else (link_tag.get('title', '') or link_tag.get('aria-label', '') or normalized_link)
                                queue.append((normalized_link, level + 1, current_url, link_anchor_text_from_tag))
                                session_visited_urls_levels.add((normalized_link, level + 1))
                                links_found_on_page_for_queue +=1
                    if links_found_on_page_for_queue > 0:
                        self._log(f"    Menemukan {links_found_on_page_for_queue} link valid untuk antrian dari {current_url}.")
                elif self.pages_visited_count >= self.max_pages_to_visit:
                     self._log(f"    Batas maksimal halaman ({self.max_pages_to_visit}) tercapai. Menghentikan pencarian link baru.")

            except Exception as e:
                self._log(f"    GAGAL TOTAL memproses (BFS) {current_url}: {e}")
                if hasattr(db, 'in_transaction') and db.in_transaction: db.rollback()
        
        if self.pages_visited_count >= self.max_pages_to_visit:
            self._log(f"Crawling BFS dihentikan karena batas maksimal {self.max_pages_to_visit} halaman tercapai.")
        self._log(f"Crawling BFS untuk [{self.institution_tag}] selesai.")
        self._log(f"Total halaman baru (BFS): {pages_added_this_session}, Diupdate (BFS): {pages_updated_this_session}, Dikunjungi: {self.pages_visited_count}")
        return self.crawl_log

# --- Kelas WebCrawlerDFS ---
class WebCrawlerDFS(BaseCrawler):
    def crawl(self):
        self.crawl_log = []
        self._log(f"Memulai crawling DFS untuk [{self.institution_tag}] dari {self.seed_url} (depth: {self.max_depth}, max pages: {self.max_pages_to_visit})")
        db = get_db()
        # Stack: (url, current_level, parent_url_di_db, anchor_text_menuju_url_ini)
        stack = [] 
        # Visited_urls untuk DFS: untuk menghindari loop tak terbatas dan memproses ulang halaman yang sama
        # Kita simpan (url) saja, karena DFS bisa mengunjungi level yang sama berkali-kali dari path berbeda.
        # Kontrol kedalaman dilakukan secara eksplisit.
        visited_content_urls = set() 

        stack.append((self.seed_url, 0, None, "Seed URL"))
        self._log(f"Seed URL {self.seed_url} ditambahkan ke stack.")

        pages_added_this_session = 0
        pages_updated_this_session = 0
        self.pages_visited_count = 0

        while stack and self.pages_visited_count < self.max_pages_to_visit:
            current_url, level, parent_url_db, anchor_text = stack.pop() # Ambil dari atas stack (LIFO)

            if current_url in visited_content_urls and level > 0 : # Jika bukan seed dan sudah pernah diproses kontennya, skip
                # Untuk seed (level 0), kita mungkin ingin selalu memprosesnya untuk mendapatkan link awal,
                # atau jika ada update. Pengecekan di _process_page_content akan menangani update.
                self._log(f"  L{level}: {current_url} sudah pernah diproses kontennya. Skip DFS.")
                continue
            
            if level > self.max_depth:
                self._log(f"  L{level}: Melebihi kedalaman maksimal ({self.max_depth}) untuk {current_url}. Mundur (DFS).")
                continue

            self._log(f"  L{level}: Memproses (DFS) {current_url} ({self.pages_visited_count + 1}/{self.max_pages_to_visit})")
            
            current_headers = self.headers.copy()
            current_headers['Referer'] = parent_url_db if parent_url_db else self.seed_url
            
            try:
                try:
                    time.sleep(0.25)
                    response = requests.get(current_url, timeout=15, headers=current_headers, allow_redirects=True)
                    response.raise_for_status()
                except requests.exceptions.RequestException as e:
                    self._log(f"    Error saat mengambil {current_url}: {e}")
                    continue

                if 'text/html' not in response.headers.get('Content-Type', '').lower():
                    self._log(f"    Konten bukan HTML di {current_url}. Skip.")
                    continue
                
                # Tandai URL ini sudah diproses kontennya
                visited_content_urls.add(current_url)
                self.pages_visited_count += 1

                processed_flag, soup = self._process_page_content(db, current_url, level, parent_url_db, anchor_text, response.text)
                if processed_flag:
                    # Cek apakah ini penambahan baru atau update
                    # Ini bisa disederhanakan jika _process_page_content mengembalikan status add/update
                    if not query_db("SELECT id FROM pages WHERE url = ? AND institution_tag = ? AND title IS NOT NULL AND crawled_at < datetime('now', '-1 second')", [current_url, self.institution_tag], one=True):
                         pages_added_this_session +=1
                    else:
                         pages_updated_this_session +=1

                if level < self.max_depth and self.pages_visited_count < self.max_pages_to_visit:
                    links_to_add_to_stack = []
                    for link_tag in soup.find_all('a', href=True):
                        href_value = link_tag['href']
                        if not href_value or href_value.startswith('#') or href_value.lower().startswith('mailto:') or href_value.lower().startswith('javascript:'):
                            continue
                        
                        absolute_link = urljoin(current_url, href_value)
                        parsed_link = urlparse(absolute_link)
                        normalized_link = parsed_link._replace(fragment="").geturl()

                        if self._is_valid_url_for_domain(normalized_link) and normalized_link not in visited_content_urls:
                            link_anchor_text_from_tag = link_tag.string.strip() if link_tag.string else (link_tag.get('title', '') or link_tag.get('aria-label', '') or normalized_link)
                            links_to_add_to_stack.append((normalized_link, level + 1, current_url, link_anchor_text_from_tag))
                    
                    # Untuk DFS, link ditambahkan ke stack dalam urutan terbalik agar link pertama yang ditemukan diproses lebih dulu
                    if links_to_add_to_stack:
                        self._log(f"    Menemukan {len(links_to_add_to_stack)} link valid untuk stack dari {current_url}.")
                        for link_data in reversed(links_to_add_to_stack):
                            stack.append(link_data)
                elif self.pages_visited_count >= self.max_pages_to_visit:
                     self._log(f"    Batas maksimal halaman ({self.max_pages_to_visit}) tercapai. Menghentikan pencarian link baru (DFS).")
            
            except Exception as e:
                self._log(f"    GAGAL TOTAL memproses (DFS) {current_url}: {e}")
                if hasattr(db, 'in_transaction') and db.in_transaction: db.rollback()

        if self.pages_visited_count >= self.max_pages_to_visit:
            self._log(f"Crawling DFS dihentikan karena batas maksimal {self.max_pages_to_visit} halaman tercapai.")
        self._log(f"Crawling DFS untuk [{self.institution_tag}] selesai.")
        self._log(f"Total halaman baru (DFS): {pages_added_this_session}, Diupdate (DFS): {pages_updated_this_session}, Dikunjungi: {self.pages_visited_count}")
        return self.crawl_log


# --- Rute Aplikasi Flask ---
@app.before_request
def make_current_year_available():
    g.current_year = datetime.datetime.now().year

@app.route('/', methods=['GET'])
def index():
    selected_institution_tag = request.args.get('institution', DEFAULT_INSTITUTION_TAG)
    keyword_prefili = request.args.get('keyword', '') 
    
    return render_template('index.html',
                           project_name=PROJECT_NAME,
                           available_institutions=AVAILABLE_INSTITUTIONS,
                           default_institution_tag=DEFAULT_INSTITUTION_TAG,
                           selected_institution_tag=selected_institution_tag,
                           max_depth_limit_default=MAX_DEPTH_LIMIT_DEFAULT, # Kirim default depth
                           max_pages_default=MAX_PAGES_DEFAULT # Kirim default max pages
                           )

@app.route('/initiate_action', methods=['POST'])
def initiate_action_route():
    keyword = request.form.get('keyword', '').strip()
    target_type = request.form.get('target_type', 'institution') 
    institution_tag_form = request.form.get('institution_tag')
    manual_seed_url_form = request.form.get('manual_seed_url', '').strip()
    crawl_method_form = request.form.get('crawl_method', 'bfs') # Ambil metode crawl
    max_depth_from_form = request.form.get('max_depth', MAX_DEPTH_LIMIT_DEFAULT, type=int)
    max_pages_from_form = request.form.get('max_pages', MAX_PAGES_DEFAULT, type=int) # Ambil max pages
    clear_data_flag = request.form.get('clear_data_on_search_crawl') == 'yes'

    if not keyword:
        flash("Kata kunci pencarian wajib diisi!", "danger")
        return redirect(url_for('index', institution=(institution_tag_form or DEFAULT_INSTITUTION_TAG)))

    if not (0 <= max_depth_from_form <= 5): 
        flash(f"Kedalaman maksimal harus antara 0 dan 5.", "danger")
        return redirect(url_for('index', institution=(institution_tag_form or DEFAULT_INSTITUTION_TAG), keyword=keyword))
    
    if not (1 <= max_pages_from_form <= 500): # Batasi max_pages agar tidak terlalu besar
        flash(f"Maksimal halaman dikunjungi harus antara 1 dan 500.", "danger")
        return redirect(url_for('index', institution=(institution_tag_form or DEFAULT_INSTITUTION_TAG), keyword=keyword, max_depth=max_depth_from_form))


    session['action_params'] = {
        'keyword': keyword,
        'target_type': target_type,
        'institution_tag': institution_tag_form,
        'manual_seed_url': manual_seed_url_form,
        'crawl_method': crawl_method_form, # Simpan metode crawl
        'max_depth': max_depth_from_form,
        'max_pages': max_pages_from_form, # Simpan max pages
        'clear_data': clear_data_flag
    }
    return redirect(url_for('process_crawling_route'))


@app.route('/proses_crawling')
def process_crawling_route():
    action_params = session.get('action_params')
    if not action_params:
        flash("Parameter aksi tidak ditemukan. Silakan mulai lagi.", "warning")
        return redirect(url_for('index'))

    keyword = action_params['keyword']
    target_type = action_params['target_type']
    institution_tag_form = action_params['institution_tag']
    manual_seed_url = action_params['manual_seed_url']
    crawl_method = action_params['crawl_method'] # Ambil metode crawl dari session
    max_depth_to_crawl = action_params['max_depth']
    max_pages_to_crawl = action_params['max_pages'] # Ambil max pages dari session
    clear_data_before_crawl = action_params['clear_data']
    
    current_seed_url = ""
    current_domain = ""
    current_institution_tag_for_db = ""
    current_institution_name = "Tidak Diketahui"

    if target_type == 'institution':
        if not institution_tag_form or institution_tag_form not in AVAILABLE_INSTITUTIONS:
            flash("Institusi yang dipilih tidak valid saat memproses.", "danger")
            return redirect(url_for('index', keyword=keyword)) 
        config = AVAILABLE_INSTITUTIONS[institution_tag_form]
        current_seed_url = config['seed']
        current_domain = config['domain']
        current_institution_tag_for_db = institution_tag_form
        current_institution_name = config['name']
    elif target_type == 'manual_url':
        if not manual_seed_url: 
            flash("Seed URL manual wajib diisi saat memproses.", "danger")
            return redirect(url_for('index', keyword=keyword))
        try:
            parsed_url = urlparse(manual_seed_url)
            if not parsed_url.scheme or not parsed_url.netloc:
                raise ValueError("URL tidak valid")
            current_seed_url = manual_seed_url
            current_domain = parsed_url.netloc
            current_institution_tag_for_db = "manual_" + current_domain.replace('.', '_').replace('-', '_') 
            current_institution_name = f"Manual: {current_domain}"
        except ValueError as e:
            flash(f"Seed URL manual tidak valid saat memproses: {e}", "danger")
            return redirect(url_for('index', keyword=keyword))
    else: 
        flash("Tipe target tidak valid saat memproses.", "danger")
        return redirect(url_for('index', keyword=keyword))

    self_log_for_template = []
    if clear_data_before_crawl:
        try:
            db = get_db()
            db.execute("DELETE FROM pages WHERE institution_tag = ?", (current_institution_tag_for_db,))
            db.commit()
            self_log_for_template.append(f"Data lama untuk '{current_institution_name}' telah dihapus.")
            print(f"Data lama untuk '{current_institution_name}' telah dihapus.")
        except Exception as e:
            print(f"Error menghapus data lama untuk {current_institution_name}: {e}")
            self_log_for_template.append(f"Gagal menghapus data lama: {e}")
    
    crawl_log_messages = []
    crawl_summary = ""
    crawler_instance = None

    if crawl_method == 'bfs':
        crawler_instance = WebCrawlerBFS(current_institution_tag_for_db, current_seed_url, current_domain, max_depth_to_crawl, max_pages_to_crawl)
    elif crawl_method == 'dfs':
        crawler_instance = WebCrawlerDFS(current_institution_tag_for_db, current_seed_url, current_domain, max_depth_to_crawl, max_pages_to_crawl)
    else:
        crawl_summary = f"Metode crawling '{crawl_method}' tidak dikenal."
        crawl_log_messages = [crawl_summary]
    
    if crawler_instance:
        crawl_log_messages = crawler_instance.crawl()
        pages_added = sum(1 for msg in crawl_log_messages if 'SUKSES:' in msg) # Perlu disesuaikan jika _log diubah
        pages_updated = sum(1 for msg in crawl_log_messages if 'UPDATE:' in msg) # Perlu disesuaikan
        crawl_summary = f"Crawling ({crawl_method.upper()}) untuk '{current_institution_name}' (kata kunci: '{keyword}', depth: {max_depth_to_crawl}, max pages: {max_pages_to_crawl}) selesai. {pages_added} halaman baru, {pages_updated} halaman diupdate. Dikunjungi: {crawler_instance.pages_visited_count}."
        print(crawl_summary)

    final_log_for_template = self_log_for_template + crawl_log_messages
    
    session['search_params'] = {
        'keyword': keyword,
        'institution_tag': current_institution_tag_for_db,
        'institution_name': current_institution_name
    }

    return render_template('proses_crawling.html',
                           project_name=PROJECT_NAME,
                           keyword=keyword,
                           current_institution_name=current_institution_name,
                           crawl_log=final_log_for_template,
                           crawl_summary=crawl_summary,
                           redirect_url=url_for('show_search_results_route') 
                           )

# Route /hasil_pencarian dan /tree/<institution_tag> tetap sama seperti V7

@app.route('/hasil_pencarian')
def show_search_results_route():
    search_params = session.pop('search_params', None)
    if not search_params:
        flash("Parameter pencarian tidak ditemukan. Silakan coba lagi.", "warning")
        return redirect(url_for('index'))

    keyword = search_params['keyword']
    institution_tag = search_params['institution_tag']
    institution_name = search_params['institution_name']
    
    final_results = []
    error_message_search = None
    search_term_for_query = f"%{keyword}%"
    try:
        final_results = query_db("""
            SELECT url, title, content_preview, level, anchor_text, parent_url
            FROM pages
            WHERE institution_tag = ? AND 
                  (LOWER(title) LIKE LOWER(?) OR 
                   LOWER(content_preview) LIKE LOWER(?) OR 
                   LOWER(anchor_text) LIKE LOWER(?))
            ORDER BY level, title
        """, [institution_tag, search_term_for_query, search_term_for_query, search_term_for_query])
        
        if not final_results:
             error_message_search = f"Tidak ditemukan hasil yang cocok untuk '{keyword}' pada target '{institution_name}'."

    except Exception as e:
        print(f"Error saat mengambil hasil pencarian: {e}")
        error_message_search = "Terjadi kesalahan saat mengambil hasil pencarian."
    
    return render_template('hasil_pencarian.html', 
                           project_name=PROJECT_NAME,
                           keyword=keyword,
                           institution_tag=institution_tag,
                           current_institution_name=institution_name,
                           results=final_results,
                           error_message=error_message_search)


@app.route('/tree/<path:institution_tag>') 
def view_crawl_tree_route(institution_tag):
    pages_from_db = [] 
    try:
        pages_from_db = query_db("""
            SELECT id, url, title, level, parent_url, anchor_text 
            FROM pages 
            WHERE institution_tag = ? 
            ORDER BY level, parent_url, id
        """, [institution_tag])
    except Exception as e:
        print(f"Error querying pages for tree view: {e}")
        flash(f"Tidak dapat mengambil data pohon untuk {institution_tag}.", "danger")

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
    if institution_tag in AVAILABLE_INSTITUTIONS:
        current_institution_name_for_view = AVAILABLE_INSTITUTIONS[institution_tag]['name']
    elif institution_tag.startswith("manual_"):
        try:
            domain_part = institution_tag.split("manual_", 1)[1]
            parts = domain_part.split('_')
            if len(parts) > 1: 
                reconstructed_domain = ".".join(parts)
            else: 
                reconstructed_domain = domain_part
            current_institution_name_for_view = f"Manual: {reconstructed_domain}"
        except:
             current_institution_name_for_view = f"Manual Target: {institution_tag}"


    return render_template('crawl_tree_view.html',
                           project_name=PROJECT_NAME,
                           institution_tag=institution_tag,
                           current_institution_name=current_institution_name_for_view,
                           tree_roots=tree_roots,
                           max_depth_limit=MAX_DEPTH_LIMIT_DEFAULT) # Kirim default depth ke tree view

@app.cli.command('initdb')
def initdb_command():
    init_db()

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        print(f"File database '{DATABASE}' tidak ditemukan. Akan dilakukan inisialisasi otomatis...")
        init_db() 
    
    app.run(debug=True, port=5003)
