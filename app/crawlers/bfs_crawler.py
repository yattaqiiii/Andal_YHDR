# app/crawlers/bfs_crawler.py
import requests
import time
from collections import deque
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup # Diperlukan jika soup digunakan secara langsung
from .base_crawler import BaseCrawler
from app.database import query_db, get_db # Akses fungsi database

class WebCrawlerBFS(BaseCrawler):
    def crawl(self):
        self.crawl_log = []
        self._log(f"Memulai crawling BFS untuk [{self.institution_tag}] dari {self.seed_url} (depth: {self.max_depth}, max pages: {self.max_pages_to_visit})")
        # db = get_db() # Tidak perlu di sini jika _process_page_content yang handle
        queue = deque()
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
                
                self.pages_visited_count += 1
                
                # _process_page_content sekarang dipanggil tanpa db sebagai argumen pertama
                processed_flag, soup = self._process_page_content(current_url, level, parent_url_db, anchor_text, response.text)
                
                # Logika untuk pages_added/updated_this_session perlu penyesuaian
                # Cara paling mudah adalah dengan _process_page_content mengembalikan status 'added', 'updated', atau 'none'
                # Untuk sementara, kita bisa asumsikan processed_flag = True berarti ada perubahan.
                # Penentuan add/update bisa lebih akurat jika _process_page_content memberi info lebih.
                if processed_flag:
                    # Untuk akurasi, cek apakah page_id baru dibuat atau title/content berubah signifikan
                    # Ini hanya perkiraan berdasarkan logika lama:
                    existing_after_process = query_db("SELECT id, title, content_preview FROM pages WHERE url = ? AND institution_tag = ?", [current_url, self.institution_tag], one=True)
                    if existing_after_process: # Berarti berhasil insert atau update
                        # Sulit membedakan add vs update secara pasti tanpa query sebelum dan sesudah _process_page_content,
                        # atau _process_page_content mengembalikan status yang lebih detail.
                        # Untuk V8, kita sederhanakan; jika processed_flag=true, anggap ada aktivitas.
                        # Jika ingin presisi, _process_page_content harus return 'added' atau 'updated'.
                        # Misalnya, jika existing_page_in_db di _process_page_content adalah None, itu 'added'.
                        # Jika tidak None dan ada perubahan, itu 'updated'.
                        # Kita akan menyederhanakan ini di log ringkasan saja.
                        pass


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
                # db = get_db() # Pastikan db connection ada untuk rollback jika diperlukan
                # if hasattr(db, 'in_transaction') and db.in_transaction: db.rollback() # Handle rollback di _process_page_content jika perlu
        
        if self.pages_visited_count >= self.max_pages_to_visit:
            self._log(f"Crawling BFS dihentikan karena batas maksimal {self.max_pages_to_visit} halaman tercapai.")
        
        # Hitung pages_added dan pages_updated berdasarkan log (kurang ideal tapi bisa untuk V8)
        # Logika yang lebih baik adalah _process_page_content yang memberi status jelas.
        pages_added_this_session = sum(1 for msg in self.crawl_log if "SUKSES: Halaman" in msg and "disimpan ke DB" in msg)
        pages_updated_this_session = sum(1 for msg in self.crawl_log if "UPDATE: Info untuk" in msg and "diupdate di DB" in msg)

        self._log(f"Crawling BFS untuk [{self.institution_tag}] selesai.")
        self._log(f"Total halaman baru (BFS): {pages_added_this_session}, Diupdate (BFS): {pages_updated_this_session}, Dikunjungi: {self.pages_visited_count}")
        return self.crawl_log