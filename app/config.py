# app/config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'kunci_rahasia_super_untuk_doksli_mint_!@#$%^_V8_lebih_aman_lagi'
    PROJECT_NAME = "doksli mint"
    MAX_DEPTH_LIMIT_DEFAULT = 2
    MAX_PAGES_DEFAULT = 50
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 DoksliMintBot/1.0 (+https://github.com/yourusername/dokslimint)'
    CRAWL_METHODS = ['bfs', 'dfs'] # Tetap berguna untuk pilihan metode crawl
    AUTO_INIT_DB = True 