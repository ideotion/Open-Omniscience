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
  Button,
  CircularProgress,
  Alert,
  Chip,
  MenuItem,
  Select,
  FormControl,
  InputLabel
} from '@mui/material';

interface SimilarArticle {
  article_id: string;
  title: string;
  similarity_score: number;
  published_date: string;
}

interface SimilarityResult {
  article_id: string;
  similar_articles: SimilarArticle[];
}

const SimilarityPage: React.FC = () => {
  const [articles, setArticles] = useState<any[]>([]);
  const [selectedArticle, setSelectedArticle] = useState<string>('');
  const [similarArticles, setSimilarArticles] = useState<SimilarArticle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [method, setMethod] = useState<string>('cosine');
  const [topN, setTopN] = useState<number>(5);

  useEffect(() => {
    const fetchArticles = async () => {
      try {
        setLoading(true);
        const response = await fetch('http://localhost:8000/api/articles/?page=1&per_page=50');
        if (response.ok) {
          const data = await response.json();
          setArticles(data.articles);
          if (data.articles.length > 0) {
            setSelectedArticle(data.articles[0].id);
          }
        }
      } catch (err) {
        setError('Failed to fetch articles');
      } finally {
        setLoading(false);
      }
    };

    fetchArticles();
  }, []);

  useEffect(() => {
    if (selectedArticle) {
      const fetchSimilar = async () => {
        try {
          setLoading(true);
          setError(null);

          const response = await fetch(
            `http://localhost:8000/api/similarity/${selectedArticle}/similar?top_n=${topN}&method=${method}`
          );
          if (response.ok) {
            const data = await response.json();
            setSimilarArticles(data.similar_articles);
          } else {
            setError('Failed to fetch similar articles');
          }
        } catch (err) {
          setError('Error fetching similar articles');
          console.error('Similarity error:', err);
        } finally {
          setLoading(false);
        }
      };

      fetchSimilar();
    }
  }, [selectedArticle, method, topN]);

  const handleFindSimilar = () => {
    // Trigger re-fetch by changing state
    if (selectedArticle) {
      // Force re-fetch
      const temp = selectedArticle;
      setSelectedArticle('');
      setTimeout(() => setSelectedArticle(temp), 100);
    }
  };

  if (loading && articles.length === 0) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Article Similarity
      </Typography>

      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Find Similar Articles
        </Typography>

        <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
          <FormControl sx={{ minWidth: 300 }}>
            <InputLabel>Select Article</InputLabel>
            <Select
              value={selectedArticle}
              onChange={(e) => setSelectedArticle(e.target.value)}
              label="Select Article"
            >
              {articles.map((article) => (
                <MenuItem key={article.id} value={article.id}>
                  {article.title}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl sx={{ minWidth: 150 }}>
            <InputLabel>Method</InputLabel>
            <Select
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              label="Method"
            >
              <MenuItem value="cosine">Cosine</MenuItem>
              <MenuItem value="jaccard">Jaccard</MenuItem>
              <MenuItem value="tfidf">TF-IDF</MenuItem>
            </Select>
          </FormControl>

          <TextField
            label="Top N"
            type="number"
            value={topN}
            onChange={(e) => setTopN(parseInt(e.target.value) || 5)}
            inputProps={{ min: 1, max: 20 }}
            sx={{ width: 100 }}
          />

          <Button
            variant="contained"
            onClick={handleFindSimilar}
            disabled={loading}
            sx={{ alignSelf: 'flex-end' }}
          >
            {loading ? <CircularProgress size={24} /> : 'Find Similar'}
          </Button>
        </Box>

        {error && <Alert severity="error">{error}</Alert>}
      </Paper>

      {similarArticles.length > 0 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Similar Articles (using {method} similarity)
          </Typography>

          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Rank</TableCell>
                  <TableCell>Title</TableCell>
                  <TableCell>Similarity Score</TableCell>
                  <TableCell>Date</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {similarArticles.map((article, index) => (
                  <TableRow key={article.article_id} hover>
                    <TableCell>{index + 1}</TableCell>
                    <TableCell>{article.title}</TableCell>
                    <TableCell>
                      <Chip
                        label={(article.similarity_score * 100).toFixed(1) + '%'}
                        color={article.similarity_score > 0.7 ? 'success' : article.similarity_score > 0.4 ? 'warning' : 'default'}
                      />
                    </TableCell>
                    <TableCell>{article.published_date || 'N/A'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {similarArticles.length === 0 && !loading && (
        <Alert severity="info">No similar articles found</Alert>
      )}
    </Box>
  );
};

export default SimilarityPage;
