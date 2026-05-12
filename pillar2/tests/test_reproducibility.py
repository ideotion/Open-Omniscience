"""Tests for reproducibility.py module - Phase 2.3"""
import pytest
from src.analysis.reproducibility import (
    ReproducibilityCalculator,
    ReproducibilityScore,
    DataLineageTracker,
    DataLineage,
    DataSourceType
)


class TestReproducibilityCalculator:
    def test_initialization(self):
        calculator = ReproducibilityCalculator()
        assert calculator.lineage_tracker is not None
    
    def test_calculate_score_all_true(self):
        calculator = ReproducibilityCalculator()
        score = calculator.calculate_score(
            data_available=True,
            methods_described=True,
            code_available=True,
            documentation_complete=True
        )
        assert score.overall_score == 100.0
        assert score.grade == "A+"
        assert len(score.issues) == 0
    
    def test_calculate_score_all_false(self):
        calculator = ReproducibilityCalculator()
        score = calculator.calculate_score(
            data_available=False,
            methods_described=False,
            code_available=False,
            documentation_complete=False
        )
        assert score.overall_score == 0.0
        assert score.grade == "F"
        assert len(score.issues) == 4
    
    def test_calculate_score_partial(self):
        calculator = ReproducibilityCalculator()
        score = calculator.calculate_score(
            data_available=True,
            methods_described=True,
            code_available=False,
            documentation_complete=True
        )
        assert score.overall_score == 75.0
        assert score.data_availability == 100.0
        assert score.code_availability == 0.0
        assert len(score.issues) == 1
    
    def test_score_to_grade(self):
        calculator = ReproducibilityCalculator()
        assert calculator._score_to_grade(95) == "A+"
        assert calculator._score_to_grade(85) == "A"
        assert calculator._score_to_grade(75) == "B"
        assert calculator._score_to_grade(65) == "C"
        assert calculator._score_to_grade(55) == "D"
        assert calculator._score_to_grade(45) == "F"
    
    def test_generate_report(self):
        calculator = ReproducibilityCalculator()
        score = calculator.calculate_score(
            data_available=True,
            methods_described=True,
            code_available=True,
            documentation_complete=True
        )
        report = calculator.generate_report(score)
        assert "# Reproducibility Report" in report
        assert "100.0/100" in report
        assert "A+" in report
    
    def test_generate_report_with_issues(self):
        calculator = ReproducibilityCalculator()
        score = calculator.calculate_score(
            data_available=False,
            methods_described=True,
            code_available=True,
            documentation_complete=True
        )
        report = calculator.generate_report(score)
        assert "Data not available" in report


class TestDataLineageTracker:
    def test_initialization(self):
        tracker = DataLineageTracker()
        assert len(tracker.lineage_records) == 0
    
    def test_add_source(self):
        tracker = DataLineageTracker()
        lineage = tracker.add_source(
            source="test_data.csv",
            data=[1, 2, 3, 4, 5],
            source_type=DataSourceType.RAW,
            processing_steps=["loaded"],
            metadata={"format": "csv"}
        )
        assert lineage.source == "test_data.csv"
        assert lineage.source_type == DataSourceType.RAW
        assert lineage.data_hash is not None
        assert len(tracker.lineage_records) == 1
    
    def test_add_processing_step(self):
        tracker = DataLineageTracker()
        source_lineage = tracker.add_source(
            source="raw_data.csv",
            data=[1, 2, 3]
        )
        
        processed_lineage = tracker.add_processing_step(
            input_hash=source_lineage.data_hash,
            output_data=[4, 5, 6],
            step_description="normalized",
            output_source="normalized_data.csv"
        )
        
        assert processed_lineage.source == "normalized_data.csv"
        assert processed_lineage.source_type == DataSourceType.PROCESSED
        assert "normalized" in processed_lineage.processing_steps
        assert source_lineage.data_hash in processed_lineage.dependencies
    
    def test_get_lineage(self):
        tracker = DataLineageTracker()
        lineage = tracker.add_source(source="test.csv", data=[1, 2, 3])
        retrieved = tracker.get_lineage(lineage.data_hash)
        assert retrieved == lineage
    
    def test_get_lineage_not_found(self):
        tracker = DataLineageTracker()
        result = tracker.get_lineage("nonexistent_hash")
        assert result is None
    
    def test_get_full_lineage(self):
        tracker = DataLineageTracker()
        source = tracker.add_source(source="raw.csv", data=[1, 2, 3])
        step1 = tracker.add_processing_step(
            input_hash=source.data_hash,
            output_data=[4, 5, 6],
            step_description="cleaned",
            output_source="cleaned.csv"
        )
        step2 = tracker.add_processing_step(
            input_hash=step1.data_hash,
            output_data=[7, 8, 9],
            step_description="normalized",
            output_source="normalized.csv"
        )
        
        full_lineage = tracker.get_full_lineage(step2.data_hash)
        assert len(full_lineage) == 3
        assert full_lineage[0].source == "raw.csv"
        assert full_lineage[1].source == "cleaned.csv"
        assert full_lineage[2].source == "normalized.csv"
    
    def test_export_import_lineage(self):
        tracker = DataLineageTracker()
        tracker.add_source(source="data1.csv", data=[1, 2, 3])
        tracker.add_source(source="data2.csv", data=[4, 5, 6])
        
        exported = tracker.export_lineage()
        assert len(exported) == 2
        
        new_tracker = DataLineageTracker()
        new_tracker.import_lineage(exported)
        assert len(new_tracker.lineage_records) == 2


class TestDataClasses:
    def test_data_lineage_to_dict(self):
        lineage = DataLineage(
            source="test.csv",
            data_hash="abc123",
            source_type=DataSourceType.RAW,
            timestamp=1234567890.0,
            processing_steps=["loaded"],
            dependencies=[],
            metadata={"key": "value"}
        )
        d = lineage.to_dict()
        assert d["source"] == "test.csv"
        assert d["data_hash"] == "abc123"
        assert d["source_type"] == "raw"
    
    def test_reproducibility_score_to_dict(self):
        score = ReproducibilityScore(
            data_availability=85.0,
            method_transparency=90.0,
            code_availability=75.0,
            documentation=80.0,
            overall_score=82.5,
            grade="B",
            timestamp=1234567890.0,
            lineage=[],
            issues=["Minor issue"]
        )
        d = score.to_dict()
        assert d["data_availability"] == 85.0
        assert d["overall_score"] == 82.5
        assert d["grade"] == "B"
        assert len(d["issues"]) == 1
