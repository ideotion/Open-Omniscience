# Reproducibility Report Template

**Project:** {{project_name}}
**Report ID:** {{report_id}}
**Generated:** {{generated_date}}
**Prepared by:** {{prepared_by}}

---

## Executive Summary

**Overall Reproducibility Score:** {{overall_score}}/100 (Grade: {{grade}})

This report evaluates the reproducibility of the research artifacts for {{project_name}}. The score is based on four key components: data availability, method transparency, code availability, and documentation quality.

### Quick Assessment

| Component | Score | Weight | Weighted Score |
|-----------|-------|--------|----------------|
| Data Availability | {{data_availability}} | 25% | {{data_weighted}} |
| Method Transparency | {{method_transparency}} | 25% | {{method_weighted}} |
| Code Availability | {{code_availability}} | 25% | {{code_weighted}} |
| Documentation | {{documentation}} | 25% | {{doc_weighted}} |
| **Total** | **{{overall_score}}** | **100%** | **{{overall_score}}** |

---

## Detailed Evaluation

### 1. Data Availability ({{data_availability}}/100)

**Definition:** The extent to which raw and processed data are available for verification and reuse.

**Evaluation Criteria:**
- [ ] Raw data is publicly available
- [ ] Processed data is publicly available
- [ ] Data is in open, non-proprietary formats
- [ ] Data is properly documented
- [ ] Data access instructions are clear
- [ ] Data integrity is verified (checksums, hashes)

**Strengths:**
{{data_strengths}}

**Weaknesses:**
{{data_weaknesses}}

**Recommendations:**
{{data_recommendations}}

---

### 2. Method Transparency ({{method_transparency}}/100)

**Definition:** The clarity and completeness of the methodology description.

**Evaluation Criteria:**
- [ ] All methods are clearly described
- [ ] Statistical analyses are fully specified
- [ ] Parameters and hyperparameters are documented
- [ ] Assumptions and limitations are stated
- [ ] Reproducibility steps are provided

**Strengths:**
{{method_strengths}}

**Weaknesses:**
{{method_weaknesses}}

**Recommendations:**
{{method_recommendations}}

---

### 3. Code Availability ({{code_availability}}/100)

**Definition:** The availability and usability of code and scripts used in the analysis.

**Evaluation Criteria:**
- [ ] All analysis code is publicly available
- [ ] Code is in a version-controlled repository
- [ ] Code includes clear documentation
- [ ] Dependencies are specified
- [ ] Code is executable with provided data
- [ ] Software versions are documented

**Strengths:**
{{code_strengths}}

**Weaknesses:**
{{code_weaknesses}}

**Recommendations:**
{{code_recommendations}}

---

### 4. Documentation ({{documentation}}/100)

**Definition:** The quality and completeness of documentation for the research.

**Evaluation Criteria:**
- [ ] README file with project overview
- [ ] Data dictionary or schema
- [ ] Methodology documentation
- [ ] Usage instructions
- [ ] License information
- [ ] Citation information

**Strengths:**
{{doc_strengths}}

**Weaknesses:**
{{doc_weaknesses}}

**Recommendations:**
{{doc_recommendations}}

---

## Data Lineage

This section tracks the provenance of data from source to final analysis.

### Data Processing Chain

{{#lineage}}
{{#each lineage}}
#### Step {{@index}}: {{source}} ({{source_type}})
- **Hash:** `{{data_hash}}`
- **Timestamp:** {{timestamp}}
- **Processing Steps:** {{processing_steps}}
- **Dependencies:** {{dependencies}}
- **Metadata:** {{metadata}}

{{/each}}
{{/lineage}}

### Data Flow Diagram

```
{{data_flow_diagram}}
```

---

## Issues and Concerns

The following issues were identified that may affect reproducibility:

{{#issues}}
{{#each issues}}
- {{this}}
{{/each}}
{{/issues}}

{{^issues}}
No significant issues identified.
{{/issues}}

---

## Compliance Checklist

### Open Science Principles
- [ ] Data is openly available
- [ ] Code is openly available
- [ ] Methods are transparent
- [ ] Results are reproducible

### FAIR Principles
- **Findable:**
  - [ ] Data has persistent identifiers
  - [ ] Data is described with rich metadata
  - [ ] Data is registered in a searchable resource

- **Accessible:**
  - [ ] Data is accessible via standard protocols
  - [ ] Authentication and authorization are clearly specified
  - [ ] Metadata remains accessible even when data is no longer available

- **Interoperable:**
  - [ ] Data uses formal, accessible, shared, and broadly applicable language
  - [ ] Data uses vocabularies that follow FAIR principles
  - [ ] Data includes qualified references to other data

- **Reusable:**
  - [ ] Data has a clear usage license
  - [ ] Data is associated with its provenance
  - [ ] Data meets domain-relevant community standards

---

## Conclusion

The overall reproducibility score of **{{overall_score}}/100 ({{grade}})** indicates that this project {{conclusion_text}}.

### Key Achievements
{{achievements}}

### Areas for Improvement
{{improvement_areas}}

### Next Steps
{{next_steps}}

---

*This report was generated automatically by Open-Omniscience - Pillar 2: Scientific Rigor*
*For more information, visit: https://github.com/open-omniscience*
