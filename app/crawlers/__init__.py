# app/crawlers/__init__.py
from .base_crawler import BaseCrawler
from .bfs_crawler import WebCrawlerBFS
from .dfs_crawler import WebCrawlerDFS

__all__ = ['BaseCrawler', 'WebCrawlerBFS', 'WebCrawlerDFS']