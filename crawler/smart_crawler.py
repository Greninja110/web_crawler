"""
Smart Web Crawler

A modular, intelligent web crawler designed to extract structured information
from websites based on configurable parameters and machine learning.

Main components:
1. Configuration
2. Basic Crawler
3. Intelligent Content Extraction
4. Structured Data Extraction
5. Machine Learning Model Training
6. Post-Processing & Validation
7. Scheduling & Infrastructure
8. Monitoring & Maintenance
"""

import os
import re
import json
import csv
import time
import logging
import threading
import datetime
import hashlib
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Any, Set, Tuple, Optional, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import random

# Web crawling libraries
import requests
from bs4 import BeautifulSoup
import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor

# NLP and ML libraries
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.metrics import classification_report, accuracy_score, precision_recall_fscore_support
import spacy
from spacy.matcher import Matcher
from dateutil.parser import parse as parse_date
import joblib
import fnmatch
# Scheduling
import schedule

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("crawler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# 1. CONFIGURATION SECTION
# =============================================================================

class CrawlFrequency(Enum):
    """Enumeration for crawl frequency options."""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"  # For custom intervals in minutes


@dataclass
class CrawlerConfig:
    """Configuration class for the smart web crawler."""
    
    # Basic configuration
    project_name: str
    goal: str
    seed_urls: List[str]
    keywords: List[str]
    allowed_domains: List[str] = field(default_factory=list)
    
    # Crawling parameters
    max_depth: int = 3
    max_pages_per_domain: int = 100
    crawl_frequency: CrawlFrequency = CrawlFrequency.DAILY
    custom_frequency_minutes: int = 1440  # Default to daily in minutes
    respect_robots_txt: bool = True
    user_agent: str = "SmartWebCrawler/1.0"
    
    # Content extraction parameters
    extract_full_text: bool = True
    min_content_length: int = 100
    filter_advertisements: bool = True
    
    # ML and NLP parameters
    use_nlp: bool = True
    use_ml_classification: bool = False
    confidence_threshold: float = 0.7
    
    # Storage and output
    output_directory: str = "crawl_results"
    output_format: str = "json"  # Options: json, csv
    save_html: bool = False
    
    # Infrastructure
    parallel_crawlers: int = 1
    request_timeout: int = 30  # in seconds
    request_delay: float = 0.5  # in seconds
    
    # Notification
    enable_notifications: bool = False
    notification_email: str = ""
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        # Generate allowed domains from seed URLs if not provided
        if not self.allowed_domains:
            self.allowed_domains = []
            for url in self.seed_urls:
                # Ensure URL has proper protocol for parsing
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                self.allowed_domains.append(urlparse(url).netloc)
            
        # Create output directory if it doesn't exist
        os.makedirs(self.output_directory, exist_ok=True)
        
        # Save configuration to file
        self.save_config()
            
    def save_config(self):
        """Save the configuration to a JSON file."""
        config_dict = {k: (v.value if isinstance(v, Enum) else v) 
                      for k, v in self.__dict__.items()}
        
        with open(os.path.join(self.output_directory, "config.json"), "w") as f:
            json.dump(config_dict, f, indent=4)
        
    @classmethod
    def load_config(cls, config_path: str) -> 'CrawlerConfig':
        """Load configuration from a JSON file."""
        with open(config_path, "r") as f:
            config_dict = json.load(f)
            
        # Convert string to enum for crawl_frequency
        if "crawl_frequency" in config_dict:
            config_dict["crawl_frequency"] = CrawlFrequency(config_dict["crawl_frequency"])
            
        return cls(**config_dict)

    def get_crawl_interval_minutes(self) -> int:
        """Get the crawl interval in minutes based on the frequency setting."""
        if self.crawl_frequency == CrawlFrequency.CUSTOM:
            return self.custom_frequency_minutes
        elif self.crawl_frequency == CrawlFrequency.HOURLY:
            return 60
        elif self.crawl_frequency == CrawlFrequency.DAILY:
            return 1440  # 24 * 60
        elif self.crawl_frequency == CrawlFrequency.WEEKLY:
            return 10080  # 7 * 24 * 60
        elif self.crawl_frequency == CrawlFrequency.MONTHLY:
            return 43200  # 30 * 24 * 60
        else:
            return 1440  # Default to daily


# Example configuration
def get_sample_config() -> CrawlerConfig:
    """Create a sample configuration for educational website crawling."""
    return CrawlerConfig(
        project_name="university_admissions",
        goal="Extract educational admission announcements, deadlines, and entrance exam details",
        seed_urls=[
            "https://www.mbit.edu.in",
        ],
        keywords=[
            "admission", "deadline", "application", "entrance exam", 
            "eligibility", "scholarship", "fee", "requirement", "placement"
        ],
        max_depth=3,
        use_nlp=True,
        use_ml_classification=True
    )


# =============================================================================
# 2. BASIC CRAWLER
# =============================================================================

class URLQueue:
    """A queue system to manage URLs for crawling."""
    
    def __init__(self, config: CrawlerConfig):
        self.queue = deque()  # URLs waiting to be processed
        self.visited = set()  # URLs that have been processed
        self.url_metadata = {}  # Store metadata like depth, referrer, etc.
        self.config = config
        
        # Domain-specific counters and limits
        self.domain_counts = defaultdict(int)
        
        # Initialize the queue with seed URLs
        for url in config.seed_urls:
            # Ensure URL has proper protocol
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            self.add_url(url, depth=0, referrer=None)
    
    def add_url(self, url: str, depth: int, referrer: Optional[str] = None) -> bool:
        """
        Add a URL to the queue if it meets the criteria.
        
        Args:
            url: The URL to add
            depth: The crawl depth of this URL
            referrer: The URL that led to this one
            
        Returns:
            bool: True if the URL was added, False otherwise
        """
        # Skip if URL already visited or queued
        if url in self.visited or url in self.url_metadata:
            return False
            
        # Check max depth
        if depth > self.config.max_depth:
            logger.debug(f"Skipping {url} - exceeds max depth of {self.config.max_depth}")
            return False
            
        # Check if URL is in allowed domains
        domain = urlparse(url).netloc
        if domain not in self.config.allowed_domains:
            logger.debug(f"Skipping {url} - domain {domain} not in allowed domains")
            return False
            
        # Check domain page limit
        if self.domain_counts[domain] >= self.config.max_pages_per_domain:
            logger.debug(f"Skipping {url} - domain {domain} reached max pages")
            return False
        
        # Add to queue
        self.queue.append(url)
        self.url_metadata[url] = {
            'depth': depth,
            'referrer': referrer,
            'added_time': time.time(),
            'domain': domain
        }
        
        logger.debug(f"Added URL to queue: {url} (depth {depth})")
        return True
    
    def get_next_url(self) -> Optional[str]:
        """Get the next URL from the queue."""
        if not self.queue:
            return None
            
        url = self.queue.popleft()
        self.visited.add(url)
        
        # Increment domain counter
        domain = self.url_metadata[url]['domain']
        self.domain_counts[domain] += 1
        
        return url
    
    def get_metadata(self, url: str) -> Dict:
        """Get metadata for a URL."""
        return self.url_metadata.get(url, {})
    
    def size(self) -> int:
        """Get the current queue size."""
        return len(self.queue)
    
    def visited_count(self) -> int:
        """Get the number of visited URLs."""
        return len(self.visited)
    
    def clear(self):
        """Clear the queue and visited sets."""
        self.queue.clear()
        self.visited.clear()
        self.url_metadata.clear()
        self.domain_counts.clear()


class URLExtractor:
    """Extract and normalize URLs from HTML content."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
    
    def extract_urls(self, html_content: str) -> List[str]:
        """Extract URLs from HTML content."""
        soup = BeautifulSoup(html_content, 'html.parser')
        urls = []
        
        # Extract from anchor tags
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Normalize URL
            full_url = urljoin(self.base_url, href)
            # Skip fragment URLs that point to the same page
            if '#' in full_url and full_url.split('#')[0] == self.base_url:
                continue
            # Skip non-HTTP URLs
            if not full_url.startswith(('http://', 'https://')):
                continue
            urls.append(full_url)
        
        return urls


class BasicCrawler:
    """Basic web crawler that fetches pages and extracts links."""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.url_queue = URLQueue(config)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': config.user_agent})
        
        # Create output directory if it doesn't exist
        os.makedirs(config.output_directory, exist_ok=True)
        
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
    
    def extract_urls(self, html_content: str, base_url: str) -> List[str]:
        """Extract URLs from HTML content."""
        extractor = URLExtractor(base_url)
        return extractor.extract_urls(html_content)
    
    def process_url(self, url: str) -> Dict:
        """
        Process a single URL: fetch, extract content and links.
        
        Args:
            url: The URL to process
            
        Returns:
            Dict with processing results
        """
        logger.info(f"Processing URL: {url}")
        
        # Get URL metadata (depth, etc.)
        url_meta = self.url_queue.get_metadata(url)
        current_depth = url_meta.get('depth', 0)
        
        # Fetch the page
        html_content, response_meta = self.fetch_page(url)
        if not html_content:
            return {"url": url, "success": False, "error": "Failed to fetch page"}
        
        # Extract links if not at max depth
        if current_depth < self.config.max_depth:
            extracted_urls = self.extract_urls(html_content, url)
            logger.debug(f"Extracted {len(extracted_urls)} URLs from {url}")
            
            # Add URLs to queue
            new_urls_added = 0
            for extracted_url in extracted_urls:
                if self.url_queue.add_url(
                    extracted_url, 
                    depth=current_depth + 1,
                    referrer=url
                ):
                    new_urls_added += 1
                    
            logger.debug(f"Added {new_urls_added} new URLs to the queue")
        
        # Save HTML content if configured
        if self.config.save_html:
            self.save_html_content(url, html_content)
        
        return {
            "url": url,
            "success": True,
            "depth": current_depth,
            "html_content": html_content,
            "response_meta": response_meta
        }
    
    def save_html_content(self, url: str, html_content: str):
        """Save HTML content to a file."""
        # Create a filename from the URL
        filename = hashlib.md5(url.encode()).hexdigest() + ".html"
        filepath = os.path.join(self.config.output_directory, "html", filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save the file
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        logger.debug(f"Saved HTML content for {url} to {filepath}")
    
    def run(self, max_pages: Optional[int] = None) -> List[Dict]:
        """
        Run the crawler until the queue is empty or max_pages is reached.
        
        Args:
            max_pages: Maximum number of pages to process (None for unlimited)
            
        Returns:
            List of results from processing each URL
        """
        results = []
        pages_processed = 0
        
        while True:
            # Check if we've reached the max pages limit
            if max_pages is not None and pages_processed >= max_pages:
                logger.info(f"Reached maximum pages limit ({max_pages})")
                break
                
            # Get the next URL from the queue
            url = self.url_queue.get_next_url()
            if not url:
                logger.info("URL queue is empty, crawler finished")
                break
            
            # Process the URL
            result = self.process_url(url)
            results.append(result)
            
            pages_processed += 1
            if pages_processed % 10 == 0:
                logger.info(f"Processed {pages_processed} pages, {self.url_queue.size()} remaining in queue")
        
        logger.info(f"Crawling complete. Processed {pages_processed} pages.")
        return results


# Scrapy Implementation (Alternative)
class SmartCrawlerSpider(CrawlSpider):
    """Scrapy spider implementation of the crawler."""
    
    name = "smart_crawler"
    
    def __init__(self, config: CrawlerConfig, *args, **kwargs):
        self.config = config
        self.allowed_domains = config.allowed_domains
        self.start_urls = config.seed_urls
        
        # Set up link extraction rules
        self.rules = (
            Rule(
                LinkExtractor(allow_domains=self.allowed_domains),
                callback='parse_item',
                follow=True
            ),
        )
        
        super(SmartCrawlerSpider, self).__init__(*args, **kwargs)
        
    def parse_item(self, response):
        """Parse a fetched page."""
        url = response.url
        depth = response.meta.get('depth', 0)
        
        # Skip if depth exceeds limit
        if depth > self.config.max_depth:
            return
        
        # Extract domain for tracking
        domain = urlparse(url).netloc
        
        yield {
            'url': url,
            'depth': depth,
            'domain': domain,
            'content_type': response.headers.get('Content-Type', b'').decode('utf-8'),
            'html_content': response.body.decode('utf-8'),
            'fetch_time': datetime.datetime.now().isoformat()
        }


# =============================================================================
# 3. INTELLIGENT CONTENT EXTRACTION
# =============================================================================

class ContentExtractor:
    """Extract and filter main content from HTML pages."""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        
        # Initialize spaCy if NLP is enabled
        self.nlp = None
        if config.use_nlp:
            try:
                self.nlp = spacy.load("en_core_web_sm")
                logger.info("Loaded spaCy NLP model")
            except OSError:
                logger.warning("Could not load spaCy model. Run: python -m spacy download en_core_web_sm")
    
    def extract_main_content(self, html: str) -> str:
        """
        Extract the main content from an HTML page, removing navigation, ads, etc.
        
        Args:
            html: HTML content as string
            
        Returns:
            Extracted main content as string
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove non-content elements
        self._remove_non_content_elements(soup)
        
        # Try to find the main content area
        main_content = self._find_main_content(soup)
        
        # If no main content area found, use the body
        if not main_content:
            main_content = soup.get_text(separator=' ', strip=True)
        
        # Filter out short content
        if len(main_content) < self.config.min_content_length:
            logger.debug(f"Extracted content too short: {len(main_content)} chars")
        
        return main_content
    
    def _remove_non_content_elements(self, soup: BeautifulSoup):
        """Remove navigation, ads, footers, etc. from the soup."""
        # Remove common non-content elements by tag and class
        for selector in [
            'nav', 'header', 'footer', 'aside', 'script', 'style', 'meta',
            '[class*="nav"]', '[class*="menu"]', '[class*="sidebar"]',
            '[class*="footer"]', '[class*="header"]', '[class*="banner"]',
            '[class*="ad-"]', '[class*="advertisement"]'
        ]:
            for element in soup.select(selector):
                element.decompose()
    
    def _find_main_content(self, soup: BeautifulSoup) -> str:
        """Find the main content area of the page."""
        # Try common content selectors
        for selector in [
            'main', 'article', '[role="main"]', '#content', '.content',
            '#main', '.main', '[class*="content"]', '[class*="article"]'
        ]:
            content_elements = soup.select(selector)
            if content_elements:
                # Return the text from the largest content element
                return max(
                    (elem.get_text(separator=' ', strip=True) 
                     for elem in content_elements),
                    key=len
                )
        
        # If no content found with selectors, try density analysis
        return self._extract_by_density(soup)
    
    def _extract_by_density(self, soup: BeautifulSoup) -> str:
        """Extract content by text density analysis."""
        # Get all paragraph tags
        paragraphs = soup.find_all('p')
        
        if not paragraphs:
            return soup.get_text(separator=' ', strip=True)
        
        # Find the densest part of the document (most text in smallest area)
        # This is a simple approximation
        best_density = 0
        best_content = ""
        
        for i in range(len(paragraphs)):
            # Consider consecutive paragraphs
            for j in range(i, min(i + 5, len(paragraphs))):
                content = ' '.join(p.get_text(strip=True) for p in paragraphs[i:j+1])
                if not content:
                    continue
                    
                # Calculate density (length of text divided by number of tags)
                density = len(content) / (j - i + 1)
                
                if density > best_density and len(content) > self.config.min_content_length:
                    best_density = density
                    best_content = content
        
        return best_content if best_content else soup.get_text(separator=' ', strip=True)
    
    def extract_keywords(self, text: str) -> List[Tuple[str, int]]:
        """
        Extract occurrences of keywords from text.
        
        Args:
            text: The text to search for keywords
            
        Returns:
            List of (keyword, count) tuples
        """
        results = []
        for keyword in self.config.keywords:
            # Create a regex pattern that matches whole words
            pattern = r'\b' + re.escape(keyword) + r'\b'
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                results.append((keyword, len(matches)))
        
        return sorted(results, key=lambda x: x[1], reverse=True)
    
    def extract_named_entities(self, text: str) -> List[Dict]:
        """
        Extract named entities from text using spaCy NLP.
        
        Args:
            text: Text to analyze
            
        Returns:
            List of entity dictionaries with type, text, etc.
        """
        if not self.nlp:
            logger.warning("NLP model not loaded, skipping named entity extraction")
            return []
        
        doc = self.nlp(text)
        entities = []
        
        for ent in doc.ents:
            entities.append({
                'text': ent.text,
                'start': ent.start_char,
                'end': ent.end_char,
                'type': ent.label_,
                'type_description': spacy.explain(ent.label_)
            })
        
        return entities
        
    def extract_tables(self, html: str) -> List[Dict]:
        """
        Extract tables from HTML content.
        
        Args:
            html: HTML content
            
        Returns:
            List of extracted tables with their data
        """
        soup = BeautifulSoup(html, 'html.parser')
        tables = []
        
        for table_elem in soup.find_all('table'):
            # Extract table headers
            headers = []
            header_row = table_elem.find('thead')
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            
            # If no thead, look for th elements in the first row
            if not headers:
                first_row = table_elem.find('tr')
                if first_row:
                    headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
            
            # Extract rows
            rows = []
            for row in table_elem.find_all('tr')[1:] if headers else table_elem.find_all('tr'):
                row_data = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                if row_data and len(row_data) > 0:  # Skip empty rows
                    rows.append(row_data)
            
            # Get table caption or nearby heading
            caption = table_elem.find('caption')
            caption_text = caption.get_text(strip=True) if caption else None
            
            # If no caption, look for nearby heading
            if not caption_text:
                previous_elem = table_elem.previous_sibling
                while previous_elem and not caption_text:
                    if hasattr(previous_elem, 'name') and previous_elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        caption_text = previous_elem.get_text(strip=True)
                    previous_elem = previous_elem.previous_sibling
            
            # Add to tables list
            tables.append({
                'caption': caption_text,
                'headers': headers,
                'rows': rows
            })
        
        return tables


# =============================================================================
# 4. STRUCTURED DATA EXTRACTION
# =============================================================================

class DataExtractor:
    """Extract structured data from text using patterns and NLP."""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        
        # Initialize NLP if enabled
        self.nlp = None
        if config.use_nlp:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except OSError:
                logger.warning("Could not load spaCy model for structured data extraction")
        
        # Compile common regex patterns
        self.patterns = {
            'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'phone': re.compile(r'\b(?:\+\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b'),
            'url': re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w\.-]*\??[/\w\.-=&%]*'),
            # Format: MM/DD/YYYY, DD-MM-YYYY, Month DD, YYYY, etc.
            'date': re.compile(r'\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4})\b'),
            # Format: HH:MM (AM/PM)
            'time': re.compile(r'\b(?:\d{1,2}:\d{2}(?::\d{2})?(?: ?[AP]M)?)\b'),
            # Currency format: $123,456.78 or 123,456.78 USD
            'price': re.compile(r'\b(?:\$\d+(?:,\d{3})*(?:\.\d{2})?|\d+(?:,\d{3})*(?:\.\d{2})? (?:USD|EUR|GBP))\b')
        }
        
        # Custom patterns for educational data
        self.edu_patterns = {
            'deadline': re.compile(r'\b(?:deadline|due date|close[sd]? on|submission deadline)(?:[\s\w]+)(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4})\b', re.IGNORECASE),
            'exam_date': re.compile(r'\b(?:exam date|examination date|exam schedule[sd]? on|test date)(?:[\s\w]+)(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4})\b', re.IGNORECASE),
            'application_fee': re.compile(r'(?:application fee|processing fee)(?:[\s\w]+)(\$\d+(?:,\d{3})*(?:\.\d{2})?|\d+(?:,\d{3})*(?:\.\d{2})? (?:USD|EUR|GBP))', re.IGNORECASE),
            'placement_rate': re.compile(r'(?:placement|placed)(?:[\s\w]+)(\d+(?:\.\d+)?)%', re.IGNORECASE),
            'placement_stats': re.compile(r'(?:placement statistics|placement data|placement record)(?:[\s\w]+)(\d+(?:\.\d+)?)%', re.IGNORECASE),
            'salary_package': re.compile(r'(?:salary|package|CTC)(?:[\s\w]+)((?:Rs\.?|INR|₹)?\s*\d+(?:\.\d+)?(?:\s*lakhs?|L|Lacs?|k|K|LPA))', re.IGNORECASE),
            'companies_visited': re.compile(r'(?:companies|recruiters)(?:[\s\w]+)(\d+)(?:[\s\w]+)(?:campus|placement|recruitment)', re.IGNORECASE),
        }
        
        # Initialize spaCy matchers for educational entities
        if self.nlp:
            self.matcher = Matcher(self.nlp.vocab)
            
            # Add matcher patterns for educational terms
            self.matcher.add("ADMISSION_REQ", [
                [{"LOWER": "admission"}, {"LOWER": "requirement"}],
                [{"LOWER": "eligibility"}, {"LOWER": "criteria"}]
            ])
            
            self.matcher.add("SCHOLARSHIP", [
                [{"LOWER": "scholarship"}],
                [{"LOWER": "financial"}, {"LOWER": "aid"}],
                [{"LOWER": "grant"}]
            ])
            
            self.matcher.add("PLACEMENT", [
                [{"LOWER": "placement"}],
                [{"LOWER": "career"}, {"LOWER": "services"}],
                [{"LOWER": "job"}, {"LOWER": "placement"}]
            ])
    
    def extract_patterns(self, text: str) -> Dict[str, List[str]]:
        """
        Extract common patterns from text.
        
        Args:
            text: Text to search for patterns
            
        Returns:
            Dictionary mapping pattern types to lists of matches
        """
        results = {}
        
        # Extract with common patterns
        for pattern_name, pattern in self.patterns.items():
            matches = pattern.findall(text)
            if matches:
                results[pattern_name] = matches
        
        # Extract with educational patterns
        for pattern_name, pattern in self.edu_patterns.items():
            matches = pattern.findall(text)
            if matches:
                results[pattern_name] = matches
        
        return results
    
    def extract_dates(self, text: str) -> List[Dict]:
        """
        Extract and normalize dates from text.
        
        Args:
            text: Text to extract dates from
            
        Returns:
            List of dictionaries with original text and ISO format
        """
        date_matches = self.patterns['date'].findall(text)
        normalized_dates = []
        
        for date_str in date_matches:
            try:
                # Parse the date and convert to ISO format
                parsed_date = parse_date(date_str, fuzzy=True)
                normalized_dates.append({
                    'original': date_str,
                    'iso_format': parsed_date.strftime('%Y-%m-%d'),
                    'timestamp': parsed_date.timestamp()
                })
            except ValueError:
                # Skip dates that can't be parsed
                continue
        
        return normalized_dates
    
    def extract_edu_entities(self, text: str) -> Dict[str, List[Dict]]:
        """
        Extract education-specific entities using spaCy matchers.
        
        Args:
            text: Text to extract entities from
            
        Returns:
            Dictionary mapping entity types to lists of matches
        """
        if not self.nlp:
            return {}
            
        doc = self.nlp(text)
        matches = self.matcher(doc)
        
        results = defaultdict(list)
        
        for match_id, start, end in matches:
            string_id = self.nlp.vocab.strings[match_id]
            span = doc[start:end]
            
            # Extract surrounding context (50 chars before and after)
            context_start = max(0, span.start_char - 50)
            context_end = min(len(text), span.end_char + 50)
            context = text[context_start:context_end]
            
            results[string_id].append({
                'text': span.text,
                'start': span.start_char,
                'end': span.end_char,
                'context': context
            })
        
        return dict(results)
    
    def normalize_data(self, extracted_data: Dict) -> Dict:
        """
        Normalize extracted data for consistent formatting.
        
        Args:
            extracted_data: Dictionary of extracted data
            
        Returns:
            Dictionary with normalized data
        """
        normalized = {}
        
        # Normalize dates
        if 'date' in extracted_data:
            normalized['dates'] = self.extract_dates(
                ' '.join(extracted_data['date'])
            )
        
        # Copy other data as is
        for key, value in extracted_data.items():
            if key != 'date':  # Skip dates as they're handled above
                normalized[key] = value
        
        return normalized
        
    def extract_placement_stats(self, text: str) -> Dict:
        """
        Extract placement statistics from text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Dictionary with extracted placement statistics
        """
        stats = {}
        
        # Extract placement percentages
        placement_rate_match = re.search(r'(\d+(?:\.\d+)?)%\s+(?:placement|placed)', text, re.IGNORECASE)
        if placement_rate_match:
            stats['placement_rate'] = placement_rate_match.group(1)
        
        # Extract salary packages
        salary_matches = re.findall(r'(?:Rs\.?|INR|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:lakhs?|L|Lacs?|k|K|LPA)', text, re.IGNORECASE)
        if salary_matches:
            stats['salary_packages'] = salary_matches
        
        # Extract number of companies
        company_match = re.search(r'(\d+)\s+(?:companies|recruiters|firms)', text, re.IGNORECASE)
        if company_match:
            stats['companies_count'] = company_match.group(1)
        
        # Extract number of students placed
        students_placed_match = re.search(r'(\d+)\s+students\s+(?:placed|recruited)', text, re.IGNORECASE)
        if students_placed_match:
            stats['students_placed'] = students_placed_match.group(1)
        
        return stats
    
    def extract_chart_data(self, html: str) -> List[Dict]:
        """
        Extract data from charts in HTML.
        
        Args:
            html: HTML content
            
        Returns:
            List of dictionaries containing chart data
        """
        soup = BeautifulSoup(html, 'html.parser')
        charts = []
        
        # Look for common chart containers
        chart_containers = []
        
        # Check for SVG elements (often used for charts)
        for svg in soup.find_all('svg'):
            chart_containers.append(svg.parent)
        
        # Check for chart divs
        for div in soup.find_all('div', class_=lambda c: c and any(chart_term in c.lower() for chart_term in ['chart', 'graph', 'pie', 'donut', 'statistics'])):
            chart_containers.append(div)
        
        # Process each potential chart container
        for container in chart_containers:
            # Find a heading or caption for this chart
            heading = None
            heading_elem = container.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if heading_elem:
                heading = heading_elem.get_text(strip=True)
            
            # Extract text data from the chart
            chart_text = container.get_text(strip=True)
            
            # Extract stats from text
            stats = self.extract_placement_stats(chart_text)
            
            # Get any legend items
            legend_items = []
            for span in container.find_all(['span', 'div', 'li'], class_=lambda c: c and 'legend' in c.lower()):
                legend_items.append(span.get_text(strip=True))
            
            # Create chart data structure
            chart_data = {
                'heading': heading,
                'text': chart_text,
                'stats': stats,
                'legend': legend_items,
                'type': 'chart'
            }
            
            # Try to determine chart type
            if 'pie' in container.get('class', '') or 'donut' in container.get('class', ''):
                chart_data['chart_type'] = 'pie'
            elif 'bar' in container.get('class', ''):
                chart_data['chart_type'] = 'bar'
            elif 'line' in container.get('class', ''):
                chart_data['chart_type'] = 'line'
            
            charts.append(chart_data)
        
        return charts

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


# =============================================================================
# 5. MACHINE LEARNING MODEL TRAINING
# =============================================================================

class TextClassifier:
    """Train and use ML models to classify text."""
    
    def __init__(self, config: CrawlerConfig, model_dir: str = "models"):
        self.config = config
        self.model_dir = model_dir
        self.vectorizer = None
        self.model = None
        
        # Create model directory if it doesn't exist
        os.makedirs(model_dir, exist_ok=True)
    
    def prepare_sample_data(self) -> Tuple[List[str], List[str]]:
        """
        Prepare sample data for model training.
        This would typically load from a labeled dataset.
        
        Returns:
            Tuple of (texts, labels)
        """
        # This is a placeholder - in a real system, you'd load from files
        # or a database of previously labeled data
        texts = [
            "Application deadline for fall semester is August 15, 2023. All documents must be submitted by this date.",
            "The entrance examination will be conducted on September 5, 2023 at the main campus hall.",
            "Eligible candidates must have a GPA of at least 3.0 in their undergraduate studies.",
            "The application fee is $75 for domestic students and $150 for international applicants.",
            "Scholarships are available for students with exceptional academic records.",
            "The university will be closed for winter break from December 20 to January 5.",
            "For more information about our programs, please contact admissions@example.edu.",
            "The department of computer science is hosting an open house next Friday.",
            "Campus tours are conducted every Monday and Wednesday at 10 AM.",
            "Student housing applications are processed on a first-come, first-served basis.",
            "Our placement rate this year was 95% with an average package of 6.5 lakhs.",
            "Top recruiters include Google, Microsoft, and Amazon who hired 45 students.",
            "The placement cell coordinates with over 200 companies for campus recruitment.",
            "Students from the IT department received the highest placement offers with an average of 8.2 LPA.",
            "This year's placement season saw a 15% increase in the number of companies visiting the campus."
        ]
        
        labels = [
            "deadline",
            "exam_info",
            "eligibility",
            "fee_info",
            "scholarship",
            "general_info",
            "contact_info",
            "event_info",
            "tour_info",
            "housing_info",
            "placement_stats",
            "placement_companies",
            "placement_process",
            "placement_department",
            "placement_trend"
        ]
        
        return texts, labels
    
    def load_and_preprocess_data(self, data_path: Optional[str] = None) -> Tuple[np.ndarray, np.ndarray]:
        """
        Load and preprocess text data for classification.
        
        Args:
            data_path: Path to the labeled data (optional)
            
        Returns:
            Tuple of (X, y) arrays for training
        """
        if data_path and os.path.exists(data_path):
            # Load real data if available
            try:
                df = pd.read_csv(data_path)
                texts = df['text'].tolist()
                labels = df['label'].tolist()
            except Exception as e:
                logger.error(f"Error loading data from {data_path}: {e}")
                # Fall back to sample data
                texts, labels = self.prepare_sample_data()
        else:
            # Use sample data
            texts, labels = self.prepare_sample_data()
            
        # Create or load vectorizer
        if self.vectorizer is None:
            self.vectorizer = TfidfVectorizer(
                max_features=5000,
                ngram_range=(1, 2),
                stop_words='english'
            )
            X = self.vectorizer.fit_transform(texts)
        else:
            X = self.vectorizer.transform(texts)
            
        # Convert labels to array
        encoder = {label: i for i, label in enumerate(set(labels))}
        y = np.array([encoder[label] for label in labels])
        
        return X, y
    
    def train_model(self, model_type: str = 'lr', data_path: Optional[str] = None) -> Dict:
        """
        Train a classification model on text data.
        
        Args:
            model_type: Type of model to train ('lr' for LogisticRegression, 'svm' for SVC)
            data_path: Path to the labeled data (optional)
            
        Returns:
            Dictionary with training results
        """
        # Load and preprocess data
        X, y = self.load_and_preprocess_data(data_path)
        
        # Split into train and validation sets
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.2, random_state=42
        )
        
        # Initialize model
        if model_type.lower() == 'lr':
            model = LogisticRegression(C=1.0, max_iter=1000, class_weight='balanced')
        elif model_type.lower() == 'svm':
            model = SVC(C=1.0, kernel='linear', probability=True, class_weight='balanced')
        else:
            raise ValueError(f"Unknown model type: {model_type}")
        
        # Train the model
        model.fit(X_train, y_train)
        self.model = model
        
        # Evaluate on validation set
        y_pred = model.predict(X_val)
        accuracy = accuracy_score(y_val, y_pred)
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_val, y_pred, average='weighted'
        )
        
        # Get classification report
        report = classification_report(y_val, y_pred, output_dict=True)
        
        # Save model and vectorizer
        self.save_model(model_type)
        
        return {
            'model_type': model_type,
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1': f1,
            'report': report
        }
    
    def save_model(self, model_type: str):
        """Save the trained model and vectorizer."""
        model_path = os.path.join(self.model_dir, f"{model_type}_model.joblib")
        vectorizer_path = os.path.join(self.model_dir, "vectorizer.joblib")
        
        joblib.dump(self.model, model_path)
        joblib.dump(self.vectorizer, vectorizer_path)
        
        logger.info(f"Saved model to {model_path} and vectorizer to {vectorizer_path}")
    
    def load_model(self, model_type: str) -> bool:
        """
        Load a trained model and vectorizer.
        
        Args:
            model_type: Type of model to load
            
        Returns:
            True if successful, False otherwise
        """
        model_path = os.path.join(self.model_dir, f"{model_type}_model.joblib")
        vectorizer_path = os.path.join(self.model_dir, "vectorizer.joblib")
        
        try:
            if os.path.exists(model_path) and os.path.exists(vectorizer_path):
                self.model = joblib.load(model_path)
                self.vectorizer = joblib.load(vectorizer_path)
                logger.info(f"Loaded model from {model_path} and vectorizer from {vectorizer_path}")
                return True
            else:
                logger.warning(f"Model or vectorizer file not found")
                return False
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False
    
    def classify_text(self, text: str) -> Tuple[str, float]:
        """
        Classify a text using the trained model.
        
        Args:
            text: Text to classify
            
        Returns:
            Tuple of (predicted_class, confidence)
        """
        if self.model is None or self.vectorizer is None:
            if not self.load_model('lr'):  # Try to load a logistic regression model by default
                logger.error("No model available for classification")
                return ("unknown", 0.0)
        
        # Transform the text
        X = self.vectorizer.transform([text])
        
        # Get prediction and probability
        predicted_class_idx = self.model.predict(X)[0]
        probabilities = self.model.predict_proba(X)[0]
        confidence = probabilities[predicted_class_idx]
        
        # Map index back to class name
        class_names = self.model.classes_
        predicted_class = class_names[predicted_class_idx]
        
        return (str(predicted_class), float(confidence))


# =============================================================================
# 6. POST-PROCESSING & VALIDATION
# =============================================================================

class DataValidator:
    """Validate and clean extracted data."""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.confidence_threshold = config.confidence_threshold
    
    def validate_extracted_data(self, data: Dict) -> Dict:
        """
        Validate extracted data and filter out low-confidence items.
        
        Args:
            data: Dictionary of extracted data
            
        Returns:
            Dictionary with validated data
        """
        validated = {}
        
        # Validate classification results
        if 'classification' in data:
            class_name, confidence = data['classification']
            if confidence >= self.confidence_threshold:
                validated['classification'] = (class_name, confidence)
            else:
                logger.debug(f"Filtered out low-confidence classification: {class_name} ({confidence:.2f})")
        
        # Copy other data
        for key, value in data.items():
            if key != 'classification':
                validated[key] = value
        
        return validated


class DataMerger:
    """Merge and deduplicate data from multiple sources."""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
    
    def merge_data(self, data_list: List[Dict]) -> Dict:
        """
        Merge data from multiple sources, keeping the most reliable.
        
        Args:
            data_list: List of data dictionaries to merge
            
        Returns:
            Merged dictionary
        """
        if not data_list:
            return {}
            
        # Start with the first dictionary
        merged = data_list[0].copy()
        
        # Merge the rest
        for data in data_list[1:]:
            for key, value in data.items():
                if key not in merged:
                    # Add if not present
                    merged[key] = value
                elif isinstance(value, list) and isinstance(merged[key], list):
                    # For lists, combine and deduplicate
                    merged[key] = list(set(merged[key] + value))
                elif isinstance(value, tuple) and isinstance(merged[key], tuple):
                    # For classifications, keep the one with higher confidence
                    _, merged_conf = merged[key]
                    _, new_conf = value
                    if new_conf > merged_conf:
                        merged[key] = value
        
        return merged


class HumanVerificationQueue:
    """Queue for data that needs human verification."""
    
    def __init__(self, output_dir: str = "human_verification"):
        self.output_dir = output_dir
        self.queue = []
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
    
    def add_to_queue(self, data: Dict, reason: str):
        """
        Add data to the verification queue.
        
        Args:
            data: Data to verify
            reason: Reason for verification
        """
        item = {
            'data': data,
            'reason': reason,
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'pending'
        }
        self.queue.append(item)
        
        # Save to file
        filename = f"verify_{len(self.queue)}_{int(time.time())}.json"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(item, f, indent=4)
        
        logger.info(f"Added item to human verification queue: {filepath}")
    
    def get_pending_items(self) -> List[Dict]:
        """Get items pending verification."""
        return [item for item in self.queue if item['status'] == 'pending']
    
    def mark_verified(self, item_index: int, is_valid: bool, corrected_data: Optional[Dict] = None):
        """
        Mark an item as verified.
        
        Args:
            item_index: Index of the item in the queue
            is_valid: Whether the data is valid
            corrected_data: Corrected data if applicable
        """
        if 0 <= item_index < len(self.queue):
            self.queue[item_index]['status'] = 'verified'
            self.queue[item_index]['is_valid'] = is_valid
            if corrected_data:
                self.queue[item_index]['corrected_data'] = corrected_data
            
            # Update the file
            # Find the file by pattern matching
            pattern = f"verify_{item_index + 1}_*.json"
            for file in os.listdir(self.output_dir):
                if fnmatch.fnmatch(file, pattern):
                    filepath = os.path.join(self.output_dir, file)
                    with open(filepath, 'w') as f:
                        json.dump(self.queue[item_index], f, indent=4)
                    break
        else:
            logger.error(f"Invalid item index: {item_index}")


# =============================================================================
# 7. SCHEDULING & INFRASTRUCTURE
# =============================================================================

class CrawlerScheduler:
    """Schedule and run crawler jobs."""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.running = False
        self.crawl_job = None
    
    def crawl_task(self):
        """The actual crawling task to run on schedule."""
        logger.info("Starting scheduled crawl job")
        
        try:
            # Create a crawler instance
            crawler = SmartWebCrawler(self.config)
            
            # Run the crawler
            results = crawler.crawl()
            
            # Log results
            logger.info(f"Scheduled crawl completed: {len(results)} pages processed")
            
            # Save results
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            result_file = f"crawl_results_{timestamp}.json"
            result_path = os.path.join(self.config.output_directory, result_file)
            
            with open(result_path, 'w') as f:
                json.dump(results, f, indent=4)
                
            logger.info(f"Saved results to {result_path}")
            
        except Exception as e:
            logger.error(f"Error in scheduled crawl: {str(e)}")
    
    def start_scheduler(self):
        """Start the scheduler."""
        if self.running:
            logger.warning("Scheduler is already running")
            return
            
        # Get interval in minutes
        interval = self.config.get_crawl_interval_minutes()
        
        # Schedule the job
        schedule.every(interval).minutes.do(self.crawl_task)
        self.running = True
        
        logger.info(f"Scheduler started, will run every {interval} minutes")
        
        # Run the job immediately
        self.crawl_task()
    
    def run_continuously(self):
        """Run the scheduler in a background thread."""
        cease_continuous_run = threading.Event()
        
        class ScheduleThread(threading.Thread):
            @classmethod
            def run(cls):
                while not cease_continuous_run.is_set():
                    schedule.run_pending()
                    time.sleep(1)
        
        continuous_thread = ScheduleThread()
        continuous_thread.start()
        return cease_continuous_run
    
    def stop_scheduler(self):
        """Stop the scheduler."""
        schedule.clear()
        self.running = False
        logger.info("Scheduler stopped")


class ParallelCrawler:
    """Run multiple crawler instances in parallel."""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.num_crawlers = config.parallel_crawlers
        self.results = []
    
    def run_parallel(self) -> List[Dict]:
        """
        Run multiple crawler instances in parallel.
        
        Returns:
            Combined results from all crawlers
        """
        if self.num_crawlers <= 1:
            # Just run a single crawler
            crawler = SmartWebCrawler(self.config)
            return crawler.crawl()
        
        # Split the seed URLs among crawlers
        seed_urls = self.config.seed_urls
        urls_per_crawler = max(1, len(seed_urls) // self.num_crawlers)
        
        # Create a config for each crawler
        crawler_configs = []
        for i in range(self.num_crawlers):
            # Clone the config
            crawler_config = CrawlerConfig(
                project_name=f"{self.config.project_name}_part{i}",
                goal=self.config.goal,
                seed_urls=seed_urls[i*urls_per_crawler:(i+1)*urls_per_crawler] if i < self.num_crawlers - 1 else seed_urls[i*urls_per_crawler:],
                keywords=self.config.keywords,
                allowed_domains=self.config.allowed_domains,
                max_depth=self.config.max_depth,
                output_directory=os.path.join(self.config.output_directory, f"part{i}")
            )
            crawler_configs.append(crawler_config)
        
        # Create and start threads
        threads = []
        for config in crawler_configs:
            thread = threading.Thread(target=self._run_crawler, args=(config,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Combine results
        all_results = []
        for result_list in self.results:
            all_results.extend(result_list)
        
        return all_results
    
    def _run_crawler(self, config: CrawlerConfig):
        """Run a single crawler instance and store results."""
        crawler = SmartWebCrawler(config)
        results = crawler.crawl()
        self.results.append(results)


# =============================================================================
# 8. MONITORING & MAINTENANCE
# =============================================================================

class CrawlerMonitor:
    """Monitor crawler performance and detect issues."""
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.metrics = {
            'pages_crawled': 0,
            'extraction_success_rate': 1.0,
            'average_processing_time': 0.0,
            'errors': [],
            'last_crawl_time': None,
            'extraction_counts': defaultdict(int)
        }
        
        # Performance history
        self.history = {
            'pages_crawled': [],
            'extraction_success_rate': [],
            'average_processing_time': []
        }
        
        # Monitoring directory
        self.monitor_dir = os.path.join(config.output_directory, "monitoring")
        os.makedirs(self.monitor_dir, exist_ok=True)
    
    def update_metrics(self, metrics_update: Dict):
        """
        Update monitoring metrics.
        
        Args:
            metrics_update: Dictionary with updated metrics
        """
        # Update current metrics
        for key, value in metrics_update.items():
            if key in self.metrics:
                if key == 'errors':
                    self.metrics[key].extend(value)
                else:
                    self.metrics[key] = value
        
        # Update history
        for key in ['pages_crawled', 'extraction_success_rate', 'average_processing_time']:
            if key in metrics_update:
                self.history[key].append({
                    'timestamp': datetime.datetime.now().isoformat(),
                    'value': metrics_update[key]
                })
        
        # Save metrics
        self.save_metrics()
    
    def save_metrics(self):
        """Save metrics to file."""
        metrics_file = os.path.join(self.monitor_dir, "metrics.json")
        
        with open(metrics_file, 'w') as f:
            json.dump({
                'current': self.metrics,
                'history': self.history
            }, f, indent=4)
    
    def log_error(self, error_message: str, error_type: str, url: Optional[str] = None):
        """
        Log an error.
        
        Args:
            error_message: Error message
            error_type: Type of error
            url: URL where the error occurred (optional)
        """
        error = {
            'message': error_message,
            'type': error_type,
            'url': url,
            'timestamp': datetime.datetime.now().isoformat()
        }
        
        self.metrics['errors'].append(error)
        
        # Save to error log
        error_log = os.path.join(self.monitor_dir, "errors.log")
        with open(error_log, 'a') as f:
            f.write(f"{error['timestamp']} - {error['type']} - {error['url'] or 'N/A'} - {error['message']}\n")
        
        # Update metrics
        self.save_metrics()
    
    def check_for_issues(self) -> List[Dict]:
        """
        Check for issues in the crawler performance.
        
        Returns:
            List of detected issues
        """
        issues = []
        
        # Check extraction success rate
        if self.metrics['extraction_success_rate'] < 0.8:
            issues.append({
                'type': 'low_extraction_rate',
                'message': f"Low extraction success rate: {self.metrics['extraction_success_rate']:.2f}",
                'severity': 'warning'
            })
        
        # Check for recent errors
        recent_errors = [
            e for e in self.metrics['errors']
            if datetime.datetime.fromisoformat(e['timestamp']) > 
               datetime.datetime.now() - datetime.timedelta(hours=24)
        ]
        if len(recent_errors) > 5:
            issues.append({
                'type': 'high_error_rate',
                'message': f"High error rate: {len(recent_errors)} errors in the last 24 hours",
                'severity': 'error'
            })
        
        # Check processing time
        if self.metrics['average_processing_time'] > 10.0:
            issues.append({
                'type': 'slow_processing',
                'message': f"Slow processing time: {self.metrics['average_processing_time']:.2f} seconds per page",
                'severity': 'warning'
            })
        
        # Log issues
        if issues:
            issue_log = os.path.join(self.monitor_dir, "issues.log")
            with open(issue_log, 'a') as f:
                for issue in issues:
                    f.write(f"{datetime.datetime.now().isoformat()} - {issue['severity']} - {issue['type']} - {issue['message']}\n")
        
        return issues
    
    def detect_layout_changes(self, url: str, html_content: str) -> bool:
        """
        Detect changes in website layout by comparing with previous crawls.
        
        Args:
            url: The URL
            html_content: Current HTML content
            
        Returns:
            True if layout changed, False otherwise
        """
        # Create a hash of the domain
        domain = urlparse(url).netloc
        domain_hash = hashlib.md5(domain.encode()).hexdigest()
        
        # Path for layout fingerprint
        fingerprint_path = os.path.join(self.monitor_dir, f"layout_{domain_hash}.json")
        
        # Generate a simple fingerprint of the layout
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Count tags and classes as a simple fingerprint
        tag_counts = {}
        for tag in soup.find_all():
            tag_name = tag.name
            tag_counts[tag_name] = tag_counts.get(tag_name, 0) + 1
            
        classes = []
        for tag in soup.find_all(attrs={"class": True}):
            classes.extend(tag.get("class"))
        class_counts = {cls: classes.count(cls) for cls in set(classes)}
        
        # Create fingerprint
        fingerprint = {
            'url': url,
            'tag_counts': tag_counts,
            'class_counts': class_counts,
            'timestamp': datetime.datetime.now().isoformat()
        }
        
        # Check for previous fingerprint
        if os.path.exists(fingerprint_path):
            with open(fingerprint_path, 'r') as f:
                previous_fingerprint = json.load(f)
                
            # Compare fingerprints
            # Simple comparison: check if the number of common tags changed by more than 20%
            prev_tags = set(previous_fingerprint['tag_counts'].keys())
            curr_tags = set(tag_counts.keys())
            
            common_tags = prev_tags.intersection(curr_tags)
            all_tags = prev_tags.union(curr_tags)
            
            similarity = len(common_tags) / len(all_tags) if all_tags else 1.0
            
            # Save new fingerprint
            with open(fingerprint_path, 'w') as f:
                json.dump(fingerprint, f, indent=4)
                
            # Return True if similarity is less than 80%
            return similarity < 0.8
        else:
            # Save first fingerprint
            with open(fingerprint_path, 'w') as f:
                json.dump(fingerprint, f, indent=4)
            return False


# =============================================================================
# MAIN CRAWLER CLASS
# =============================================================================

class SmartWebCrawler:
    """
    Main crawler class that brings together all components.
    """
    
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.basic_crawler = BasicCrawler(config)
        self.content_extractor = ContentExtractor(config)
        self.data_extractor = DataExtractor(config)
        self.validator = DataValidator(config)
        self.merger = DataMerger(config)
        self.monitor = CrawlerMonitor(config)
        
        # Initialize ML components if enabled
        self.classifier = None
        if config.use_ml_classification:
            self.classifier = TextClassifier(config)
            
            # Try to load existing model, train if not available
            if not self.classifier.load_model('lr'):
                logger.info("No trained model found, training a new one")
                self.classifier.train_model()
        
        # Human verification queue
        self.verification_queue = HumanVerificationQueue(
            os.path.join(config.output_directory, "verification")
        )
    
    def crawl(self) -> List[Dict]:
        """
        Run the crawler.
        
        Args:
            max_pages: Maximum number of pages to process (None for unlimited)
            
        Returns:
            List of results
        """
        start_time = time.time()
        results = []
        
        # Process URLs
        raw_results = self.basic_crawler.run(max_pages=30)  # Limit to 30 pages for speed
        
        # Track processing stats
        successful_extractions = 0
        processing_times = []
        
        # Keywords to look for in each category
        admission_keywords = [
            "admission", "eligibility", "criteria", "fee", "application", 
            "entrance", "form", "cutoff", "document", "deadline"
        ]
        
        placement_keywords = [
            "placement", "career", "recruiter", "company", "package", 
            "salary", "offer", "job", "opportunity", "lpa", "ctc"
        ]
        
        # Process each result
        for raw_result in raw_results:
            if not raw_result.get('success', False):
                continue
                
            page_start_time = time.time()
            
            try:
                # Extract main content
                url = raw_result['url']
                html_content = raw_result['html_content']
                
                # Check for layout changes
                if self.monitor.detect_layout_changes(url, html_content):
                    logger.warning(f"Detected layout change on {url}")
                    self.monitor.log_error(
                        "Website layout changed significantly", 
                        "layout_change", 
                        url
                    )
                
                # Extract content
                main_content = self.content_extractor.extract_main_content(html_content)
                lower_content = main_content.lower()
                
                # ENHANCED APPROACH: Use more sophisticated content detection
                # Look for specific admission patterns in the URL first
                if any(term in url.lower() for term in ["admission", "apply", "enroll", "entrance"]):
                    # Highly likely an admission page, extract all tables
                    admission_tables = self.data_extractor.extract_tables_from_page(html_content, admission_keywords)
                    
                    for idx, table_data in enumerate(admission_tables):
                        results.append({
                            'url': url,
                            'type': 'admission_table',
                            'data': table_data,
                            'crawl_time': datetime.datetime.now().isoformat()
                        })
                # Otherwise check content
                elif any(keyword in lower_content for keyword in admission_keywords):
                    # Extract admission data
                    admission_data = self.extract_structured_data(html_content, main_content, 'admission')
                    if admission_data:
                        results.append({
                            'url': url,
                            'type': 'admission_data',
                            'data': admission_data,
                            'crawl_time': datetime.datetime.now().isoformat()
                        })
                
                # Similarly for placement
                if any(term in url.lower() for term in ["placement", "career", "recruit"]):
                    # Highly likely a placement page, extract all tables
                    placement_tables = self.data_extractor.extract_tables_from_page(html_content, placement_keywords)
                    
                    for idx, table_data in enumerate(placement_tables):
                        results.append({
                            'url': url,
                            'type': 'placement_table',
                            'data': table_data,
                            'crawl_time': datetime.datetime.now().isoformat()
                        })
                    
                    # Also look for placement charts and non-tabular data
                    charts = self.data_extractor.extract_chart_data(html_content)
                    if charts:
                        for idx, chart_data in enumerate(charts):
                            results.append({
                                'url': url,
                                'type': 'placement_chart',
                                'data': chart_data,
                                'crawl_time': datetime.datetime.now().isoformat()
                            })
                # Otherwise check content
                elif any(keyword in lower_content for keyword in placement_keywords):
                    # Extract placement data
                    placement_data = self.extract_structured_data(html_content, main_content, 'placement')
                    if placement_data:
                        results.append({
                            'url': url,
                            'type': 'placement_data',
                            'data': placement_data,
                            'crawl_time': datetime.datetime.now().isoformat()
                        })
                
                # Track successful extraction
                successful_extractions += 1
                
                # Track processing time
                page_processing_time = time.time() - page_start_time
                processing_times.append(page_processing_time)
                
            except Exception as e:
                logger.error(f"Error processing {raw_result.get('url')}: {str(e)}")
                self.monitor.log_error(
                    str(e),
                    "processing_error",
                    raw_result.get('url')
                )
        
        # Calculate metrics
        total_time = time.time() - start_time
        pages_crawled = len(raw_results)
        extraction_success_rate = successful_extractions / pages_crawled if pages_crawled > 0 else 0
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
        
        # Update monitor
        self.monitor.update_metrics({
            'pages_crawled': pages_crawled,
            'extraction_success_rate': extraction_success_rate,
            'average_processing_time': avg_processing_time,
            'last_crawl_time': datetime.datetime.now().isoformat()
        })
        
        # Check for issues
        issues = self.monitor.check_for_issues()
        if issues:
            for issue in issues:
                logger.warning(f"Detected issue: {issue['message']}")
        
        logger.info(f"Crawl completed: {pages_crawled} pages crawled, {successful_extractions} successful extractions")
        
        return results
    
    def extract_structured_data(self, html_content: str, main_content: str, data_type: str) -> Dict:
        """
        Extract structured data of a specific type.
        
        Args:
            html_content: Raw HTML content
            main_content: Extracted main content
            data_type: Type of data to extract ('admission' or 'placement')
            
        Returns:
            Dictionary with extracted structured data
        """
        result = {}
        
        # Extract patterns from text
        patterns = self.data_extractor.extract_patterns(main_content)
        result['patterns'] = patterns
        
        # Extract tables
        tables = self.content_extractor.extract_tables(html_content)
        result['tables'] = tables
        
        # Extract specific data based on type
        if data_type == 'admission':
            # Extract admission-specific data
            deadlines = patterns.get('deadline', [])
            if deadlines:
                result['deadlines'] = deadlines
                
            fees = patterns.get('application_fee', [])
            if fees:
                result['fees'] = fees
                
            # Extract eligibility criteria from text
            eligibility_section = self._extract_section_by_keyword(html_content, ['eligibility', 'criteria', 'requirements'])
            if eligibility_section:
                result['eligibility'] = eligibility_section
                
        elif data_type == 'placement':
            # Extract placement-specific data
            charts = self.data_extractor.extract_chart_data(html_content)
            if charts:
                result['charts'] = charts
                
            # Extract placement statistics
            placement_stats = self.data_extractor.extract_placement_stats(main_content)
            if placement_stats:
                result['statistics'] = placement_stats
        
        return result
    
    def _extract_section_by_keyword(self, html_content: str, keywords: List[str]) -> Optional[str]:
        """
        Extract a section of text that contains specific keywords.
        
        Args:
            html_content: HTML content
            keywords: List of keywords to look for
            
        Returns:
            Extracted section or None if not found
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # First try to find headings with these keywords
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5']):
            heading_text = heading.get_text(strip=True).lower()
            if any(keyword in heading_text for keyword in keywords):
                # Extract the next few elements
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
                for _ in range(15):  # Look at the next 15 elements
                    if current is None:
                        break
                    
                    if hasattr(current, 'name') and current.name in ['h1', 'h2', 'h3', 'h4']:
                        break
                        
                    if hasattr(current, 'get_text'):
                        text = current.get_text(strip=True)
                        if text:
                            content.append(text)
                            
                    current = current.next_sibling
                    
                if content:
                    return ' '.join(content)
        
        # If no section found by heading, look for paragraphs with these keywords
        for p in soup.find_all('p'):
            p_text = p.get_text(strip=True).lower()
            if any(keyword in p_text for keyword in keywords):
                # Get the paragraph and its next few siblings
                content = [p.get_text(strip=True)]
                current = p.next_sibling
                
                for _ in range(5):  # Look at the next 5 elements
                    if current is None:
                        break
                    
                    if hasattr(current, 'get_text'):
                        text = current.get_text(strip=True)
                        if text:
                            content.append(text)
                            
                    current = current.next_sibling
                    
                return ' '.join(content)
        
        return None
    
    def _save_results(self, results: List[Dict]):
        """Save results to a file."""
        if not results:
            return
            
        # Create output filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"crawl_results_{timestamp}"
        
        if self.config.output_format.lower() == 'json':
            filepath = os.path.join(self.config.output_directory, f"{filename}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=4)
        elif self.config.output_format.lower() == 'csv':
            filepath = os.path.join(self.config.output_directory, f"{filename}.csv")
            
            # Extract fields from the first result
            if results:
                # Flatten the structure for CSV
                flattened = []
                for result in results:
                    flat_item = {
                        'url': result.get('url', ''),
                        'crawl_time': result.get('crawl_time', ''),
                        'type': result.get('type', '')
                    }
                    
                    # Add data fields
                    data = result.get('data', {})
                    for key, value in data.items():
                        if isinstance(value, dict):
                            for sub_key, sub_value in value.items():
                                flat_item[f"{key}_{sub_key}"] = str(sub_value)
                        elif isinstance(value, list):
                            flat_item[key] = ', '.join(str(v) for v in value)
                        else:
                            flat_item[key] = str(value)
                    
                    flattened.append(flat_item)
                
                # Write to CSV
                if flattened:
                    fieldnames = flattened[0].keys()
                    with open(filepath, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(flattened)
        else:
            logger.warning(f"Unsupported output format: {self.config.output_format}")
        
        logger.info(f"Saved {len(results)} results to {filepath}")


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def parse_args():
    """Parse command line arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Smart Web Crawler")
    
    parser.add_argument('--config', type=str, help='Path to configuration file')
    parser.add_argument('--output', type=str, help='Output directory')
    parser.add_argument('--max-pages', type=int, help='Maximum pages to crawl')
    parser.add_argument('--parallel', type=int, help='Number of parallel crawlers')
    parser.add_argument('--schedule', action='store_true', help='Run as a scheduled job')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    # Load or create configuration
    if args.config and os.path.exists(args.config):
        config = CrawlerConfig.load_config(args.config)
    else:
        config = get_sample_config()
    
    # Override config with command line args
    if args.output:
        config.output_directory = args.output
    
    if args.parallel:
        config.parallel_crawlers = args.parallel
    
    # Create crawler
    if config.parallel_crawlers > 1:
        crawler = ParallelCrawler(config)
        results = crawler.run_parallel()
    else:
        crawler = SmartWebCrawler(config)
        
        if args.schedule:
            # Run as a scheduled job
            scheduler = CrawlerScheduler(config)
            stop_event = scheduler.run_continuously()
            
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                stop_event.set()
                logger.info("Scheduler stopped")
        else:
            # Run a single crawl
            results = crawler.crawl()
    
    logger.info(f"Crawling complete, processed {len(results)} pages")


if __name__ == "__main__":
    main()