import os, sqlite3
from datetime import datetime
from playwright.sync_api import sync_playwright
import trafilatura
import json
import re
from bs4 import BeautifulSoup

def setup_database():
    db_path = os.environ.get('NEWS_DB', os.path.join(os.path.dirname(__file__), '..', 'data', 'news_articles.db'))
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            url TEXT UNIQUE,
            content TEXT,
            date_string TEXT,
            scraped_at TIMESTAMP
        )
    ''')
    conn.commit()
    return conn

def is_already_scraped(conn, url):
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM articles WHERE url = ?', (url,))
    return cursor.fetchone() is not None

def fetch_rendered_html(url):
    print(f"Fetching: {url}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="load", timeout=90000)
            return page.content()
        except Exception as e:
            print(f"   -> Error: {e}")
            return None
        finally:
            browser.close()

def parse_article(html_content):
    if not html_content:
        return None, None, None
    soup = BeautifulSoup(html_content, 'html.parser')
    page_title = soup.title.string.strip() if soup.title else "Unknown Title"
    
    # Try to find the date in the HTML text first (Aldar format)
    date_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+202\d', html_content)
    extracted_date = date_match.group(0) if date_match else None
    
    json_string = trafilatura.extract(html_content, output_format="json")
    if not json_string:
        return page_title, None, extracted_date
        
    extracted = json.loads(json_string)
    content = extracted.get('text', '')
    
    # If regex missed it, use trafilatura's metadata
    if not extracted_date:
        extracted_date = extracted.get('date', '')
        
    return page_title, content, extracted_date

def save_article(conn, title, url, content, date_string):
    cursor = conn.cursor()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cursor.execute('''
            INSERT INTO articles (title, url, content, date_string, scraped_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (title, url, content, date_string, current_time))
        conn.commit()
        print(f"   -> Saved with date: {date_string}")
    except sqlite3.IntegrityError:
        pass

def get_article_links(homepage_url, max_pages=30):
    all_links = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(homepage_url, wait_until="load")
        for i in range(max_pages):
            print(f"--- Scanning Page {i+1} ---")
            page.wait_for_selector("a[href*='/news-and-media/']", timeout=15000)
            hrefs = page.eval_on_selector_all("a", "elements => elements.map(e => e.href)")
            for href in hrefs:
                if "/news-and-media/" in href and len(href) > len(homepage_url) + 5:
                    all_links.add(href)
            
            next_btn = page.locator("div.flex.justify-center.mt-20 button").last
            if next_btn.is_visible() and next_btn.is_enabled():
                next_btn.click(force=True)
                page.wait_for_timeout(4000)
            else:
                break
        browser.close()
    return list(all_links)

def run_agent(urls):
    db_conn = setup_database()
    for url in urls:
        if is_already_scraped(db_conn, url): continue
        html = fetch_rendered_html(url)
        title, content, article_date = parse_article(html)
        if content and (article_date and "2024" in str(article_date)):
            save_article(db_conn, title, url, content, article_date)

if __name__ == "__main__":
    links = get_article_links("https://www.aldar.com/en/news-and-media")
    run_agent(links)
