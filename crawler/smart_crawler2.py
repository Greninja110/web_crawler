"""
Enhanced College Crawler

This module extends the functionality of the SmartWebCrawler to better extract
college-specific information including admission details, placement statistics,
and internship records with improved image handling and AI-based interpretation.
"""

import os
import re
import json
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import requests
import time
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Set, Any
import base64
import threading
from collections import Counter
import random


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("enhanced_crawler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class CrawlProgress:
    """Track crawling progress for UI display"""
    def __init__(self):
        self.total_pages = 0
        self.processed_pages = 0
        self.current_status = "Not started"
        self.current_url = ""
        self.errors = []
        self.lock = threading.Lock()
        
    def update(self, processed=None, total=None, status=None, url=None, error=None):
        """Update the progress information"""
        with self.lock:
            if processed is not None:
                self.processed_pages = processed
            if total is not None:
                self.total_pages = total
            if status is not None:
                self.current_status = status
            if url is not None:
                self.current_url = url
            if error is not None:
                self.errors.append(error)
    
    def get_percentage(self):
        """Get the percentage of completion"""
        with self.lock:
            if self.total_pages == 0:
                return 0
            return min(100, int((self.processed_pages / self.total_pages) * 100))
    
    def get_status(self):
        """Get the current status information"""
        with self.lock:
            return {
                "percentage": self.get_percentage(),
                "processed": self.processed_pages,
                "total": self.total_pages,
                "status": self.current_status,
                "url": self.current_url,
                "errors": self.errors[:5]  # Return only the last 5 errors
            }


class EnhancedCollegeCrawler:
    """
    Enhanced crawler specifically designed for extracting college data with a focus on:
    - Admission information (courses, fees, eligibility)
    - Placement information (statistics, recruiters, packages)
    - Internship information (companies, statistics)
    
    Includes improved image handling and AI-based interpretation of extracted text.
    """
    
    def __init__(self, college_name, website_url, config, output_dir="data/results"):
        self.college_name = college_name
        
        # Ensure URL has proper protocol
        if not website_url.startswith(('http://', 'https://')):
            website_url = 'https://' + website_url
            
        self.website_url = website_url
        self.domain = urlparse(website_url).netloc
        self.config = config
        self.output_dir = output_dir
        self.progress = CrawlProgress()
        
        # List of explored and pending URLs
        self.explored_urls = set()
        self.pending_urls = set([website_url])
        
        # URLs categorized by type
        self.admission_urls = set()
        self.placement_urls = set()
        self.internship_urls = set()
        
        # Keywords for identifying relevance
        self.admission_keywords = [
            "admission", "eligibility", "criteria", "fee", "application", 
            "entrance", "form", "cutoff", "document", "deadline", "course",
            "program", "stream", "scholarship", "hostel", "tuition"
        ]
        
        self.placement_keywords = [
            "placement", "career", "recruiter", "company", "package", 
            "salary", "offer", "job", "opportunity", "lpa", "ctc",
            "placed", "recruited", "hiring", "employed", "position",
            "statistics", "recruitment", "employer"
        ]
        
        self.internship_keywords = [
            "internship", "intern", "summer training", "industrial training",
            "practical training", "apprentice", "trainee", "on-job training"
        ]
        
        # Keywords that help identify image content
        self.logo_keywords = [
            "logo", "brand", "company", "recruiter", "partner", "client",
            "collaborator", "corporate", "industry"
        ]

        # Initialize session with custom headers and proxy rotation capabilities
        self.session = self.create_session()
        
        # Results storage
        self.results = {
            'college_name': college_name,
            'website': website_url,
            'admission_data': {},
            'placement_data': {},
            'internship_data': {},
            'crawl_time': datetime.now().isoformat(),
            'status': 'success',
            'message': '',
            'pages_processed': 0,
            'parsed_data': {
                'admission': {},
                'placement': {},
                'internship': {}
            }
        }
    
    def create_session(self):
        """Create an HTTP session with rotation of user agents and other anti-blocking measures"""
        session = requests.Session()
        
        # List of common user agents to rotate
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'
        ]
        
        # Set random user agent
        session.headers.update({
            'User-Agent': random.choice(user_agents),
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'DNT': '1',
            'Cache-Control': 'no-cache'
        })
        
        return session

    def fetch_page(self, url: str, max_retries=5) -> Tuple[Optional[str], Optional[Dict]]:
        """
        Fetch a webpage with robust retry mechanism to handle transient errors.
        """
        retry_delay = 1
        
        for retry in range(max_retries):
            try:
                # Update progress
                self.progress.update(status="Fetching", url=url)
                
                # Add a small delay with randomization to avoid detection
                time.sleep(retry_delay + random.uniform(0.5, 2.0))
                
                # Rotate user agent on retries
                if retry > 0:
                    self.session.headers.update({
                        'User-Agent': random.choice([
                            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15',
                            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0',
                            'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'
                        ]),
                        # Add cookie consent headers that are common on websites
                        'Cookie': 'cookieconsent_status=dismiss; PHPSESSID=' + ''.join(random.choices('0123456789abcdef', k=32))
                    })
                
                # Make the request with enhanced headers
                response = self.session.get(
                    url, 
                    timeout=30, 
                    allow_redirects=True,
                    headers={
                        'Referer': random.choice([
                            'https://www.google.com/search?q=' + self.domain,
                            'https://www.bing.com/search?q=' + self.domain,
                            'https://search.yahoo.com/search?p=' + self.domain,
                            self.website_url
                        ]),
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                        'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
                        'Sec-Ch-Ua-Mobile': '?0',
                        'Sec-Ch-Ua-Platform': '"Windows"',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1',
                        'Upgrade-Insecure-Requests': '1',
                        'Cache-Control': 'max-age=0'
                    }
                )
                
                # Check if request was successful
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch {url} - Status code: {response.status_code}")
                    if retry < max_retries - 1:
                        retry_delay = min(retry_delay * 2, 15)  # Exponential backoff, max 15 seconds
                        time.sleep(retry_delay)
                        continue
                    return None, None
                    
                # Extract metadata
                metadata = {
                    'url': url,
                    'status_code': response.status_code,
                    'content_type': response.headers.get('Content-Type', ''),
                    'fetch_time': datetime.now().isoformat(),
                }
                
                # Handle different content types
                content_type = response.headers.get('Content-Type', '').lower()
                
                if 'text/html' in content_type:
                    # Try to detect encoding issues
                    try:
                        html_content = response.text
                        # Check if the encoding seems wrong (common for Indian college websites)
                        if '�' in html_content:
                            # Try with different encoding
                            html_content = response.content.decode('utf-8', errors='replace')
                    except Exception:
                        html_content = response.text
                    
                    return html_content, metadata
                elif 'image/' in content_type:
                    # For images, return base64 encoded data
                    img_data = base64.b64encode(response.content).decode('utf-8')
                    metadata['is_image'] = True
                    metadata['image_data'] = img_data
                    return img_data, metadata
                else:
                    # For other content types, just return text
                    return response.text, metadata
                    
            except requests.exceptions.ConnectionError as e:
                error_msg = f"Connection error for {url}: {str(e)}"
                logger.error(error_msg)
                self.progress.update(error=error_msg)
                if retry < max_retries - 1:
                    retry_delay = min(retry_delay * 2, 15)  # Exponential backoff, max 15 seconds
                    logger.info(f"Retrying {url} (attempt {retry + 2}/{max_retries})...")
                    time.sleep(retry_delay)
                else:
                    return None, None
            except Exception as e:
                error_msg = f"Error fetching {url}: {str(e)}"
                logger.error(error_msg)
                self.progress.update(error=error_msg)
                if retry < max_retries - 1:
                    retry_delay = min(retry_delay * 2, 15)  # Exponential backoff, max 15 seconds
                    logger.info(f"Retrying {url} (attempt {retry + 2}/{max_retries})...")
                    time.sleep(retry_delay)
                else:
                    return None, None
                    
        return None, None
    
    def categorize_url(self, url: str, html_content: str = None) -> str:
        """
        Categorize a URL as admission, placement, internship, or general based on URL path and content.
        Uses both URL structure and content analysis for better accuracy.
        """
        url_lower = url.lower()
        
        # First check URL path for quick categorization
        if any(keyword in url_lower for keyword in ['admission', 'apply', 'enroll', 'course', 'fee']):
            return 'admission'
        elif any(keyword in url_lower for keyword in ['placement', 'career', 'recruit', 'company']):
            return 'placement'
        elif any(keyword in url_lower for keyword in ['intern', 'training']):
            return 'internship'
        
        # Extract page ID for more context
        page_id = self.extract_page_id(url)
        
        # Known page IDs from the images you shared
        if page_id:
            # From your screenshots, we know some page IDs
            if page_id in ['2681', '2692', '2670']:  # Update with actual admission page IDs
                return 'admission'
            elif page_id in ['9812', '9821', '9836']:  # Update with actual placement page IDs
                return 'placement'
            elif page_id in ['10198']:  # Update with actual internship page IDs
                return 'internship'
                
        # If HTML content is provided, perform deeper analysis
        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style tags
            for script in soup(["script", "style"]):
                script.extract()
                
            text_content = soup.get_text().lower()
            
            # Try to find headings that would indicate the page type
            headings = soup.find_all(['h1', 'h2', 'h3', 'h4'])
            heading_text = ' '.join([h.get_text().lower() for h in headings])
            
            # Score each category based on keyword presence
            admission_score = sum(5 if keyword in heading_text else 
                                1 if keyword in text_content else 
                                0 
                                for keyword in self.admission_keywords)
            
            placement_score = sum(5 if keyword in heading_text else 
                                1 if keyword in text_content else 
                                0
                                for keyword in self.placement_keywords)
            
            internship_score = sum(5 if keyword in heading_text else 
                                1 if keyword in text_content else 
                                0 
                                for keyword in self.internship_keywords)
            
            # Check for specific structural elements
            if soup.find('table'):
                # Analyze table content to boost relevant scores
                for table in soup.find_all('table'):
                    table_text = table.get_text().lower()
                    if any(keyword in table_text for keyword in self.admission_keywords):
                        admission_score += 10
                    if any(keyword in table_text for keyword in self.placement_keywords):
                        placement_score += 10
                    if any(keyword in table_text for keyword in self.internship_keywords):
                        internship_score += 10
            
            # Look for images that might indicate company logos
            if soup.find_all('img'):
                # Count number of small images in a row - likely logos
                logo_like_images = []
                for img in soup.find_all('img'):
                    try:
                        # Fix for parsing width/height with units like 'px'
                        width = img.get('width', '100')
                        height = img.get('height', '100')
                        
                        # Extract numeric part if it contains non-numeric characters
                        if isinstance(width, str) and not width.isdigit():
                            width = ''.join(c for c in width if c.isdigit() or c == '.')
                        if isinstance(height, str) and not height.isdigit():
                            height = ''.join(c for c in height if c.isdigit() or c == '.')
                        
                        # Parse as float first to handle decimal values
                        width_val = float(width) if width else 100
                        height_val = float(height) if height else 100
                        
                        if width_val < 200 and height_val < 100:
                            logo_like_images.append(img)
                    except (ValueError, TypeError):
                        # Skip images with invalid width/height
                        continue
                
                if len(logo_like_images) > 3:  # Several logos in the page
                    placement_score += 15
            
            # Determine category based on highest score (with a minimum threshold)
            if max(admission_score, placement_score, internship_score) > 5:
                if admission_score > placement_score and admission_score > internship_score:
                    return 'admission'
                elif placement_score > admission_score and placement_score > internship_score:
                    return 'placement'
                elif internship_score > admission_score and internship_score > placement_score:
                    return 'internship'
        
        # Default to general if we can't determine
        return 'general'

    def extract_urls(self, html: str, base_url: str) -> List[str]:
        """
        Extract all URLs from an HTML page and normalize them.
        """
        soup = BeautifulSoup(html, 'html.parser')
        urls = []
        
        # Get all links
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            
            # Skip empty or javascript links
            if not href or href.startswith(('javascript:', '#', 'tel:', 'mailto:')):
                continue
                
            # Normalize URL
            full_url = urljoin(base_url, href)
            
            # Clean URL by removing fragments and standardizing
            if '#' in full_url:
                full_url = full_url.split('#')[0]
                
            # Exclude common file types that aren't web pages
            if any(full_url.endswith(ext) for ext in ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.zip', '.rar']):
                continue
                
            # Only keep URLs from the same domain
            if urlparse(full_url).netloc == self.domain:
                urls.append(full_url)
        
        # Remove duplicate URLs
        return list(set(urls))
    
    def extract_page_id(self, url: str) -> Optional[str]:
        """
        Extract page ID from URL query parameters or path.
        Many college websites use page IDs in their URLs.
        """
        parsed_url = urlparse(url)
        
        # Check for query parameters
        query_params = parse_qs(parsed_url.query)
        
        # Common page ID parameters
        id_params = ['id', 'page_id', 'p', 'pid', 'pageid']
        
        for param in id_params:
            if param in query_params and query_params[param]:
                return query_params[param][0]
        
        # Check path for ID-like patterns
        path_parts = parsed_url.path.split('/')
        for part in path_parts:
            # ID-only parts
            if part.isdigit() and len(part) > 2:
                return part
                
            # Parts that end with ID
            if part.endswith('.html') and part[:-5].isdigit():
                return part[:-5]
                
        return None
    
    def extract_tables(self, html_content: str) -> List[Dict]:
        """
        Extract all tables from HTML content with improved handling.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        tables = []
        
        # Find all table elements
        for table_idx, table in enumerate(soup.find_all('table')):
            # Skip tiny tables (likely layout tables, not data tables)
            if len(table.find_all('tr')) < 2:
                continue
                
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
            
            # Add table to list if it has content
            if headers or rows:
                table_content = {
                    'id': f'table_{table_idx}',
                    'title': title,
                    'headers': headers,
                    'rows': rows
                }
                
                # Analyze table content to determine its type
                table_text = ' '.join([' '.join(row) for row in rows])
                if any(keyword in table_text.lower() for keyword in self.admission_keywords):
                    table_content['category'] = 'admission'
                elif any(keyword in table_text.lower() for keyword in self.placement_keywords):
                    table_content['category'] = 'placement'
                elif any(keyword in table_text.lower() for keyword in self.internship_keywords):
                    table_content['category'] = 'internship'
                else:
                    table_content['category'] = 'general'
                
                tables.append(table_content)
                
        return tables
    
    def extract_fee_structure(self, html_content: str) -> Dict:
        """
        Extract fee structure information from HTML content.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        fee_data = {}
        
        # Look for fee-related headings
        fee_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], 
                                    string=lambda s: s and any(term in s.lower() 
                                                            for term in ['fee', 'tuition', 'cost', 'payment', 'charges']))
        
        for heading in fee_headings:
            heading_text = heading.get_text(strip=True)
            
            # Look for tables after this heading
            table = heading.find_next('table')
            if table:
                # Extract table data
                headers = []
                header_row = table.find('thead')
                if header_row:
                    headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
                
                if not headers:
                    first_row = table.find('tr')
                    if first_row:
                        headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
                
                rows = []
                for row in table.find_all('tr')[1:] if headers else table.find_all('tr'):
                    row_data = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                    if row_data and any(cell.strip() for cell in row_data):
                        rows.append(row_data)
                
                fee_data[heading_text] = {
                    'headers': headers,
                    'rows': rows
                }
        
        # If no structured fee data found from headings, look for tables with fee-related terms
        if not fee_data:
            for table in soup.find_all('table'):
                table_text = table.get_text().lower()
                if any(term in table_text for term in ['fee', 'tuition', 'cost', 'payment', 'charges']):
                    # Get the title from heading or make a default
                    title = None
                    heading = table.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                    if heading:
                        title = heading.get_text(strip=True)
                    else:
                        title = "Fee Structure"
                    
                    # Extract table data
                    headers = []
                    header_row = table.find('thead')
                    if header_row:
                        headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
                    
                    if not headers:
                        first_row = table.find('tr')
                        if first_row:
                            headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
                    
                    rows = []
                    for row in table.find_all('tr')[1:] if headers else table.find_all('tr'):
                        row_data = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                        if row_data and any(cell.strip() for cell in row_data):
                            rows.append(row_data)
                    
                    fee_data[title] = {
                        'headers': headers,
                        'rows': rows
                    }
        
        # If no structured data found, try to extract text content
        if not fee_data:
            fee_paragraphs = []
            for p in soup.find_all(['p', 'div']):
                text = p.get_text(strip=True)
                if any(term in text.lower() for term in ['fee', 'tuition', 'cost', 'payment', 'charges']) and len(text) < 500:
                    fee_paragraphs.append(text)
            
            if fee_paragraphs:
                fee_data['text_content'] = fee_paragraphs
                
        return fee_data
    
    def extract_course_information(self, html_content: str) -> Dict:
        """
        Extract course/program information from HTML content.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        course_data = {}
        
        # Look for course-related headings
        course_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], 
                                      string=lambda s: s and any(term in s.lower() 
                                                              for term in ['course', 'program', 'degree', 
                                                                          'stream', 'specialization', 'department']))
        
        for heading in course_headings:
            heading_text = heading.get_text(strip=True)
            
            # Look for tables after this heading
            table = heading.find_next('table')
            if table:
                # Extract table data similar to fee structure
                headers = []
                header_row = table.find('thead')
                if header_row:
                    headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
                
                if not headers:
                    first_row = table.find('tr')
                    if first_row:
                        headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
                
                rows = []
                for row in table.find_all('tr')[1:] if headers else table.find_all('tr'):
                    row_data = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                    if row_data and any(cell.strip() for cell in row_data):
                        rows.append(row_data)
                
                course_data[heading_text] = {
                    'headers': headers,
                    'rows': rows
                }
        
        # If no data found from headings, look for tables with course-related terms
        if not course_data:
            for table in soup.find_all('table'):
                table_text = table.get_text().lower()
                if any(term in table_text for term in ['course', 'program', 'degree', 'stream', 'intake']):
                    # Get the title from heading or make a default
                    title = None
                    heading = table.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                    if heading:
                        title = heading.get_text(strip=True)
                    else:
                        title = "Course Information"
                    
                    # Extract table data
                    headers = []
                    header_row = table.find('thead')
                    if header_row:
                        headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
                    
                    if not headers:
                        first_row = table.find('tr')
                        if first_row:
                            headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
                    
                    rows = []
                    for row in table.find_all('tr')[1:] if headers else table.find_all('tr'):
                        row_data = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                        if row_data and any(cell.strip() for cell in row_data):
                            rows.append(row_data)
                    
                    course_data[title] = {
                        'headers': headers,
                        'rows': rows
                    }
        
        # Look for course lists
        course_lists = []
        for ul in soup.find_all('ul'):
            if any(term in ul.get_text().lower() for term in ['course', 'program', 'degree']):
                courses = [li.get_text(strip=True) for li in ul.find_all('li')]
                if courses:
                    course_lists.append(courses)
        
        if course_lists:
            course_data['course_lists'] = course_lists
                
        return course_data
    
    def extract_placement_statistics(self, html_content: str) -> Dict:
        """
        Extract placement statistics information from HTML content.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        placement_stats = {}
        
        # Look for tables with placement data
        tables = self.extract_tables(html_content)
        placement_tables = []
        
        for table in tables:
            if table.get('category') == 'placement' or any(keyword in (table.get('title') or '').lower() 
                                                         for keyword in self.placement_keywords):
                placement_tables.append(table)
        
        if placement_tables:
            placement_stats['tables'] = placement_tables
        
        # Extract placement percentages
        text_content = soup.get_text()
        percentage_matches = re.findall(r'(\d+(?:\.\d+)?)%\s+(?:placement|placed|recruited)', text_content, re.IGNORECASE)
        if percentage_matches:
            placement_stats['placement_percentages'] = percentage_matches
        
        # Extract salary/package information
        salary_matches = re.findall(r'(?:Rs\.?|INR|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:lakhs?|lpa|L|Lacs?|k|K|CTC)', text_content, re.IGNORECASE)
        if salary_matches:
            placement_stats['salary_packages'] = salary_matches
        
        # Extract company counts
        company_matches = re.findall(r'(\d+)\s+(?:companies|recruiters|firms|organizations)', text_content, re.IGNORECASE)
        if company_matches:
            placement_stats['company_counts'] = company_matches
        
        # Extract company logos and names
        company_logos = []
        company_names = set()
        
        # Look for company names in text
        company_sections = soup.find_all(['div', 'section'], string=lambda s: s and any(term in str(s).lower() 
                                                                                        for term in ['our recruiters', 'recruiting companies', 'our partners']))
        
        # Process image elements that might be logos
        for img in soup.find_all('img'):
            alt_text = img.get('alt', '')
            title_text = img.get('title', '')
            src = img.get('src', '')
            
            # Check if image looks like a logo (based on size attributes or class)
            is_logo = False
            
            # Check img attributes for logo hints
            if any(logo_term in (alt_text + ' ' + title_text + ' ' + src).lower() for logo_term in ['logo', 'company', 'recruiter']):
                is_logo = True
            
            # Check size - logos are typically small to medium width/height
            width = img.get('width', '')
            height = img.get('height', '')
            if width and height:
                try:
                    # Parse with the improved method
                    if isinstance(width, str) and not width.isdigit():
                        width = ''.join(c for c in width if c.isdigit() or c == '.')
                    if isinstance(height, str) and not height.isdigit():
                        height = ''.join(c for c in height if c.isdigit() or c == '.')
                    
                    # Convert to float first to handle any decimal values
                    w = float(width) if width else 0
                    h = float(height) if height else 0
                    
                    if (30 <= w <= 200) and (30 <= h <= 100):  # Typical logo dimensions
                        is_logo = True
                except ValueError:
                    pass
            
            # Check class attributes for logo hints
            img_class = img.get('class', [])
            if isinstance(img_class, list):
                img_class = ' '.join(img_class)
            if any(term in str(img_class).lower() for term in ['logo', 'company', 'recruiter', 'partner']):
                is_logo = True
            
            # If it seems to be a logo, extract information
            if is_logo:
                logo_info = {
                    'src': urljoin(self.website_url, src) if src else None,
                    'alt': alt_text if alt_text else None,
                    'title': title_text if title_text else None
                }
                
                # Add company name if available from alt or title
                if alt_text and len(alt_text) < 50:
                    company_names.add(alt_text)
                elif title_text and len(title_text) < 50:
                    company_names.add(title_text)
                
                company_logos.append(logo_info)
        
        # Check for lists of companies
        for ul in soup.find_all('ul'):
            if any(term in ul.get_text().lower() for term in ['recruiter', 'compan', 'placement', 'recruited']):
                for li in ul.find_all('li'):
                    company_name = li.get_text(strip=True)
                    if company_name and len(company_name) < 50:  # Reasonable length for a company name
                        company_names.add(company_name)
        
        if company_logos:
            placement_stats['company_logos'] = company_logos
            
        if company_names:
            placement_stats['companies'] = list(company_names)
        
        # Look for charts or graphs
        charts = []
        
        # Find chart containers
        chart_terms = ['chart', 'graph', 'pie', 'donut']
        chart_containers = soup.find_all(['div', 'figure'], class_=lambda c: c and any(chart_term in str(c).lower() for chart_term in chart_terms))
        
        # Also look for SVG elements (often used for charts)
        svg_elements = soup.find_all('svg')
        
        # Process chart containers
        for container in chart_containers:
            chart_data = {
                'type': 'chart',
                'content': container.get_text(strip=True)
            }
            
            # Try to find headings for the chart
            chart_heading = container.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if chart_heading:
                chart_data['heading'] = chart_heading.get_text(strip=True)
            
            # Look for percentage values in the chart
            percentages = re.findall(r'(\d+(?:\.\d+)?)%', container.get_text(), re.IGNORECASE)
            if percentages:
                chart_data['percentages'] = percentages
            
            charts.append(chart_data)
            
        # Process SVG elements
        for svg in svg_elements:
            parent = svg.parent
            chart_data = {
                'type': 'svg_chart',
                'content': svg.get_text(strip=True)
            }
            
            # Try to find headings for the chart
            chart_heading = parent.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if chart_heading:
                chart_data['heading'] = chart_heading.get_text(strip=True)
            
            # Look for percentage values in the chart
            percentages = re.findall(r'(\d+(?:\.\d+)?)%', svg.get_text(), re.IGNORECASE)
            if percentages:
                chart_data['percentages'] = percentages
            
            charts.append(chart_data)
        
        if charts:
            placement_stats['charts'] = charts
            
        return placement_stats
    
    def extract_internship_data(self, html_content: str) -> Dict:
        """
        Extract internship information from HTML content.
        Identifies tables, company information, and student internship statistics.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        internship_data = {}
        
        # Look for tables with internship data
        tables = self.extract_tables(html_content)
        internship_tables = []
        
        for table in tables:
            if table.get('category') == 'internship' or any(keyword in (table.get('title') or '').lower() 
                                                         for keyword in self.internship_keywords):
                internship_tables.append(table)
            else:
                # Check table content for internship keywords
                table_text = ' '.join([' '.join(row) for row in table['rows']])
                if any(keyword in table_text.lower() for keyword in self.internship_keywords):
                    internship_tables.append(table)
        
        if internship_tables:
            internship_data['tables'] = internship_tables
        
        # Extract internship statistics from text
        text_content = soup.get_text()
        
        # Look for internship counts
        intern_count_matches = re.findall(r'(\d+)\s+(?:interns|internships|students\s+interned)', text_content, re.IGNORECASE)
        if intern_count_matches:
            internship_data['internship_counts'] = intern_count_matches
        
        # Look for company mentions
        company_pattern = r'(?:internship at|internship with|interned at|interned with)\s+([A-Z][A-Za-z\s]+)'
        company_matches = re.findall(company_pattern, text_content)
        
        # Also look for specific internship company sections
        internship_sections = soup.find_all(['div', 'section'], string=lambda s: s and any(term in str(s).lower() 
                                                                                        for term in ['internship companies', 'internship partners']))
        
        # Process image elements that might be internship company logos
        company_logos = []
        for img in soup.find_all('img'):
            alt_text = img.get('alt', '')
            title_text = img.get('title', '')
            
            # If the image seems to be related to internships
            if any(term in (alt_text + ' ' + title_text).lower() for term in self.internship_keywords):
                logo_info = {
                    'src': urljoin(self.website_url, img.get('src', '')),
                    'alt': alt_text,
                    'title': title_text
                }
                company_logos.append(logo_info)
                
                # Extract company name from alt or title
                if alt_text and len(alt_text) < 50:
                    company_matches.append(alt_text)
                elif title_text and len(title_text) < 50:
                    company_matches.append(title_text)
        
        if company_logos:
            internship_data['company_logos'] = company_logos
            
        if company_matches:
            internship_data['mentioned_companies'] = list(set(company_matches))
        
        # Look for sections with yearly internship data
        year_pattern = r'(20\d{2}[-–]\d{2,4}|20\d{2})'
        years_mentioned = re.findall(year_pattern, text_content)
        
        yearly_data = {}
        if years_mentioned:
            for year in set(years_mentioned):
                # Find content related to this academic year
                year_matches = re.findall(rf'{year}.*?(\d+).*?(?:students|interns)', text_content, re.IGNORECASE | re.DOTALL)
                if year_matches:
                    yearly_data[year] = int(year_matches[0])
        
        if yearly_data:
            internship_data['yearly_counts'] = yearly_data
            
        # Look for specific internship programs or opportunities
        programs = []
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            if any(term in heading.get_text().lower() for term in self.internship_keywords):
                program_info = {
                    'title': heading.get_text(strip=True),
                    'description': ''
                }
                
                # Get description from following paragraphs
                next_elem = heading.next_sibling
                description_parts = []
                
                while next_elem and not (hasattr(next_elem, 'name') and next_elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    if hasattr(next_elem, 'get_text'):
                        text = next_elem.get_text(strip=True)
                        if text:
                            description_parts.append(text)
                    next_elem = next_elem.next_sibling
                
                if description_parts:
                    program_info['description'] = ' '.join(description_parts)
                    programs.append(program_info)
        
        if programs:
            internship_data['programs'] = programs
            
        return internship_data
    
    def extract_admission_data(self, html_content: str, url: str) -> Dict:
        """
        Extract comprehensive admission information from HTML content.
        Processes fee structures, course details, eligibility criteria, and other admission-related information.
        """
        admission_data = {}
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract all tables
        tables = self.extract_tables(html_content)
        admission_tables = [table for table in tables if table.get('category') == 'admission']
        
        # Extract fee structure
        fee_data = self.extract_fee_structure(html_content)
        if fee_data:
            admission_data['fee_structure'] = fee_data
        
        # Extract course information
        course_data = self.extract_course_information(html_content)
        if course_data:
            admission_data['courses'] = course_data
        
        # If we have admission tables but no categorized data, include them
        if admission_tables and not (fee_data or course_data):
            admission_data['tables'] = admission_tables
        elif not admission_tables and not (fee_data or course_data) and tables:
            # If no specific admission data found, include general tables that might be relevant
            for table in tables:
                table_text = ' '.join([' '.join(row) for row in table['rows']])
                if any(keyword in table_text.lower() for keyword in self.admission_keywords):
                    if 'tables' not in admission_data:
                        admission_data['tables'] = []
                    admission_data['tables'].append(table)
        
        # Extract eligibility criteria
        eligibility_sections = []
        
        # Look for eligibility headings
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            if 'eligibility' in heading.get_text().lower() or 'criteria' in heading.get_text().lower():
                section_content = []
                
                # Get content following the heading
                next_elem = heading.next_sibling
                while next_elem and not (hasattr(next_elem, 'name') and next_elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    if hasattr(next_elem, 'get_text'):
                        text = next_elem.get_text(strip=True)
                        if text:
                            section_content.append(text)
                    next_elem = next_elem.next_sibling
                
                if section_content:
                    eligibility_sections.append({
                        'heading': heading.get_text(strip=True),
                        'content': ' '.join(section_content)
                    })
        
        if eligibility_sections:
            admission_data['eligibility'] = eligibility_sections
            
        # Look for scholarship information
        scholarship_data = {}
        scholarship_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], 
                                           string=lambda s: s and 'scholarship' in s.lower())
        
        for heading in scholarship_headings:
            heading_text = heading.get_text(strip=True)
            
            # Get content following the heading
            next_elem = heading.next_sibling
            scholarship_content = []
            
            while next_elem and not (hasattr(next_elem, 'name') and next_elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                if hasattr(next_elem, 'get_text'):
                    text = next_elem.get_text(strip=True)
                    if text:
                        scholarship_content.append(text)
                next_elem = next_elem.next_sibling
            
            if scholarship_content:
                scholarship_data[heading_text] = ' '.join(scholarship_content)
        
        if scholarship_data:
            admission_data['scholarships'] = scholarship_data
            
        # Look for hostel facilities information
        hostel_data = {}
        hostel_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], 
                                       string=lambda s: s and 'hostel' in s.lower())
        
        for heading in hostel_headings:
            heading_text = heading.get_text(strip=True)
            
            # Get content following the heading
            next_elem = heading.next_sibling
            hostel_content = []
            
            while next_elem and not (hasattr(next_elem, 'name') and next_elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                if hasattr(next_elem, 'get_text'):
                    text = next_elem.get_text(strip=True)
                    if text:
                        hostel_content.append(text)
                next_elem = next_elem.next_sibling
            
            if hostel_content:
                hostel_data[heading_text] = ' '.join(hostel_content)
        
        if hostel_data:
            admission_data['hostel'] = hostel_data
            
        # Look for admission procedure or steps
        procedure_data = {}
        procedure_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], 
                                         string=lambda s: s and any(term in s.lower() 
                                                                  for term in ['admission procedure', 
                                                                              'admission process', 
                                                                              'how to apply', 
                                                                              'application steps']))
        
        for heading in procedure_headings:
            heading_text = heading.get_text(strip=True)
            
            # Get content following the heading
            next_elem = heading.next_sibling
            procedure_content = []
            
            while next_elem and not (hasattr(next_elem, 'name') and next_elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                if hasattr(next_elem, 'get_text'):
                    text = next_elem.get_text(strip=True)
                    if text:
                        procedure_content.append(text)
                elif hasattr(next_elem, 'name') and next_elem.name == 'ul':
                    # Extract steps from list items
                    for li in next_elem.find_all('li'):
                        procedure_content.append(li.get_text(strip=True))
                next_elem = next_elem.next_sibling
            
            if procedure_content:
                procedure_data[heading_text] = procedure_content
        
        if procedure_data:
            admission_data['procedure'] = procedure_data
        
        # Extract application/admission deadline information
        deadline_pattern = r'(?:admission|application)\s+(?:deadline|due date|last date|closes on)\s*(?::|is|are|for)?\s*([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z]+,?\s+\d{4})'
        deadline_matches = re.findall(deadline_pattern, html_content, re.IGNORECASE)
        
        if deadline_matches:
            admission_data['deadlines'] = deadline_matches
        
        # Add the URL for reference
        admission_data['source_url'] = url
        
        # Add page ID if available
        page_id = self.extract_page_id(url)
        if page_id:
            admission_data['page_id'] = page_id
        
        return admission_data
    
    def crawl(self, max_pages=30, max_depth=3) -> Dict:
        """
        Perform the crawl to gather all college information.
        
        Args:
            max_pages: Maximum number of pages to process
            max_depth: Maximum depth to crawl from seed URL
            
        Returns:
            Dictionary with the extracted data
        """
        logger.info(f"Starting enhanced crawl for {self.college_name} at {self.website_url}")
        
        # Initialize progress tracking
        self.progress.update(total=max_pages, status="Starting")
        
        pages_processed = 0
        current_depth = 0
        depth_urls = {0: [self.website_url]}
        
        # Process seed URL and then BFS for subsequent URLs
        while current_depth <= max_depth and pages_processed < max_pages:
            # If no URLs at this depth, move to next depth
            if current_depth not in depth_urls or not depth_urls[current_depth]:
                current_depth += 1
                continue
            
            # Get the next URL to process at current depth
            url = depth_urls[current_depth].pop(0)
            
            # Skip if already explored
            if url in self.explored_urls:
                continue
            
            # Mark as explored
            self.explored_urls.add(url)
            
            # Update progress
            self.progress.update(status=f"Processing (depth {current_depth})", url=url)
            
            # Fetch the page
            logger.info(f"Processing URL: {url} (depth {current_depth})")
            html_content, metadata = self.fetch_page(url)
            
            if not html_content:
                logger.warning(f"Failed to fetch content from {url}")
                self.progress.update(error=f"Failed to fetch: {url}")
                continue
            
            # Increment pages processed
            pages_processed += 1
            self.progress.update(processed=pages_processed)
            
            # Categorize the URL based on content
            category = self.categorize_url(url, html_content)
            
            # Process content based on category
            if category == 'admission':
                self.admission_urls.add(url)
                admission_data = self.extract_admission_data(html_content, url)
                key = f"{url.replace('://', '_').replace('/', '_')}"
                self.results['admission_data'][key] = {
                    'url': url,
                    'data': admission_data
                }
                
            elif category == 'placement':
                self.placement_urls.add(url)
                placement_data = self.extract_placement_statistics(html_content)
                key = f"{url.replace('://', '_').replace('/', '_')}"
                self.results['placement_data'][key] = {
                    'url': url,
                    'data': placement_data
                }
                
            elif category == 'internship':
                self.internship_urls.add(url)
                internship_data = self.extract_internship_data(html_content)
                key = f"{url.replace('://', '_').replace('/', '_')}"
                self.results['internship_data'][key] = {
                    'url': url,
                    'data': internship_data
                }
            
            # Extract URLs from this page for next depth
            if current_depth < max_depth:
                extracted_urls = self.extract_urls(html_content, url)
                
                # Add to next depth if not already explored
                next_depth = current_depth + 1
                if next_depth not in depth_urls:
                    depth_urls[next_depth] = []
                
                for ext_url in extracted_urls:
                    if ext_url not in self.explored_urls and ext_url not in self.pending_urls:
                        depth_urls[next_depth].append(ext_url)
                        self.pending_urls.add(ext_url)
            
            # Log progress periodically
            if pages_processed % 5 == 0:
                logger.info(f"Processed {pages_processed} pages. Found {len(self.results['admission_data'])} admission, {len(self.results['placement_data'])} placement, and {len(self.results['internship_data'])} internship pages")
                self.progress.update(status=f"Processed {pages_processed}/{max_pages} pages")

            # Special handling for known URLs patterns
            # This is to ensure we don't miss important pages that might not get detected automatically
            lower_url = url.lower()
            
            # For admission-specific URL patterns
            if any(pattern in lower_url for pattern in ['/admission', '/apply', '/entrance', '/course']):
                self.admission_urls.add(url)
                key = f"{url.replace('://', '_').replace('/', '_')}"
                if key not in self.results['admission_data']:
                    admission_data = self.extract_admission_data(html_content, url)
                    self.results['admission_data'][key] = {
                        'url': url,
                        'data': admission_data
                    }
            
            # For placement-specific URL patterns
            if any(pattern in lower_url for pattern in ['/placement', '/career', '/recruiter', '/company']):
                self.placement_urls.add(url)
                key = f"{url.replace('://', '_').replace('/', '_')}"
                if key not in self.results['placement_data']:
                    placement_data = self.extract_placement_statistics(html_content)
                    self.results['placement_data'][key] = {
                        'url': url,
                        'data': placement_data
                    }
            
            # For internship-specific URL patterns
            if any(pattern in lower_url for pattern in ['/intern', '/training']):
                self.internship_urls.add(url)
                key = f"{url.replace('://', '_').replace('/', '_')}"
                if key not in self.results['internship_data']:
                    internship_data = self.extract_internship_data(html_content)
                    self.results['internship_data'][key] = {
                        'url': url,
                        'data': internship_data
                    }
        
        # Process AI-based interpretation of the extracted data
        self.progress.update(status="Analyzing extracted data")
        self._analyze_extracted_data()
                    
        # Update results metadata
        self.results['pages_processed'] = pages_processed
        
        # Add messages based on results
        if not self.results['admission_data']:
            self.results['message'] += "No admission data found. "
        if not self.results['placement_data']:
            self.results['message'] += "No placement data found. "
        if not self.results['internship_data']:
            self.results['message'] += "No internship data found. "
            
        if self.results['message'] == "":
            self.results['message'] = "Successfully extracted college data."
        
        # Final progress update
        self.progress.update(status="Completed", processed=pages_processed)
            
        # Save results
        self._save_results()
        
        logger.info(f"Completed enhanced crawl for {self.college_name}. Processed {pages_processed} pages.")
        return self.results
    
    def _analyze_extracted_data(self):
        """
        Analyze the extracted data to identify patterns and structure the information better.
        This is an AI-based approach to make sense of the raw extracted data.
        """
        # Analyze admission data
        self._analyze_admission_data()
        
        # Analyze placement data
        self._analyze_placement_data()
        
        # Analyze internship data
        self._analyze_internship_data()
    
    def _analyze_admission_data(self):
        """
        Analyze admission data to extract structured information like:
        - Available courses and their details
        - Fee structure for different courses
        - Eligibility criteria
        - Admission process
        """
        parsed_admission = {
            'courses': [],
            'fee_structure': {},
            'eligibility': {},
            'procedure': [],
            'deadlines': [],
            'summary': {}
        }
        
        # Process all admission data sources
        for key, item in self.results['admission_data'].items():
            data = item.get('data', {})
            
            # Extract courses
            if 'courses' in data:
                for course_title, course_data in data['courses'].items():
                    if 'headers' in course_data and 'rows' in course_data:
                        # Process course tables
                        for row in course_data['rows']:
                            if len(row) >= 2:
                                course_info = {
                                    'name': row[0] if row[0] else 'Unknown Course',
                                    'details': {}
                                }
                                
                                # Map headers to values
                                for i, header in enumerate(course_data['headers']):
                                    if i < len(row) and row[i]:
                                        course_info['details'][header] = row[i]
                                
                                parsed_admission['courses'].append(course_info)
            
            # Extract fee structure
            if 'fee_structure' in data:
                for fee_title, fee_data in data['fee_structure'].items():
                    if fee_title == 'text_content':
                        # Text-based fee info
                        parsed_admission['fee_structure']['general'] = fee_data
                    elif 'headers' in fee_data and 'rows' in fee_data:
                        # Table-based fee info
                        fee_category = fee_title.lower().replace(' ', '_')
                        parsed_admission['fee_structure'][fee_category] = []
                        
                        for row in fee_data['rows']:
                            if len(row) >= 2:
                                fee_info = {
                                    'description': row[0] if row[0] else 'Unknown Fee',
                                    'details': {}
                                }
                                
                                # Map headers to values
                                for i, header in enumerate(fee_data['headers']):
                                    if i < len(row) and row[i]:
                                        fee_info['details'][header] = row[i]
                                
                                parsed_admission['fee_structure'][fee_category].append(fee_info)
            
            # Extract eligibility
            if 'eligibility' in data:
                for eligibility_item in data['eligibility']:
                    category = eligibility_item.get('heading', 'General Eligibility')
                    content = eligibility_item.get('content', '')
                    
                    if content:
                        parsed_admission['eligibility'][category] = content
            
            # Extract deadlines
            if 'deadlines' in data:
                for deadline in data['deadlines']:
                    if deadline not in parsed_admission['deadlines']:
                        parsed_admission['deadlines'].append(deadline)
            
            # Extract procedure
            if 'procedure' in data:
                for proc_title, proc_content in data['procedure'].items():
                    procedure_info = {
                        'title': proc_title,
                        'steps': proc_content if isinstance(proc_content, list) else [proc_content]
                    }
                    parsed_admission['procedure'].append(procedure_info)
        
        # Create summary statistics
        if parsed_admission['courses']:
            parsed_admission['summary']['total_courses'] = len(parsed_admission['courses'])
            course_types = set(course.get('details', {}).get('Branch', course.get('details', {}).get('Programme', 'Unknown')) 
                              for course in parsed_admission['courses'])
            parsed_admission['summary']['course_types'] = list(course_types)
        
        # Save to results
        self.results['parsed_data']['admission'] = parsed_admission
    
    def _analyze_placement_data(self):
        """
        Analyze placement data to extract structured information like:
        - Placement statistics
        - Companies that visit for recruitment
        - Salary packages
        - Year-wise trends
        """
        parsed_placement = {
            'statistics': {},
            'companies': [],
            'salary_packages': [],
            'charts_data': [],
            'summary': {}
        }
        
        # Process all placement data sources
        placement_percentages = []
        salary_values = []
        company_counts = []
        all_companies = set()
        
        for key, item in self.results['placement_data'].items():
            data = item.get('data', {})
            
            # Extract placement percentages
            if 'placement_percentages' in data:
                for percentage in data['placement_percentages']:
                    try:
                        value = float(percentage)
                        placement_percentages.append(value)
                    except ValueError:
                        continue
            
            # Extract salary packages
            if 'salary_packages' in data:
                for salary in data['salary_packages']:
                    try:
                        value = float(salary.replace(',', ''))
                        salary_values.append(value)
                        
                        # Add to structured list
                        parsed_placement['salary_packages'].append({
                            'value': value,
                            'original': salary
                        })
                    except ValueError:
                        continue
            
            # Extract company counts
            if 'company_counts' in data:
                for count in data['company_counts']:
                    try:
                        value = int(count)
                        company_counts.append(value)
                    except ValueError:
                        continue
            
            # Extract companies
            if 'companies' in data:
                for company in data['companies']:
                    if company and len(company) < 50:  # Reasonable length for a company name
                        all_companies.add(company)
            
            # Extract company logos
            if 'company_logos' in data:
                for logo in data['company_logos']:
                    if logo.get('alt') and logo.get('alt') not in all_companies:
                        all_companies.add(logo.get('alt'))
                    elif logo.get('title') and logo.get('title') not in all_companies:
                        all_companies.add(logo.get('title'))
            
            # Process table data
            if 'tables' in data:
                for table in data['tables']:
                    table_content = ' '.join([' '.join(row) for row in table['rows']])
                    
                    # Check if this is a placement statistics table
                    if any(term in table_content.lower() for term in ['placement', 'placed', 'recruited']):
                        # Process table data
                        for row in table['rows']:
                            if len(row) >= 2:
                                # Try to identify columns
                                if any(term in str(row[0]).lower() for term in ['year', 'batch', 'session']):
                                    # Year-wise placement data
                                    year_label = row[0]
                                    
                                    # Try to find percentage in the row
                                    for cell in row[1:]:
                                        percentage_match = re.search(r'(\d+(?:\.\d+)?)%', cell)
                                        if percentage_match:
                                            try:
                                                value = float(percentage_match.group(1))
                                                placement_percentages.append(value)
                                                
                                                if 'yearly_stats' not in parsed_placement['statistics']:
                                                    parsed_placement['statistics']['yearly_stats'] = []
                                                
                                                parsed_placement['statistics']['yearly_stats'].append({
                                                    'year': year_label,
                                                    'placement_percentage': value
                                                })
                                            except ValueError:
                                                continue
            
            # Process charts data
            if 'charts' in data:
                for chart in data['charts']:
                    chart_info = {
                        'title': chart.get('heading', 'Placement Chart'),
                        'data': []
                    }
                    
                    # Extract percentages from chart
                    if 'percentages' in chart:
                        for percentage in chart['percentages']:
                            try:
                                value = float(percentage)
                                chart_info['data'].append({
                                    'label': 'Value',
                                    'value': value,
                                    'unit': '%'
                                })
                            except ValueError:
                                continue
                    
                    if chart_info['data']:
                        parsed_placement['charts_data'].append(chart_info)
        
        # Process collected data into statistics
        if placement_percentages:
            parsed_placement['statistics']['avg_placement_percentage'] = sum(placement_percentages) / len(placement_percentages)
            parsed_placement['statistics']['max_placement_percentage'] = max(placement_percentages)
        
        if salary_values:
            parsed_placement['statistics']['avg_salary_package'] = sum(salary_values) / len(salary_values)
            parsed_placement['statistics']['max_salary_package'] = max(salary_values)
            parsed_placement['statistics']['min_salary_package'] = min(salary_values)
        
        if company_counts:
            parsed_placement['statistics']['avg_companies'] = sum(company_counts) / len(company_counts)
            parsed_placement['statistics']['max_companies'] = max(company_counts)
        
        # Add companies list
        parsed_placement['companies'] = list(all_companies)
        
        # Create summary
        parsed_placement['summary'] = {
            'total_companies': len(parsed_placement['companies']),
            'placement_rate': parsed_placement['statistics'].get('avg_placement_percentage', 'Unknown'),
            'avg_package': parsed_placement['statistics'].get('avg_salary_package', 'Unknown')
        }
        
        # Save to results
        self.results['parsed_data']['placement'] = parsed_placement
    
    def _analyze_internship_data(self):
        """
        Analyze internship data to extract structured information like:
        - Internship statistics
        - Companies offering internships
        - Year-wise trends
        """
        parsed_internship = {
            'statistics': {},
            'companies': [],
            'programs': [],
            'summary': {}
        }
        
        # Process all internship data sources
        internship_counts = []
        company_names = set()
        
        for key, item in self.results['internship_data'].items():
            data = item.get('data', {})
            
            # Extract internship counts
            if 'internship_counts' in data:
                for count in data['internship_counts']:
                    try:
                        value = int(count)
                        internship_counts.append(value)
                    except ValueError:
                        continue
            
            # Extract companies
            if 'mentioned_companies' in data:
                for company in data['mentioned_companies']:
                    if company and len(company) < 50:  # Reasonable length for a company name
                        company_names.add(company)
            
            # Process yearly data
            if 'yearly_counts' in data:
                if 'yearly_stats' not in parsed_internship['statistics']:
                    parsed_internship['statistics']['yearly_stats'] = []
                
                for year, count in data['yearly_counts'].items():
                    parsed_internship['statistics']['yearly_stats'].append({
                        'year': year,
                        'count': count
                    })
            
            # Process programs
            if 'programs' in data:
                for program in data['programs']:
                    if program.get('title') and program.get('description'):
                        parsed_internship['programs'].append(program)
            
            # Process tables
            if 'tables' in data:
                for table in data['tables']:
                    table_content = ' '.join([' '.join(row) for row in table['rows']])
                    
                    # Check if this is an internship company table
                    if any(term in table_content.lower() for term in ['company', 'organization', 'firm']):
                        # Process table to extract company names
                        for row in table['rows']:
                            # Company name is often in first column
                            if row and len(row) >= 1 and row[0]:
                                company = row[0]
                                if len(company) < 50:  # Reasonable length for company name
                                    company_names.add(company)
                                    
                                    # Check if there's a count column
                                    if len(row) >= 2:
                                        try:
                                            count = int(row[1])
                                            if 'company_stats' not in parsed_internship['statistics']:
                                                parsed_internship['statistics']['company_stats'] = []
                                            
                                            parsed_internship['statistics']['company_stats'].append({
                                                'company': company,
                                                'count': count
                                            })
                                        except (ValueError, IndexError):
                                            pass
        
        # Process collected data into statistics
        if internship_counts:
            parsed_internship['statistics']['avg_internships'] = sum(internship_counts) / len(internship_counts)
            parsed_internship['statistics']['max_internships'] = max(internship_counts)
        
        # Add companies list
        parsed_internship['companies'] = list(company_names)
        
        # Create summary
        parsed_internship['summary'] = {
            'total_companies': len(parsed_internship['companies']),
            'internship_count': parsed_internship['statistics'].get('max_internships', 'Unknown')
        }
        
        # Save to results
        self.results['parsed_data']['internship'] = parsed_internship
    
    def _save_results(self):
        """Save crawl results to a JSON file."""
        # Ensure the output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Create the filename from the domain
        filename = f"{self.domain.replace('.', '_')}.json"
        filepath = os.path.join(self.output_dir, filename)
        
        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Saved results to {filepath}")
    
    def get_progress(self):
        """Get the current crawling progress."""
        return self.progress.get_status()