import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  CircularProgress,
  Alert,
  Chip
} from '@mui/material';
import { Search as SearchIcon } from '@mui/icons-material';

interface Source {
  id: string;
  url: string;
  domain: string;
  source_type: string;
  category: string;
  article_count: number;
}

const SourcesPage: React.FC = () => {
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    const fetchSources = async () => {
      try {
        setLoading(true);
        setError(null);

        const params = new URLSearchParams({ page: '1', per_page: '50' });
        if (search) {
          params.append('search', search);
        }

        const response = await fetch(`http://localhost:8000/api/sources/?${params}`);
        if (response.ok) {
          const data = await response.json();
          setSources(data);
        } else {
          setError('Failed to fetch sources');
        }
      } catch (err) {
        setError('Error fetching sources');
        console.error('Sources error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchSources();
  }, [search]);

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
        Sources
      </Typography>

      <Box sx={{ mb: 3 }}>
        <TextField
          fullWidth
          variant="outlined"
          placeholder="Search sources..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            endAdornment: <SearchIcon color="action" />,
          }}
        />
      </Box>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>URL</TableCell>
              <TableCell>Domain</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Category</TableCell>
              <TableCell>Articles</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sources.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} align="center">
                  No sources found
                </TableCell>
              </TableRow>
            ) : (
              sources.map((source) => (
                <TableRow key={source.id} hover>
                  <TableCell>
                    <a href={source.url} target="_blank" rel="noopener noreferrer">
                      {source.url.substring(0, 50)}...
                    </a>
                  </TableCell>
                  <TableCell>{source.domain}</TableCell>
                  <TableCell>
                    <Chip label={source.source_type} size="small" color="primary" />
                  </TableCell>
                  <TableCell>
                    <Chip label={source.category} size="small" color="secondary" />
                  </TableCell>
                  <TableCell>{source.article_count}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default SourcesPage;
