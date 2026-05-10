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
  Chip,
  IconButton
} from '@mui/material';
import { Search as SearchIcon } from '@mui/icons-material';

interface Keyword {
  id: string;
  name: string;
  article_count: number;
  total_appearances: number;
  avg_relevance: number;
}

const KeywordsPage: React.FC = () => {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    const fetchKeywords = async () => {
      try {
        setLoading(true);
        setError(null);

        const params = new URLSearchParams({ page: '1', per_page: '50' });
        if (search) {
          params.append('search', search);
        }

        const response = await fetch(`http://localhost:8000/api/keywords/?${params}`);
        if (response.ok) {
          const data = await response.json();
          setKeywords(data);
        } else {
          setError('Failed to fetch keywords');
        }
      } catch (err) {
        setError('Error fetching keywords');
        console.error('Keywords error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchKeywords();
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
        Keywords
      </Typography>

      <Box sx={{ mb: 3 }}>
        <TextField
          fullWidth
          variant="outlined"
          placeholder="Search keywords..."
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
              <TableCell>Keyword</TableCell>
              <TableCell>Articles</TableCell>
              <TableCell>Total Appearances</TableCell>
              <TableCell>Avg Relevance</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {keywords.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} align="center">
                  No keywords found
                </TableCell>
              </TableRow>
            ) : (
              keywords.map((keyword) => (
                <TableRow key={keyword.id} hover>
                  <TableCell>
                    <Chip label={keyword.name} size="medium" />
                  </TableCell>
                  <TableCell>{keyword.article_count}</TableCell>
                  <TableCell>{keyword.total_appearances}</TableCell>
                  <TableCell>{keyword.avg_relevance.toFixed(3)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default KeywordsPage;
