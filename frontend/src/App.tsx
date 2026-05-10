import React, { useState, useEffect } from 'react';
import { Box, Typography, Paper, CircularProgress, Alert, Grid, Card, CardContent } from '@mui/material';
import { Check as CheckIcon, Error as ErrorIcon, Info as InfoIcon } from '@mui/icons-material';

function App() {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'healthy' | 'unhealthy' | 'error'>('checking');
  const [apiInfo, setApiInfo] = useState<any>(null);

  useEffect(() => {
    // Check backend health
    fetch('http://localhost:8000/health')
      .then(response => response.json())
      .then(data => {
        setBackendStatus(data.status === 'healthy' ? 'healthy' : 'unhealthy');
        setAPIInfo(data);
      })
      .catch(error => {
        setBackendStatus('error');
      });
  }, []);

  const features = [
    {
      icon: '🔍',
      title: 'Keyword Extraction',
      description: 'Automatically extract important keywords from articles with relevance scoring and sentiment analysis.'
    },
    {
      icon: '🔗',
      title: 'Source Tracking',
      description: 'Detect and track all links/sources referenced in articles, building a citation network.'
    },
    {
      icon: '📊',
      title: 'Article Similarity',
      description: 'Find similar articles using multiple algorithms including TF-IDF, cosine similarity, and more.'
    },
    {
      icon: '📈',
      title: 'Temporal Analysis',
      description: 'Track relationships between article publication dates and source dates for investigative insights.'
    },
    {
      icon: '🎨',
      title: 'Customizable Dashboard',
      description: 'Drag-and-drop widgets with real-time updates and multiple visualization options.'
    },
    {
      icon: '💾',
      title: 'Local Storage',
      description: 'All data stored locally in SQLite database. No cloud dependencies, completely portable.'
    }
  ];

  const getStatusComponent = () => {
    switch (backendStatus) {
      case 'checking':
        return (
          <Alert icon={<CircularProgress size={20} />} severity="info">
            Checking backend connection...
          </Alert>
        );
      case 'healthy':
        return (
          <Alert icon={<CheckIcon />} severity="success">
            Backend is running and healthy
          </Alert>
        );
      case 'unhealthy':
        return (
          <Alert icon={<ErrorIcon />} severity="warning">
            Backend is running but unhealthy
          </Alert>
        );
      case 'error':
        return (
          <Alert icon={<ErrorIcon />} severity="error">
            Backend is not running. Please start the backend server.
          </Alert>
        );
      default:
        return null;
    }
  };

  return (
    <Box sx={{ 
      minHeight: '100vh', 
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      p: 3
    }}>
      <Paper sx={{ 
        maxWidth: 1000, 
        margin: '0 auto',
        p: 4,
        borderRadius: 2
      }}>
        <Typography variant="h3" component="h1" gutterBottom sx={{ textAlign: 'center' }}>
          🌐 Open-Omniscience
        </Typography>
        
        <Typography variant="h6" color="text.secondary" sx={{ textAlign: 'center', mb: 3 }}>
          Local Article Intelligence & Source Tracking System
        </Typography>

        {getStatusComponent()}

        <Grid container spacing={3} sx={{ mt: 3, mb: 4 }}>
          {features.map((feature, index) => (
            <Grid item xs={12} sm={6} md={4} key={index}>
              <Card>
                <CardContent>
                  <Typography variant="h5" component="h3" gutterBottom>
                    {feature.icon} {feature.title}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {feature.description}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>

        <Paper sx={{ p: 3, backgroundColor: 'background.default' }}>
          <Typography variant="subtitle1" gutterBottom>
            <InfoIcon color="primary" sx={{ verticalAlign: 'middle', mr: 1 }} />
            API Information
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Backend API is running at <code>http://localhost:8000</code>
          </Typography>
          <Typography variant="body2" color="text.secondary">
            API Documentation: <code>http://localhost:8000/api/docs</code>
          </Typography>
        </Paper>
      </Paper>
    </Box>
  );
}

export default App;
