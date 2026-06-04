# Open-Omniscience - Pillar 2: Scientific Rigor

**Pillar 2** implements the **Scientific Rigor** component of Open-Omniscience, providing comprehensive statistical validation, peer-review simulation, and reproducibility scoring capabilities.

## Overview

Pillar 2: Scientific Rigor consists of three phases:

1. **Phase 2.1: Statistical Validation Engine** - Core statistical tests and confidence intervals
2. **Phase 2.2: Peer-Review Simulation (Local)** - Multi-model cross-validation using local LLMs
3. **Phase 2.3: Reproducibility Scoring** - Data lineage tracking and reproducibility assessment

All implementations use 100% FOSS tools and work offline (except for optional Ollama integration).

## Project Structure

```
pillar2/
├── README.md                    # This file
├── requirements.txt             # Dependencies
├── src/
│   └── analysis/
│       ├── __init__.py          # Package exports
│       ├── statistical_tests.py # Phase 2.1: Statistical tests
│       ├── confidence_intervals.py # Phase 2.1: Confidence intervals
│       ├── peer_review.py      # Phase 2.2: Peer-review simulation
│       ├── consensus.py        # Phase 2.2: Consensus scoring
│       └── reproducibility.py  # Phase 2.3: Reproducibility scoring
│   └── reports/
│       └── reproducibility_template.md # Phase 2.3: Report template
├── tests/
│   ├── __init__.py
│   ├── test_statistical_tests.py   # 26 tests
│   ├── test_confidence_intervals.py # 34 tests
│   ├── test_peer_review.py         # 38 tests
│   ├── test_consensus.py           # 13 tests
│   └── test_reproducibility.py     # 17 tests
└── examples/
    ├── statistical_validation_demo.py # Phase 2.1 demo
    └── peer_review_demo.py         # Phases 2.2 & 2.3 demo
```

## Quick Start

### Installation

```bash
# Navigate to pillar2 directory
cd pillar2

# Install dependencies
pip install -r requirements.txt

# For Ollama (Phase 2.2 - optional)
# Install from: https://ollama.ai
ollama pull llama3.2:3b
ollama pull mistral:7b
```

### Run Tests

```bash
# Run all tests
PYTHONPATH=pillar2 python -m pytest tests/ -v
```

### Run Demos

```bash
# Phase 2.1: Statistical Validation
PYTHONPATH=pillar2 python examples/statistical_validation_demo.py

# Phases 2.2 & 2.3: Peer-Review and Reproducibility
PYTHONPATH=pillar2 python examples/peer_review_demo.py
```

## Documentation

- [Main README](README.md) - Detailed documentation for all phases
- [Reproducibility Template](src/reports/reproducibility_template.md) - Report template
