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
  Button,
  TextField,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  CircularProgress,
  Alert,
  Chip
} from '@mui/material';
import { Add as AddIcon, Edit as EditIcon, Delete as DeleteIcon, Search as SearchIcon } from '@mui/icons-material';

interface Article {
  id: string;
  title: string;
  content: string;
  url: string;
  author: string;
  published_date: string;
  word_count: number;
  keyword_count: number;
  source_count: number;
}

const ArticlesPage: React.FC = () => {
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    const fetchArticles = async () => {
      try {
        setLoading(true);
        setError(null);

        const params = new URLSearchParams({
          page: page.toString(),
          per_page: '20',
        });

        if (search) {
          params.append('search', search);
        }

        const response = await fetch(`http://localhost:8000/api/articles/?${params}`);
        if (response.ok) {
          const data = await response.json();
          setArticles(data.articles);
          setTotal(data.total);
        } else {
          setError('Failed to fetch articles');
        }
      } catch (err) {
        setError('Error fetching articles');
        console.error('Articles error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchArticles();
  }, [page, search]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
  };

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
        Articles
      </Typography>

      <Box sx={{ mb: 3, display: 'flex', gap: 2 }}>
        <TextField
          fullWidth
          variant="outlined"
          placeholder="Search articles..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onSubmit={handleSearch}
          InputProps={{
            endAdornment: (
              <IconButton type="submit" onClick={handleSearch}>
                <SearchIcon />
              </IconButton>
            ),
          }}
        />
        <Button variant="contained" startIcon={<AddIcon />}>
          Add Article
        </Button>
      </Box>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Title</TableCell>
              <TableCell>Author</TableCell>
              <TableCell>Date</TableCell>
              <TableCell>Words</TableCell>
              <TableCell>Keywords</TableCell>
              <TableCell>Sources</TableCell>
              <TableCell>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {articles.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} align="center">
                  No articles found
                </TableCell>
              </TableRow>
            ) : (
              articles.map((article) => (
                <TableRow key={article.id} hover>
                  <TableCell>
                    <Typography variant="body2">{article.title}</Typography>
                  </TableCell>
                  <TableCell>{article.author || 'Unknown'}</TableCell>
                  <TableCell>{article.published_date || 'N/A'}</TableCell>
                  <TableCell>{article.word_count}</TableCell>
                  <TableCell>
                    <Chip label={article.keyword_count} size="small" color="primary" />
                  </TableCell>
                  <TableCell>
                    <Chip label={article.source_count} size="small" color="secondary" />
                  </TableCell>
                  <TableCell>
                    <IconButton size="small"><EditIcon fontSize="small" /></IconButton>
                    <IconButton size="small" color="error"><DeleteIcon fontSize="small" /></IconButton>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {total > 20 && (
        <Box sx={{ mt: 2, display: 'flex', justifyContent: 'center' }}>
          <Typography>
            Page {page} of {Math.ceil(total / 20)}
          </Typography>
        </Box>
      )}
    </Box>
  );
};

export default ArticlesPage;
