/**
 * Financial Component Styles for Pillar 5 - Financial Intelligence
 * 
 * CSS styles for all financial GUI components:
 * - Metric Explorer
 * - Correlation View
 * - Instrument Browser
 * - Financial Dashboard
 * 
 * These styles integrate with Open-Omniscience's existing CSS framework
 */

// Function to inject styles into the document
function injectFinancialStyles() {
    const styleId = 'pillar5-financial-styles';
    
    // Check if styles are already injected
    if (document.getElementById(styleId)) {
        return;
    }
    
    const styleElement = document.createElement('style');
    styleElement.id = styleId;
    styleElement.type = 'text/css';
    
    styleElement.textContent = `
        /* ============================================
           PILLAR 5 - FINANCIAL INTELLIGENCE STYLES
           ============================================ */
        
        /* Base Variables */
        :root {
            --p5-primary: #2563eb;
            --p5-secondary: #1e40af;
            --p5-success: #10b981;
            --p5-warning: #f59e0b;
            --p5-danger: #ef4444;
            --p5-info: #06b6d4;
            --p5-light: #f8fafc;
            --p5-dark: #0f172a;
            --p5-border: #e2e8f0;
            --p5-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
            --p5-shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
            --p5-radius: 8px;
            --p5-radius-sm: 4px;
            --p5-transition: all 0.2s ease;
        }
        
        /* ============================================
           FINANCIAL DASHBOARD
           ============================================ */
        
        .financial-dashboard {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
            color: var(--p5-dark);
        }
        
        .dashboard-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--p5-border);
            flex-wrap: wrap;
            gap: 20px;
        }
        
        .dashboard-logo h1 {
            margin: 0;
            font-size: 24px;
            font-weight: 700;
            color: var(--p5-primary);
        }
        
        .dashboard-logo p {
            margin: 5px 0 0 0;
            font-size: 14px;
            color: #64748b;
        }
        
        .dashboard-nav {
            flex: 1;
            min-width: 400px;
        }
        
        .nav-tabs {
            display: flex;
            list-style: none;
            margin: 0;
            padding: 0;
            gap: 5px;
            background: var(--p5-light);
            padding: 5px;
            border-radius: var(--p5-radius);
        }
        
        .nav-tab {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            cursor: pointer;
            border-radius: var(--p5-radius-sm);
            transition: var(--p5-transition);
            font-size: 14px;
            font-weight: 500;
            color: #64748b;
        }
        
        .nav-tab:hover {
            background: rgba(255, 255, 255, 0.5);
        }
        
        .nav-tab.active {
            background: white;
            color: var(--p5-primary);
            box-shadow: var(--p5-shadow);
        }
        
        .nav-tab .tab-icon {
            font-size: 16px;
        }
        
        .dashboard-actions {
            display: flex;
            gap: 10px;
        }
        
        .dashboard-actions button {
            padding: 10px 20px;
            border: 1px solid var(--p5-border);
            background: white;
            border-radius: var(--p5-radius-sm);
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: var(--p5-transition);
        }
        
        .dashboard-actions button:hover {
            background: var(--p5-light);
        }
        
        .dashboard-system-stats {
            margin-bottom: 20px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }
        
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: var(--p5-radius);
            box-shadow: var(--p5-shadow);
            border: 1px solid var(--p5-border);
        }
        
        .stat-card h4 {
            margin: 0 0 10px 0;
            font-size: 14px;
            font-weight: 600;
            color: #64748b;
        }
        
        .stat-card .stat-value {
            margin: 0 0 5px 0;
            font-size: 28px;
            font-weight: 700;
            color: var(--p5-primary);
        }
        
        .stat-card .stat-label {
            margin: 0;
            font-size: 12px;
            color: #94a3b8;
        }
        
        .dashboard-main-content {
            background: white;
            border-radius: var(--p5-radius);
            box-shadow: var(--p5-shadow);
            border: 1px solid var(--p5-border);
            overflow: hidden;
        }
        
        .tab-content {
            display: none;
            padding: 20px;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .tab-pane {
            height: 100%;
        }
        
        .dashboard-footer {
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid var(--p5-border);
            text-align: center;
            font-size: 12px;
            color: #94a3b8;
        }
        
        /* ============================================
           METRIC EXPLORER
           ============================================ */
        
        .metric-explorer {
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        
        .metric-explorer-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .metric-explorer-header h2 {
            margin: 0;
            font-size: 20px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .metric-explorer-controls {
            display: flex;
            gap: 15px;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .search-box {
            display: flex;
            align-items: center;
        }
        
        .search-box input {
            padding: 8px 12px;
            border: 1px solid var(--p5-border);
            border-radius: var(--p5-radius-sm) 0 0 var(--p5-radius-sm);
            font-size: 14px;
            min-width: 200px;
        }
        
        ..btn-search {
            padding: 8px 12px;
            border: 1px solid var(--p5-border);
            border-left: none;
            background: var(--p5-light);
            border-radius: 0 var(--p5-radius-sm) var(--p5-radius-sm) 0;
            cursor: pointer;
        }
        
        .metric-explorer-controls select {
            padding: 8px 12px;
            border: 1px solid var(--p5-border);
            border-radius: var(--p5-radius-sm);
            font-size: 14px;
            min-width: 150px;
        }
        
        .metric-explorer-layout {
            display: grid;
            grid-template-columns: 250px 1fr;
            gap: 20px;
            flex: 1;
            overflow: hidden;
        }
        
        .metric-groups-sidebar {
            background: var(--p5-light);
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
            overflow-y: auto;
        }
        
        .metric-groups-sidebar h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .metric-groups-list {
            list-style: none;
            margin: 0;
            padding: 0;
        }
        
        .metric-group-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 12px;
            margin-bottom: 5px;
            cursor: pointer;
            border-radius: var(--p5-radius-sm);
            transition: var(--p5-transition);
            font-size: 14px;
        }
        
        .metric-group-item:hover {
            background: rgba(255, 255, 255, 0.5);
        }
        
        .metric-group-item.active {
            background: white;
            box-shadow: var(--p5-shadow);
        }
        
        .group-color {
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }
        
        .metric-main-content {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            overflow-y: auto;
        }
        
        .metric-list-container {
            background: white;
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
        }
        
        .metric-list-container h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .metric-count {
            color: #64748b;
            font-weight: normal;
        }
        
        .metric-cards {
            display: grid;
            gap: 15px;
        }
        
        .metric-card {
            background: var(--p5-light);
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
            cursor: pointer;
            transition: var(--p5-transition);
        }
        
        .metric-card:hover {
            box-shadow: var(--p5-shadow-lg);
            transform: translateY(-2px);
        }
        
        .metric-card-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }
        
        .metric-group-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }
        
        .metric-card-header h4 {
            margin: 0;
            font-size: 14px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .metric-card-body {
            margin-bottom: 10px;
        }
        
        .metric-card-body p {
            margin: 5px 0;
            font-size: 13px;
            color: #64748b;
        }
        
        .metric-formula {
            font-family: 'Courier New', monospace;
            font-size: 12px;
            color: #94a3b8;
        }
        
        .metric-value {
            font-weight: 600;
            color: var(--p5-primary);
        }
        
        .metric-card-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 10px;
            border-top: 1px solid var(--p5-border);
        }
        
        .metric-use-case {
            font-size: 12px;
            color: #94a3b8;
        }
        
        .btn-view-details {
            padding: 5px 15px;
            background: var(--p5-primary);
            color: white;
            border: none;
            border-radius: var(--p5-radius-sm);
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            transition: var(--p5-transition);
        }
        
        .btn-view-details:hover {
            background: var(--p5-secondary);
        }
        
        .metric-visualization {
            background: white;
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
        }
        
        .metric-visualization h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .chart-container {
            height: 300px;
            margin-bottom: 15px;
            background: var(--p5-light);
            border-radius: var(--p5-radius-sm);
            padding: 15px;
        }
        
        .chart-container canvas {
            width: 100% !important;
            height: 100% !important;
        }
        
        .metric-details {
            background: var(--p5-light);
            padding: 15px;
            border-radius: var(--p5-radius-sm);
        }
        
        .metric-details h4 {
            margin: 0 0 10px 0;
            font-size: 14px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .metric-info {
            font-size: 13px;
        }
        
        .metric-info p {
            margin: 8px 0;
        }
        
        .metric-info strong {
            color: #64748b;
        }
        
        .metric-explorer-footer {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid var(--p5-border);
        }
        
        .metric-explorer-footer button {
            padding: 8px 16px;
            border: 1px solid var(--p5-border);
            background: white;
            border-radius: var(--p5-radius-sm);
            cursor: pointer;
            font-size: 14px;
            transition: var(--p5-transition);
        }
        
        .metric-explorer-footer button:hover:not(:disabled) {
            background: var(--p5-light);
        }
        
        .metric-explorer-footer button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        /* ============================================
           CORRELATION VIEW
           ============================================ */
        
        .correlation-view {
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        
        .correlation-view-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .correlation-view-header h2 {
            margin: 0;
            font-size: 20px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .correlation-view-controls {
            display: flex;
            gap: 15px;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .article-selector {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        
        .article-selector select {
            padding: 8px 12px;
            border: 1px solid var(--p5-border);
            border-radius: var(--p5-radius-sm);
            font-size: 14px;
            min-width: 250px;
        }
        
        .article-selector button {
            padding: 8px 16px;
            background: var(--p5-primary);
            color: white;
            border: none;
            border-radius: var(--p5-radius-sm);
            cursor: pointer;
            font-size: 14px;
            transition: var(--p5-transition);
        }
        
        .article-selector button:hover {
            background: var(--p5-secondary);
        }
        
        .score-filter {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .score-filter label {
            font-size: 14px;
            color: #64748b;
        }
        
        .score-slider {
            width: 150px;
        }
        
        ..score-value {
            font-weight: 600;
            color: var(--p5-primary);
        }
        
        .type-filter {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .type-filter label {
            font-size: 14px;
            color: #64748b;
        }
        
        .type-filter select {
            padding: 8px;
            border: 1px solid var(--p5-border);
            border-radius: var(--p5-radius-sm);
            font-size: 14px;
            height: 100px;
        }
        
        .correlation-view-layout {
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 20px;
            flex: 1;
            overflow: hidden;
        }
        
        .correlation-summary {
            background: var(--p5-light);
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
            overflow-y: auto;
        }
        
        .correlation-summary h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .summary-stats {
            display: grid;
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .summary-stats .stat-card {
            background: white;
            padding: 15px;
            border-radius: var(--p5-radius-sm);
            border: 1px solid var(--p5-border);
        }
        
        .summary-stats .stat-card h4 {
            margin: 0 0 5px 0;
            font-size: 12px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
        }
        
        .summary-stats .stat-card .stat-value {
            margin: 0;
            font-size: 20px;
            font-weight: 700;
            color: var(--p5-primary);
        }
        
        .weights-display {
            background: white;
            padding: 15px;
            border-radius: var(--p5-radius-sm);
            border: 1px solid var(--p5-border);
        }
        
        .weights-display h4 {
            margin: 0 0 15px 0;
            font-size: 14px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .weight-bars {
            display: grid;
            gap: 10px;
            margin-bottom: 10px;
        }
        
        .weight-bar {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .weight-label {
            width: 80px;
            font-size: 12px;
            font-weight: 500;
            color: #64748b;
        }
        
        .weight-bar-container {
            flex: 1;
            height: 8px;
            background: var(--p5-border);
            border-radius: 4px;
            overflow: hidden;
        }
        
        .weight-bar-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s ease;
        }
        
        .weight-value {
            width: 40px;
            text-align: right;
            font-size: 12px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .weight-formula {
            font-size: 11px;
            color: #94a3b8;
            margin: 0;
            line-height: 1.4;
        }
        
        .correlation-main-content {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            overflow-y: auto;
        }
        
        .correlation-list-container {
            background: white;
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
        }
        
        .correlation-list-container h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .correlation-count {
            color: #64748b;
            font-weight: normal;
        }
        
        .correlation-cards {
            display: grid;
            gap: 15px;
        }
        
        .correlation-card {
            background: var(--p5-light);
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
        }
        
        .correlation-card-header {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 15px;
        }
        
        .correlation-score-display {
            width: 60px;
            height: 60px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 700;
            font-size: 18px;
        }
        
        .correlation-score-display .score-value {
            font-size: 16px;
        }
        
        .correlation-card-header h4 {
            margin: 0;
            font-size: 14px;
            font-weight: 600;
            color: var(--p5-dark);
            flex: 1;
        }
        
        .correlation-card-body {
            font-size: 13px;
        }
        
        .correlation-card-body p {
            margin: 5px 0;
            color: #64748b;
        }
        
        .correlation-components {
            margin: 15px 0;
            padding: 15px;
            background: white;
            border-radius: var(--p5-radius-sm);
            border: 1px solid var(--p5-border);
        }
        
        .correlation-components h5 {
            margin: 0 0 10px 0;
            font-size: 12px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
        }
        
        .component-bars {
            display: grid;
            gap: 10px;
        }
        
        .component-bar {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .component-label {
            width: 80px;
            font-size: 12px;
            font-weight: 500;
            color: #64748b;
        }
        
        .component-bar-container {
            flex: 1;
            height: 8px;
            background: var(--p5-border);
            border-radius: 4px;
            overflow: hidden;
        }
        
        .component-bar-fill {
            height: 100%;
            border-radius: 4px;
        }
        
        .component-value {
            font-size: 11px;
            color: #94a3b8;
        }
        
        .total-score {
            margin: 10px 0 0 0;
            padding-top: 10px;
            border-top: 1px solid var(--p5-border);
            font-size: 14px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .matched-keywords, .matched-sectors {
            margin-top: 10px;
        }
        
        .matched-keywords h5, .matched-sectors h5 {
            margin: 0 0 8px 0;
            font-size: 12px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
        }
        
        .keyword-tags, .sector-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }
        
        .keyword-tag, .sector-tag {
            background: var(--p5-primary);
            color: white;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
        }
        
        .correlation-visualization {
            background: white;
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
        }
        
        .correlation-visualization h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .network-container {
            height: 400px;
            background: var(--p5-light);
            border-radius: var(--p5-radius-sm);
            padding: 15px;
        }
        
        .correlation-network {
            width: 100%;
            height: 100%;
        }
        
        .correlation-view-footer {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid var(--p5-border);
        }
        
        .correlation-view-footer button {
            padding: 8px 16px;
            border: 1px solid var(--p5-border);
            background: white;
            border-radius: var(--p5-radius-sm);
            cursor: pointer;
            font-size: 14px;
            transition: var(--p5-transition);
        }
        
        .correlation-view-footer button:hover:not(:disabled) {
            background: var(--p5-light);
        }
        
        .correlation-view-footer button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        /* ============================================
           INSTRUMENT BROWSER
           ============================================ */
        
        .instrument-browser {
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        
        .instrument-browser-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .instrument-browser-header h2 {
            margin: 0;
            font-size: 20px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .instrument-browser-controls {
            display: flex;
            gap: 15px;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .instrument-browser-controls select {
            padding: 8px 12px;
            border: 1px solid var(--p5-border);
            border-radius: var(--p5-radius-sm);
            font-size: 14px;
        }
        
        .instrument-browser-controls .type-filter {
            height: 100px;
        }
        
        .instrument-browser-layout {
            display: grid;
            grid-template-columns: 250px 1fr;
            gap: 20px;
            flex: 1;
            overflow: hidden;
        }
        
        .instrument-types-sidebar {
            background: var(--p5-light);
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
            overflow-y: auto;
        }
        
        .instrument-types-sidebar h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .type-list {
            list-style: none;
            margin: 0;
            padding: 0;
        }
        
        .type-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 12px;
            margin-bottom: 5px;
            cursor: pointer;
            border-radius: var(--p5-radius-sm);
            transition: var(--p5-transition);
            font-size: 14px;
        }
        
        .type-item:hover {
            background: rgba(255, 255, 255, 0.5);
        }
        
        .type-item.active {
            background: white;
            box-shadow: var(--p5-shadow);
        }
        
        .type-color {
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }
        
        .type-name {
            flex: 1;
        }
        
        .type-count {
            color: #64748b;
            font-size: 12px;
        }
        
        .quick-stats {
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid var(--p5-border);
        }
        
        .quick-stats h4 {
            margin: 0 0 10px 0;
            font-size: 14px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .stat-row {
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            font-size: 13px;
        }
        
        .stat-row span:first-child {
            color: #64748b;
        }
        
        .stat-row .stat-value {
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .instrument-main-content {
            display: grid;
            grid-template-columns: 1fr 350px;
            gap: 20px;
            overflow-y: auto;
        }
        
        .instrument-list-container {
            background: white;
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
        }
        
        .instrument-list-container h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .instrument-count {
            color: #64748b;
            font-weight: normal;
        }
        
        .instrument-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .instrument-table th {
            text-align: left;
            padding: 10px;
            background: var(--p5-light);
            font-size: 12px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            cursor: pointer;
            user-select: none;
            transition: var(--p5-transition);
        }
        
        .instrument-table th:hover {
            background: var(--p5-border);
        }
        
        .instrument-table td {
            padding: 12px 10px;
            border-bottom: 1px solid var(--p5-border);
            font-size: 13px;
        }
        
        .instrument-table tr:last-child td {
            border-bottom: none;
        }
        
        .instrument-table tr:hover td {
            background: var(--p5-light);
        }
        
        .type-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            color: white;
        }
        
        .col-symbol {
            font-weight: 600;
            color: var(--p5-primary);
        }
        
        .col-price {
            font-weight: 600;
        }
        
        .col-volume, .col-market-cap {
            color: #64748b;
        }
        
        .col-actions {
            white-space: nowrap;
        }
        
        .col-actions button {
            padding: 5px 12px;
            background: var(--p5-primary);
            color: white;
            border: none;
            border-radius: var(--p5-radius-sm);
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            transition: var(--p5-transition);
        }
        
        .col-actions button:hover {
            background: var(--p5-secondary);
        }
        
        .pagination-controls {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid var(--p5-border);
        }
        
        .pagination-controls button {
            padding: 5px 10px;
            border: 1px solid var(--p5-border);
            background: white;
            border-radius: var(--p5-radius-sm);
            cursor: pointer;
            font-size: 14px;
            transition: var(--p5-transition);
        }
        
        .pagination-controls button:hover:not(:disabled) {
            background: var(--p5-light);
        }
        
        .pagination-controls button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .page-info {
            font-size: 13px;
            color: #64748b;
        }
        
        .items-per-page {
            padding: 5px;
            border: 1px solid var(--p5-border);
            border-radius: var(--p5-radius-sm);
            font-size: 13px;
        }
        
        .instrument-details-panel {
            background: white;
            padding: 15px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
            overflow-y: auto;
        }
        
        .instrument-details-panel h3 {
            margin: 0 0 15px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .instrument-details {
            font-size: 13px;
        }
        
        .instrument-details p {
            margin: 8px 0;
        }
        
        .instrument-details strong {
            color: #64748b;
        }
        
        .detail-section {
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid var(--p5-border);
        }
        
        .detail-section h4 {
            margin: 0 0 10px 0;
            font-size: 14px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .fundamentals-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        
        .fundamental-item {
            display: flex;
            justify-content: space-between;
            padding: 8px;
            background: var(--p5-light);
            border-radius: var(--p5-radius-sm);
        }
        
        .fundamental-label {
            color: #64748b;
            font-size: 12px;
        }
        
        .fundamental-value {
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .detail-description {
            line-height: 1.5;
            color: #64748b;
        }
        
        .detail-keywords {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }
        
        .instrument-browser-footer {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid var(--p5-border);
        }
        
        .instrument-browser-footer button {
            padding: 8px 16px;
            border: 1px solid var(--p5-border);
            background: white;
            border-radius: var(--p5-radius-sm);
            cursor: pointer;
            font-size: 14px;
            transition: var(--p5-transition);
        }
        
        .instrument-browser-footer button:hover:not(:disabled) {
            background: var(--p5-light);
        }
        
        .instrument-browser-footer button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        /* ============================================
           ANALYTICS PANE
           ============================================ */
        
        .analytics-pane {
            padding: 20px;
        }
        
        .analytics-pane h2 {
            margin: 0 0 10px 0;
            font-size: 20px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .analytics-pane p {
            color: #64748b;
            margin-bottom: 20px;
        }
        
        .analytics-features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
        }
        
        .feature-card {
            background: var(--p5-light);
            padding: 20px;
            border-radius: var(--p5-radius);
            border: 1px solid var(--p5-border);
            transition: var(--p5-transition);
        }
        
        .feature-card:hover {
            box-shadow: var(--p5-shadow-lg);
            transform: translateY(-2px);
        }
        
        .feature-card h3 {
            margin: 0 0 10px 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--p5-dark);
        }
        
        .feature-card p {
            margin: 0;
            color: #64748b;
            font-size: 14px;
        }
        
        /* ============================================
           RESPONSIVE DESIGN
           ============================================ */
        
        @media (max-width: 1200px) {
            .metric-explorer-layout,
            .correlation-view-layout,
            .instrument-browser-layout {
                grid-template-columns: 1fr;
            }
            
            .metric-main-content,
            .correlation-main-content,
            .instrument-main-content {
                grid-template-columns: 1fr;
            }
        }
        
        @media (max-width: 768px) {
            .financial-dashboard {
                padding: 10px;
            }
            
            .dashboard-header {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .nav-tabs {
                width: 100%;
                overflow-x: auto;
            }
            
            .nav-tab {
                white-space: nowrap;
            }
            
            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            
            .instrument-browser-controls {
                flex-direction: column;
                align-items: stretch;
            }
            
            .instrument-browser-controls select {
                width: 100%;
            }
            
            .fundamentals-grid {
                grid-template-columns: 1fr;
            }
        }
        
        /* ============================================
           UTILITY CLASSES
           ============================================ */
        
        .no-metrics,
        .no-correlations,
        .no-instruments {
            text-align: center;
            padding: 40px 20px;
            color: #94a3b8;
            font-size: 14px;
        }
        
        .loading-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        
        /* Animation for score displays */
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.05); }
            100% { transform: scale(1); }
        }
        
        .correlation-score-display {
            animation: pulse 2s ease-in-out infinite;
        }
    `;
    
    document.head.appendChild(styleElement);
}

// Auto-inject styles when DOM is ready
if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectFinancialStyles);
    } else {
        injectFinancialStyles();
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { injectFinancialStyles };
}
