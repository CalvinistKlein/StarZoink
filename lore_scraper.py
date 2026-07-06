import requests
import os
import sys
import re
from html.parser import HTMLParser

class WookieepediaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_blocks = []
        self.in_p = False

    def handle_starttag(self, tag, attrs):
        if tag == 'p':
            self.in_p = True

    def handle_endtag(self, tag):
        if tag == 'p':
            self.in_p = False
            self.text_blocks.append("\n\n")

    def handle_data(self, data):
        if self.in_p:
            self.text_blocks.append(data)

def fetch_wookieepedia(title):
    print(f"Searching Wookieepedia directly for '{title}'...")
    
    # We use action=parse to bypass Cloudflare REST API blocking
    url = "https://starwars.fandom.com/api.php"
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
        "redirects": 1
    }
    
    headers = {
        "User-Agent": "DungeonOfTheStarsEngine/1.0 (calvin@zoink.local)"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        data = response.json()
        
        if "error" in data:
            print(f"Error: {data['error'].get('info', 'Article not found')}")
            return False
            
        html_content = data.get("parse", {}).get("text", {}).get("*", "")
        if not html_content:
            print("Article found, but failed to extract HTML content.")
            return False
            
        # Parse the raw HTML into plain text using standard Python libraries
        parser = WookieepediaParser()
        parser.feed(html_content)
        
        raw_text = "".join(parser.text_blocks)
        
        # Clean up the text (remove citations like [1] and cleanup spacing)
        clean_text = re.sub(r'\[\d+\]', '', raw_text)
        clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text).strip()
        
        # Filter out common Wookieepedia warning banners at the top of pages
        filtered_lines = []
        for p in clean_text.split('\n\n'):
            if "I have a bad feeling about this" in p or "multiple issues" in p or "Please help Wookieepedia" in p or "Choose your words carefully" in p:
                continue
            filtered_lines.append(p)
            
        final_text = "\n\n".join(filtered_lines).strip()
        
        if not final_text:
            print("No readable lore text found after cleaning.")
            return False
            
        # Save the text
        safe_title = title.replace(" ", "_").replace("/", "-")
        file_path = os.path.join("KnowledgeBase", f"{safe_title}.txt")
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(final_text)
            
        print(f"Success! Wookieepedia lore saved perfectly to {file_path}")
        return True
        
    except Exception as e:
        print(f"Error fetching data: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 lore_scraper.py \"Article Title\"")
        print("Example: python3 lore_scraper.py \"Lightsaber\"")
        sys.exit(1)
        
    query = sys.argv[1]
    fetch_wookieepedia(query)
