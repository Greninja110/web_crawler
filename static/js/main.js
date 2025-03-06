document.addEventListener('DOMContentLoaded', function() {
    // Tab switching functionality
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    if (tabButtons.length > 0) {
        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                // Deactivate all tabs
                tabButtons.forEach(btn => btn.classList.remove('active'));
                tabContents.forEach(content => content.classList.remove('active'));
                
                // Activate the clicked tab
                button.classList.add('active');
                const tabId = `${button.getAttribute('data-tab')}-tab`;
                document.getElementById(tabId).classList.add('active');
            });
        });
    }
    
    // Start crawl button functionality
    const startCrawlButtons = document.querySelectorAll('.start-crawl');
    
    if (startCrawlButtons.length > 0) {
        startCrawlButtons.forEach(button => {
            button.addEventListener('click', async () => {
                const collegeId = button.getAttribute('data-id');
                const statusIndicator = document.getElementById(`status-${collegeId}`);
                
                button.disabled = true;
                button.textContent = 'Starting...';
                
                try {
                    const response = await fetch('/start_crawl', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ college_id: collegeId }),
                    });
                    
                    const result = await response.json();
                    
                    // Update UI based on response
                    if (result.status === 'success') {
                        if (statusIndicator) {
                            statusIndicator.textContent = 'Queued';
                            statusIndicator.className = 'status-indicator queued';
                        }
                        
                        // If we're on the college data page, reload after 2 seconds
                        if (window.location.pathname.includes('/college_data/')) {
                            setTimeout(() => {
                                window.location.reload();
                            }, 2000);
                        }
                    } else {
                        alert(result.message);
                        button.disabled = false;
                        button.textContent = 'Start Crawl';
                    }
                } catch (error) {
                    console.error('Error starting crawl:', error);
                    alert('Error starting crawl. Please try again.');
                    button.disabled = false;
                    button.textContent = 'Start Crawl';
                }
            });
        });
    }
    
    // Status polling for college list page
    const collegeCards = document.querySelectorAll('.college-card');
    
    if (collegeCards.length > 0) {
        // Poll status for each college
        collegeCards.forEach(card => {
            const collegeId = card.getAttribute('data-id');
            const statusIndicator = document.getElementById(`status-${collegeId}`);
            
            if (statusIndicator) {
                // Check initial status
                checkCrawlStatus(collegeId, statusIndicator);
                
                // Set up polling every 10 seconds
                setInterval(() => {
                    checkCrawlStatus(collegeId, statusIndicator);
                }, 10000);
            }
        });
    }
    
    // Function to check crawl status
    async function checkCrawlStatus(collegeId, statusElement) {
        try {
            const response = await fetch(`/crawl_status/${collegeId}`);
            const data = await response.json();
            
            // Update the status text and class
            if (data.status) {
                statusElement.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
                statusElement.className = `status-indicator ${data.status}`;
                
                // If completed and we have summary data, add it
                if (data.status === 'completed' && data.result_summary) {
                    const summary = data.result_summary;
                    statusElement.textContent += ` (${summary.admission_count} admission, ${summary.placement_count} placement)`;
                }
            }
        } catch (error) {
            console.error('Error checking status:', error);
        }
    }
    
    // Responsive table handling
    const tables = document.querySelectorAll('.data-table');
    
    if (tables.length > 0) {
        tables.forEach(table => {
            const wrapper = document.createElement('div');
            wrapper.className = 'table-responsive';
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        });
    }
});