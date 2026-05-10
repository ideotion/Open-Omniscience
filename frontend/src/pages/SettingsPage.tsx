import React, { useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  TextField,
  Button,
  Switch,
  FormControlLabel,
  Divider,
  Alert
} from '@mui/material';

const SettingsPage: React.FC = () => {
  const [settings, setSettings] = useState({
    backendUrl: 'http://localhost:8000',
    autoRefresh: true,
    refreshInterval: 30,
    theme: 'light',
    language: 'en',
  });
  const [saved, setSaved] = useState(false);

  const handleChange = (field: string, value: any) => {
    setSettings({ ...settings, [field]: value });
  };

  const handleSave = () => {
    // Save settings to localStorage
    localStorage.setItem('openOmniscienceSettings', JSON.stringify(settings));
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const handleReset = () => {
    setSettings({
      backendUrl: 'http://localhost:8000',
      autoRefresh: true,
      refreshInterval: 30,
      theme: 'light',
      language: 'en',
    });
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Settings
      </Typography>

      {saved && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Settings saved successfully!
        </Alert>
      )}

      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Backend Configuration
        </Typography>

        <Box sx={{ mb: 2 }}>
          <TextField
            fullWidth
            label="Backend URL"
            value={settings.backendUrl}
            onChange={(e) => handleChange('backendUrl', e.target.value)}
            variant="outlined"
          />
        </Box>

        <Divider sx={{ my: 2 }} />

        <Typography variant="h6" gutterBottom>
          Display Preferences
        </Typography>

        <Box sx={{ mb: 2 }}>
          <FormControlLabel
            control={
              <Switch
                checked={settings.autoRefresh}
                onChange={(e) => handleChange('autoRefresh', e.target.checked)}
              />
            }
            label="Auto-refresh data"
          />
        </Box>

        {settings.autoRefresh && (
          <Box sx={{ mb: 2 }}>
            <TextField
              fullWidth
              label="Refresh Interval (seconds)"
              type="number"
              value={settings.refreshInterval}
              onChange={(e) => handleChange('refreshInterval', parseInt(e.target.value) || 30)}
              variant="outlined"
              inputProps={{ min: 10, max: 300 }}
            />
          </Box>
        )}

        <Box sx={{ mb: 2 }}>
          <TextField
            fullWidth
            label="Language"
            value={settings.language}
            onChange={(e) => handleChange('language', e.target.value)}
            variant="outlined"
            select
            SelectProps={{
              native: true,
            }}
          >
            <option value="en">English</option>
            <option value="fr">French</option>
            <option value="de">German</option>
            <option value="es">Spanish</option>
          </TextField>
        </Box>

        <Box sx={{ mb: 2 }}>
          <TextField
            fullWidth
            label="Theme"
            value={settings.theme}
            onChange={(e) => handleChange('theme', e.target.value)}
            variant="outlined"
            select
            SelectProps={{
              native: true,
            }}
          >
            <option value="light">Light</option>
            <option value="dark">Dark</option>
            <option value="system">System</option>
          </TextField>
        </Box>

        <Divider sx={{ my: 2 }} />

        <Box sx={{ display: 'flex', gap: 2 }}>
          <Button variant="contained" color="primary" onClick={handleSave}>
            Save Settings
          </Button>
          <Button variant="outlined" color="secondary" onClick={handleReset}>
            Reset to Defaults
          </Button>
        </Box>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>
          About
        </Typography>
        <Typography variant="body1" paragraph>
          Open-Omniscience is a local article intelligence and source tracking system.
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Version: 1.0.0
        </Typography>
      </Paper>
    </Box>
  );
};

export default SettingsPage;
