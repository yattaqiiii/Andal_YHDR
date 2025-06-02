# app/config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'kunci_rahasia_super_untuk_doksli_mint_!@#$%^_V8_lebih_aman_lagi'
    PROJECT_NAME = "doksli mint"

    # AVAILABLE_INSTITUTIONS dan DEFAULT_INSTITUTION_TAG DIHAPUS/DIKOMENTARI
    # AVAILABLE_INSTITUTIONS = {
    #     "itb_ac_id": {"name": "Institut Teknologi Bandung", "seed": "https://www.itb.ac.id", "domain": "itb.ac.id"},
    # }
    # DEFAULT_INSTITUTION_TAG = "itb_ac_id" 

    MAX_DEPTH_LIMIT_DEFAULT = 2
    MAX_PAGES_DEFAULT = 50
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 DoksliMintBot/1.0 (+https://github.com/yourusername/dokslimint)'
    CRAWL_METHODS = ['bfs', 'dfs'] # Tetap berguna untuk pilihan metode crawl
    AUTO_INIT_DB = True 