"""
College Data Crawler - Flask Web Application

This application uses the smart web crawler to extract admission and placement information
from college websites and displays it in a user-friendly web interface.
"""

import os
import json
import logging
from flask import Flask, render_template, request, jsonify
from datetime import datetime
from urllib.parse import urlparse
import re
import threading
import queue
import time
import requests
from typing import List, Dict, Tuple, Optional


# Import the smart web crawler components
from crawler.smart_crawler import (
    CrawlerConfig, SmartWebCrawler, ContentExtractor, 
    DataExtractor, URLQueue, BasicCrawler
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("college_crawler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Directory for storing extracted data
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
COLLEGES_JSON_PATH = os.path.join(DATA_DIR, 'colleges.json')
RESULTS_DIR = os.path.join(DATA_DIR, 'results')

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# Queue for background crawling tasks
crawl_queue = queue.Queue()
crawl_results = {}
crawl_status = {}

class CollegeCrawler:
    """
    A specialized crawler for extracting college data (admission and placement information).
    """
    def __init__(self, college_name, website_url):
        self.college_name = college_name
        
        # Ensure URL has proper protocol
        if not website_url.startswith(('http://', 'https://')):
            website_url = 'https://' + website_url
            
        self.website_url = website_url
        self.domain = urlparse(website_url).netloc
        
        # Create a specific configuration for this college
        self.config = CrawlerConfig(
            project_name=f"college_crawler_{self.domain}",
            goal="Extract admission and placement information",
            seed_urls=[website_url],
            keywords=[
                "admission", "placement", "eligibility", "fee", "cutoff", 
                "entrance exam", "scholarship", "placed", "packages", "recruiter"
            ],
            allowed_domains=[self.domain],
            max_depth=3,
            max_pages_per_domain=50,
            request_delay=1.0,
            respect_robots_txt=False,
            use_nlp=True,
            use_ml_classification=False,
            output_directory=os.path.join(RESULTS_DIR, self.domain.replace('.', '_'))
        )
        
        # Create crawler instance
        self.crawler = SmartWebCrawler(self.config)
        self.content_extractor = ContentExtractor(self.config)
        self.data_extractor = DataExtractor(self.config)
        
        # Initialize session
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': self.config.user_agent})
        
    def fetch_page(self, url: str) -> Tuple[Optional[str], Optional[Dict]]:
        """
        Fetch a webpage and return its content and response metadata.
        
        Args:
            url: The URL to fetch
            
        Returns:
            Tuple of (content, metadata) where content is the HTML content
            and metadata contains response details
        """
        max_retries = 3
        retry_delay = 2
        
        for retry in range(max_retries):
            try:
                # Respect crawl delay
                time.sleep(self.config.request_delay)
                
                # Make the request with increased timeout
                response = self.session.get(
                    url, 
                    timeout=self.config.request_timeout, 
                    allow_redirects=True,
                    headers={
                        'User-Agent': self.config.user_agent,
                        'Accept': 'text/html,application/xhtml+xml,application/xml',
                        'Accept-Language': 'en-US,en;q=0.9',
                    }
                )
                
                # Check if request was successful
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch {url} - Status code: {response.status_code}")
                    if retry < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return None, None
                    
                # Extract metadata
                metadata = {
                    'url': url,
                    'status_code': response.status_code,
                    'content_type': response.headers.get('Content-Type', ''),
                    'fetch_time': datetime.datetime.now().isoformat(),
                    'encoding': response.encoding,
                    'queue_metadata': self.url_queue.get_metadata(url)
                }
                
                return response.text, metadata
                
            except Exception as e:
                logger.error(f"Error fetching {url}: {str(e)}")
                if retry < max_retries - 1:
                    logger.info(f"Retrying {url} (attempt {retry + 2}/{max_retries})...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    return None, None
        
    def _extract_section_after_heading(self, heading, max_elements=15):
        """Extract content from the section after a heading with improved extraction."""
        content = []
        current = heading.next_sibling
        
        # Also check parent elements in case the content is wrapped
        parent_content = ""
        parent = heading.parent
        if parent and parent.name in ['div', 'section', 'article']:
            # Get all text after the heading within the parent
            found_heading = False
            for child in parent.children:
                if found_heading:
                    if hasattr(child, 'get_text'):
                        text = child.get_text(strip=True)
                        if text:
                            parent_content += " " + text
                elif child == heading:
                    found_heading = True
        
        # If we found substantial content in the parent, use that
        if len(parent_content) > 100:
            return parent_content
        
        # Otherwise collect direct siblings
        for _ in range(max_elements):
            if current is None:
                break
            
            if hasattr(current, 'name') and current.name in ['h1', 'h2', 'h3', 'h4']:
                break
                
            if hasattr(current, 'get_text'):
                text = current.get_text(strip=True)
                if text:
                    content.append(text)
                    
            current = current.next_sibling
            
        return ' '.join(content)
    
    def extract_admission_data(self, html_content):
        """Extract admission information from HTML content."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html_content, 'html.parser')
        admission_data = {}
        
        # Look for admission tables
        admission_tables = []
        
        # Look for tables with admission-related keywords in captions or headers
        admission_keywords = ['admission', 'eligibility', 'criteria', 'fee', 'application', 'entrance']
        
        # FIX: Improved table detection logic
        for table in soup.find_all('table'):
            # Check if table or its container has admission-related class or id
            table_parent = table.parent
            for elem in [table, table_parent]:
                if elem.get('id') and any(keyword in elem['id'].lower() for keyword in admission_keywords):
                    admission_tables.append(table)
                    break
                if elem.get('class') and any(any(keyword in cls.lower() for keyword in admission_keywords) for cls in elem['class']):
                    admission_tables.append(table)
                    break
            
            # Check caption
            caption = table.find('caption')
            if caption and any(keyword in caption.get_text().lower() for keyword in admission_keywords):
                admission_tables.append(table)
                continue
            
            # Check for admission keywords in table headers
            headers = table.find_all('th')
            if headers and any(any(keyword in th.get_text().lower() for keyword in admission_keywords) for th in headers):
                admission_tables.append(table)
                continue
                
            # FIX: Look for nearby headings with direct checks without using find()
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
                if any(keyword in heading.get_text().lower() for keyword in admission_keywords):
                    # Check for proximity using parent-child relationship instead of siblings
                    heading_parent = heading.parent
                    if table_parent == heading_parent or heading_parent.find(table) is not None:
                        admission_tables.append(table)
                        break
        
        # Extract data from admission tables
        for idx, table in enumerate(admission_tables):
            admission_data[f'table_{idx}'] = self._extract_table_data(table)
            
        return admission_data
        
    def extract_placement_data(self, html_content):
        """Extract placement information from HTML content."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html_content, 'html.parser')
        placement_data = {}
        
        # Look for placement-related content
        placement_keywords = ['placement', 'placed', 'recruited', 'salary', 'package', 'recruiter', 'company', 'statistics']
        
        # Look for tables with placement information
        placement_tables = []
        
        # IMPROVED TABLE DETECTION
        for table in soup.find_all('table'):
            # Check if table or its container has placement-related class or id
            table_parent = table.parent
            for elem in [table, table_parent]:
                if elem.get('id') and any(keyword in elem['id'].lower() for keyword in placement_keywords):
                    placement_tables.append(table)
                    break
                if elem.get('class') and any(any(keyword in cls.lower() for keyword in placement_keywords) for cls in elem['class']):
                    placement_tables.append(table)
                    break
        
            # Check table captions
            caption = table.find('caption')
            if caption and any(keyword in caption.get_text().lower() for keyword in placement_keywords):
                placement_tables.append(table)
                continue
                
            # Check for placement keywords in table headers
            headers = table.find_all('th')
            if headers and any(any(keyword in th.get_text().lower() for keyword in placement_keywords) for th in headers):
                placement_tables.append(table)
                continue
                
            # FIX: Check nearby headings with direct checks without using find()
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
                if any(keyword in heading.get_text().lower() for keyword in placement_keywords):
                    # Check for proximity using parent-child relationship instead of siblings
                    heading_parent = heading.parent
                    if table_parent == heading_parent or heading_parent.find(table) is not None:
                        placement_tables.append(table)
                        break
        
        # Extract data from placement tables
        for idx, table in enumerate(placement_tables):
            placement_data[f'table_{idx}'] = {
                'type': 'table',
                'data': self._extract_table_data(table)
            }
            
        # CHART/GRAPH DETECTION
        charts = []
        
        # Look for common chart elements or containers
        chart_containers = soup.find_all(['div', 'figure'], class_=lambda c: c and any(chart_term in c.lower() for chart_term in ['chart', 'graph', 'pie', 'donut']))
        for container in chart_containers:
            # Check if it's placement-related
            if any(keyword in container.get_text().lower() for keyword in placement_keywords):
                charts.append(container)
        
        # Also look for divs with specific placement stats structures
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
            if any(keyword in heading.get_text().lower() for keyword in placement_keywords):
                years = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]
                if any(year in heading.get_text() for year in years) or "A.Y." in heading.get_text():
                    # Might be a year-wise placement stat
                    container = heading.parent
                    charts.append(container)
        
        # Extract data from charts
        for idx, chart in enumerate(charts):
            # For SVG or chart data, try to extract text and structure
            chart_data = {
                'heading': None,
                'content': chart.get_text(strip=True),
                'type': 'chart'
            }
            
            # Try to find the heading for this chart
            headings = chart.find_all(['h2', 'h3', 'h4', 'h5'])
            if headings:
                chart_data['heading'] = headings[0].get_text(strip=True)
            else:
                # Look for nearby heading
                prev_elem = chart.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if prev_elem:
                    chart_data['heading'] = prev_elem.get_text(strip=True)
            
            # Look for specific data patterns in the chart
            extracted_stats = self._extract_placement_stats_from_text(chart_data['content'])
            if extracted_stats:
                chart_data['extracted_stats'] = extracted_stats
            
            placement_data[f'chart_{idx}'] = chart_data
        
        # If no tables or charts found, look for sections with placement statistics
        if not placement_tables and not charts:
            placement_sections = []
            
            # Find sections by headings
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
                if any(keyword in heading.get_text().lower() for keyword in placement_keywords):
                    section_content = self._extract_section_after_heading(heading)
                    if section_content:
                        placement_data[f'section_{len(placement_sections)}'] = {
                            'heading': heading.get_text(strip=True),
                            'content': section_content,
                            'type': 'text'
                        }
                        placement_sections.append(section_content)
                    
                    # Extract stats from this section
                    extracted_stats = self._extract_placement_stats_from_text(section_content)
                    if extracted_stats:
                        placement_data[f'section_{len(placement_sections)-1}']['extracted_stats'] = extracted_stats
        
        # Log what we found
        logger.info(f"Found {len(placement_tables)} placement tables and {len(charts)} charts/graphs")
        logger.info(f"Extracted {len(placement_data)} placement data items")
        
        return placement_data
    
    def extract_tables_from_page(self, html_content: str, keywords: List[str]) -> List[Dict]:
        """
        Extract tables from an HTML page that match the given keywords.
        
        Args:
            html_content: HTML content as string
            keywords: List of keywords to match with table content
            
        Returns:
            List of extracted tables with their content
        """
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html_content, 'html.parser')
        matching_tables = []
        
        # First, look for tables directly
        for table in soup.find_all('table'):
            table_text = table.get_text(' ', strip=True).lower()
            
            # Check if any keyword is in the table text
            if any(keyword.lower() in table_text for keyword in keywords):
                # Get table headers
                headers = []
                header_row = table.find('thead')
                if header_row:
                    headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
                
                # If no thead, look for th elements in the first row
                if not headers:
                    first_row = table.find('tr')
                    if first_row:
                        headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
                
                # Get rows
                rows = []
                for row in table.find_all('tr')[1:] if headers else table.find_all('tr'):
                    row_data = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                    if row_data and any(cell.strip() for cell in row_data):  # Skip empty rows
                        rows.append(row_data)
                
                # Get caption or find a heading nearby
                title = None
                caption = table.find('caption')
                if caption:
                    title = caption.get_text(strip=True)
                else:
                    # Find the nearest heading above this table
                    heading = table.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                    if heading:
                        title = heading.get_text(strip=True)
                
                matching_tables.append({
                    'title': title,
                    'headers': headers,
                    'rows': rows,
                    'keyword_matches': [kw for kw in keywords if kw.lower() in table_text]
                })
        
        # Next, look for divs that might be styled as tables
        for div in soup.find_all('div', class_=lambda c: c and ('table' in c or 'grid' in c)):
            div_text = div.get_text(' ', strip=True).lower()
            
            if any(keyword.lower() in div_text for keyword in keywords):
                # Try to extract a table structure from the div
                rows = []
                header_row = []
                
                # Check for row elements
                row_elements = div.find_all('div', class_=lambda c: c and ('row' in c or 'tr' in c))
                if row_elements:
                    for i, row_elem in enumerate(row_elements):
                        cell_elements = row_elem.find_all('div', class_=lambda c: c and ('cell' in c or 'td' in c or 'th' in c))
                        row_data = [cell.get_text(strip=True) for cell in cell_elements]
                        
                        if i == 0:  # Assume first row is headers
                            header_row = row_data
                        else:
                            rows.append(row_data)
                
                # Get title
                title = None
                heading = div.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if heading:
                    title = heading.get_text(strip=True)
                
                if header_row or rows:
                    matching_tables.append({
                        'title': title,
                        'headers': header_row,
                        'rows': rows,
                        'keyword_matches': [kw for kw in keywords if kw.lower() in div_text],
                        'type': 'div-table'
                    })
        
        return matching_tables
        
    def _extract_table_data(self, table):
        """Extract structured data from a table."""
        data = {'headers': [], 'rows': []}
        
        # Extract headers
        headers = table.find_all('th')
        data['headers'] = [header.get_text(strip=True) for header in headers]
        
        # If no explicit headers, use first row
        if not data['headers']:
            first_row = table.find('tr')
            if first_row:
                data['headers'] = [cell.get_text(strip=True) for cell in first_row.find_all(['td', 'th'])]
                
        # Extract rows
        for row in table.find_all('tr')[1 if data['headers'] else 0:]:  # Skip header row if we used it
            row_data = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
            if row_data and any(cell.strip() for cell in row_data):  # Skip empty rows
                data['rows'].append(row_data)
                
        return data
        
    def _extract_placement_stats_from_text(self, text):
        """Extract placement statistics from text with improved patterns."""
        stats = {}
        
        # Extract percentages (e.g., "89% of students placed")
        percentage_matches = re.findall(r'(\d+(?:\.\d+)?)%', text)
        if percentage_matches:
            stats['percentages'] = percentage_matches
            
        # Extract salary/package information (improved pattern)
        salary_matches = re.findall(r'(?:Rs\.?|INR|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:lakhs?|lpa|L|Lacs?|k|K|CTC)', text, re.IGNORECASE)
        if salary_matches:
            stats['salaries'] = salary_matches
            
        # Extract company counts
        company_matches = re.findall(r'(\d+)\s+(?:companies|recruiters|firms|organizations)', text, re.IGNORECASE)
        if company_matches:
            stats['company_counts'] = company_matches
        
        # Extract placement rate directly (e.g., "85% placement rate")
        placement_rate = re.findall(r'(\d+(?:\.\d+)?)\s*%\s+placement', text, re.IGNORECASE)
        if placement_rate:
            stats['placement_rate'] = placement_rate
            
        return stats
        
    def crawl(self):
        """Crawl the college website and extract relevant information."""
        logger.info(f"Starting crawl for {self.college_name} at {self.website_url}")
        
        results = {
            'college_name': self.college_name,
            'website': self.website_url,
            'admission_data': {},
            'placement_data': {},
            'crawl_time': datetime.now().isoformat(),
            'status': 'success',
            'message': '',
            'pages_processed': 0
        }
        
        try:
            # Run basic crawler to fetch pages
            basic_crawler = BasicCrawler(self.config)
            raw_results = basic_crawler.run(max_pages=30)  # Limit to 30 pages for speed
            
            results['pages_processed'] = len(raw_results)
            
            # Keywords to look for in each category
            admission_keywords = [
                "admission", "eligibility", "criteria", "fee", "application", 
                "entrance", "form", "cutoff", "document", "deadline"
            ]
            
            placement_keywords = [
                "placement", "career", "recruiter", "company", "package", 
                "salary", "offer", "job", "opportunity", "lpa", "ctc"
            ]
            
            # Process each page for admission and placement data
            for raw_result in raw_results:
                if not raw_result.get('success', False):
                    continue
                    
                url = raw_result['url']
                html_content = raw_result['html_content']
                
                # Check if this page likely contains admission or placement data
                main_content = self.content_extractor.extract_main_content(html_content)
                lower_content = main_content.lower()
                
                # ENHANCED APPROACH: Use more sophisticated content detection
                # Look for specific admission patterns in the URL first
                if any(term in url.lower() for term in ["admission", "apply", "enroll", "entrance"]):
                    # Highly likely an admission page, extract all tables
                    admission_tables = self.extract_tables_from_page(html_content, admission_keywords)
                    
                    for idx, table_data in enumerate(admission_tables):
                        results['admission_data'][f"{url}_table_{idx}"] = {
                            'url': url,
                            'data': {
                                'type': 'table',
                                'title': table_data['title'],
                                'headers': table_data['headers'],
                                'rows': table_data['rows']
                            }
                        }
                # Otherwise check content
                elif any(keyword in lower_content for keyword in admission_keywords):
                    page_admission_data = self.extract_admission_data(html_content)
                    if page_admission_data:
                        for key, data in page_admission_data.items():
                            results['admission_data'][f"{url}_{key}"] = {
                                'url': url,
                                'data': data
                            }
                
                # Similarly for placement
                if any(term in url.lower() for term in ["placement", "career", "recruit"]):
                    # Highly likely a placement page, extract all tables
                    placement_tables = self.extract_tables_from_page(html_content, placement_keywords)
                    
                    for idx, table_data in enumerate(placement_tables):
                        results['placement_data'][f"{url}_table_{idx}"] = {
                            'url': url,
                            'data': {
                                'type': 'table',
                                'title': table_data['title'],
                                'headers': table_data['headers'],
                                'rows': table_data['rows']
                            }
                        }
                    
                    # Also look for placement charts and non-tabular data
                    page_placement_data = self.extract_placement_data(html_content)
                    if page_placement_data:
                        for key, data in page_placement_data.items():
                            results['placement_data'][f"{url}_{key}"] = {
                                'url': url,
                                'data': data
                            }
                # Otherwise check content
                elif any(keyword in lower_content for keyword in placement_keywords):
                    page_placement_data = self.extract_placement_data(html_content)
                    if page_placement_data:
                        for key, data in page_placement_data.items():
                            results['placement_data'][f"{url}_{key}"] = {
                                'url': url,
                                'data': data
                            }
            
            # If no admission or placement data found, set message
            if not results['admission_data']:
                results['message'] += "No admission data found. "
            if not results['placement_data']:
                results['message'] += "No placement data found. "
                
            if results['message'] == "":
                results['message'] = "Successfully extracted college data."
                
        except Exception as e:
            results['status'] = 'error'
            results['message'] = f"Error crawling website: {str(e)}"
            logger.error(f"Error crawling {self.website_url}: {str(e)}", exc_info=True)
            
        # Save results to file
        result_path = os.path.join(RESULTS_DIR, f"{self.domain.replace('.', '_')}.json")
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
            
        logger.info(f"Completed crawl for {self.college_name}, saved to {result_path}")
        return results

def load_colleges():
    """Load college details from the JSON file."""
    try:
        if os.path.exists(COLLEGES_JSON_PATH):
            with open(COLLEGES_JSON_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            logger.warning(f"Colleges JSON file not found at {COLLEGES_JSON_PATH}")
            # Create a sample JSON file if not exists
            sample_colleges = [
                {
                    "name": "MBIT COLLEGE",
                    "website": "www.mbit.edu.in"
                },
                {
                    "name": "ADIT COLLEGE",
                    "website": "www.adit.ac.in"
                }
            ]
            os.makedirs(os.path.dirname(COLLEGES_JSON_PATH), exist_ok=True)
            with open(COLLEGES_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(sample_colleges, f, indent=2)
            return sample_colleges
    except Exception as e:
        logger.error(f"Error loading colleges JSON: {str(e)}", exc_info=True)
        return []

def crawl_worker():
    """Background worker to process the crawl queue."""
    while True:
        try:
            college = crawl_queue.get()
            if college is None:  # Sentinel value to stop the thread
                break
                
            college_id = int(college['id'])  # Convert to int for proper comparison
            crawl_status[college_id] = 'running'
            
            # Create and run crawler
            crawler = CollegeCrawler(college['name'], college['website'])
            results = crawler.crawl()
            
            # Store results
            crawl_results[college_id] = results
            crawl_status[college_id] = 'completed'
            
        except Exception as e:
            if 'college_id' in locals():
                crawl_status[college_id] = 'error'
                crawl_results[college_id] = {
                    'status': 'error',
                    'message': f"Error: {str(e)}"
                }
            logger.error(f"Error in crawl worker: {str(e)}", exc_info=True)
        finally:
            if 'college_id' in locals():
                crawl_queue.task_done()

# Start worker thread
worker_thread = threading.Thread(target=crawl_worker, daemon=True)
worker_thread.start()

@app.route('/')
def index():
    """Render the main page with college list."""
    colleges = load_colleges()
    return render_template('index.html', colleges=colleges, count=len(colleges))

@app.route('/start_crawl', methods=['POST'])
def start_crawl():
    """Start crawling for a specific college."""
    try:
        data = request.get_json()
        college_id = int(data.get('college_id', 0))  # Convert to int
        colleges = load_colleges()
        
        if not colleges or college_id >= len(colleges):
            return jsonify({'status': 'error', 'message': 'Invalid college ID'})
            
        college = colleges[college_id]
        college['id'] = college_id
        
        # Check if already in queue or completed
        if college_id in crawl_status:
            status = crawl_status[college_id]
            return jsonify({'status': 'info', 'message': f'Crawl already {status}'})
            
        # Queue the job
        crawl_queue.put(college)
        crawl_status[college_id] = 'queued'
        
        return jsonify({'status': 'success', 'message': 'Crawl job started'})
        
    except Exception as e:
        logger.error(f"Error starting crawl: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Error: {str(e)}'})

@app.route('/crawl_status/<int:college_id>')
def get_crawl_status(college_id):
    """Get the status of a crawl job."""
    if college_id not in crawl_status:
        return jsonify({'status': 'not_started'})
    
    status = crawl_status[college_id]
    response = {'status': status}
    
    if status == 'completed' and college_id in crawl_results:
        response['result_summary'] = {
            'admission_count': len(crawl_results[college_id].get('admission_data', {})),
            'placement_count': len(crawl_results[college_id].get('placement_data', {}))
        }
        
    return jsonify(response)

@app.route('/college_data/<int:college_id>')
def college_data(college_id):
    """Display the extracted data for a college."""
    colleges = load_colleges()
    
    if not colleges or college_id >= len(colleges):
        return render_template('error.html', message="Invalid college ID")
        
    college = colleges[college_id]
    
    # Check if we have results for this college
    if college_id in crawl_results and crawl_status.get(college_id) == 'completed':
        results = crawl_results[college_id]
    else:
        # Try to load from file
        domain = urlparse(college['website'] if college['website'].startswith(('http://', 'https://')) 
                          else 'https://' + college['website']).netloc
        result_path = os.path.join(RESULTS_DIR, f"{domain.replace('.', '_')}.json")
        
        if os.path.exists(result_path):
            with open(result_path, 'r', encoding='utf-8') as f:
                results = json.load(f)
                crawl_results[college_id] = results
                crawl_status[college_id] = 'completed'
        else:
            return render_template('college_data.html', college=college, results=None, 
                                  status=crawl_status.get(college_id, 'not_started'), college_id=college_id)
    
    return render_template('college_data.html', college=college, results=results,
                          status=crawl_status.get(college_id, 'completed'), college_id=college_id)

# Error page route
@app.route('/error')
def error():
    """Display error page."""
    message = request.args.get('message', 'An unknown error occurred')
    return render_template('error.html', message=message)

if __name__ == '__main__':
    app.run(debug=True, port=5000)