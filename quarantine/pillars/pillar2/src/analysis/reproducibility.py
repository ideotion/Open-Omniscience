"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
"""Reproducibility Scoring Module for Open-Omniscience - Phase 2.3"""
import hashlib
import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd


class DataSourceType(Enum):
    RAW = "raw"
    PROCESSED = "processed"
    DERIVED = "derived"
    EXTERNAL = "external"


@dataclass
class DataLineage:
    source: str
    data_hash: str
    source_type: DataSourceType
    timestamp: float
    processing_steps: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "data_hash": self.data_hash,
            "source_type": self.source_type.value,
            "timestamp": self.timestamp,
            "processing_steps": self.processing_steps,
            "dependencies": self.dependencies,
            "metadata": self.metadata
        }


@dataclass
class ReproducibilityScore:
    data_availability: float
    method_transparency: float
    code_availability: float
    documentation: float
    overall_score: float
    grade: str
    timestamp: float
    lineage: List[DataLineage] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_availability": self.data_availability,
            "method_transparency": self.method_transparency,
            "code_availability": self.code_availability,
            "documentation": self.documentation,
            "overall_score": self.overall_score,
            "grade": self.grade,
            "timestamp": self.timestamp,
            "lineage": [l.to_dict() for l in self.lineage],
            "issues": self.issues
        }


class ReproducibilityCalculator:
    def __init__(self):
        self.lineage_tracker = DataLineageTracker()
    
    def calculate_score(
        self,
        data_available: bool = True,
        methods_described: bool = True,
        code_available: bool = True,
        documentation_complete: bool = True,
        lineage: Optional[List[DataLineage]] = None
    ) -> ReproducibilityScore:
        data_score = 100.0 if data_available else 0.0
        method_score = 100.0 if methods_described else 0.0
        code_score = 100.0 if code_available else 0.0
        doc_score = 100.0 if documentation_complete else 0.0
        overall = (data_score + method_score + code_score + doc_score) / 4.0
        grade = self._score_to_grade(overall)
        issues = []
        if not data_available:
            issues.append("Data not available")
        if not methods_described:
            issues.append("Methods not adequately described")
        if not code_available:
            issues.append("Code not available")
        if not documentation_complete:
            issues.append("Documentation incomplete")
        return ReproducibilityScore(
            data_availability=data_score,
            method_transparency=method_score,
            code_availability=code_score,
            documentation=doc_score,
            overall_score=overall,
            grade=grade,
            timestamp=time.time(),
            lineage=lineage or [],
            issues=issues
        )
    
    def _score_to_grade(self, score: float) -> str:
        if score >= 90:
            return "A+"
        elif score >= 80:
            return "A"
        elif score >= 70:
            return "B"
        elif score >= 60:
            return "C"
        elif score >= 50:
            return "D"
        else:
            return "F"
    
    def generate_report(self, score: ReproducibilityScore) -> str:
        lines = []
        lines.append("# Reproducibility Report")
        lines.append("")
        lines.append(f"**Generated:** {time.ctime(score.timestamp)}")
        lines.append(f"**Overall Score:** {score.overall_score:.1f}/100 ({score.grade})")
        lines.append("")
        lines.append("## Score Breakdown")
        lines.append("")
        lines.append("| Component | Score | Status |")
        lines.append("|-----------|-------|--------|")
        da_status = "Pass" if score.data_availability >= 80 else "Fail"
        mt_status = "Pass" if score.method_transparency >= 80 else "Fail"
        ca_status = "Pass" if score.code_availability >= 80 else "Fail"
        dc_status = "Pass" if score.documentation >= 80 else "Fail"
        lines.append(f"| Data Availability | {score.data_availability:.1f} | {da_status} |")
        lines.append(f"| Method Transparency | {score.method_transparency:.1f} | {mt_status} |")
        lines.append(f"| Code Availability | {score.code_availability:.1f} | {ca_status} |")
        lines.append(f"| Documentation | {score.documentation:.1f} | {dc_status} |")
        lines.append("")
        lines.append("## Data Lineage")
        lines.append("")
        if score.lineage:
            lines.append("### Processing Chain")
            lines.append("")
            for i, step in enumerate(score.lineage, 1):
                lines.append(f"{i}. **{step.source}** ({step.source_type.value})")
                lines.append(f"   - Hash: {step.data_hash[:16]}...")
                lines.append(f"   - Timestamp: {time.ctime(step.timestamp)}")
                if step.processing_steps:
                    lines.append(f"   - Steps: {', '.join(step.processing_steps)}")
                if step.dependencies:
                    lines.append(f"   - Dependencies: {', '.join(step.dependencies)}")
        if score.issues:
            lines.append("")
            lines.append("## Issues")
            lines.append("")
            for issue in score.issues:
                lines.append(f"- {issue}")
        lines.append("")
        lines.append("## Recommendations")
        lines.append("")
        if score.overall_score < 80:
            lines.append("- Improve data availability and documentation")
        if score.method_transparency < 80:
            lines.append("- Provide more detailed methodology")
        if score.code_availability < 80:
            lines.append("- Share code and scripts")
        return "\n".join(lines)


class DataLineageTracker:
    def __init__(self):
        self.lineage_records: Dict[str, DataLineage] = {}
    
    def add_source(
        self,
        source: str,
        data: Any,
        source_type: DataSourceType = DataSourceType.RAW,
        processing_steps: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> DataLineage:
        data_hash = self._generate_hash(data)
        lineage = DataLineage(
            source=source,
            data_hash=data_hash,
            source_type=source_type,
            timestamp=time.time(),
            processing_steps=processing_steps or [],
            dependencies=dependencies or [],
            metadata=metadata or {}
        )
        self.lineage_records[data_hash] = lineage
        return lineage
    
    def add_processing_step(
        self,
        input_hash: str,
        output_data: Any,
        step_description: str,
        output_source: str
    ) -> DataLineage:
        if input_hash not in self.lineage_records:
            raise ValueError(f"Input hash {input_hash} not found in lineage")
        input_lineage = self.lineage_records[input_hash]
        output_hash = self._generate_hash(output_data)
        output_lineage = DataLineage(
            source=output_source,
            data_hash=output_hash,
            source_type=DataSourceType.PROCESSED,
            timestamp=time.time(),
            processing_steps=input_lineage.processing_steps + [step_description],
            dependencies=[input_hash],
            metadata={"input_source": input_lineage.source}
        )
        self.lineage_records[output_hash] = output_lineage
        return output_lineage
    
    def get_lineage(self, data_hash: str) -> Optional[DataLineage]:
        return self.lineage_records.get(data_hash)
    
    def get_full_lineage(self, data_hash: str) -> List[DataLineage]:
        lineage_chain = []
        current_hash = data_hash
        while current_hash in self.lineage_records:
            record = self.lineage_records[current_hash]
            lineage_chain.append(record)
            if not record.dependencies:
                break
            current_hash = record.dependencies[0]
        return lineage_chain[::-1]
    
    def _generate_hash(self, data: Any) -> str:
        if isinstance(data, pd.DataFrame):
            data_str = data.to_json()
        elif isinstance(data, dict):
            data_str = json.dumps(data, sort_keys=True)
        else:
            data_str = str(data)
        return hashlib.sha256(data_str.encode()).hexdigest()
    
    def export_lineage(self) -> List[Dict[str, Any]]:
        return [record.to_dict() for record in self.lineage_records.values()]
    
    def import_lineage(self, lineage_data: List[Dict[str, Any]]) -> None:
        for record_data in lineage_data:
            lineage = DataLineage(
                source=record_data["source"],
                data_hash=record_data["data_hash"],
                source_type=DataSourceType(record_data["source_type"]),
                timestamp=record_data["timestamp"],
                processing_steps=record_data.get("processing_steps", []),
                dependencies=record_data.get("dependencies", []),
                metadata=record_data.get("metadata", {})
            )
            self.lineage_records[lineage.data_hash] = lineage
