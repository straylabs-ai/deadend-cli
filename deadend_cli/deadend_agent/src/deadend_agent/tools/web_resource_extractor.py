
# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Web resource extraction and analysis tool for security research.

This module provides functionality to extract, analyze, and process web
resources including HTML content, JavaScript files, CSS stylesheets, and
other web assets for security analysis and vulnerability research.
"""

import asyncio
import json
import os
import pathlib
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import List, Dict

import aiofiles
import aiohttp
from playwright.async_api import async_playwright

@dataclass
class Resource:
    """Represents a web resource with its metadata and properties.
    
    Attributes:
        url: The URL of the resource
        resource_type: Type of resource (document, script, stylesheet, etc.)
        method: HTTP method used to request the resource
        file_hash: Optional hash of the file content
        status_code: HTTP status code of the response
        size: Size of the resource in bytes
        mime_type: MIME type of the resource
        from_cache: Whether the resource was served from cache
        failed: Whether the request failed
        timing: Performance timing information
    """
    url: str
    resource_type: str
    method: str
    file_hash: str | None = None
    status_code: int | None = None
    size: int | None = None
    mime_type: str | None = None
    from_cache: bool = False
    failed: bool = False
    timing: Dict | None = None

class WebResourceExtractor:
    """Extracts and analyzes web resources from a webpage using Playwright.
    
    This class captures all network requests, responses, and performance metrics
    from a webpage, including dynamically loaded content and resources.
    
    Attributes:
        resources: List of successfully captured resources
        failed_resources: List of resources that failed to load
    """

    def __init__(self) -> None:
        """Initialize the WebResourceExtractor."""
        self.resources: List[Resource] = []
        self.failed_resources: List[Resource] = []

    async def extract_all_resources(
            self,
            url: str,
            wait_time: int = 10,
            screenshot: bool = False,
            download_resources: bool = False,
            download_path: str = "./"
    ) -> List[Resource]:
        """Extract all resources from a webpage.
        
        Args:
            url: The URL of the webpage to analyze
            wait_time: Time to wait for dynamic content to load (seconds)
            screenshot: Whether to take a screenshot of the page
            download_resources: Whether to download all resources locally
            download_path: Path where to download resources
            
        Returns:
            List of Resource objects containing all captured resources
            
        Raises:
            Exception: If page loading fails or browser errors occur
        """
        async with async_playwright() as play:
            # Using chromium
            browser = await play.chromium.launch(
                headless=True,
                # args=[
                #     '--disable-web-security',
                #     '--disable-features=TranslateUI',
                #     '--no-sandbox',
                #     'disable-setuid-sandbox',
                # ]
            )

            ctx = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            page = await ctx.new_page()
            # Capturing all requests
            await page.route('**/*', self._handle_route)

            page.on('request', self._on_request)
            page.on('response', self._on_response)
            page.on('requestfailed', self._on_request_failed)

            try:
                start_time = time.time()

                # Ensure URL has protocol
                if not url.startswith(('http://', 'https://')):
                    url = 'http://' + url

                await page.goto(url, wait_until='networkidle', timeout=30000)
                print(f"Waiting {wait_time}s for dynamic content...")
                await asyncio.sleep(wait_time)

                await page.evaluate("""
                    // Scroll to bottom to trigger lazy loading
                    window.scrollTo(0, document.body.scrollHeight);
                    
                    // Trigger mouse events that might load resources
                    document.querySelectorAll('img[data-src], [data-lazy]').forEach(el => {
                        el.scrollIntoView();
                    });
                    
                    // Force load any intersection observer images
                    if ('IntersectionObserver' in window) {
                        document.querySelectorAll('img').forEach(img => {
                            if (img.loading === 'lazy') {
                                img.loading = 'eager';
                            }
                        });
                    }
                """)
                await asyncio.sleep(1)
                load_time = time.time() - start_time
                print(f"Page loaded in {load_time:.2f}s")

                if screenshot:
                    await page.screenshot(path='page_screenshot.png', full_page=True)
                    print("Screenshot saved as page_screenshot.png")

                performance_metrics = await page.evaluate("""
                    JSON.stringify({
                        navigation: performance.getEntriesByType('navigation')[0],
                        resources: performance.getEntriesByType('resource').map(r => ({
                            name: r.name,
                            type: r.initiatorType,
                            size: r.transferSize,
                            duration: r.duration,
                            startTime: r.startTime
                        }))
                    })
                """)

                perf_data = json.loads(performance_metrics)
                self._merge_performance_data(perf_data)
            except Exception as e:
                print(f"Error loading page: {e}")
                # Add failed resource for the main page
                failed_resource = Resource(
                    url=url,
                    resource_type='document',
                    method='GET',
                    failed=True
                )
                self.failed_resources.append(failed_resource)

            finally:
                await browser.close()

        if download_resources and self.resources:
            await self._download_resources(download_path)

        return self.resources

    async def _handle_route(self, route) -> None:
        """Handle all network requests by allowing them to continue.
        
        Args:
            route: Playwright route object
        """
        await route.continue_()

    def _on_request(self, request) -> None:
        """Handle request events and create Resource objects.
        
        Args:
            request: Playwright request object
        """
        resource = Resource(
            url=request.url,
            resource_type=request.resource_type,
            method=request.method,
        )
        self.resources.append(resource)

    def _on_response(self, response) -> None:
        """Handle response events and update Resource objects with response data.
        
        Args:
            response: Playwright response object
        """
        for resource in reversed(self.resources):
            if resource.url == response.url and resource.status_code is None:
                resource.status_code = response.status
                resource.mime_type = response.headers.get('content-type', '')
                resource.from_cache = (
                    response.from_service_worker or
                    'cache' in response.headers.get('x-cache', '').lower()
                )

                content_length = response.headers.get('content-length')
                if content_length:
                    try:
                        resource.size = int(content_length)
                    except ValueError:
                        # Skip invalid content-length values
                        pass
                break

    def _on_request_failed(self, request) -> None:
        """Handle failed requests and add them to failed_resources list.
        
        Args:
            request: Playwright request object that failed
        """
        failed_resource = Resource(
            url=request.url,
            resource_type=request.resource_type,
            method=request.method,
            failed=True
        )
        self.failed_resources.append(failed_resource)

    def _merge_performance_data(self, perf_data: Dict) -> None:
        """Merge performance API data with network data.
        
        Args:
            perf_data: Performance data from browser performance API
        """
        perf_resources = {r['name']: r for r in perf_data.get('resources', [])}

        for resource in self.resources:
            if resource.url in perf_resources:
                perf_resource = perf_resources[resource.url]
                if not resource.size and perf_resource.get('size'):
                    resource.size = perf_resource['size']
                resource.timing = {
                    'duration': perf_resource.get('duration', 0),
                    'startTime': perf_resource.get('startTime', 0)
                }

    async def _download_resources(self, download_path: str) -> None:
        """Download all successful resources to the specified path.
        
        Args:
            download_path: Directory path where resources will be downloaded
        """
        os.makedirs(download_path, exist_ok=True)

        print(f"Downloading {len(self.resources)} resources...")

        async with aiohttp.ClientSession() as session:
            tasks = []
            for resource in self.resources:
                if resource.status_code == 200 and not resource.failed:
                    task = self._download_single_resource(session, resource, download_path)
                    tasks.append(task)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _download_single_resource(
        self,
        session: aiohttp.ClientSession,
        resource: Resource,
        download_path: str
        ) -> None:
        """Download a single resource to the specified path.
        Args:
            session: aiohttp client session
            resource: Resource object to download
            download_path: Base directory for downloads
        """
        try:
            async with session.get(resource.url) as response:
                if response.status == 200:
                    parsed_url = urlparse(resource.url)
                    path = parsed_url.path
                    directory = parsed_url.path.split('/')[:-1]
                    directory_str = '/'.join(directory)

                    domain = parsed_url.netloc.replace(':', '_')
                    filename_path = f"{domain}{path}"
                    if filename_path.split('/')[-1] == '':
                        filename_path += 'index.html'

                    dir_path = f"{download_path}/{domain}{directory_str}"
                    pathlib.Path(dir_path).mkdir(parents=True, exist_ok=True)
                    filepath = os.path.join(download_path, filename_path)

                    async with aiofiles.open(filepath, 'wb') as f:
                        await f.write(await response.read())

        except Exception as e:
            print(f"Failed to download {resource.url}: {e}")

    def export_to_json(self, filename: str = "resources.json") -> Dict:
        """Export resources to JSON file in HAR-like format.
        Args:
            filename: Name of the output JSON file
            
        Returns:
            Dictionary containing the exported data
        """
        data = {
            'url': self.resources[0].url if self.resources else '',
            'timestamp': time.time(),
            'resources': [
                {
                    'url': r.url,
                    'type': r.resource_type,
                    'method': r.method,
                    'status': r.status_code,
                    'size': r.size,
                    'mimeType': r.mime_type,
                    'fromCache': r.from_cache,
                    'failed': r.failed,
                    'timing': r.timing
                }
                for r in self.resources
            ],
            'failed_resources': [
                {
                    'url': r.url,
                    'type': r.resource_type,
                    'method': r.method,
                    'failed': True
                }
                for r in self.failed_resources
            ]
        }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        print(f"Resources exported to {filename}")
        return data
