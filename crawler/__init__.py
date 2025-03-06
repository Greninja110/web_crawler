"""
Crawler package for the College Data Crawler application.
"""

from .smart_crawler import (
    CrawlerConfig, SmartWebCrawler, ContentExtractor, 
    DataExtractor, URLQueue, BasicCrawler
)

__all__ = [
    'CrawlerConfig', 
    'SmartWebCrawler', 
    'ContentExtractor', 
    'DataExtractor', 
    'URLQueue', 
    'BasicCrawler'
]