-- schema.sql
-- Hapus tabel jika sudah ada untuk memungkinkan inisialisasi ulang
DROP TABLE IF EXISTS pages;

-- Tabel untuk menyimpan informasi halaman yang di-crawl
CREATE TABLE pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- ID unik untuk setiap entri halaman
    url TEXT NOT NULL,                    -- URL halaman yang di-crawl
    title TEXT,                           -- Judul halaman
    content_preview TEXT,                 -- Potongan konten dari halaman untuk preview pencarian
    level INTEGER NOT NULL,               -- Kedalaman (level) halaman dari seed URL (0 untuk seed URL)
    parent_url TEXT,                      -- URL dari halaman induk (parent) yang mengarah ke halaman ini
    anchor_text TEXT,                     -- Teks dari tag <a> (anchor) yang digunakan untuk link ke halaman ini
    institution_tag TEXT NOT NULL,        -- Penanda unik untuk institusi (misal: "upi_edu", "itb_ac_id")
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Waktu kapan halaman ini di-crawl atau di-update
    UNIQUE (url, institution_tag)         -- Kombinasi URL dan tag institusi harus unik
);

-- Index untuk mempercepat query pencarian dan penampilan pohon
CREATE INDEX IF NOT EXISTS idx_pages_institution_level ON pages (institution_tag, level);
CREATE INDEX IF NOT EXISTS idx_pages_institution_parent ON pages (institution_tag, parent_url);
CREATE INDEX IF NOT EXISTS idx_pages_search ON pages (institution_tag, title, content_preview);
