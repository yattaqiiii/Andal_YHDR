# app/crawlers/dfs_crawler.py
import requests
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup # Diperlukan jika soup digunakan secara langsung
from .base_crawler import BaseCrawler
from app.database import query_db, get_db # Akses fungsi database

class WebCrawlerDFS(BaseCrawler):
    def crawl(self):
        self.crawl_log = []
        self._log(f"Memulai crawling DFS untuk [{self.institution_tag}] dari {self.seed_url} (depth: {self.max_depth}, max pages: {self.max_pages_to_visit})")
        # db = get_db() # Tidak perlu di sini
        stack = []
        visited_content_urls = set()

        stack.append((self.seed_url, 0, None, "Seed URL"))
        self._log(f"Seed URL {self.seed_url} ditambahkan ke stack.")

        pages_added_this_session = 0
        pages_updated_this_session = 0
        self.pages_visited_count = 0

        while stack and self.pages_visited_count < self.max_pages_to_visit:
            current_url, level, parent_url_db, anchor_text = stack.pop()

            if current_url in visited_content_urls and level > 0 :
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
                
                visited_content_urls.add(current_url)
                self.pages_visited_count += 1

                # _process_page_content sekarang dipanggil tanpa db sebagai argumen pertama
                processed_flag, soup = self._process_page_content(current_url, level, parent_url_db, anchor_text, response.text)
                
                # Logika untuk pages_added/updated_this_session (sama seperti BFS)
                if processed_flag:
                    # Penentuan add/update bisa lebih akurat jika _process_page_content memberi info lebih.
                    pass


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
                    
                    if links_to_add_to_stack:
                        self._log(f"    Menemukan {len(links_to_add_to_stack)} link valid untuk stack dari {current_url}.")
                        for link_data in reversed(links_to_add_to_stack):
                            stack.append(link_data)
                elif self.pages_visited_count >= self.max_pages_to_visit:
                     self._log(f"    Batas maksimal halaman ({self.max_pages_to_visit}) tercapai. Menghentikan pencarian link baru (DFS).")
            
            except Exception as e:
                self._log(f"    GAGAL TOTAL memproses (DFS) {current_url}: {e}")
                # db = get_db() # Pastikan db connection ada untuk rollback jika diperlukan
                # if hasattr(db, 'in_transaction') and db.in_transaction: db.rollback() # Handle rollback di _process_page_content jika perlu

        if self.pages_visited_count >= self.max_pages_to_visit:
            self._log(f"Crawling DFS dihentikan karena batas maksimal {self.max_pages_to_visit} halaman tercapai.")
        
        # Hitung pages_added dan pages_updated berdasarkan log (sama seperti BFS)
        pages_added_this_session = sum(1 for msg in self.crawl_log if "SUKSES: Halaman" in msg and "disimpan ke DB" in msg)
        pages_updated_this_session = sum(1 for msg in self.crawl_log if "UPDATE: Info untuk" in msg and "diupdate di DB" in msg)

        self._log(f"Crawling DFS untuk [{self.institution_tag}] selesai.")
        self._log(f"Total halaman baru (DFS): {pages_added_this_session}, Diupdate (DFS): {pages_updated_this_session}, Dikunjungi: {self.pages_visited_count}")
        return self.crawl_log