import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, Navigate } from 'react-router-dom';
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  IconButton,
  Container,
  CssBaseline,
  ThemeProvider,
  createTheme
} from '@mui/material';
import {
  Menu as MenuIcon,
  Dashboard as DashboardIcon,
  Article as ArticleIcon,
  Search as SearchIcon,
  Analytics as AnalyticsIcon,
  Share as ShareIcon,
  Settings as SettingsIcon,
  BarChart as BarChartIcon,
  Timeline as TimelineIcon
} from '@mui/icons-material';

// Import pages
import DashboardPage from './pages/DashboardPage';
import ArticlesPage from './pages/ArticlesPage';
import KeywordsPage from './pages/KeywordsPage';
import SourcesPage from './pages/SourcesPage';
import SimilarityPage from './pages/SimilarityPage';
import SettingsPage from './pages/SettingsPage';

const drawerWidth = 240;

const theme = createTheme({
  palette: {
    primary: {
      main: '#1976d2',
    },
    secondary: {
      main: '#9c27b0',
    },
    background: {
      default: '#f5f5f5',
    },
  },
});

interface NavItem {
  text: string;
  path: string;
  icon: React.ReactNode;
}

const navItems: NavItem[] = [
  { text: 'Dashboard', path: '/', icon: <DashboardIcon /> },
  { text: 'Articles', path: '/articles', icon: <ArticleIcon /> },
  { text: 'Keywords', path: '/keywords', icon: <SearchIcon /> },
  { text: 'Sources', path: '/sources', icon: <ShareIcon /> },
  { text: 'Similarity', path: '/similarity', icon: <AnalyticsIcon /> },
  { text: 'Timeline', path: '/timeline', icon: <TimelineIcon /> },
  { text: 'Statistics', path: '/stats', icon: <BarChartIcon /> },
  { text: 'Settings', path: '/settings', icon: <SettingsIcon /> },
];

function App() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [backendStatus, setBackendStatus] = useState<string>('checking...');

  // Check backend health
  useEffect(() => {
    const checkBackend = async () => {
      try {
        const response = await fetch('http://localhost:8000/health');
        if (response.ok) {
          const data = await response.json();
          setBackendStatus(`✓ Backend: ${data.status}`);
        } else {
          setBackendStatus('✗ Backend not responding');
        }
      } catch (error) {
        setBackendStatus('✗ Backend not available');
      }
    };

    checkBackend();
    const interval = setInterval(checkBackend, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const drawer = (
    <div>
      <Toolbar />
      <List>
        {navItems.map((item) => (
          <ListItem key={item.text} disablePadding>
            <ListItemButton component={Link} to={item.path}>
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.text} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
    </div>
  );

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Router>
        <Box sx={{ display: 'flex' }}>
          <AppBar
            position="fixed"
            sx={{
              width: { sm: `calc(100% - ${drawerWidth}px)` },
              ml: { sm: `${drawerWidth}px` },
            }}
          >
            <Toolbar>
              <IconButton
                color="inherit"
                aria-label="open drawer"
                edge="start"
                onClick={handleDrawerToggle}
                sx={{ mr: 2, display: { sm: 'none' } }}
              >
                <MenuIcon />
              </IconButton>
              <Typography variant="h6" noWrap component="div">
                Open-Omniscience
              </Typography>
              <Box sx={{ flexGrow: 1 }} />
              <Typography variant="caption" color="inherit">
                {backendStatus}
              </Typography>
            </Toolbar>
          </AppBar>
          <Box
            component="nav"
            sx={{ width: { sm: drawerWidth }, flexShrink: { sm: 0 } }}
            aria-label="mailbox folders"
          >
            <Drawer
              variant="temporary"
              open={mobileOpen}
              onClose={handleDrawerToggle}
              ModalProps={{
                keepMounted: true,
              }}
              sx={{
                display: { xs: 'block', sm: 'none' },
                '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth },
              }}
            >
              {drawer}
            </Drawer>
            <Drawer
              variant="permanent"
              sx={{
                display: { xs: 'none', sm: 'block' },
                '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth },
              }}
              open
            >
              {drawer}
            </Drawer>
          </Box>
          <Box
            component="main"
            sx={{
              flexGrow: 1,
              p: 3,
              width: { sm: `calc(100% - ${drawerWidth}px)` },
            }}
          >
            <Toolbar />
            <Container maxWidth="xl">
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/articles" element={<ArticlesPage />} />
                <Route path="/keywords" element={<KeywordsPage />} />
                <Route path="/sources" element={<SourcesPage />} />
                <Route path="/similarity" element={<SimilarityPage />} />
                <Route path="/timeline" element={<DashboardPage />} />
                <Route path="/stats" element={<DashboardPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Container>
          </Box>
        </Box>
      </Router>
    </ThemeProvider>
  );
}

export default App;
