"""
Export Service for Open-Omniscience
Exports data to CSV, JSON, and other formats
"""

import csv
import json
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from datetime import datetime


class ExportService:
    """
    Exports data to various formats.
    """
    
    def __init__(self, export_dir: str = '/workspace/open-omniscience/data/exports'):
        """
        Initialize the export service.
        
        Args:
            export_dir: Directory for exported files
        """
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
    
    def export_to_csv(self, data: List[Dict[str, Any]], filename: str, 
                     include_header: bool = True) -> Path:
        """
        Export data to CSV file.
        
        Args:
            data: List of dictionaries to export
            filename: Output filename (without extension)
            include_header: Whether to include header row (default: True)
            
        Returns:
            Path to exported file
        """
        if not data:
            return None
        
        # Add .csv extension if not present
        if not filename.endswith('.csv'):
            filename += '.csv'
        
        filepath = self.export_dir / filename
        
        # Get all fieldnames from first item
        fieldnames = list(data[0].keys()) if data else []
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                if include_header:
                    writer.writeheader()
                
                for row in data:
                    # Ensure all fieldnames are present
                    row_data = {field: row.get(field, '') for field in fieldnames}
                    writer.writerow(row_data)
            
            return filepath
        except Exception as e:
            raise Exception(f"Failed to export CSV: {str(e)}")
    
    def export_to_json(self, data: Any, filename: str, indent: int = 2) -> Path:
        """
        Export data to JSON file.
        
        Args:
            data: Data to export (list, dict, etc.)
            filename: Output filename (without extension)
            indent: JSON indentation (default: 2)
            
        Returns:
            Path to exported file
        """
        if data is None:
            return None
        
        # Add .json extension if not present
        if not filename.endswith('.json'):
            filename += '.json'
        
        filepath = self.export_dir / filename
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
            
            return filepath
        except Exception as e:
            raise Exception(f"Failed to export JSON: {str(e)}")
    
    def export_keywords_to_csv(self, keywords_data: List[Dict], filename: str) -> Path:
        """
        Export keyword data to CSV with specific format.
        
        Args:
            keywords_data: List of keyword dictionaries
            filename: Output filename
            
        Returns:
            Path to exported file
        """
        if not keywords_data:
            return None
        
        # Prepare data for CSV
        csv_data = []
        for item in keywords_data:
            row = {
                'keyword': item.get('keyword', ''),
                'score': item.get('score', 0),
                'frequency': item.get('frequency', 0),
                'article_count': item.get('article_count', 0),
                'first_appearance': item.get('first_appearance', ''),
                'last_appearance': item.get('last_appearance', ''),
            }
            csv_data.append(row)
        
        return self.export_to_csv(csv_data, filename)
    
    def export_articles_to_csv(self, articles: List[Dict], filename: str) -> Path:
        """
        Export article data to CSV.
        
        Args:
            articles: List of article dictionaries
            filename: Output filename
            
        Returns:
            Path to exported file
        """
        if not articles:
            return None
        
        # Prepare data for CSV
        csv_data = []
        for article in articles:
            row = {
                'id': article.get('id', ''),
                'title': article.get('title', ''),
                'url': article.get('url', ''),
                'published_date': article.get('published_date', ''),
                'author': article.get('author', ''),
                'word_count': article.get('word_count', 0),
                'source_count': article.get('source_count', 0),
            }
            csv_data.append(row)
        
        return self.export_to_csv(csv_data, filename)
    
    def export_sources_to_csv(self, sources: List[Dict], filename: str) -> Path:
        """
        Export source data to CSV.
        
        Args:
            sources: List of source dictionaries
            filename: Output filename
            
        Returns:
            Path to exported file
        """
        if not sources:
            return None
        
        # Prepare data for CSV
        csv_data = []
        for source in sources:
            row = {
                'url': source.get('url', ''),
                'domain': source.get('domain', ''),
                'type': source.get('type', ''),
                'category': source.get('category', ''),
                'article_count': source.get('article_count', 0),
                'first_referenced': source.get('first_referenced', ''),
                'last_referenced': source.get('last_referenced', ''),
            }
            csv_data.append(row)
        
        return self.export_to_csv(csv_data, filename)
    
    def export_similarity_matrix(self, matrix: List[List[float]], 
                                 labels: List[str], filename: str) -> Path:
        """
        Export similarity matrix to CSV.
        
        Args:
            matrix: Similarity matrix (2D list)
            labels: Labels for rows/columns
            filename: Output filename
            
        Returns:
            Path to exported file
        """
        if not matrix or not labels:
            return None
        
        # Prepare data for CSV
        csv_data = []
        
        # Add header row
        header = [''] + labels
        csv_data.append(dict(zip(header, header)))
        
        # Add matrix rows
        for i, row in enumerate(matrix):
            row_data = {'': labels[i] if i < len(labels) else f'item_{i}'}
            for j, value in enumerate(row):
                row_data[labels[j] if j < len(labels) else f'item_{j}'] = value
            csv_data.append(row_data)
        
        return self.export_to_csv(csv_data, filename)
    
    def export_report(self, report_data: Dict, filename: str) -> Dict[str, Path]:
        """
        Export a comprehensive report to multiple formats.
        
        Args:
            report_data: Report data dictionary
            filename: Base filename (without extension)
            
        Returns:
            Dictionary with paths to exported files
        """
        exported_files = {}
        
        # Export to JSON
        json_path = self.export_to_json(report_data, filename)
        if json_path:
            exported_files['json'] = json_path
        
        # Export summary to CSV if available
        if 'summary' in report_data:
            csv_path = self.export_to_csv([report_data['summary']], f"{filename}_summary")
            if csv_path:
                exported_files['csv_summary'] = csv_path
        
        return exported_files


# Global instance
export_service = ExportService()
