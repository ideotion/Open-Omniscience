import React, { useState, useEffect } from 'react';
import {
  Grid,
  Paper,
  Typography,
  Box,
  CircularProgress,
  Alert,
  Card,
  CardContent,
  CardHeader
} from '@mui/material';
import { BarChart, LineChart, DoughnutChart } from '../components/charts';

interface StatCard {
  label: string;
  value: any;
  icon?: string;
  color?: string;
}

interface ChartData {
  labels: string[];
  datasets: Array<{
    label: string;
    data: number[];
    borderColor: string;
    backgroundColor: string;
  }>;
}

const DashboardPage: React.FC = () => {
  const [stats, setStats] = useState<StatCard[]>([]);
  const [articlesChart, setArticlesChart] = useState<ChartData | null>(null);
  const [keywordsChart, setKeywordsChart] = useState<ChartData | null>(null);
  const [sourcesChart, setSourcesChart] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Fetch stats
        const statsResponse = await fetch('http://localhost:8000/api/dashboard/stats');
        if (statsResponse.ok) {
          const statsData = await statsResponse.json();
          setStats(statsData);
        }

        // Fetch articles chart
        const articlesResponse = await fetch('http://localhost:8000/api/dashboard/charts/articles-over-time?days=30');
        if (articlesResponse.ok) {
          const data = await articlesResponse.json();
          setArticlesChart(data);
        }

        // Fetch keywords chart
        const keywordsResponse = await fetch('http://localhost:8000/api/dashboard/charts/top-keywords?top_n=10');
        if (keywordsResponse.ok) {
          const data = await keywordsResponse.json();
          setKeywordsChart(data);
        }

        // Fetch sources chart
        const sourcesResponse = await fetch('http://localhost:8000/api/dashboard/charts/source-types');
        if (sourcesResponse.ok) {
          const data = await sourcesResponse.json();
          setSourcesChart(data);
        }

      } catch (err) {
        setError('Failed to fetch dashboard data');
        console.error('Dashboard error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();

    // Refresh every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Dashboard
      </Typography>

      {/* Stats Cards */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        {stats.map((stat, index) => (
          <Grid item xs={12} sm={6} md={4} lg={2} key={index}>
            <Card>
              <CardContent>
                <Typography variant="h6" color="text.secondary" gutterBottom>
                  {stat.label}
                </Typography>
                <Typography variant="h4" component="div">
                  {stat.value}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Charts */}
      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Articles Over Time
            </Typography>
            {articlesChart ? (
              <LineChart data={articlesChart} height={300} />
            ) : (
              <Typography>No data available</Typography>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Top Keywords
            </Typography>
            {keywordsChart ? (
              <BarChart data={keywordsChart} height={300} />
            ) : (
              <Typography>No data available</Typography>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Source Types Distribution
            </Typography>
            {sourcesChart ? (
              <DoughnutChart data={sourcesChart} height={300} />
            ) : (
              <Typography>No data available</Typography>
            )}
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
};

export default DashboardPage;
