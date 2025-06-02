# app/crawlers/base_crawler.py
# app/crawlers/base_crawler.py
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from flask import current_app # Untuk mengakses config
from app.database import query_db, get_db # Akses fungsi database
import time

class BaseCrawler:
    def __init__(self, institution_tag, seed_url, domain, max_depth, max_pages):
        self.institution_tag = institution_tag
        self.seed_url = seed_url
        self.domain = domain
        self.max_depth = max_depth
        self.max_pages_to_visit = max_pages
        self.crawl_log = []
        self.pages_visited_count = 0
        self.headers = {
            'User-Agent': current_app.config['USER_AGENT'],
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

    def _process_page_content(self, current_url, level, parent_url_db, anchor_text, response_text):
        db = get_db() 
        soup = BeautifulSoup(response_text, 'html.parser')
        title_from_web = soup.title.string.strip() if soup.title and soup.title.string else "Tidak Ada Judul"
        content_text = soup.get_text(separator=' ', strip=True)
        content_preview = (content_text[:300] + '...') if len(content_text) > 300 else content_text

        # institution_tag tidak lagi dipakai di WHERE clause, tapi tetap disimpan
        existing_page_in_db = query_db("SELECT id, title, content_preview FROM pages WHERE url = ?",
                                       [current_url], one=True) # Hanya URL karena DB sudah spesifik
        page_processed_flag = False

        # Kolom institution_tag di tabel 'pages' tetap diisi dengan self.institution_tag
        # Ini berguna jika suatu saat file-file DB ini ingin digabung atau dianalisis bersamaan,
        # kita masih punya jejak asal institusinya di dalam data.
        if not existing_page_in_db:
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO pages (url, title, content_preview, level, parent_url, anchor_text, institution_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (current_url, title_from_web, content_preview, level, parent_url_db, anchor_text, self.institution_tag)) # self.institution_tag tetap disimpan
            db.commit()
            page_id_in_db = cursor.lastrowid
            self._log(f"    SUKSES: Halaman '{title_from_web[:50]}...' disimpan ke DB (ID: {page_id_in_db}).")
            page_processed_flag = True
        # ... (logika update tetap sama, pastikan self.institution_tag juga dipertimbangkan jika field itu diupdate) ...
        # Biasanya institution_tag tidak diupdate setelah insert awal.
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
        
        return page_processed_flag, soup

    def crawl(self):
        raise NotImplementedError("Metode crawl harus diimplementasikan oleh subclass (BFS/DFS)")