-- PartSelect Appliance Parts Database Schema
-- This schema stores refrigerator/dishwasher models and their parts

-- Models table (refrigerators, dishwashers, etc.)
CREATE TABLE IF NOT EXISTS models (
    model_number VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255),
    brand VARCHAR(100),
    appliance_type VARCHAR(50),
    source_url TEXT
);

-- Parts table (no model_number - use junction table instead)
CREATE TABLE IF NOT EXISTS parts (
    part_number VARCHAR(50) PRIMARY KEY,
    manufacturer_part_number VARCHAR(100),
    name VARCHAR(255),
    description TEXT,
    price DECIMAL(10,2),
    manufacturer VARCHAR(100),
    appliance_type VARCHAR(50),
    source_url TEXT
);

-- Junction table for many-to-many relationship between models and parts
CREATE TABLE IF NOT EXISTS model_parts (
    model_number VARCHAR(50) REFERENCES models(model_number) ON DELETE CASCADE,
    part_number VARCHAR(50) REFERENCES parts(part_number) ON DELETE CASCADE,
    PRIMARY KEY (model_number, part_number)
);

-- =============================================================================
-- INDEXES FOR FASTER LOOKUPS
-- =============================================================================

-- Model indexes
CREATE INDEX IF NOT EXISTS idx_models_appliance_type ON models(appliance_type);
CREATE INDEX IF NOT EXISTS idx_models_brand ON models(brand);
CREATE INDEX IF NOT EXISTS idx_models_name ON models(name);
CREATE INDEX IF NOT EXISTS idx_models_appliance_type_lower ON models(LOWER(appliance_type));
CREATE INDEX IF NOT EXISTS idx_models_brand_lower ON models(LOWER(brand));
CREATE INDEX IF NOT EXISTS idx_models_name_lower ON models(LOWER(name));

-- Part indexes
CREATE INDEX IF NOT EXISTS idx_parts_appliance_type ON parts(appliance_type);
CREATE INDEX IF NOT EXISTS idx_parts_manufacturer ON parts(manufacturer);
CREATE INDEX IF NOT EXISTS idx_parts_name ON parts(name);
CREATE INDEX IF NOT EXISTS idx_parts_appliance_type_lower ON parts(LOWER(appliance_type));
CREATE INDEX IF NOT EXISTS idx_parts_manufacturer_lower ON parts(LOWER(manufacturer));
CREATE INDEX IF NOT EXISTS idx_parts_name_lower ON parts(LOWER(name));

-- Junction table indexes
CREATE INDEX IF NOT EXISTS idx_model_parts_model ON model_parts(model_number);
CREATE INDEX IF NOT EXISTS idx_model_parts_part ON model_parts(part_number);

-- Note: Sample data is loaded via the scraper, not in this init file
-- Run: python scraper.py --type all --max-models 30 --max-parts-per-model 15 --db --workers 3
