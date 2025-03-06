"""
Enhanced College Data Crawler - Flask Web Application

This Flask application crawls college websites to extract structured data about
admission, placement, and internship information with improved progress tracking
and display capabilities.
"""

import os
import json
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for
from datetime import datetime
from urllib.parse import urlparse
import threading
import queue
import time
import requests
from typing import List, Dict, Tuple, Optional, Any

# Import the original crawler components
from crawler.smart_crawler import CrawlerConfig

# Import the enhanced crawler
from crawler.smart_crawler2 import EnhancedCollegeCrawler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("enhanced_college_crawler.log"),
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
active_crawlers = {}  # Store active crawler instances for progress tracking
crawl_results = {}
crawl_status = {}

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

def enhanced_crawl_worker():
    """Background worker to process the crawl queue using the enhanced crawler."""
    while True:
        try:
            college = crawl_queue.get()
            if college is None:  # Sentinel value to stop the thread
                break
                
            college_id = int(college['id'])  
            crawl_status[college_id] = 'running'
            
            # Create crawler configuration
            website_url = college['website']
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
                
            domain = urlparse(website_url).netloc
            
            config = CrawlerConfig(
                project_name=f"college_crawler_{domain}",
                goal="Extract admission, placement, and internship information",
                seed_urls=[website_url],
                keywords=[
                    "admission", "placement", "internship", "eligibility", "fee", "cutoff", 
                    "entrance exam", "scholarship", "placed", "packages", "recruiter"
                ],
                allowed_domains=[domain],
                max_depth=3,
                max_pages_per_domain=50,
                request_delay=1.0,
                respect_robots_txt=False,
                use_nlp=True,
                use_ml_classification=False,
                output_directory=os.path.join(RESULTS_DIR, domain.replace('.', '_'))
            )
            
            # Use the enhanced crawler
            crawler = EnhancedCollegeCrawler(college['name'], college['website'], config, RESULTS_DIR)
            active_crawlers[college_id] = crawler  # Store for progress tracking
            
            results = crawler.crawl(max_pages=30, max_depth=3)
            
            # Store results
            crawl_results[college_id] = results
            crawl_status[college_id] = 'completed'
            
            # Remove from active crawlers
            active_crawlers.pop(college_id, None)
            
        except Exception as e:
            if 'college_id' in locals():
                crawl_status[college_id] = 'error'
                crawl_results[college_id] = {
                    'status': 'error',
                    'message': f"Error: {str(e)}"
                }
                active_crawlers.pop(college_id, None)
            logger.error(f"Error in enhanced crawl worker: {str(e)}", exc_info=True)
        finally:
            if 'college_id' in locals():
                crawl_queue.task_done()

# Start worker thread
enhanced_worker_thread = threading.Thread(target=enhanced_crawl_worker, daemon=True)
enhanced_worker_thread.start()

@app.route('/')
def index():
    """Render the main page with college list."""
    colleges = load_colleges()
    return render_template('index.html', colleges=colleges, count=len(colleges))

@app.route('/start_crawl', methods=['POST'])
def start_crawl():
    """Start crawling for a specific college using the enhanced crawler."""
    try:
        data = request.get_json()
        college_id = int(data.get('college_id', 0))
        colleges = load_colleges()
        
        if not colleges or college_id >= len(colleges):
            return jsonify({'status': 'error', 'message': 'Invalid college ID'})
            
        college = colleges[college_id]
        college['id'] = college_id
        
        # Check if already in queue or completed
        if college_id in crawl_status and crawl_status[college_id] == 'running':
            return jsonify({'status': 'info', 'message': f'Crawl already in progress'})
            
        # If there's a completed crawler, we're recrawling
        if college_id in crawl_status and crawl_status[college_id] == 'completed':
            crawl_status[college_id] = 'queued'  # Set to queued to indicate we're starting over
        else:
            crawl_status[college_id] = 'queued'
            
        # Queue the job
        crawl_queue.put(college)
        
        return jsonify({'status': 'success', 'message': 'Enhanced crawl job started'})
        
    except Exception as e:
        logger.error(f"Error starting crawl: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Error: {str(e)}'})

@app.route('/crawl_status/<int:college_id>')
def get_crawl_status(college_id):
    """Get the status of a crawl job with detailed progress information."""
    if college_id not in crawl_status:
        return jsonify({'status': 'not_started'})
    
    status = crawl_status[college_id]
    response = {'status': status}
    
    # If running, add progress information
    if status == 'running' and college_id in active_crawlers:
        progress = active_crawlers[college_id].get_progress()
        response['progress'] = progress
    
    # If completed, add summary
    if status == 'completed' and college_id in crawl_results:
        response['result_summary'] = {
            'admission_count': len(crawl_results[college_id].get('admission_data', {})),
            'placement_count': len(crawl_results[college_id].get('placement_data', {})),
            'internship_count': len(crawl_results[college_id].get('internship_data', {}))
        }
        
    return jsonify(response)

@app.route('/stop_crawl/<int:college_id>', methods=['POST'])
def stop_crawl(college_id):
    """Stop a running crawl job."""
    if college_id in active_crawlers:
        # Note: We can't actually stop the crawler once it's running
        # but we can mark it as stopped in the UI
        crawl_status[college_id] = 'stopped'
        return jsonify({'status': 'success', 'message': 'Crawler will stop after current page'})
    
    return jsonify({'status': 'error', 'message': 'No active crawler to stop'})

@app.route('/college_data/<int:college_id>')
def college_data(college_id):
    """Display the extracted data for a college with improved structure."""
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
            return render_template('enhanced_college_data.html', college=college, results=None, 
                                  status=crawl_status.get(college_id, 'not_started'), college_id=college_id)
    
    # Process and organize the data for display
    processed_results = process_results_for_display(results)
    
    return render_template('enhanced_college_data.html', college=college, results=processed_results,
                          status=crawl_status.get(college_id, 'completed'), college_id=college_id)

def process_results_for_display(results):
    """Process and organize the raw results for display in the template."""
    processed = {
        'college_name': results.get('college_name', ''),
        'website': results.get('website', ''),
        'crawl_time': results.get('crawl_time', ''),
        'status': results.get('status', ''),
        'message': results.get('message', ''),
        'pages_processed': results.get('pages_processed', 0),
        'admission_data': [],
        'placement_data': [],
        'internship_data': [],
        'parsed_data': results.get('parsed_data', {})
    }
    
    # Process admission data
    for key, item in results.get('admission_data', {}).items():
        url = item.get('url', '')
        data = item.get('data', {})
        
        processed_item = {
            'url': url,
            'title': get_title_from_url(url),
            'fee_structure': data.get('fee_structure', {}),
            'courses': data.get('courses', {}),
            'eligibility': data.get('eligibility', []),
            'tables': data.get('tables', []),
            'procedure': data.get('procedure', {}),
            'deadlines': data.get('deadlines', []),
            'scholarships': data.get('scholarships', {}),
            'hostel': data.get('hostel', {})
        }
        
        processed['admission_data'].append(processed_item)
    
    # Process placement data
    for key, item in results.get('placement_data', {}).items():
        url = item.get('url', '')
        data = item.get('data', {})
        
        processed_item = {
            'url': url,
            'title': get_title_from_url(url),
            'tables': data.get('tables', []),
            'placement_percentages': data.get('placement_percentages', []),
            'salary_packages': data.get('salary_packages', []),
            'company_counts': data.get('company_counts', []),
            'companies': data.get('companies', []),
            'company_logos': data.get('company_logos', []),
            'charts': data.get('charts', [])
        }
        
        processed['placement_data'].append(processed_item)
    
    # Process internship data
    for key, item in results.get('internship_data', {}).items():
        url = item.get('url', '')
        data = item.get('data', {})
        
        processed_item = {
            'url': url,
            'title': get_title_from_url(url),
            'tables': data.get('tables', []),
            'internship_counts': data.get('internship_counts', []),
            'mentioned_companies': data.get('mentioned_companies', []),
            'company_logos': data.get('company_logos', []),
            'programs': data.get('programs', []),
            'yearly_counts': data.get('yearly_counts', {})
        }
        
        processed['internship_data'].append(processed_item)
    
    return processed

def get_title_from_url(url):
    """Extract a meaningful title from the URL."""
    parts = urlparse(url)
    path = parts.path
    
    # Extract the last meaningful part of the URL
    if path.endswith('/'):
        path = path[:-1]
    
    if '=' in path:
        # If there's a parameter in the path, use it
        title = path.split('=')[-1]
    else:
        # Otherwise use the last part of the path
        title = path.split('/')[-1]
    
    # Clean up the title
    title = title.replace('-', ' ').replace('_', ' ').replace('.html', '')
    
    # If title is empty, use a generic title
    if not title:
        title = "Home Page"
    
    return title.title()

# Error page route
@app.route('/error')
def error():
    """Display error page."""
    message = request.args.get('message', 'An unknown error occurred')
    return render_template('error.html', message=message)

if __name__ == '__main__':
    app.run(debug=True, port=5000)