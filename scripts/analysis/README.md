# Analysis Scripts

This directory contains all custom analysis scripts created and used during the debugging and QA testing phases of the Open-Omniscience project.

## Scripts Overview

### Phase 1: Codebase Mapping
- **phase1_mapping.py**: Recursive codebase mapping script
- **qubes_phase1_mapping.py**: Qubes-specific codebase mapping

### Phase 2: Dependency Verification
- **phase2_dependency_checker.py**: Comprehensive dependency verification script
- **phase2_extractor.py**: Reference extraction for dependency analysis
- **phase2_simple_verifier.py**: Simplified dependency verifier
- **phase2_verifier.py**: Full dependency verification with reporting
- **qubes_phase2_dependency_checker.py**: Qubes-specific dependency checker
- **qubes_phase2_focused.py**: Focused Qubes dependency analysis

### Phase 3: Line-by-Line Analysis
- **phase3_analyzer.py**: AST-based line-by-line code analyzer
- **phase3_code_analyzer.py**: Comprehensive code analysis with detailed reporting

### Phase 4: Static Analysis
- **phase4_analyzer.py**: Custom static analysis script
- **phase4_linter.py**: Custom linter for code quality checks

## Usage

These scripts were created specifically for the Open-Omniscience debugging and QA project. They can be reused for similar analysis tasks on other Python projects.

### Common Features
- AST parsing for accurate code analysis
- Recursive directory traversal
- JSON and markdown report generation
- Severity-based issue classification (CRITICAL, HIGH, MEDIUM, LOW)
- Customizable analysis rules

## Requirements
- Python 3.12+
- Standard library modules (ast, os, json, etc.)
- Some scripts may require additional dependencies (see individual script headers)

## Output

Each script generates various output formats:
- JSON reports for machine processing
- Markdown reports for human reading
- Console output for real-time monitoring

## Notes

- These scripts were optimized for the Open-Omniscience codebase structure
- Some scripts may need modification for use with other projects
- All scripts have been tested and verified during the debugging process

## License

These scripts are part of the Open-Omniscience project and are licensed under the same terms as the main project (see LICENSE in repository root).
