// Open Omniscience - Frontend JavaScript
// Connects to FastAPI backend for article search and export

const API_BASE_URL = ''; // FastAPI will be served from the same origin

// DOM elements
const searchForm = document.getElementById('searchForm');
const articlesTableBody = document.getElementById('articlesTableBody');
const loadingElement = document.getElementById('loading');
const errorMessageElement = document.getElementById('errorMessage');
const resultsInfoElement = document.getElementById('resultsInfo');
const exportCSVButton = document.getElementById('exportCSV');
const exportJSONButton = document.getElementById('exportJSON');

// Search articles
async function searchArticles(event) {
    event.preventDefault();
    
    // Show loading state
    loadingElement.style.display = 'block';
    errorMessageElement.style.display = 'none';
    articlesTableBody.innerHTML = '';
    resultsInfoElement.textContent = '';
    
    // Get form values
    const query = document.getElementById('query').value;
    const source = document.getElementById('source').value;
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    
    // Build query parameters
    const params = new URLSearchParams();
    if (query) params.append('query', query);
    if (source) params.append('source', source);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    
    try {
        const response = await fetch(`/api/articles?${params.toString()}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const articles = await response.json();
        
        // Hide loading state
        loadingElement.style.display = 'none';
        
        // Display results count
        resultsInfoElement.textContent = `Found ${articles.length} article(s)`;
        
        // Render articles
        if (articles.length > 0) {
            renderArticles(articles);
        } else {
            resultsInfoElement.textContent = 'No articles found.';
        }
        
    } catch (error) {
        loadingElement.style.display = 'none';
        errorMessageElement.textContent = `Error: ${error.message}`;
        errorMessageElement.style.display = 'block';
        console.error('Search error:', error);
    }
}

// Render articles in the table
function renderArticles(articles) {
    articlesTableBody.innerHTML = '';
    
    articles.forEach(article => {
        const row = document.createElement('tr');
        
        const titleCell = document.createElement('td');
        titleCell.textContent = article.title || 'No title';
        
        const sourceCell = document.createElement('td');
        sourceCell.textContent = article.source || 'Unknown';
        
        const dateCell = document.createElement('td');
        dateCell.textContent = article.published_at ? new Date(article.published_at).toLocaleString() : 'Unknown';
        
        const urlCell = document.createElement('td');
        const urlLink = document.createElement('a');
        urlLink.href = article.url;
        urlLink.textContent = article.url ? article.url.substring(0, 50) + '...' : 'No URL';
        urlLink.target = '_blank';
        urlLink.rel = 'noopener noreferrer';
        urlCell.appendChild(urlLink);
        
        row.appendChild(titleCell);
        row.appendChild(sourceCell);
        row.appendChild(dateCell);
        row.appendChild(urlCell);
        
        articlesTableBody.appendChild(row);
    });
}

// Export articles as CSV
async function exportCSV() {
    const query = document.getElementById('query').value;
    const source = document.getElementById('source').value;
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    
    const params = new URLSearchParams();
    if (query) params.append('query', query);
    if (source) params.append('source', source);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    
    try {
        const response = await fetch(`/api/articles/export?format=csv&${params.toString()}`);
        if (!response.ok) throw new Error('Export failed');
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'articles.csv';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        alert(`Export failed: ${error.message}`);
    }
}

// Export articles as JSON
async function exportJSON() {
    const query = document.getElementById('query').value;
    const source = document.getElementById('source').value;
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    
    const params = new URLSearchParams();
    if (query) params.append('query', query);
    if (source) params.append('source', source);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    
    try {
        const response = await fetch(`/api/articles/export?format=json&${params.toString()}`);
        if (!response.ok) throw new Error('Export failed');
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'articles.json';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        alert(`Export failed: ${error.message}`);
    }
}

// Event listeners
searchForm.addEventListener('submit', searchArticles);
exportCSVButton.addEventListener('click', exportCSV);
exportJSONButton.addEventListener('click', exportJSON);

// Initial search on page load
window.addEventListener('load', () => {
    searchArticles(new Event('submit'));
});