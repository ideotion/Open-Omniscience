/**
 * Source Manager JavaScript - Main functionality
 * This file contains the core functionality for the source management dashboard
 */

// Global state
let currentPage = 1;
let sourcesPerPage = 50;
let allSources = [];
let allGroups = [];
let selectedSources = new Set();
let currentTab = 'sources';

// API base URL
const API_BASE = '/api/sources';

// DOM Elements
const tabButtons = document.querySelectorAll('.tab-button');
const tabPanes = document.querySelectorAll('.tab-pane');
const loadingOverlay = document.getElementById('loadingOverlay');
const loadingMessage = document.getElementById('loadingMessage');

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    initEventListeners();
    loadInitialData();
    setupTheme();
});

/**
 * Initialize all event listeners
 */
function initEventListeners() {
    // Tab navigation
    tabButtons.forEach(button => {
        button.addEventListener('click', () => switchTab(button.dataset.tab));
    });

    // Back button
    document.getElementById('backButton')?.addEventListener('click', () => {
        window.location.href = '/';
    });

    // Refresh button
    document.getElementById('refreshButton')?.addEventListener('click', loadInitialData);

    // Theme toggle
    document.getElementById('themeToggle')?.addEventListener('click', toggleTheme);

    // Source tab events
    initSourceTabEvents();
    initGroupTabEvents();
    initDiscoverTabEvents();
    initStatisticsTabEvents();
    initModalEvents();
}

/**
 * Load initial data
 */
async function loadInitialData() {
    showLoading('Loading data...');
    
    try {
        const [sourcesResponse, groupsResponse, statsResponse] = await Promise.all([
            fetch(`${API_BASE}/`),
            fetch(`${API_BASE}/groups/`),
            fetch(`${API_BASE}/stats`)
        ]);
        
        allSources = await sourcesResponse.json();
        allGroups = await groupsResponse.json();
        const statsData = await statsResponse.json();
        
        renderSourcesTable(allSources);
        populateGroupSelects();
        updateStatistics(statsData);
        
        hideLoading();
        showNotification('Data loaded successfully', 'success');
        
    } catch (error) {
        hideLoading();
        showNotification(`Error loading data: ${error.message}`, 'error');
        console.error('Error loading initial data:', error);
    }
}

/**
 * Show loading overlay
 */
function showLoading(message = 'Loading...') {
    if (loadingMessage) loadingMessage.textContent = message;
    if (loadingOverlay) loadingOverlay.style.display = 'flex';
}

/**
 * Hide loading overlay
 */
function hideLoading() {
    if (loadingOverlay) loadingOverlay.style.display = 'none';
}

/**
 * Show notification toast
 */
function showNotification(message, type = 'info') {
    const toast = document.getElementById('notificationToast');
    const msg = document.getElementById('notificationMessage');
    const icon = document.getElementById('notificationIcon');
    
    if (!toast || !msg || !icon) return;
    
    msg.textContent = message;
    icon.className = 'fas';
    
    if (type === 'success') {
        icon.classList.add('fa-check-circle');
        toast.style.borderColor = '#28a745';
        toast.style.backgroundColor = '#d4edda';
        toast.style.color = '#155724';
    } else if (type === 'error') {
        icon.classList.add('fa-exclamation-circle');
        toast.style.borderColor = '#dc3545';
        toast.style.backgroundColor = '#f8d7da';
        toast.style.color = '#721c24';
    } else if (type === 'warning') {
        icon.classList.add('fa-exclamation-triangle');
        toast.style.borderColor = '#ffc107';
        toast.style.backgroundColor = '#fff3cd';
        toast.style.color = '#856404';
    } else {
        icon.classList.add('fa-info-circle');
        toast.style.borderColor = '#17a2b8';
        toast.style.backgroundColor = '#d1ecf1';
        toast.style.color = '#0c5460';
    }
    
    toast.style.display = 'flex';
    setTimeout(() => {
        if (toast) toast.style.display = 'none';
    }, 5000);
}

/**
 * Switch between tabs
 */
function switchTab(tabName) {
    tabButtons.forEach(button => {
        button.classList.toggle('active', button.dataset.tab === tabName);
    });
    
    tabPanes.forEach(pane => {
        pane.classList.toggle('active', pane.id === `${tabName}-tab`);
    });
    
    currentTab = tabName;
    
    if (tabName === 'sources') {
        renderSourcesTable(allSources);
    } else if (tabName === 'groups') {
        renderGroupsTable(allGroups);
    }
}

/**
 * Theme management
 */
function setupTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.body.classList.toggle('dark-theme', savedTheme === 'dark');
}

function toggleTheme() {
    const isDark = document.body.classList.toggle('dark-theme');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
}

/**
 * Get priority label
 */
function getPriorityLabel(priority) {
    switch (priority) {
        case 1: return 'High';
        case 2: return 'Medium';
        case 3: return 'Low';
        default: return 'Unknown';
    }
}

/**
 * Render sources table
 */
function renderSourcesTable(sources) {
    const tbody = document.getElementById('sourcesTableBody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    // Apply pagination
    const startIndex = (currentPage - 1) * sourcesPerPage;
    const paginatedSources = sources.slice(startIndex, startIndex + sourcesPerPage);
    
    paginatedSources.forEach(source => {
        const row = document.createElement('tr');
        row.dataset.sourceId = source.id;
        
        // Checkbox
        const checkboxTd = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = selectedSources.has(source.id);
        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                selectedSources.add(source.id);
            } else {
                selectedSources.delete(source.id);
            }
        });
        checkboxTd.appendChild(checkbox);
        row.appendChild(checkboxTd);
        
        // Name
        const nameTd = document.createElement('td');
        nameTd.textContent = source.name;
        row.appendChild(nameTd);
        
        // Domain
        const domainTd = document.createElement('td');
        domainTd.textContent = source.domain;
        row.appendChild(domainTd);
        
        // RSS URL
        const rssTd = document.createElement('td');
        if (source.rss_url) {
            const rssLink = document.createElement('a');
            rssLink.href = source.rss_url;
            rssLink.textContent = source.rss_url.substring(0, 50) + (source.rss_url.length > 50 ? '...' : '');
            rssLink.target = '_blank';
            rssLink.title = source.rss_url;
            rssTd.appendChild(rssLink);
        } else {
            rssTd.textContent = 'None';
            rssTd.style.color = '#dc3545';
        }
        row.appendChild(rssTd);
        
        // Status
        const statusTd = document.createElement('td');
        const statusSpan = document.createElement('span');
        statusSpan.className = `status-badge ${source.enabled ? 'enabled' : 'disabled'}`;
        statusSpan.textContent = source.enabled ? 'Enabled' : 'Disabled';
        statusTd.appendChild(statusSpan);
        row.appendChild(statusTd);
        
        // Priority
        const priorityTd = document.createElement('td');
        const prioritySpan = document.createElement('span');
        prioritySpan.className = `priority-badge priority-${source.priority}`;
        prioritySpan.textContent = getPriorityLabel(source.priority);
        priorityTd.appendChild(prioritySpan);
        row.appendChild(priorityTd);
        
        // Rate Limit
        const rateLimitTd = document.createElement('td');
        rateLimitTd.textContent = `${source.rate_limit_ms}ms`;
        row.appendChild(rateLimitTd);
        
        // Tags
        const tagsTd = document.createElement('td');
        if (source.tags && source.tags.length > 0) {
            source.tags.forEach(tag => {
                const tagSpan = document.createElement('span');
                tagSpan.className = 'tag-badge';
                tagSpan.textContent = tag;
                tagsTd.appendChild(tagSpan);
                tagsTd.appendChild(document.createTextNode(' '));
            });
        } else {
            tagsTd.textContent = 'None';
        }
        row.appendChild(tagsTd);
        
        // Groups
        const groupsTd = document.createElement('td');
        if (source.groups && source.groups.length > 0) {
            source.groups.forEach(group => {
                const groupSpan = document.createElement('span');
                groupSpan.className = 'group-badge';
                groupSpan.textContent = group.name;
                groupSpan.style.backgroundColor = group.color || '#666666';
                groupsTd.appendChild(groupSpan);
                groupsTd.appendChild(document.createTextNode(' '));
            });
        } else {
            groupsTd.textContent = 'None';
        }
        row.appendChild(groupsTd);
        
        // Article count
        const articlesTd = document.createElement('td');
        articlesTd.textContent = source.article_count || '0';
        row.appendChild(articlesTd);
        
        // Actions
        const actionsTd = document.createElement('td');
        const editBtn = document.createElement('button');
        editBtn.className = 'action-btn edit-btn';
        editBtn.title = 'Edit';
        editBtn.innerHTML = '<i class="fas fa-edit"></i>';
        editBtn.addEventListener('click', () => openSourceModal(source.id));
        actionsTd.appendChild(editBtn);
        
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'action-btn delete-btn';
        deleteBtn.title = 'Delete';
        deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
        deleteBtn.addEventListener('click', () => deleteSource(source.id));
        actionsTd.appendChild(deleteBtn);
        
        row.appendChild(actionsTd);
        
        tbody.appendChild(row);
    });
    
    // Update pagination
    const totalPages = Math.ceil(sources.length / sourcesPerPage);
    const pageInfo = document.getElementById('pageInfoSources');
    const prevBtn = document.getElementById('prevPageSources');
    const nextBtn = document.getElementById('nextPageSources');
    
    if (pageInfo) pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
    if (prevBtn) prevBtn.disabled = currentPage === 1;
    if (nextBtn) nextBtn.disabled = currentPage === totalPages || totalPages === 0;
}

/**
 * Render groups table
 */
function renderGroupsTable(groups) {
    const tbody = document.getElementById('groupsTableBody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    groups.forEach(group => {
        const row = document.createElement('tr');
        row.dataset.groupId = group.id;
        
        // Checkbox
        const checkboxTd = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkboxTd.appendChild(checkbox);
        row.appendChild(checkboxTd);
        
        // Name
        const nameTd = document.createElement('td');
        const nameLink = document.createElement('a');
        nameLink.href = '#';
        nameLink.textContent = group.name;
        nameLink.style.color = group.color || '#666666';
        nameLink.addEventListener('click', (e) => {
            e.preventDefault();
            showGroupDetail(group.id);
        });
        nameTd.appendChild(nameLink);
        row.appendChild(nameTd);
        
        // Description
        const descTd = document.createElement('td');
        descTd.textContent = group.description || 'No description';
        row.appendChild(descTd);
        
        // Type
        const typeTd = document.createElement('td');
        const typeSpan = document.createElement('span');
        typeSpan.className = `status-badge ${group.is_tag_based ? 'tag-based' : 'manual'}`;
        typeSpan.textContent = group.is_tag_based ? 'Tag-Based' : 'Manual';
        typeTd.appendChild(typeSpan);
        row.appendChild(typeTd);
        
        // Source count
        const sourcesTd = document.createElement('td');
        sourcesTd.textContent = group.source_count || '0';
        row.appendChild(sourcesTd);
        
        // Priority
        const priorityTd = document.createElement('td');
        priorityTd.textContent = getPriorityLabel(group.priority);
        row.appendChild(priorityTd);
        
        // Rate Limit
        const rateLimitTd = document.createElement('td');
        rateLimitTd.textContent = `${group.rate_limit_ms}ms`;
        row.appendChild(rateLimitTd);
        
        // Status
        const statusTd = document.createElement('td');
        const statusSpan = document.createElement('span');
        statusSpan.className = `status-badge ${group.enabled ? 'enabled' : 'disabled'}`;
        statusSpan.textContent = group.enabled ? 'Enabled' : 'Disabled';
        statusTd.appendChild(statusSpan);
        row.appendChild(statusTd);
        
        // Tag Pattern
        const tagPatternTd = document.createElement('td');
        tagPatternTd.textContent = group.tag_pattern || 'N/A';
        row.appendChild(tagPatternTd);
        
        // Actions
        const actionsTd = document.createElement('td');
        const editBtn = document.createElement('button');
        editBtn.className = 'action-btn edit-btn';
        editBtn.title = 'Edit';
        editBtn.innerHTML = '<i class="fas fa-edit"></i>';
        editBtn.addEventListener('click', () => openGroupModal(group.id));
        actionsTd.appendChild(editBtn);
        
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'action-btn delete-btn';
        deleteBtn.title = 'Delete';
        deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
        deleteBtn.addEventListener('click', () => deleteGroup(group.id));
        actionsTd.appendChild(deleteBtn);
        
        row.appendChild(actionsTd);
        
        tbody.appendChild(row);
    });
}

/**
 * Populate group selects in modals
 */
function populateGroupSelects() {
    // For source groups checkboxes
    const sourceGroupsSelect = document.getElementById('sourceGroupsSelect');
    if (sourceGroupsSelect) {
        sourceGroupsSelect.innerHTML = '';
        allGroups.forEach(group => {
            const div = document.createElement('div');
            div.className = 'checkbox-item';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `sourceGroup_${group.id}`;
            checkbox.value = group.id;
            
            const label = document.createElement('label');
            label.htmlFor = `sourceGroup_${group.id}`;
            label.textContent = group.name;
            
            div.appendChild(checkbox);
            div.appendChild(label);
            sourceGroupsSelect.appendChild(div);
        });
    }
}

/**
 * Update statistics display
 */
function updateStatistics(stats) {
    const statElements = {
        'totalSourcesStat': stats.sources.total,
        'enabledSourcesStat': stats.sources.enabled,
        'disabledSourcesStat': stats.sources.disabled,
        'withRssStat': stats.sources.with_rss,
        'withoutRssStat': stats.sources.without_rss,
        'totalGroupsStat': stats.groups.total
    };
    
    Object.entries(statElements).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    });
}

/**
 * Show group detail panel
 */
async function showGroupDetail(groupId) {
    showLoading('Loading group details...');
    
    try {
        const response = await fetch(`${API_BASE}/groups/${groupId}`);
        const group = await response.json();
        
        // Update detail panel
        document.getElementById('groupDetailName')?.textContent = group.name;
        document.getElementById('groupDetailDescription')?.textContent = group.description || 'No description';
        document.getElementById('groupDetailColor')?.style.setProperty('background-color', group.color || '#666666');
        document.getElementById('groupDetailType')?.textContent = group.is_tag_based ? 'Tag-Based' : 'Manual';
        document.getElementById('groupDetailPriority')?.textContent = getPriorityLabel(group.priority);
        document.getElementById('groupDetailRateLimit')?.textContent = `${group.rate_limit_ms}ms`;
        document.getElementById('groupDetailEnabled')?.textContent = group.enabled ? 'Yes' : 'No';
        document.getElementById('groupDetailTagPattern')?.textContent = group.tag_pattern || 'N/A';
        
        // Render group sources
        renderGroupSourcesTable(group.sources || []);
        
        // Store current group ID for add/remove operations
        const modal = document.getElementById('groupDetailPanel');
        if (modal) {
            modal.dataset.groupId = groupId;
            modal.style.display = 'block';
        }
        
        hideLoading();
        
    } catch (error) {
        hideLoading();
        showNotification(`Error loading group details: ${error.message}`, 'error');
        console.error('Error loading group details:', error);
    }
}

/**
 * Render group sources table
 */
function renderGroupSourcesTable(sources) {
    const tbody = document.getElementById('groupSourcesTableBody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    sources.forEach(source => {
        const row = document.createElement('tr');
        row.dataset.sourceId = source.id;
        
        // Checkbox
        const checkboxTd = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkboxTd.appendChild(checkbox);
        row.appendChild(checkboxTd);
        
        // Name
        const nameTd = document.createElement('td');
        nameTd.textContent = source.name;
        row.appendChild(nameTd);
        
        // Domain
        const domainTd = document.createElement('td');
        domainTd.textContent = source.domain;
        row.appendChild(domainTd);
        
        // Status
        const statusTd = document.createElement('td');
        const statusSpan = document.createElement('span');
        statusSpan.className = `status-badge ${source.enabled ? 'enabled' : 'disabled'}`;
        statusSpan.textContent = source.enabled ? 'Enabled' : 'Disabled';
        statusTd.appendChild(statusSpan);
        row.appendChild(statusTd);
        
        // Priority
        const priorityTd = document.createElement('td');
        const prioritySpan = document.createElement('span');
        prioritySpan.className = `priority-badge priority-${source.priority}`;
        prioritySpan.textContent = getPriorityLabel(source.priority);
        priorityTd.appendChild(prioritySpan);
        row.appendChild(priorityTd);
        
        // Actions
        const actionsTd = document.createElement('td');
        const removeBtn = document.createElement('button');
        removeBtn.className = 'action-btn delete-btn';
        removeBtn.title = 'Remove from group';
        removeBtn.innerHTML = '<i class="fas fa-times"></i>';
        removeBtn.addEventListener('click', () => {
            removeSourceFromGroup(source.id, parseInt(document.getElementById('groupDetailPanel')?.dataset.groupId));
        });
        actionsTd.appendChild(removeBtn);
        row.appendChild(actionsTd);
        
        tbody.appendChild(row);
    });
}

/**
 * Close group detail panel
 */
function closeGroupDetail() {
    const panel = document.getElementById('groupDetailPanel');
    if (panel) panel.style.display = 'none';
}

// Initialize tab-specific event handlers
function initSourceTabEvents() {
    // Add source button
    document.getElementById('addSourceBtn')?.addEventListener('click', () => openSourceModal());
    
    // Batch actions button
    document.getElementById('batchActionsBtn')?.addEventListener('click', openBatchActionsModal);
    
    // Export button
    document.getElementById('exportSourcesBtn')?.addEventListener('click', exportSources);
    
    // Pagination
    document.getElementById('prevPageSources')?.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            renderSourcesTable(allSources);
        }
    });
    
    document.getElementById('nextPageSources')?.addEventListener('click', () => {
        const totalPages = Math.ceil(allSources.length / sourcesPerPage);
        if (currentPage < totalPages) {
            currentPage++;
            renderSourcesTable(allSources);
        }
    });
}

function initGroupTabEvents() {
    // Add group button
    document.getElementById('addGroupBtn')?.addEventListener('click', () => openGroupModal());
    
    // Refresh groups button
    document.getElementById('refreshGroupsBtn')?.addEventListener('click', refreshTagBasedGroups);
}

function initDiscoverTabEvents() {
    // Discover by topic
    document.getElementById('discoverTopicBtn')?.addEventListener('click', discoverSourcesByTopic);
    
    // Discover RSS feeds
    document.getElementById('startRssDiscoveryBtn')?.addEventListener('click', discoverRssFeeds);
    
    // Web search
    document.getElementById('webSearchBtn')?.addEventListener('click', webSearch);
}

function initStatisticsTabEvents() {
    // Refresh statistics button
    document.getElementById('refreshStatsBtn')?.addEventListener('click', loadStatistics);
}

function initModalEvents() {
    // Source modal
    document.getElementById('closeSourceModal')?.addEventListener('click', closeSourceModal);
    document.getElementById('cancelSourceBtn')?.addEventListener('click', closeSourceModal);
    document.getElementById('saveSourceBtn')?.addEventListener('click', saveSource);
    
    // Group modal
    document.getElementById('closeGroupModal')?.addEventListener('click', closeGroupModal);
    document.getElementById('cancelGroupBtn')?.addEventListener('click', closeGroupModal);
    document.getElementById('saveGroupBtn')?.addEventListener('click', saveGroup);
    
    // Batch actions modal
    document.getElementById('closeBatchActionsModal')?.addEventListener('click', closeBatchActionsModal);
    document.getElementById('closeBatchActionsBtn')?.addEventListener('click', closeBatchActionsModal);
    
    // Group detail panel
    document.getElementById('closeGroupDetail')?.addEventListener('click', closeGroupDetail);
    
    // Tag-based group toggle
    document.getElementById('groupIsTagBased')?.addEventListener('change', (e) => {
        const tagPatternGroup = document.getElementById('tagPatternGroup');
        if (tagPatternGroup) {
            tagPatternGroup.style.display = e.target.value === 'true' ? 'block' : 'none';
        }
    });
}

/**
 * Open source modal
 */
function openSourceModal(sourceId = null) {
    const modal = document.getElementById('sourceModal');
    const modalTitle = document.getElementById('sourceModalTitle');
    
    if (!modal || !modalTitle) return;
    
    if (sourceId) {
        // Edit mode
        modalTitle.textContent = 'Edit Source';
        showLoading('Loading source...');
        
        fetch(`${API_BASE}/${sourceId}`)
            .then(response => response.json())
            .then(source => {
                hideLoading();
                populateSourceForm(source);
                modal.style.display = 'flex';
            })
            .catch(error => {
                hideLoading();
                showNotification(`Error loading source: ${error.message}`, 'error');
                console.error('Error loading source:', error);
            });
    } else {
        // Add mode
        modalTitle.textContent = 'Add Source';
        resetSourceForm();
        modal.style.display = 'flex';
    }
}

/**
 * Close source modal
 */
function closeSourceModal() {
    const modal = document.getElementById('sourceModal');
    if (modal) modal.style.display = 'none';
    resetSourceForm();
}

/**
 * Populate source form
 */
function populateSourceForm(source) {
    const formElements = {
        'sourceId': source.id || '',
        'sourceName': source.name || '',
        'sourceDomain': source.domain || '',
        'sourceRssUrl': source.rss_url || '',
        'sourceUrl': source.url || `https://${source.domain || ''}`,
        'sourceRateLimit': source.rate_limit_ms || 2000,
        'sourcePriority': source.priority || 2,
        'sourceEnabled': source.enabled !== false ? 'true' : 'false',
        'sourceTags': source.tags ? source.tags.join(', ') : ''
    };
    
    Object.entries(formElements).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element && value !== undefined) {
            element.value = value;
        }
    });
    
    // Populate groups
    if (source.groups) {
        source.groups.forEach(group => {
            const checkbox = document.getElementById(`sourceGroup_${group.id}`);
            if (checkbox) {
                checkbox.checked = true;
            }
        });
    }
}

/**
 * Reset source form
 */
function resetSourceForm() {
    const form = document.getElementById('sourceForm');
    if (form) form.reset();
    
    const sourceId = document.getElementById('sourceId');
    if (sourceId) sourceId.value = '';
    
    // Uncheck all group checkboxes
    const checkboxes = document.querySelectorAll('#sourceGroupsSelect input[type="checkbox"]');
    checkboxes.forEach(checkbox => {
        checkbox.checked = false;
    });
}

/**
 * Save source
 */
async function saveSource() {
    const sourceId = document.getElementById('sourceId')?.value;
    const sourceData = {
        name: document.getElementById('sourceName')?.value.trim() || '',
        domain: document.getElementById('sourceDomain')?.value.trim() || '',
        rss_url: document.getElementById('sourceRssUrl')?.value.trim() || null,
        rate_limit_ms: parseInt(document.getElementById('sourceRateLimit')?.value) || 2000,
        priority: parseInt(document.getElementById('sourcePriority')?.value) || 2,
        enabled: document.getElementById('sourceEnabled')?.value === 'true',
        tags: document.getElementById('sourceTags')?.value.split(',').map(t => t.trim()).filter(t => t).join(', ') || ''
    };
    
    // Get selected groups
    const selectedGroupIds = Array.from(document.querySelectorAll('#sourceGroupsSelect input[type="checkbox"]:checked'))
        .map(cb => parseInt(cb.value));
    
    if (!sourceData.name || !sourceData.domain) {
        showNotification('Name and Domain are required', 'warning');
        return;
    }
    
    showLoading(`Saving source...`);
    
    try {
        let response;
        
        if (sourceId) {
            // Update existing source
            response = await fetch(`${API_BASE}/${sourceId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(sourceData)
            });
        } else {
            // Create new source
            response = await fetch(`${API_BASE}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(sourceData)
            });
        }
        
        const result = await response.json();
        
        // If we have group selections, update them
        if (selectedGroupIds.length > 0) {
            const sourceIdToUse = sourceId || result.id;
            await fetch(`${API_BASE}/${sourceIdToUse}/groups`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ group_ids: selectedGroupIds })
            });
        }
        
        hideLoading();
        closeSourceModal();
        showNotification(result.message, 'success');
        
        // Reload sources
        const sourcesResponse = await fetch(`${API_BASE}/`);
        allSources = await sourcesResponse.json();
        renderSourcesTable(allSources);
        
    } catch (error) {
        hideLoading();
        showNotification(`Error saving source: ${error.message}`, 'error');
        console.error('Error saving source:', error);
    }
}

/**
 * Delete source
 */
async function deleteSource(sourceId) {
    if (!confirm('Are you sure you want to delete this source? This action cannot be undone.')) {
        return;
    }
    
    showLoading('Deleting source...');
    
    try {
        const response = await fetch(`${API_BASE}/${sourceId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        hideLoading();
        showNotification(result.message, 'success');
        
        // Reload sources
        const sourcesResponse = await fetch(`${API_BASE}/`);
        allSources = await sourcesResponse.json();
        renderSourcesTable(allSources);
        
        // Remove from selected if present
        selectedSources.delete(sourceId);
        
    } catch (error) {
        hideLoading();
        showNotification(`Error deleting source: ${error.message}`, 'error');
        console.error('Error deleting source:', error);
    }
}

/**
 * Open group modal
 */
function openGroupModal(groupId = null) {
    const modal = document.getElementById('groupModal');
    const modalTitle = document.getElementById('groupModalTitle');
    
    if (!modal || !modalTitle) return;
    
    if (groupId) {
        // Edit mode
        modalTitle.textContent = 'Edit Group';
        showLoading('Loading group...');
        
        fetch(`${API_BASE}/groups/${groupId}`)
            .then(response => response.json())
            .then(group => {
                hideLoading();
                populateGroupForm(group);
                modal.style.display = 'flex';
            })
            .catch(error => {
                hideLoading();
                showNotification(`Error loading group: ${error.message}`, 'error');
                console.error('Error loading group:', error);
            });
    } else {
        // Add mode
        modalTitle.textContent = 'Add Group';
        resetGroupForm();
        modal.style.display = 'flex';
    }
}

/**
 * Close group modal
 */
function closeGroupModal() {
    const modal = document.getElementById('groupModal');
    if (modal) modal.style.display = 'none';
    resetGroupForm();
}

/**
 * Populate group form
 */
function populateGroupForm(group) {
    const formElements = {
        'groupId': group.id || '',
        'groupName': group.name || '',
        'groupDescription': group.description || '',
        'groupColor': group.color || '#666666',
        'groupIsTagBased': group.is_tag_based ? 'true' : 'false',
        'groupTagPattern': group.tag_pattern || '',
        'groupPriority': group.priority || 2,
        'groupRateLimit': group.rate_limit_ms || 2000,
        'groupEnabled': group.enabled !== false ? 'true' : 'false'
    };
    
    Object.entries(formElements).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element && value !== undefined) {
            element.value = value;
        }
    });
    
    // Show/hide tag pattern based on is_tag_based
    const tagPatternGroup = document.getElementById('tagPatternGroup');
    if (tagPatternGroup) {
        tagPatternGroup.style.display = group.is_tag_based ? 'block' : 'none';
    }
}

/**
 * Reset group form
 */
function resetGroupForm() {
    const form = document.getElementById('groupForm');
    if (form) form.reset();
    
    const groupId = document.getElementById('groupId');
    if (groupId) groupId.value = '';
    
    const groupColor = document.getElementById('groupColor');
    if (groupColor) groupColor.value = '#666666';
    
    const tagPatternGroup = document.getElementById('tagPatternGroup');
    if (tagPatternGroup) tagPatternGroup.style.display = 'none';
}

/**
 * Save group
 */
async function saveGroup() {
    const groupId = document.getElementById('groupId')?.value;
    const groupData = {
        name: document.getElementById('groupName')?.value.trim() || '',
        description: document.getElementById('groupDescription')?.value.trim() || '',
        color: document.getElementById('groupColor')?.value || '#666666',
        is_tag_based: document.getElementById('groupIsTagBased')?.value === 'true',
        tag_pattern: document.getElementById('groupTagPattern')?.value.trim() || '',
        priority: parseInt(document.getElementById('groupPriority')?.value) || 2,
        rate_limit_ms: parseInt(document.getElementById('groupRateLimit')?.value) || 2000,
        enabled: document.getElementById('groupEnabled')?.value === 'true'
    };
    
    if (!groupData.name) {
        showNotification('Name is required', 'warning');
        return;
    }
    
    showLoading(`Saving group...`);
    
    try {
        let response;
        
        if (groupId) {
            // Update existing group
            response = await fetch(`${API_BASE}/groups/${groupId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(groupData)
            });
        } else {
            // Create new group
            response = await fetch(`${API_BASE}/groups/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(groupData)
            });
        }
        
        const result = await response.json();
        
        hideLoading();
        closeGroupModal();
        showNotification(result.message, 'success');
        
        // Reload groups
        const groupsResponse = await fetch(`${API_BASE}/groups/`);
        allGroups = await groupsResponse.json();
        renderGroupsTable(allGroups);
        populateGroupSelects();
        
    } catch (error) {
        hideLoading();
        showNotification(`Error saving group: ${error.message}`, 'error');
        console.error('Error saving group:', error);
    }
}

/**
 * Delete group
 */
async function deleteGroup(groupId) {
    if (!confirm('Are you sure you want to delete this group? This will not delete the sources in the group.')) {
        return;
    }
    
    showLoading('Deleting group...');
    
    try {
        const response = await fetch(`${API_BASE}/groups/${groupId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        hideLoading();
        showNotification(result.message, 'success');
        
        // Reload groups
        const groupsResponse = await fetch(`${API_BASE}/groups/`);
        allGroups = await groupsResponse.json();
        renderGroupsTable(allGroups);
        populateGroupSelects();
        
    } catch (error) {
        hideLoading();
        showNotification(`Error deleting group: ${error.message}`, 'error');
        console.error('Error deleting group:', error);
    }
}

/**
 * Open batch actions modal
 */
function openBatchActionsModal() {
    if (selectedSources.size === 0) {
        showNotification('No sources selected', 'warning');
        return;
    }
    
    const modal = document.getElementById('batchActionsModal');
    if (modal) modal.style.display = 'flex';
}

/**
 * Close batch actions modal
 */
function closeBatchActionsModal() {
    const modal = document.getElementById('batchActionsModal');
    if (modal) modal.style.display = 'none';
}

/**
 * Export sources
 */
async function exportSources() {
    showLoading('Exporting sources...');
    
    try {
        const response = await fetch(`${API_BASE}/export`);
        const data = await response.json();
        
        // Create download link
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `open-omniscience-sources-${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        hideLoading();
        showNotification('Sources exported successfully', 'success');
        
    } catch (error) {
        hideLoading();
        showNotification(`Error exporting sources: ${error.message}`, 'error');
        console.error('Error exporting sources:', error);
    }
}

/**
 * Discover sources by topic
 */
async function discoverSourcesByTopic() {
    const topic = document.getElementById('discoveryTopic')?.value.trim();
    const maxSources = parseInt(document.getElementById('discoveryMaxSources')?.value) || 20;
    const region = document.getElementById('discoveryRegion')?.value || 'wt-wt';
    
    if (!topic) {
        showNotification('Please enter a topic', 'warning');
        return;
    }
    
    showLoading(`Discovering sources for "${topic}"...`);
    
    try {
        const response = await fetch(`${API_BASE}/discover/topic`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                topic: topic,
                max_sources: maxSources,
                region: region
            })
        });
        
        const result = await response.json();
        
        // Show results
        const discoveryResults = document.getElementById('discoveryResults');
        const discoveryResultsInfo = document.getElementById('discoveryResultsInfo');
        
        if (discoveryResults) discoveryResults.style.display = 'block';
        if (discoveryResultsInfo) discoveryResultsInfo.textContent = `${result.count} sources discovered`;
        
        renderDiscoveredSourcesTable(result.sources);
        
        hideLoading();
        showNotification(result.message, 'success');
        
    } catch (error) {
        hideLoading();
        showNotification(`Error discovering sources: ${error.message}`, 'error');
        console.error('Error discovering sources:', error);
    }
}

/**
 * Render discovered sources table
 */
function renderDiscoveredSourcesTable(sources) {
    const tbody = document.getElementById('discoveredSourcesTableBody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    sources.forEach(source => {
        const row = document.createElement('tr');
        row.dataset.sourceId = source.id;
        
        // Checkbox
        const checkboxTd = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkboxTd.appendChild(checkbox);
        row.appendChild(checkboxTd);
        
        // Name
        const nameTd = document.createElement('td');
        nameTd.textContent = source.name || source.domain;
        row.appendChild(nameTd);
        
        // Domain
        const domainTd = document.createElement('td');
        domainTd.textContent = source.domain;
        row.appendChild(domainTd);
        
        // URL
        const urlTd = document.createElement('td');
        if (source.url) {
            const urlLink = document.createElement('a');
            urlLink.href = source.url;
            urlLink.textContent = source.url.substring(0, 50) + (source.url.length > 50 ? '...' : '');
            urlLink.target = '_blank';
            urlLink.title = source.url;
            urlTd.appendChild(urlLink);
        } else {
            urlTd.textContent = 'N/A';
        }
        row.appendChild(urlTd);
        
        // RSS Feeds
        const rssTd = document.createElement('td');
        if (source.rss_urls && source.rss_urls.length > 0) {
            source.rss_urls.forEach((rssUrl, index) => {
                if (index > 0) rssTd.appendChild(document.createTextNode(', '));
                const rssLink = document.createElement('a');
                rssLink.href = rssUrl;
                rssLink.textContent = rssUrl.substring(0, 40) + (rssUrl.length > 40 ? '...' : '');
                rssLink.target = '_blank';
                rssLink.title = rssUrl;
                rssTd.appendChild(rssLink);
            });
        } else {
            rssTd.textContent = 'None';
        }
        row.appendChild(rssTd);
        
        // Relevance
        const relevanceTd = document.createElement('td');
        const relevanceBar = document.createElement('div');
        relevanceBar.className = 'relevance-bar';
        const relevancePercent = (source.relevance || 0) * 100;
        relevanceBar.style.width = `${relevancePercent}%`;
        relevanceBar.title = `Relevance: ${relevancePercent.toFixed(0)}%`;
        relevanceTd.appendChild(relevanceBar);
        row.appendChild(relevanceTd);
        
        // Actions
        const actionsTd = document.createElement('td');
        const addBtn = document.createElement('button');
        addBtn.className = 'action-btn primary-btn';
        addBtn.title = 'Add to Database';
        addBtn.innerHTML = '<i class="fas fa-plus"></i>';
        addBtn.addEventListener('click', () => {
            // For now, just show a message
            showNotification('Add to database functionality would be implemented here', 'info');
        });
        actionsTd.appendChild(addBtn);
        row.appendChild(actionsTd);
        
        tbody.appendChild(row);
    });
}

/**
 * Discover RSS feeds
 */
async function discoverRssFeeds() {
    const scope = document.getElementById('rssDiscoveryScope')?.value;
    
    showLoading('Discovering RSS feeds...');
    
    try {
        let sourceIds = null;
        if (scope === 'selected' && selectedSources.size > 0) {
            sourceIds = Array.from(selectedSources);
        }
        
        const response = await fetch(`${API_BASE}/discover/rss`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                source_ids: sourceIds,
                timeout: 10
            })
        });
        
        const result = await response.json();
        
        // Show results
        const rssDiscoveryResults = document.getElementById('rssDiscoveryResults');
        const rssDiscoveryResultsInfo = document.getElementById('rssDiscoveryResultsInfo');
        
        if (rssDiscoveryResults) rssDiscoveryResults.style.display = 'block';
        if (rssDiscoveryResultsInfo) rssDiscoveryResultsInfo.textContent = 
            `${result.with_rss_found} RSS feeds discovered out of ${result.total_checked} checked`;
        
        renderRssDiscoveryTable(result.results);
        
        hideLoading();
        showNotification(result.message, 'success');
        
        // Reload sources to show updated RSS URLs
        const sourcesResponse = await fetch(`${API_BASE}/`);
        allSources = await sourcesResponse.json();
        renderSourcesTable(allSources);
        
    } catch (error) {
        hideLoading();
        showNotification(`Error discovering RSS feeds: ${error.message}`, 'error');
        console.error('Error discovering RSS feeds:', error);
    }
}

/**
 * Render RSS discovery table
 */
function renderRssDiscoveryTable(results) {
    const tbody = document.getElementById('rssDiscoveryTableBody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    results.forEach(result => {
        const row = document.createElement('tr');
        
        // Name
        const nameTd = document.createElement('td');
        nameTd.textContent = result.name || 'Unknown';
        row.appendChild(nameTd);
        
        // Domain
        const domainTd = document.createElement('td');
        domainTd.textContent = result.domain || 'Unknown';
        row.appendChild(domainTd);
        
        // Discovered RSS URL
        const rssTd = document.createElement('td');
        if (result.rss_url) {
            const rssLink = document.createElement('a');
            rssLink.href = result.rss_url;
            rssLink.textContent = result.rss_url.substring(0, 60) + (result.rss_url.length > 60 ? '...' : '');
            rssLink.target = '_blank';
            rssLink.title = result.rss_url;
            rssTd.appendChild(rssLink);
        } else {
            rssTd.textContent = 'None found';
        }
        row.appendChild(rssTd);
        
        // Status
        const statusTd = document.createElement('td');
        const statusSpan = document.createElement('span');
        statusSpan.className = `status-badge ${result.rss_url ? 'success' : 'warning'}`;
        statusSpan.textContent = result.rss_url ? 'Found' : 'Not found';
        statusTd.appendChild(statusSpan);
        row.appendChild(statusTd);
        
        tbody.appendChild(row);
    });
}

/**
 * Web search
 */
async function webSearch() {
    const query = document.getElementById('webSearchQuery')?.value.trim();
    const maxResults = parseInt(document.getElementById('webSearchMaxResults')?.value) || 10;
    
    if (!query) {
        showNotification('Please enter a search query', 'warning');
        return;
    }
    
    showLoading(`Searching web for "${query}"...`);
    
    try {
        // Use the discover topic endpoint for now
        const response = await fetch(`${API_BASE}/discover/topic`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                topic: query,
                max_sources: maxResults,
                region: 'wt-wt'
            })
        });
        
        const result = await response.json();
        
        // Show results
        const webSearchResults = document.getElementById('webSearchResults');
        const webSearchResultsInfo = document.getElementById('webSearchResultsInfo');
        
        if (webSearchResults) webSearchResults.style.display = 'block';
        if (webSearchResultsInfo) webSearchResultsInfo.textContent = `${result.count} results found`;
        
        renderWebSearchTable(result.sources);
        
        hideLoading();
        showNotification(result.message, 'success');
        
    } catch (error) {
        hideLoading();
        showNotification(`Error searching web: ${error.message}`, 'error');
        console.error('Error searching web:', error);
    }
}

/**
 * Render web search table
 */
function renderWebSearchTable(results) {
    const tbody = document.getElementById('webSearchTableBody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    results.forEach(result => {
        const row = document.createElement('tr');
        
        // Title
        const titleTd = document.createElement('td');
        titleTd.textContent = result.title || 'No title';
        row.appendChild(titleTd);
        
        // URL
        const urlTd = document.createElement('td');
        if (result.url) {
            const urlLink = document.createElement('a');
            urlLink.href = result.url;
            urlLink.textContent = result.url.substring(0, 60) + (result.url.length > 60 ? '...' : '');
            urlLink.target = '_blank';
            urlLink.title = result.url;
            urlTd.appendChild(urlLink);
        } else {
            urlTd.textContent = 'No URL';
        }
        row.appendChild(urlTd);
        
        // Domain
        const domainTd = document.createElement('td');
        domainTd.textContent = result.domain || 'Unknown';
        row.appendChild(domainTd);
        
        // Actions
        const actionsTd = document.createElement('td');
        const addBtn = document.createElement('button');
        addBtn.className = 'action-btn primary-btn';
        addBtn.title = 'Add as Source';
        addBtn.innerHTML = '<i class="fas fa-plus"></i>';
        addBtn.addEventListener('click', () => {
            // Create a source from the search result
            openSourceModal(null, {
                name: result.title,
                domain: result.domain,
                url: result.url
            });
        });
        actionsTd.appendChild(addBtn);
        row.appendChild(actionsTd);
        
        tbody.appendChild(row);
    });
}

/**
 * Load and update statistics
 */
async function loadStatistics() {
    showLoading('Loading statistics...');
    
    try {
        const response = await fetch(`${API_BASE}/stats`);
        const stats = await response.json();
        
        updateStatistics(stats);
        
        hideLoading();
        showNotification('Statistics updated', 'success');
        
    } catch (error) {
        hideLoading();
        showNotification(`Error loading statistics: ${error.message}`, 'error');
        console.error('Error loading statistics:', error);
    }
}

/**
 * Refresh tag-based groups
 */
async function refreshTagBasedGroups() {
    showLoading('Refreshing tag-based groups...');
    
    try {
        const response = await fetch(`${API_BASE}/groups/refresh-all`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        hideLoading();
        showNotification(result.message, 'success');
        
        // Reload groups
        const groupsResponse = await fetch(`${API_BASE}/groups/`);
        allGroups = await groupsResponse.json();
        renderGroupsTable(allGroups);
        
    } catch (error) {
        hideLoading();
        showNotification(`Error refreshing groups: ${error.message}`, 'error');
        console.error('Error refreshing groups:', error);
    }
}

/**
 * Remove source from group
 */
async function removeSourceFromGroup(sourceId, groupId) {
    if (!confirm('Are you sure you want to remove this source from the group?')) {
        return;
    }
    
    showLoading('Removing source from group...');
    
    try {
        const response = await fetch(`${API_BASE}/groups/${groupId}/sources`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_ids: [sourceId] })
        });
        
        const result = await response.json();
        
        hideLoading();
        showNotification(result.message, 'success');
        
        // Reload group details
        showGroupDetail(groupId);
        
    } catch (error) {
        hideLoading();
        showNotification(`Error removing source from group: ${error.message}`, 'error');
        console.error('Error removing source from group:', error);
    }
}

/**
 * Open source modal with prefill data
 */
function openSourceModal(sourceId = null, prefillData = null) {
    const modal = document.getElementById('sourceModal');
    const modalTitle = document.getElementById('sourceModalTitle');
    
    if (!modal || !modalTitle) return;
    
    if (sourceId) {
        // Edit mode
        modalTitle.textContent = 'Edit Source';
        showLoading('Loading source...');
        
        fetch(`${API_BASE}/${sourceId}`)
            .then(response => response.json())
            .then(source => {
                hideLoading();
                populateSourceForm(source);
                modal.style.display = 'flex';
            })
            .catch(error => {
                hideLoading();
                showNotification(`Error loading source: ${error.message}`, 'error');
                console.error('Error loading source:', error);
            });
    } else {
        // Add mode
        modalTitle.textContent = 'Add Source';
        
        if (prefillData) {
            populateSourceForm(prefillData);
        } else {
            resetSourceForm();
        }
        
        modal.style.display = 'flex';
    }
}

// Make functions available globally
window.openSourceModal = openSourceModal;
window.deleteSource = deleteSource;
window.openGroupModal = openGroupModal;
window.deleteGroup = deleteGroup;
