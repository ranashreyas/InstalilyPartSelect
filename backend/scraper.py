"""
PartSelect Web Scraper - Recursive Model-Based Approach

This script scrapes refrigerator and dishwasher parts from PartSelect.com
by navigating through model pages to find all parts.

Approach:
1. Get list of models from Refrigerator-Models.htm
2. For each model, visit its page to get list of parts
3. For each part, visit its detail page to get full information

Usage:
    python scraper.py --type refrigerator --max-models 3
    python scraper.py --type dishwasher --max-models 3
    
    # With database insertion:
    python scraper.py --type refrigerator --max-models 3 --db
    
    # With parallel processing (faster):
    python scraper.py --type all --max-models 30 --max-parts-per-model 15 --db --workers 3
"""

from bs4 import BeautifulSoup
import time
import random
import re
import argparse
import json
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict, field
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Database imports
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Base URLs
REFRIGERATOR_MODELS_URL = "https://www.partselect.com/Refrigerator-Models.htm"
DISHWASHER_MODELS_URL = "https://www.partselect.com/Dishwasher-Models.htm"
BASE_URL = "https://www.partselect.com"

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin123@localhost:5432/searchdb")

# Thread-local storage for drivers (each thread gets its own browser)
_thread_local = threading.local()
_all_drivers = []  # Track all drivers for cleanup
_drivers_lock = threading.Lock()


def is_driver_alive(driver) -> bool:
    """Check if the WebDriver session is still valid."""
    try:
        # Try to get the current URL - this will fail if session is dead
        _ = driver.current_url
        return True
    except:
        return False


def create_new_driver(headless: bool = True):
    """Create a fresh WebDriver instance."""
    options = Options()
    if headless:
        options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Set timeouts to avoid long hangs
    driver.set_page_load_timeout(45)  # Max 45 seconds to load a page
    driver.set_script_timeout(45)      # Max 45 seconds for scripts
    driver.implicitly_wait(10)         # Max 10 seconds for element lookups
    
    # Additional stealth settings
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def get_driver(headless: bool = True):
    """Get or create a Selenium WebDriver instance for the current thread."""
    need_new_driver = False
    
    if not hasattr(_thread_local, 'driver') or _thread_local.driver is None:
        need_new_driver = True
    elif not is_driver_alive(_thread_local.driver):
        # Driver exists but session is dead - clean it up
        print("  [Driver] Session dead, creating new browser instance...")
        try:
            _thread_local.driver.quit()
        except:
            pass
        need_new_driver = True
    
    if need_new_driver:
        driver = create_new_driver(headless)
        _thread_local.driver = driver
        
        # Track for cleanup
        with _drivers_lock:
            _all_drivers.append(driver)
    
    return _thread_local.driver


def close_driver():
    """Close the WebDriver instance for the current thread."""
    if hasattr(_thread_local, 'driver') and _thread_local.driver:
        _thread_local.driver.quit()
        _thread_local.driver = None


def close_all_drivers():
    """Close all WebDriver instances (for cleanup at end)."""
    import signal
    
    print("\n  Closing all browser instances...")
    with _drivers_lock:
        for i, driver in enumerate(_all_drivers):
            try:
                # Set a short timeout for quit
                driver.set_page_load_timeout(5)
                driver.quit()
                print(f"    Closed browser {i+1}/{len(_all_drivers)}")
            except Exception as e:
                print(f"    Browser {i+1} already closed or unresponsive")
        _all_drivers.clear()
    
    # Force kill any orphaned chrome processes (Unix/Mac only)
    try:
        import subprocess
        subprocess.run(['pkill', '-f', 'chrome.*--headless'], timeout=5, capture_output=True)
    except:
        pass  # Windows or pkill not available
    
    print("  All browsers closed.")


@dataclass
class Model:
    """Represents an appliance model (e.g., a specific refrigerator model)."""
    model_number: str  # e.g., "00740570"
    name: str  # e.g., "00740570 Bosch Refrigerator"
    brand: Optional[str] = None  # e.g., "Bosch"
    appliance_type: Optional[str] = None  # e.g., "Refrigerator"
    source_url: Optional[str] = None


@dataclass
class Part:
    """Represents an appliance part."""
    part_number: str  # PartSelect Number (e.g., PS16556076)
    manufacturer_part_number: str  # Manufacturer Part Number (e.g., 11034152)
    name: str
    description: str
    price: Optional[float] = None
    manufacturer: Optional[str] = None
    appliance_type: Optional[str] = None
    model_number: Optional[str] = None  # Foreign key to Model
    source_url: Optional[str] = None


def get_page(url: str, retries: int = 2) -> Optional[BeautifulSoup]:
    """Fetch a page using Selenium and return BeautifulSoup object."""
    from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidSessionIdException
    
    for attempt in range(retries):
        try:
            # Get driver (will auto-recover if session is dead)
            driver = get_driver()
            
            # Random delay to appear more human-like
            time.sleep(random.uniform(3, 6))
            
            driver.get(url)
            
            # Wait for page to fully load (max 15 seconds)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Additional wait for dynamic content
            time.sleep(random.uniform(2, 4))
            
            # Check for access denied
            page_source = driver.page_source
            if 'Access Denied' in page_source:
                print(f"    Access Denied - waiting before retry...")
                time.sleep(5)
                continue
            
            return BeautifulSoup(page_source, 'html.parser')
            
        except TimeoutException:
            print(f"  Timeout on attempt {attempt + 1} for {url}")
            if attempt < retries - 1:
                time.sleep(3)
        except (WebDriverException, InvalidSessionIdException) as e:
            error_msg = str(e)[:100]
            print(f"  WebDriver error on attempt {attempt + 1}: {error_msg}")
            
            # If session is dead, force cleanup so next get_driver() creates new one
            if 'invalid session id' in str(e).lower() or 'session deleted' in str(e).lower():
                print(f"  [Recovery] Clearing dead session, will create new browser...")
                _thread_local.driver = None
            
            if attempt < retries - 1:
                time.sleep(3)
        except Exception as e:
            print(f"  Attempt {attempt + 1} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    return None


def extract_brand_from_name(name: str) -> Optional[str]:
    """Extract brand name from model name like '00740570 Bosch Refrigerator'."""
    # Order matters - check longer names first, and be careful with short names like "GE" or "LG"
    known_brands = [
        'Whirlpool', 'Samsung', 'Frigidaire', 'Kenmore', 'Maytag', 
        'KitchenAid', 'Bosch', 'Amana', 'Admiral', 'Electrolux', 'Hotpoint',
        'Jenn-Air', 'Magic Chef', 'Midea', 'Haier', 'Sub-Zero', 'Viking', 
        'Thermador', 'GE', 'LG'  # Short brands at end
    ]
    
    # Split name into words and check for brand match
    words = name.split()
    for brand in known_brands:
        # For short brands (GE, LG), require exact word match
        if len(brand) <= 2:
            if brand.upper() in [w.upper() for w in words]:
                return brand
        else:
            # For longer brands, check if brand appears as a word
            for word in words:
                if brand.lower() == word.lower():
                    return brand
    return None


def is_page_not_found(soup: BeautifulSoup) -> bool:
    """Check if the page is a 'Page Not Found' error page."""
    if not soup:
        return True
    page_text = soup.get_text()
    return "Page Not Found" in page_text or "We can't find the page you are looking for" in page_text


def get_models_from_listing(appliance_type: str, max_models: int = 3) -> List[Model]:
    """Get list of models from the models listing page with pagination."""
    base_url = REFRIGERATOR_MODELS_URL if appliance_type == 'Refrigerator' else DISHWASHER_MODELS_URL
    # Remove .htm extension for pagination
    base_url_paginated = base_url.replace('.htm', '')
    
    print(f"\n{'='*60}")
    print(f"Step 1: Getting {appliance_type} models (with pagination)")
    print(f"{'='*60}")
    
    models = []
    seen_urls = set()
    page_num = 1
    
    while len(models) < max_models:
        # Build paginated URL
        page_url = f"{base_url_paginated}.htm?start={page_num}"
        print(f"\n  Loading page {page_num}: {page_url}")
        
        soup = get_page(page_url)
        
        # Check for page not found or empty page
        if not soup or is_page_not_found(soup):
            print(f"  Reached end of model pages at page {page_num}")
            break
        
        # Find model links - they're in <a> tags with href like /Models/XXXXX/
        model_links = soup.find_all('a', href=re.compile(r'^/Models/[A-Za-z0-9]+/?$'))
        
        if not model_links:
            print(f"  No more models found on page {page_num}")
            break
        
        models_on_page = 0
        for link in model_links:
            if len(models) >= max_models:
                break
                
            href = link.get('href', '')
            if href in seen_urls:
                continue
            seen_urls.add(href)
            
            # Extract model number from href
            model_match = re.search(r'/Models/([^/]+)/?', href)
            if model_match:
                model_number = model_match.group(1)
                model_name = link.get_text(strip=True)
                brand = extract_brand_from_name(model_name)
                
                model = Model(
                    model_number=model_number,
                    name=model_name,
                    brand=brand,
                    appliance_type=appliance_type,
                    source_url=f"{BASE_URL}{href}"
                )
                models.append(model)
                models_on_page += 1
                print(f"    Found model: {model_number} - {model_name} ({brand or 'Unknown brand'})")
        
        print(f"  Page {page_num}: Found {models_on_page} new models (total: {len(models)})")
        
        # If we didn't find any new models on this page, we've reached the end
        if models_on_page == 0:
            break
            
        page_num += 1
    
    print(f"\nTotal models found: {len(models)}")
    return models


def get_parts_from_model_page(model_url: str, model_number: str, appliance_type: str, max_parts: int = 1000) -> List[Dict]:
    """Get list of parts from a model's page with pagination."""
    print(f"\n  Getting parts for model {model_number} (with pagination)...")
    
    # Build base URL for parts pagination: /Models/XXXXX/Parts/?start=N
    # Clean up model_url to get base
    base_model_url = model_url.rstrip('/')
    parts_base_url = f"{base_model_url}/Parts/"
    
    parts = []
    seen_part_numbers = set()
    page_num = 1
    
    while len(parts) < max_parts:
        # Build paginated URL
        page_url = f"{parts_base_url}?start={page_num}"
        print(f"    Loading parts page {page_num}: {page_url}")
        
        soup = get_page(page_url)
        
        # Check for page not found
        if not soup or is_page_not_found(soup):
            print(f"    Reached end of parts pages at page {page_num}")
            break
        
        # Parts are in divs with class 'mega-m__part'
        part_containers = soup.find_all('div', class_='mega-m__part')
        
        if not part_containers:
            # Also try alternate patterns
            part_links = soup.find_all('a', href=re.compile(r'/PS\d+'))
            if not part_links:
                print(f"    No parts found on page {page_num}")
                break
        
        parts_on_page = 0
        for container in part_containers:
            if len(parts) >= max_parts:
                break
                
            try:
                # Get part link and name
                name_link = container.find('a', class_='mega-m__part__name')
                if not name_link:
                    continue
                
                href = name_link.get('href', '')
                name = name_link.get_text(strip=True)
                
                # Extract PartSelect number from the page or URL
                ps_number = None
                ps_div = container.find(string=re.compile(r'PartSelect #:'))
                if ps_div:
                    ps_text = ps_div.parent.get_text(strip=True)
                    ps_match = re.search(r'PS(\d+)', ps_text)
                    if ps_match:
                        ps_number = f"PS{ps_match.group(1)}"
                
                # Fallback: extract from URL
                if not ps_number:
                    url_match = re.search(r'/PS(\d+)', href)
                    if url_match:
                        ps_number = f"PS{url_match.group(1)}"
                
                if not ps_number or ps_number in seen_part_numbers:
                    continue
                
                seen_part_numbers.add(ps_number)
                
                # Extract Manufacturer Part Number
                mfr_number = None
                mfr_div = container.find(string=re.compile(r'Manufacturer #:'))
                if mfr_div:
                    mfr_text = mfr_div.parent.get_text(strip=True)
                    mfr_match = re.search(r'Manufacturer #:\s*(\S+)', mfr_text)
                    if mfr_match:
                        mfr_number = mfr_match.group(1)
                
                # Extract price
                price = None
                price_div = container.find('div', class_='mega-m__part__price')
                if price_div:
                    price_text = price_div.get_text(strip=True)
                    price_match = re.search(r'\$?([\d,]+\.?\d*)', price_text)
                    if price_match:
                        price = float(price_match.group(1).replace(',', ''))
                
                # Get short description from the listing
                short_desc = ""
                text_content = container.get_text(separator='\n', strip=True)
                lines = text_content.split('\n')
                for i, line in enumerate(lines):
                    if 'Manufacturer #:' in line and i + 1 < len(lines):
                        for j in range(i + 1, min(i + 3, len(lines))):
                            if len(lines[j]) > 50 and not lines[j].startswith('$'):
                                short_desc = lines[j][:200]
                                break
                        break
                
                # Build full URL
                full_url = f"{BASE_URL}{href}" if href.startswith('/') else href
                full_url = full_url.split('?')[0]
                
                parts.append({
                    'part_number': ps_number,
                    'manufacturer_part_number': mfr_number,
                    'name': name,
                    'short_description': short_desc,
                    'price': price,
                    'model_number': model_number,
                    'appliance_type': appliance_type,
                    'detail_url': full_url
                })
                parts_on_page += 1
                
            except Exception as e:
                print(f"    Error parsing part: {e}")
                continue
        
        print(f"    Page {page_num}: Found {parts_on_page} new parts (total: {len(parts)})")
        
        # If we didn't find any new parts on this page, we've reached the end
        if parts_on_page == 0:
            break
            
        page_num += 1
    
    print(f"    Total parts found for model {model_number}: {len(parts)}")
    return parts


def get_part_details(part_info: Dict) -> Optional[Part]:
    """Get full details for a part from its detail page."""
    url = part_info.get('detail_url')
    if not url:
        return None
    
    print(f"      Getting details for {part_info.get('part_number')}...")
    
    soup = get_page(url)
    if not soup:
        print(f"        Failed to load part page")
        return None
    
    try:
        # Extract PartSelect Number
        ps_number = part_info.get('part_number')
        ps_elem = soup.find('span', itemprop='productID')
        if ps_elem:
            ps_number = ps_elem.get_text(strip=True)
        
        # Extract Manufacturer Part Number
        mfr_number = part_info.get('manufacturer_part_number')
        mfr_elem = soup.find('span', itemprop='mpn')
        if mfr_elem:
            mfr_number = mfr_elem.get_text(strip=True)
        
        # Extract Name from title or h1
        name = part_info.get('name')
        title_elem = soup.find('h1', class_=re.compile(r'title', re.I))
        if title_elem:
            name = title_elem.get_text(strip=True)
        if not name:
            title_tag = soup.find('title')
            if title_tag:
                name = title_tag.get_text(strip=True).split('–')[0].strip()
        
        # Extract Description
        description = ""
        desc_elem = soup.find('div', itemprop='description')
        if desc_elem:
            description = desc_elem.get_text(strip=True)
        
        # If no itemprop description, try ProductDescription section
        if not description:
            desc_section = soup.find('div', class_='pd__description')
            if desc_section:
                description = desc_section.get_text(strip=True)
        
        # Extract price
        price = part_info.get('price')
        price_elem = soup.find('span', itemprop='price')
        if price_elem:
            price_text = price_elem.get('content') or price_elem.get_text(strip=True)
            try:
                price = float(price_text.replace('$', '').replace(',', ''))
            except:
                pass
        
        # Extract manufacturer from URL or page
        manufacturer = None
        brand_elem = soup.find('span', itemprop='brand')
        if brand_elem:
            manufacturer = brand_elem.get_text(strip=True)
        if not manufacturer:
            url_match = re.search(r'/PS\d+-([A-Za-z]+)-', url)
            if url_match:
                manufacturer = url_match.group(1)
        
        return Part(
            part_number=ps_number,
            manufacturer_part_number=mfr_number or "",
            name=name or "Unknown Part",
            description=description,
            price=price,
            manufacturer=manufacturer,
            appliance_type=part_info.get('appliance_type'),
            model_number=part_info.get('model_number'),
            source_url=url
        )
        
    except Exception as e:
        print(f"        Error getting part details: {e}")
        return None


def process_single_model(model: Model, appliance_type: str, max_parts_per_model: int, model_index: int, total_models: int) -> List[Part]:
    """Process a single model - get its parts. Used for parallel processing."""
    thread_name = threading.current_thread().name
    print(f"\n[{thread_name}] {'='*50}")
    print(f"[{thread_name}] Processing model {model_index+1}/{total_models}: {model.model_number}")
    print(f"[{thread_name}] {'='*50}")
    
    parts_list = get_parts_from_model_page(
        model.source_url, 
        model.model_number,
        appliance_type,
        max_parts=max_parts_per_model
    )
    
    # Get full details for each part
    print(f"[{thread_name}]     Getting full details for {len(parts_list)} parts...")
    
    model_parts = []
    for j, part_info in enumerate(parts_list):
        part = get_part_details(part_info)
        if part:
            model_parts.append(part)
            print(f"[{thread_name}]       ✓ {j+1}/{len(parts_list)}: {part.name[:50]}...")
    
    print(f"[{thread_name}] ✓ Completed {model.model_number}: {len(model_parts)} parts")
    return model_parts


def scrape_parts_recursive(appliance_type: str, max_models: int = 3, max_parts_per_model: int = 10, num_workers: int = 1) -> tuple[List[Model], List[Part]]:
    """
    Main scraping function using recursive model-based approach.
    
    1. Get models from the models listing page
    2. For each model, get list of parts (can be parallelized with num_workers > 1)
    3. For each part, get full details
    
    Args:
        appliance_type: 'Refrigerator' or 'Dishwasher'
        max_models: Maximum number of models to scrape
        max_parts_per_model: Maximum parts per model
        num_workers: Number of parallel workers (default 1 = sequential)
    
    Returns:
        Tuple of (models list, parts list)
    """
    all_parts = []
    
    # Step 1: Get models
    models = get_models_from_listing(appliance_type, max_models)
    
    if not models:
        print("No models found")
        return [], []
    
    # Step 2: Process models (parallel or sequential)
    if num_workers > 1:
        print(f"\n🚀 Using {num_workers} parallel workers for {len(models)} models")
        
        executor = ThreadPoolExecutor(max_workers=num_workers)
        try:
            # Submit all model processing tasks
            future_to_model = {
                executor.submit(
                    process_single_model, 
                    model, 
                    appliance_type, 
                    max_parts_per_model,
                    i,
                    len(models)
                ): model 
                for i, model in enumerate(models)
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_model):
                model = future_to_model[future]
                try:
                    parts = future.result(timeout=300)  # 5 min max wait per result
                    all_parts.extend(parts)
                except Exception as e:
                    print(f"Error processing model {model.model_number}: {e}")
        finally:
            print("\n  Shutting down workers...")
            executor.shutdown(wait=False, cancel_futures=True)  # Don't wait forever
            print("  Workers shutdown initiated.")
    else:
        # Sequential processing (original behavior)
        for i, model in enumerate(models):
            print(f"\n{'='*60}")
            print(f"Step 2: Processing model {i+1}/{len(models)}: {model.model_number}")
            print(f"{'='*60}")
            
            parts_list = get_parts_from_model_page(
                model.source_url, 
                model.model_number,
                appliance_type,
                max_parts=max_parts_per_model
            )
            
            # Step 3: For each part, get full details
            print(f"\n    Getting full details for {len(parts_list)} parts...")
            
            for j, part_info in enumerate(parts_list):
                print(f"\n    Part {j+1}/{len(parts_list)}:")
                
                part = get_part_details(part_info)
                if part:
                    all_parts.append(part)
                    print(f"      ✓ {part.name}")
                    print(f"        PartSelect #: {part.part_number}")
                    print(f"        Manufacturer #: {part.manufacturer_part_number}")
                    print(f"        Model #: {part.model_number}")
                    print(f"        Description: {part.description[:100]}..." if len(part.description) > 100 else f"        Description: {part.description}")
    
    return models, all_parts


def export_to_json(data: list, filename: str, data_type: str = "items"):
    """Export data to JSON file."""
    with open(filename, 'w') as f:
        json.dump([asdict(item) for item in data], f, indent=2)
    print(f"Exported {len(data)} {data_type} to {filename}")


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_db_engine():
    """Create and return a database engine."""
    return create_engine(DATABASE_URL)


def clear_tables(engine, appliance_type: str = None):
    """
    Clear data from tables before inserting new data.
    If appliance_type is specified, only clear data for that type.
    """
    with engine.connect() as conn:
        if appliance_type:
            # Clear only specific appliance type data
            # Delete from junction table first (references both tables)
            conn.execute(text("""
                DELETE FROM model_parts 
                WHERE model_number IN (SELECT model_number FROM models WHERE appliance_type = :appliance_type)
                   OR part_number IN (SELECT part_number FROM parts WHERE appliance_type = :appliance_type)
            """), {"appliance_type": appliance_type})
            # Then delete parts and models
            conn.execute(text(
                "DELETE FROM parts WHERE appliance_type = :appliance_type"
            ), {"appliance_type": appliance_type})
            conn.execute(text(
                "DELETE FROM models WHERE appliance_type = :appliance_type"
            ), {"appliance_type": appliance_type})
            print(f"  Cleared existing {appliance_type} data from database")
        else:
            # Clear all data - junction table first
            conn.execute(text("DELETE FROM model_parts"))
            conn.execute(text("DELETE FROM parts"))
            conn.execute(text("DELETE FROM models"))
            print("  Cleared all data from database")
        conn.commit()


def insert_models_to_db(engine, models: List[Model]):
    """Insert models into the database."""
    if not models:
        return
    
    with engine.connect() as conn:
        for model in models:
            conn.execute(text("""
                INSERT INTO models (model_number, name, brand, appliance_type, source_url)
                VALUES (:model_number, :name, :brand, :appliance_type, :source_url)
                ON CONFLICT (model_number) DO UPDATE SET
                    name = EXCLUDED.name,
                    brand = EXCLUDED.brand,
                    appliance_type = EXCLUDED.appliance_type,
                    source_url = EXCLUDED.source_url
            """), {
                "model_number": model.model_number,
                "name": model.name,
                "brand": model.brand,
                "appliance_type": model.appliance_type,
                "source_url": model.source_url
            })
        conn.commit()
    print(f"  Inserted {len(models)} models into database")


def insert_parts_to_db(engine, parts: List[Part]):
    """Insert parts into the database (without model_number - use junction table)."""
    if not parts:
        return
    
    unique_parts = {}  # Deduplicate by part_number
    for part in parts:
        unique_parts[part.part_number] = part
    
    with engine.connect() as conn:
        for part in unique_parts.values():
            conn.execute(text("""
                INSERT INTO parts (
                    part_number, manufacturer_part_number, name, description,
                    price, manufacturer, appliance_type, source_url
                )
                VALUES (
                    :part_number, :manufacturer_part_number, :name, :description,
                    :price, :manufacturer, :appliance_type, :source_url
                )
                ON CONFLICT (part_number) DO UPDATE SET
                    manufacturer_part_number = EXCLUDED.manufacturer_part_number,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    price = EXCLUDED.price,
                    manufacturer = EXCLUDED.manufacturer,
                    appliance_type = EXCLUDED.appliance_type,
                    source_url = EXCLUDED.source_url
            """), {
                "part_number": part.part_number,
                "manufacturer_part_number": part.manufacturer_part_number,
                "name": part.name,
                "description": part.description,
                "price": part.price,
                "manufacturer": part.manufacturer,
                "appliance_type": part.appliance_type,
                "source_url": part.source_url
            })
        conn.commit()
    print(f"  Inserted {len(unique_parts)} unique parts into database")


def insert_model_parts_to_db(engine, parts: List[Part]):
    """Insert model-part relationships into the junction table."""
    if not parts:
        return
    
    relationships = set()  # Use set to deduplicate
    for part in parts:
        if part.model_number and part.part_number:
            relationships.add((part.model_number, part.part_number))
    
    with engine.connect() as conn:
        for model_number, part_number in relationships:
            conn.execute(text("""
                INSERT INTO model_parts (model_number, part_number)
                VALUES (:model_number, :part_number)
                ON CONFLICT (model_number, part_number) DO NOTHING
            """), {
                "model_number": model_number,
                "part_number": part_number
            })
        conn.commit()
    print(f"  Inserted {len(relationships)} model-part relationships into database")


def save_to_database(models: List[Model], parts: List[Part], appliance_type: str):
    """
    Save scraped data to PostgreSQL database.
    Clears existing data for the appliance type before inserting.
    """
    print(f"\n{'='*60}")
    print(f"SAVING TO DATABASE")
    print(f"{'='*60}")
    
    try:
        engine = get_db_engine()
        
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"  Connected to database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
        
        # Clear existing data for this appliance type
        clear_tables(engine, appliance_type)
        
        # Insert models first
        insert_models_to_db(engine, models)
        
        # Insert parts (deduplicated)
        insert_parts_to_db(engine, parts)
        
        # Insert model-part relationships
        insert_model_parts_to_db(engine, parts)
        
        print(f"\n  ✓ Successfully saved to database!")
        print(f"    - {len(models)} models")
        print(f"    - {len(set(p.part_number for p in parts))} unique parts")
        print(f"    - {len(parts)} model-part relationships")
        
    except SQLAlchemyError as e:
        print(f"\n  ✗ Database error: {e}")
        print(f"    Make sure PostgreSQL is running and accessible.")
        raise


def scrape_appliance_type(appliance_type: str, args):
    """Scrape a single appliance type and optionally save to DB/JSON."""
    output_prefix = args.output_prefix or appliance_type.lower()
    num_workers = getattr(args, 'workers', 1)
    
    print(f"\n{'#'*60}")
    print(f"# PartSelect Scraper - Recursive Model-Based Approach")
    print(f"# Appliance: {appliance_type}")
    print(f"# Max Models: {args.max_models}")
    print(f"# Max Parts per Model: {args.max_parts_per_model}")
    print(f"# Workers: {num_workers}")
    print(f"# Save to DB: {args.db}")
    print(f"{'#'*60}")
    
    models, parts = scrape_parts_recursive(
        appliance_type,
        max_models=args.max_models,
        max_parts_per_model=args.max_parts_per_model,
        num_workers=num_workers
    )
    
    print(f"\n{'='*60}")
    print(f"SCRAPING COMPLETE - {appliance_type}")
    print(f"{'='*60}")
    print(f"Total models scraped: {len(models)}")
    print(f"Total parts scraped: {len(parts)}")
    
    # Export to JSON files (unless --no-json)
    if not args.no_json:
        if models:
            models_file = f"output/{output_prefix}_models.json"
            export_to_json(models, models_file, "models")
        
        if parts:
            parts_file = f"output/{output_prefix}_parts.json"
            export_to_json(parts, parts_file, "parts")
            
            print(f"\n{'='*60}")
            print(f"OUTPUT FILES")
            print(f"{'='*60}")
            print(f"  Models: {models_file}")
            print(f"  Parts:  {parts_file}")
    
    # Save to database if --db flag is set
    if args.db:
        save_to_database(models, parts, appliance_type)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"SAMPLE DATA - {appliance_type}")
    print(f"{'='*60}")
    
    print(f"\nModels:")
    for model in models[:3]:
        print(f"  • {model.model_number} ({model.brand or 'Unknown'}) - {model.appliance_type}")
    
    print(f"\nParts:")
    for part in parts[:3]:
        print(f"\n  {part.name}")
        print(f"    PartSelect #: {part.part_number}")
        print(f"    Manufacturer #: {part.manufacturer_part_number}")
        print(f"    Parent Model: {part.model_number}")
        print(f"    Price: ${part.price}" if part.price else "    Price: N/A")
    
    return models, parts


def main():
    parser = argparse.ArgumentParser(description='Scrape appliance parts from PartSelect (recursive method)')
    parser.add_argument('--type', choices=['refrigerator', 'dishwasher', 'all'], 
                        default='refrigerator', help='Type of appliance to scrape (use "all" for both)')
    parser.add_argument('--max-models', type=int, default=3,
                        help='Maximum number of models to scrape per appliance type')
    parser.add_argument('--max-parts-per-model', type=int, default=10,
                        help='Maximum parts to scrape per model')
    parser.add_argument('--workers', type=int, default=1,
                        help='Number of parallel workers (default: 1, recommended: 2-4)')
    parser.add_argument('--output-prefix', type=str, default=None,
                        help='Prefix for output files (default: appliance type)')
    parser.add_argument('--db', action='store_true',
                        help='Save scraped data to PostgreSQL database')
    parser.add_argument('--no-json', action='store_true',
                        help='Skip JSON file export')
    
    args = parser.parse_args()
    
    try:
        if args.type == 'all':
            # Scrape both refrigerator and dishwasher
            print(f"\n{'*'*60}")
            print(f"* SCRAPING ALL APPLIANCE TYPES")
            print(f"* Workers: {args.workers}")
            print(f"{'*'*60}")
            
            all_models = []
            all_parts = []
            
            for appliance in ['Refrigerator', 'Dishwasher']:
                models, parts = scrape_appliance_type(appliance, args)
                all_models.extend(models)
                all_parts.extend(parts)
            
            print(f"\n{'*'*60}")
            print(f"* GRAND TOTAL")
            print(f"{'*'*60}")
            print(f"Total models: {len(all_models)}")
            print(f"Total parts: {len(all_parts)}")
        else:
            # Scrape single appliance type
            appliance_type = 'Refrigerator' if args.type == 'refrigerator' else 'Dishwasher'
            scrape_appliance_type(appliance_type, args)
        
    finally:
        close_all_drivers()


if __name__ == "__main__":
    main()
