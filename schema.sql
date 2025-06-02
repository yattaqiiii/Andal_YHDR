-- schema.sql
DROP TABLE IF EXISTS pages;

CREATE TABLE pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    content_preview TEXT,
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level INTEGER,
    parent_url TEXT,
    anchor_text TEXT,
    institution_tag TEXT NOT NULL -- Tag untuk institusi atau sumber manual
);

CREATE INDEX IF NOT EXISTS idx_pages_institution_tag ON pages (institution_tag);
CREATE INDEX IF NOT EXISTS idx_pages_url ON pages (url);
CREATE INDEX IF NOT EXISTS idx_pages_content ON pages (content_preview);
CREATE INDEX IF NOT EXISTS idx_pages_title ON pages (title);