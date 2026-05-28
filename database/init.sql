-- UniChat — PostgreSQL Başlangıç
-- Docker container ilk oluşturulduğunda çalışır

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS food_menus (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL UNIQUE,
    menu_items JSONB NOT NULL,
    source_url TEXT NOT NULL,
    raw_text TEXT,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_food_menus_date
ON food_menus(date);
