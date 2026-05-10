// Open Omniscience - Frontend JavaScript
// Connects to FastAPI backend for article search, export, visualization, and settings

const API_BASE_URL = ''; // FastAPI will be served from the same origin

// DOM elements
const searchForm = document.getElementById('searchForm');
const articlesTableBody = document.getElementById('articlesTableBody');
const loadingElement = document.getElementById('loading');
const errorMessageElement = document.getElementById('errorMessage');
const resultsInfoElement = document.getElementById('resultsInfo');
const exportCSVButton = document.getElementById('exportCSV');
const exportJSONButton = document.getElementById('exportJSON');
const clearFiltersButton = document.getElementById('clearFilters');
const prevPageButton = document.getElementById('prevPage');
const nextPageButton = document.getElementById('nextPage');
const pageInfoElement = document.getElementById('pageInfo');
const prevPageBottomButton = document.getElementById('prevPageBottom');
const nextPageBottomButton = document.getElementById('nextPageBottom');
const pageInfoBottomElement = document.getElementById('pageInfoBottom');
const sourceSelect = document.getElementById('source');

// Settings modal elements
const settingsButton = document.getElementById('settingsButton');
const settingsModal = document.getElementById('settingsModal');
const closeSettingsButton = document.getElementById('closeSettings');
const saveSettingsButton = document.getElementById('saveSettings');
const resetSettingsButton = document.getElementById('resetSettings');
const defaultSourceSelect = document.getElementById('defaultSource');
const defaultLanguageSelect = document.getElementById('defaultLanguage');
const themeSelect = document.getElementById('theme');
const articlesPerPageSelect = document.getElementById('articlesPerPage');
const themeToggleButton = document.getElementById('themeToggle');

// State
let currentPage = 1;
let articlesPerPage = 20;
let totalArticles = 0;
let allSources = [];
let allArticles = []; // Store all articles for visualization

// Load settings from localStorage
function loadSettings() {
    const settings = JSON.parse(localStorage.getItem('openOmniscienceSettings')) || {};

    // Apply theme
    const theme = settings.theme || 'light';
    document.documentElement.setAttribute('data-theme', theme);
    themeSelect.value = theme;

    // Apply articles per page
    articlesPerPage = parseInt(settings.articlesPerPage) || 20;
    articlesPerPageSelect.value = articlesPerPage;

    // Apply default source
    defaultSourceSelect.value = settings.defaultSource || '';

    // Apply default language
    defaultLanguageSelect.value = settings.defaultLanguage || '';
}

// Save settings to localStorage
function saveSettings() {
    const settings = {
        theme: themeSelect.value,
        articlesPerPage: parseInt(articlesPerPageSelect.value),
        defaultSource: defaultSourceSelect.value,
        defaultLanguage: defaultLanguageSelect.value
    };
    localStorage.setItem('openOmniscienceSettings', JSON.stringify(settings));
    applySettings();
}

// Apply settings (e.g., theme, articles per page)
function applySettings() {
    // Apply theme
    const theme = themeSelect.value;
    document.documentElement.setAttribute('data-theme', theme);

    // Update articles per page
    articlesPerPage = parseInt(articlesPerPageSelect.value);

    // Update default source and language in search form
    document.getElementById('source').value = defaultSourceSelect.value;
    document.getElementById('language').value = defaultLanguageSelect.value;
}

// Reset settings to defaults
function resetSettings() {
    themeSelect.value = 'light';
    articlesPerPageSelect.value = '20';
    defaultSourceSelect.value = '';
    defaultLanguageSelect.value = '';
    applySettings();
}

// Toggle theme between light and dark
function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    themeSelect.value = newTheme;
    saveSettings();
}

// Initialize the app
async function init() {
    // Load settings
    loadSettings();

    // Load sources for the dropdown
    await loadSources();

    // Set default dates (last 7 days)
    const today = new Date().toISOString().split('T')[0];
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    const sevenDaysAgoStr = sevenDaysAgo.toISOString().split('T')[0];
    document.getElementById('startDate').value = sevenDaysAgoStr;
    document.getElementById('endDate').value = today;

    // Populate default source and language in settings modal
    populateSettingsModal();
}

// Populate settings modal with sources and languages
function populateSettingsModal() {
    // Populate default source dropdown
    defaultSourceSelect.innerHTML = '<option value="">None</option>';
    allSources.forEach(source => {
        const option = document.createElement('option');
        option.value = source.name;
        option.textContent = source.name;
        defaultSourceSelect.appendChild(option);
    });
}

// Load sources from the API
async function loadSources() {
    try {
        const response = await fetch('/api/sources');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        allSources = await response.json();

        // Populate the source dropdown in search form
        sourceSelect.innerHTML = '<option value="">All Sources</option>';
        allSources.forEach(source => {
            const option = document.createElement('option');
            option.value = source.name;
            option.textContent = source.name;
            sourceSelect.appendChild(option);
        });

        // Populate settings modal
        populateSettingsModal();
    } catch (error) {
        console.error('Error loading sources:', error);
        errorMessageElement.textContent = 'Failed to load sources. Using defaults.';
        errorMessageElement.style.display = 'block';
    }
}

// Search articles with pagination
async function searchArticles(event, page = 1) {
    if (event) {
        event.preventDefault();
    }

    // Show loading state
    loadingElement.style.display = 'block';
    errorMessageElement.style.display = 'none';
    articlesTableBody.innerHTML = '';
    resultsInfoElement.textContent = '';

    // Get form values
    const query = document.getElementById('query').value;
    const source = document.getElementById('source').value;
    const language = document.getElementById('language').value;
    const tags = document.getElementById('tags').value;
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;

    // Build query parameters
    const params = new URLSearchParams();
    if (query) params.append('query', query);
    if (source) params.append('source', source);
    if (language) params.append('language', language);
    if (tags) params.append('tags', tags);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    params.append('limit', 1000); // Fetch more for visualization
    params.append('offset', 0);

    try {
        const response = await fetch(`/api/articles?${params.toString()}`);

        if (!response.ok) {
            // Handle rate limiting (429) and other errors
            if (response.status === 429) {
                errorMessageElement.textContent = 'Too many requests. Please wait and try again.';
            } else {
                errorMessageElement.textContent = `HTTP error! status: ${response.status}`;
            }
            errorMessageElement.style.display = 'block';
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        allArticles = data.results; // Store for visualization
        totalArticles = data.total;
        currentPage = page;

        // Hide loading state
        loadingElement.style.display = 'none';

        // Display results count for the current page
        const start = (page - 1) * articlesPerPage + 1;
        const end = Math.min(page * articlesPerPage, totalArticles);
        resultsInfoElement.textContent = `Showing ${start}-${end} of ${totalArticles} article(s)`;

        // Update pagination controls
        updatePaginationControls();

        // Render articles for the current page
        const paginatedArticles = allArticles.slice((page - 1) * articlesPerPage, page * articlesPerPage);
        if (paginatedArticles.length > 0) {
            renderArticles(paginatedArticles);
        } else {
            resultsInfoElement.textContent = 'No articles found.';
        }

        // Update visualizations
        updateVisualizations();

    } catch (error) {
        loadingElement.style.display = 'none';
        errorMessageElement.style.display = 'block';
        console.error('Search error:', error);
    }
}

// Update visualizations
function updateVisualizations() {
    // Source distribution chart
    const sourceCounts = {};
    allArticles.forEach(article => {
        const source = article.source || 'Unknown';
        sourceCounts[source] = (sourceCounts[source] || 0) + 1;
    });

    // Convert to array and sort by count
    const sourceData = Object.entries(sourceCounts)
        .map(([source, count]) => ({ source, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 10); // Top 10 sources

    renderSourceChart(sourceData);

    // Articles over time chart
    const articlesByDate = {};
    allArticles.forEach(article => {
        if (article.published_at) {
            const date = new Date(article.published_at).toISOString().split('T')[0];
            articlesByDate[date] = (articlesByDate[date] || 0) + 1;
        }
    });

    // Convert to array and sort by date
    const timeData = Object.entries(articlesByDate)
        .map(([date, count]) => ({ date, count }))
        .sort((a, b) => a.date.localeCompare(b.date));

    renderTimeChart(timeData);
}

// Render source distribution chart
function renderSourceChart(data) {
    const container = document.getElementById('sourceChart');
    container.innerHTML = '';

    if (data.length === 0) {
        container.innerHTML = '<p>No data available.</p>';
        return;
    }

    // Create the chart using Recharts
    const chart = Recharts.ResponsiveContainer({
        width: '100%',
        height: 300
    }, Recharts.BarChart({
        data: data,
        layout: 'vertical',
        margin: { top: 20, right: 30, left: 20, bottom: 5 }
    }, [
        Recharts.CartesianGrid({ strokeDasharray: '3 3' }),
        Recharts.XAxis({ type: 'number' }),
        Recharts.YAxis({ dataKey: 'source', type: 'category', width: 150 }),
        Recharts.Tooltip(),
        Recharts.Bar({ dataKey: 'count', fill: '#3498db' })
    ]));

    container.appendChild(chart);
}

// Render articles over time chart
function renderTimeChart(data) {
    const container = document.getElementById('timeChart');
    container.innerHTML = '';

    if (data.length === 0) {
        container.innerHTML = '<p>No data available.</p>';
        return;
    }

    // Create the chart using Recharts
    const chart = Recharts.ResponsiveContainer({
        width: '100%',
        height: 300
    }, Recharts.LineChart({
        data: data,
        margin: { top: 20, right: 30, left: 20, bottom: 5 }
    }, [
        Recharts.CartesianGrid({ strokeDasharray: '3 3' }),
        Recharts.XAxis({ dataKey: 'date' }),
        Recharts.YAxis(),
        Recharts.Tooltip(),
        Recharts.Line({ type: 'monotone', dataKey: 'count', stroke: '#2c3e50', strokeWidth: 2 })
    ]));

    container.appendChild(chart);
}

// Update pagination controls
function updatePaginationControls() {
    const totalPages = Math.ceil(totalArticles / articlesPerPage);

    // Update page info
    pageInfoElement.textContent = `Page ${currentPage} of ${totalPages}`;
    pageInfoBottomElement.textContent = `Page ${currentPage} of ${totalPages}`;

    // Update button states
    prevPageButton.disabled = currentPage <= 1;
    nextPageButton.disabled = currentPage >= totalPages;
    prevPageBottomButton.disabled = currentPage <= 1;
    nextPageBottomButton.disabled = currentPage >= totalPages;
}

// Render articles in the table
function renderArticles(articles) {
    articlesTableBody.innerHTML = '';

    articles.forEach(article => {
        const row = document.createElement('tr');

        const titleCell = document.createElement('td');
        titleCell.innerHTML = `<a href="${article.url}" target="_blank" rel="noopener noreferrer">${article.title || 'No title'}</a>`;

        const sourceCell = document.createElement('td');
        sourceCell.textContent = article.source || 'Unknown';

        const languageCell = document.createElement('td');
        languageCell.textContent = article.language || 'Unknown';

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
        row.appendChild(languageCell);
        row.appendChild(dateCell);
        row.appendChild(urlCell);

        articlesTableBody.appendChild(row);
    });
}

// Export articles as CSV
async function exportCSV() {
    const query = document.getElementById('query').value;
    const source = document.getElementById('source').value;
    const language = document.getElementById('language').value;
    const tags = document.getElementById('tags').value;
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;

    const params = new URLSearchParams();
    if (query) params.append('query', query);
    if (source) params.append('source', source);
    if (language) params.append('language', language);
    if (tags) params.append('tags', tags);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    params.append('format', 'csv');

    try {
        const response = await fetch(`/api/articles/export?${params.toString()}`);
        if (!response.ok) {
            if (response.status === 429) {
                alert('Too many requests. Please wait and try again.');
            } else {
                alert(`Export failed: HTTP ${response.status}`);
            }
            throw new Error('Export failed');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `articles_${new Date().toISOString().split('T')[0]}.csv`;
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
    const language = document.getElementById('language').value;
    const tags = document.getElementById('tags').value;
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;

    const params = new URLSearchParams();
    if (query) params.append('query', query);
    if (source) params.append('source', source);
    if (language) params.append('language', language);
    if (tags) params.append('tags', tags);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    params.append('format', 'json');

    try {
        const response = await fetch(`/api/articles/export?${params.toString()}`);
        if (!response.ok) {
            if (response.status === 429) {
                alert('Too many requests. Please wait and try again.');
            } else {
                alert(`Export failed: HTTP ${response.status}`);
            }
            throw new Error('Export failed');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `articles_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        alert(`Export failed: ${error.message}`);
    }
}

// Clear all filters
function clearFilters() {
    document.getElementById('query').value = '';
    document.getElementById('source').value = '';
    document.getElementById('language').value = '';
    document.getElementById('tags').value = '';
    document.getElementById('startDate').value = '';
    document.getElementById('endDate').value = '';
    currentPage = 1;
    allArticles = [];
    searchArticles(new Event('submit'), 1);
}

// Show settings modal
function showSettingsModal() {
    settingsModal.style.display = 'block';
}

// Hide settings modal
function hideSettingsModal() {
    settingsModal.style.display = 'none';
}

// Event listeners
searchForm.addEventListener('submit', (e) => {
    currentPage = 1;
    searchArticles(e, 1);
});
exportCSVButton.addEventListener('click', exportCSV);
exportJSONButton.addEventListener('click', exportJSON);
clearFiltersButton.addEventListener('click', clearFilters);
prevPageButton.addEventListener('click', () => {
    if (currentPage > 1) {
        searchArticles(new Event('submit'), currentPage - 1);
    }
});
nextPageButton.addEventListener('click', () => {
    const totalPages = Math.ceil(totalArticles / articlesPerPage);
    if (currentPage < totalPages) {
        searchArticles(new Event('submit'), currentPage + 1);
    }
});
prevPageBottomButton.addEventListener('click', () => {
    if (currentPage > 1) {
        searchArticles(new Event('submit'), currentPage - 1);
    }
});
nextPageBottomButton.addEventListener('click', () => {
    const totalPages = Math.ceil(totalArticles / articlesPerPage);
    if (currentPage < totalPages) {
        searchArticles(new Event('submit'), currentPage + 1);
    }
});

// Settings modal event listeners
settingsButton.addEventListener('click', showSettingsModal);
closeSettingsButton.addEventListener('click', hideSettingsModal);
saveSettingsButton.addEventListener('click', () => {
    saveSettings();
    hideSettingsModal();
});
resetSettingsButton.addEventListener('click', () => {
    resetSettings();
    hideSettingsModal();
});

// Theme toggle event listener
themeToggleButton.addEventListener('click', toggleTheme);

// Close modal when clicking outside
window.addEventListener('click', (event) => {
    if (event.target === settingsModal) {
        hideSettingsModal();
    }
});

// Initialize the app when the page loads
window.addEventListener('load', init);