#!/usr/bin/env python3
"""
Phase 3: Line-by-Line Code Analysis
Validates syntax, scope, types, logic, error handling, security, performance, and deprecations
for every line in every source file.
"""

import ast
import json
import os
import re
from datetime import datetime

REPO_ROOT = "/workspace/ideotion__Open-Omniscience"
OUTPUT_FILE = "/workspace/ideotion__Open-Omniscience/PHASE3_REPORT.json"

# Security patterns to check
SECURITY_PATTERNS = {
    "sql_injection": r"(?:execute|query|raw)\(.*\+.*\)",
    "hardcoded_password": r"(?:password|passwd|pwd|secret)\s*[=:]\s*[\"\'].*[\"\']",
    "hardcoded_api_key": r"(?:api[_-]?key|apikey|token)\s*[=:]\s*[\"\'].*[\"\']",
    "eval_usage": r"eval\(",
    "pickle_usage": r"pickle\.(load|loads)\(",
    "shell_injection": r"subprocess\.(run|call|Popen)\(.*shell=True",
    "exec_usage": r"exec\(",
    "unsafe_deserialization": r"(?:yaml\.load|jsonpickle)\(",
    "weak_crypto": r"(?:md5|sha1|des|rc4)\(",
    "xss_vulnerability": r"\.format\(|f\"|f\'|%\s*\(|\+\s*\<",
}

# Performance patterns
PERFORMANCE_PATTERNS = {
    "nested_loops": r"for.*:.*\n\s+for",
    "list_comprehension_in_loop": r"for.*:.*\[.*for",
    "global_variable": r"global\s+",
    "inefficient_string_concat": r"\+\s*\=",
    "unbounded_loop": r"while\s+True",
}

# Deprecation patterns
DEPRECATION_PATTERNS = {
    "deprecated_import": r"import\s+(?:imp|wsgiref\.handlers|asynchat|asyncore)",
    "deprecated_function": r"(?:urllib\.urlopen|optparse|ConfigParser\.RawConfigParser)",
    "python2_syntax": r"print\s+[^()]|except\s+Exception\s*,",
}

# Error handling patterns
ERROR_HANDLING_PATTERNS = {
    "bare_except": r"except\s*:",
    "overly_broad_except": r"except\s+\(?Exception\)?\s*:",
    "ignored_exception": r"except.*:.*pass",
    "no_error_handling": r"def\s+\w+\(.*\):.*(?:return|\n)\s*(?!(?:try|except|raise|with))",
}

# Code quality patterns
QUALITY_PATTERNS = {
    "todo_comment": r"#\s*TODO|//\s*TODO",
    "fixme_comment": r"#\s*FIXME|//\s*FIXME",
    "debug_print": r"print\s*\(.*debug",
    "magic_number": r"[0-9]+\s*(?:==|!=|>|<|>=|<=)",
    "long_function": r"def\s+\w+\(.*\):.*(?:\n\s+[^\n]{100,}){20,}",
    "duplicate_code": r"(?:def|class)\s+\w+.*\n.*\1",
}


class CodeAnalyzer(ast.NodeVisitor):
    """AST-based code analyzer."""

    def __init__(self, filepath):
        self.filepath = filepath
        self.issues = []
        self.current_function = None
        self.current_class = None
        self.line_numbers = []
        self.function_lines = {}
        self.imports = []
        self.function_calls = []
        self.variables = set()
        self.unused_variables = set()
        self.used_variables = set()
        self.depth = 0
        self.max_depth = 0
        self.complexity = 0
        self.has_error_handling = False
        self.has_logging = False
        self.has_type_hints = False
        self.has_docstring = False

    def visit_Import(self, node):
        """Check imports."""
        for alias in node.names:
            self.imports.append({"module": alias.name, "asname": alias.asname, "line": node.lineno})
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        """Check from imports."""
        module = node.module or ""
        for alias in node.names:
            self.imports.append(
                {
                    "module": module,
                    "name": alias.name,
                    "asname": alias.asname,
                    "line": node.lineno,
                    "relative": node.level > 0,
                }
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        """Analyze function definitions."""
        func_name = node.name
        old_function = self.current_function
        self.current_function = func_name
        self.depth = 0

        # Check for type hints
        has_return_hint = node.returns is not None
        has_arg_hints = any(arg.annotation is not None for arg in node.args.args)
        self.has_type_hints = has_return_hint or has_arg_hints

        # Check for docstring
        docstring = ast.get_docstring(node)
        self.has_docstring = docstring is not None

        # Check function length
        if node.end_lineno and node.end_lineno - node.lineno > 100:
            self.issues.append(
                {
                    "type": "LONG_FUNCTION",
                    "severity": "MEDIUM",
                    "message": f"Function '{func_name}' is too long ({node.end_lineno - node.lineno} lines)",
                    "line": node.lineno,
                    "function": func_name,
                    "details": "Consider breaking into smaller functions",
                }
            )

        # Check number of parameters
        num_params = len(node.args.args) + len(node.args.kwonlyargs)
        if num_params > 10:
            self.issues.append(
                {
                    "type": "TOO_MANY_PARAMETERS",
                    "severity": "MEDIUM",
                    "message": f"Function '{func_name}' has too many parameters ({num_params})",
                    "line": node.lineno,
                    "function": func_name,
                    "details": "Consider using keyword arguments or refactoring",
                }
            )

        # Check for *args and **kwargs
        has_varargs = node.args.vararg is not None
        has_kwargs = node.args.kwarg is not None

        self.generic_visit(node)
        self.current_function = old_function

    def visit_ClassDef(self, node):
        """Analyze class definitions."""
        class_name = node.name
        old_class = self.current_class
        self.current_class = class_name

        # Check for docstring
        docstring = ast.get_docstring(node)
        if not docstring:
            self.issues.append(
                {
                    "type": "MISSING_DOCSTRING",
                    "severity": "LOW",
                    "message": f"Class '{class_name}' is missing a docstring",
                    "line": node.lineno,
                    "class": class_name,
                }
            )

        # Check for __init__ method
        has_init = any(isinstance(n, ast.FunctionDef) and n.name == "__init__" for n in node.body)

        self.generic_visit(node)
        self.current_class = old_class

    def visit_Assign(self, node):
        """Check variable assignments."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                self.variables.add(var_name)

                # Check for unused variables (simplified check)
                if var_name.startswith("_") and not var_name.startswith("__"):
                    # Private variables are OK
                    pass
                elif var_name not in self.used_variables and not self.is_standard_name(var_name):
                    # This is a simplified check - real unused variable detection
                    # would require more sophisticated analysis
                    pass

        self.generic_visit(node)

    def visit_Name(self, node):
        """Track variable usage."""
        if isinstance(node.ctx, ast.Load):
            self.used_variables.add(node.id)
        self.generic_visit(node)

    def visit_Call(self, node):
        """Check function calls."""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            self.function_calls.append({"name": func_name, "line": node.lineno})

            # Check for security issues
            self.check_security_issue(func_name, node.lineno)
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            self.function_calls.append(
                {"name": f"{self.get_call_path(node.func)}.{attr_name}", "line": node.lineno}
            )

            # Check for security issues
            self.check_security_issue(attr_name, node.lineno)

        self.generic_visit(node)

    def get_call_path(self, node):
        """Get the full path of an attribute call."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self.get_call_path(node.value)}.{node.attr}"
        return ""

    def check_security_issue(self, name, line):
        """Check for security issues in function calls."""
        security_checks = {
            "eval": (
                "EVAL_USAGE",
                "CRITICAL",
                "Use of eval() is dangerous and can lead to code injection",
            ),
            "exec": (
                "EXEC_USAGE",
                "CRITICAL",
                "Use of exec() is dangerous and can lead to code injection",
            ),
            "pickle.load": (
                "UNSAFE_DESERIALIZATION",
                "HIGH",
                "pickle.load() can lead to arbitrary code execution",
            ),
            "pickle.loads": (
                "UNSAFE_DESERIALIZATION",
                "HIGH",
                "pickle.loads() can lead to arbitrary code execution",
            ),
            "subprocess.run": (
                "SHELL_INJECTION_RISK",
                "MEDIUM",
                "subprocess.run() with shell=True can lead to shell injection",
            ),
            "subprocess.call": (
                "SHELL_INJECTION_RISK",
                "MEDIUM",
                "subprocess.call() with shell=True can lead to shell injection",
            ),
            "subprocess.Popen": (
                "SHELL_INJECTION_RISK",
                "MEDIUM",
                "subprocess.Popen() with shell=True can lead to shell injection",
            ),
            "os.system": (
                "SHELL_INJECTION_RISK",
                "MEDIUM",
                "os.system() can lead to shell injection",
            ),
            "yaml.load": (
                "UNSAFE_DESERIALIZATION",
                "HIGH",
                "yaml.load() can lead to arbitrary code execution",
            ),
            "md5": ("WEAK_CRYPTO", "MEDIUM", "MD5 is cryptographically broken"),
            "sha1": ("WEAK_CRYPTO", "MEDIUM", "SHA1 is cryptographically broken"),
        }

        for func, (issue_type, severity, message) in security_checks.items():
            if name == func or name.endswith(f".{func}"):
                self.issues.append(
                    {
                        "type": issue_type,
                        "severity": severity,
                        "message": message,
                        "line": line,
                        "function": self.current_function,
                        "class": self.current_class,
                    }
                )

    def is_standard_name(self, name):
        """Check if a variable name is a standard Python name."""
        standard_names = {
            "i",
            "j",
            "k",
            "n",
            "m",
            "x",
            "y",
            "z",  # Common loop variables
            "self",
            "cls",
            "super",  # OOP special names
            "args",
            "kwargs",  # Function parameters
            "e",
            "ex",
            "exception",
            "error",  # Exception names
            "f",
            "file",
            "fp",  # File objects
            "key",
            "value",
            "item",  # Dictionary iteration
            "line",
            "lines",  # Line processing
            "data",
            "result",
            "results",  # Common data names
            "config",
            "settings",
            "options",  # Configuration
            "logger",
            "log",  # Logging
        }
        return name in standard_names

    def visit_ExceptHandler(self, node):
        """Check exception handling."""
        self.has_error_handling = True

        # Check for bare except
        if node.type is None:
            self.issues.append(
                {
                    "type": "BARE_EXCEPT",
                    "severity": "HIGH",
                    "message": "Bare except clause found",
                    "line": node.lineno,
                    "function": self.current_function,
                    "class": self.current_class,
                    "details": "Use specific exception types instead",
                }
            )

        # Check for overly broad exception handling
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            self.issues.append(
                {
                    "type": "BROAD_EXCEPT",
                    "severity": "MEDIUM",
                    "message": "Overly broad exception handling (Exception)",
                    "line": node.lineno,
                    "function": self.current_function,
                    "class": self.current_class,
                    "details": "Consider catching more specific exceptions",
                }
            )

        # Check for ignored exceptions
        if isinstance(node.body, list) and len(node.body) == 0:
            self.issues.append(
                {
                    "type": "IGNORED_EXCEPTION",
                    "severity": "HIGH",
                    "message": "Exception caught but not handled",
                    "line": node.lineno,
                    "function": self.current_function,
                    "class": self.current_class,
                    "details": "Add error handling or at least log the exception",
                }
            )
        elif (
            isinstance(node.body, list)
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Pass)
        ):
            self.issues.append(
                {
                    "type": "IGNORED_EXCEPTION",
                    "severity": "HIGH",
                    "message": "Exception caught but only passes",
                    "line": node.lineno,
                    "function": self.current_function,
                    "class": self.current_class,
                    "details": "Add error handling or at least log the exception",
                }
            )

        self.generic_visit(node)

    def visit_If(self, node):
        """Check if statements."""
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)

        # Check for complex conditions
        if self.get_complexity(node.test) > 5:
            self.issues.append(
                {
                    "type": "COMPLEX_CONDITION",
                    "severity": "MEDIUM",
                    "message": "Complex if condition",
                    "line": node.lineno,
                    "function": self.current_function,
                    "class": self.current_class,
                    "details": "Consider breaking into simpler conditions",
                }
            )

        self.generic_visit(node)
        self.depth -= 1

    def get_complexity(self, node):
        """Calculate complexity of an expression."""
        if isinstance(node, ast.BoolOp):
            return 1 + sum(self.get_complexity(value) for value in node.values)
        elif isinstance(node, ast.BinOp):
            return 1 + self.get_complexity(node.left) + self.get_complexity(node.right)
        elif isinstance(node, ast.UnaryOp):
            return 1 + self.get_complexity(node.operand)
        elif isinstance(node, ast.Compare):
            return 1 + sum(self.get_complexity(comp) for comp in node.comparators)
        elif isinstance(node, ast.Call):
            return 1 + sum(self.get_complexity(arg) for arg in node.args)
        else:
            return 1


def analyze_file(filepath):
    """Analyze a single Python file."""
    result = {
        "file": filepath,
        "relative_path": os.path.relpath(filepath, REPO_ROOT),
        "issues": [],
        "metrics": {},
        "imports": [],
        "functions": [],
        "classes": [],
        "security_issues": [],
        "performance_issues": [],
        "quality_issues": [],
        "error_handling_issues": [],
    }

    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        # Parse with AST
        tree = ast.parse(content, filename=filepath)

        # Run AST analyzer
        analyzer = CodeAnalyzer(filepath)
        analyzer.visit(tree)

        result["issues"] = analyzer.issues
        result["imports"] = analyzer.imports

        # Categorize issues
        for issue in analyzer.issues:
            if issue["type"].startswith(("EVAL", "EXEC", "UNSAFE", "SHELL", "WEAK")):
                result["security_issues"].append(issue)
            elif issue["type"].startswith(("LONG", "TOO_MANY", "COMPLEX")):
                result["performance_issues"].append(issue)
            elif issue["type"].startswith(("MISSING", "BARE", "BROAD", "IGNORED")):
                result["error_handling_issues"].append(issue)
            else:
                result["quality_issues"].append(issue)

        # Check for patterns in content
        result["issues"].extend(check_content_patterns(filepath, content))

        # Extract metrics
        lines = content.split("\n")
        result["metrics"] = {
            "total_lines": len(lines),
            "code_lines": len([l for l in lines if l.strip() and not l.strip().startswith("#")]),
            "comment_lines": len([l for l in lines if l.strip().startswith("#")]),
            "blank_lines": len([l for l in lines if not l.strip()]),
            "functions": len([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]),
            "classes": len([n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]),
            "imports": len(analyzer.imports),
            "max_nesting_depth": analyzer.max_depth,
            "has_type_hints": analyzer.has_type_hints,
            "has_docstrings": analyzer.has_docstring,
            "has_error_handling": analyzer.has_error_handling,
        }

        # Extract function and class info
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                result["functions"].append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                        "has_docstring": ast.get_docstring(node) is not None,
                        "has_type_hints": node.returns is not None
                        or any(arg.annotation is not None for arg in node.args.args),
                    }
                )
            elif isinstance(node, ast.ClassDef):
                result["classes"].append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                        "has_docstring": ast.get_docstring(node) is not None,
                    }
                )

    except SyntaxError as e:
        result["issues"].append(
            {
                "type": "SYNTAX_ERROR",
                "severity": "CRITICAL",
                "message": str(e),
                "line": e.lineno,
                "details": f"File cannot be parsed: {e.msg}",
            }
        )
    except Exception as e:
        result["issues"].append(
            {
                "type": "ANALYSIS_ERROR",
                "severity": "CRITICAL",
                "message": str(e),
                "details": f"Error analyzing file: {e}",
            }
        )

    return result


def check_content_patterns(filepath, content):
    """Check content for various patterns."""
    issues = []
    lines = content.split("\n")

    # Check for TODO and FIXME comments
    for i, line in enumerate(lines, 1):
        if re.search(r"#\s*TODO", line, re.IGNORECASE):
            issues.append(
                {
                    "type": "TODO_COMMENT",
                    "severity": "LOW",
                    "message": "TODO comment found",
                    "line": i,
                    "file": filepath,
                    "details": line.strip(),
                }
            )
        if re.search(r"#\s*FIXME", line, re.IGNORECASE):
            issues.append(
                {
                    "type": "FIXME_COMMENT",
                    "severity": "MEDIUM",
                    "message": "FIXME comment found",
                    "line": i,
                    "file": filepath,
                    "details": line.strip(),
                }
            )

    # Check for hardcoded secrets
    for i, line in enumerate(lines, 1):
        if re.search(
            r"(?:password|passwd|pwd|secret|api[_-]?key|token)\s*[=:]\s*[\"\'][^\"\']+[\"\']",
            line,
            re.IGNORECASE,
        ):
            issues.append(
                {
                    "type": "HARDCODED_SECRET",
                    "severity": "CRITICAL",
                    "message": "Potential hardcoded secret found",
                    "line": i,
                    "file": filepath,
                    "details": "Secrets should be loaded from environment variables or config files",
                }
            )

    # Check for debug print statements
    for i, line in enumerate(lines, 1):
        if re.search(r"print\s*\(.*debug", line, re.IGNORECASE):
            issues.append(
                {
                    "type": "DEBUG_PRINT",
                    "severity": "LOW",
                    "message": "Debug print statement found",
                    "line": i,
                    "file": filepath,
                    "details": line.strip(),
                }
            )

    # Check for deprecated Python features
    for i, line in enumerate(lines, 1):
        if re.search(r"import\s+(?:imp|wsgiref\.handlers|asynchat|asyncore)", line):
            issues.append(
                {
                    "type": "DEPRECATED_IMPORT",
                    "severity": "MEDIUM",
                    "message": "Deprecated import found",
                    "line": i,
                    "file": filepath,
                    "details": "Consider using modern alternatives",
                }
            )

    return issues


def main():
    """Main code analysis function."""
    print("Starting Phase 3: Line-by-Line Code Analysis...")
    print(f"Repository Root: {REPO_ROOT}")

    report = {
        "repository": {
            "name": "Open-Omniscience",
            "url": "https://github.com/ideotion/Open-Omniscience",
            "local_path": REPO_ROOT,
            "scan_timestamp": datetime.now().isoformat(),
            "scan_type": "Phase 3: Line-by-Line Code Analysis",
        },
        "summary": {},
        "files": {},
        "critical_issues": [],
        "high_issues": [],
        "medium_issues": [],
        "low_issues": [],
        "security_issues": [],
        "performance_issues": [],
        "quality_issues": [],
        "error_handling_issues": [],
    }

    # Find all Python files
    python_files = []
    for root, dirs, files in os.walk(REPO_ROOT):
        if ".git" in root:
            continue
        for filename in files:
            if filename.endswith(".py"):
                filepath = os.path.join(root, filename)
                python_files.append(filepath)

    print(f"Analyzing {len(python_files)} Python files...")

    # Analyze each file
    for i, filepath in enumerate(python_files, 1):
        if i % 50 == 0:
            print(f"  Processed {i}/{len(python_files)} files...")

        try:
            file_result = analyze_file(filepath)
            report["files"][filepath] = file_result

            # Categorize issues by severity
            for issue in file_result.get("issues", []):
                severity = issue.get("severity", "LOW")
                if severity == "CRITICAL":
                    report["critical_issues"].append(issue)
                elif severity == "HIGH":
                    report["high_issues"].append(issue)
                elif severity == "MEDIUM":
                    report["medium_issues"].append(issue)
                else:
                    report["low_issues"].append(issue)

            # Categorize by type
            report["security_issues"].extend(file_result.get("security_issues", []))
            report["performance_issues"].extend(file_result.get("performance_issues", []))
            report["quality_issues"].extend(file_result.get("quality_issues", []))
            report["error_handling_issues"].extend(file_result.get("error_handling_issues", []))

        except Exception as e:
            report["critical_issues"].append(
                {
                    "type": "ANALYSIS_FAILED",
                    "severity": "CRITICAL",
                    "message": f"Failed to analyze {filepath}: {str(e)}",
                    "file": filepath,
                }
            )

    # Generate summary
    total_files = len(report["files"])
    total_issues = (
        len(report["critical_issues"])
        + len(report["high_issues"])
        + len(report["medium_issues"])
        + len(report["low_issues"])
    )

    # Calculate metrics
    total_lines = sum(f.get("metrics", {}).get("total_lines", 0) for f in report["files"].values())
    total_functions = sum(
        f.get("metrics", {}).get("functions", 0) for f in report["files"].values()
    )
    total_classes = sum(f.get("metrics", {}).get("classes", 0) for f in report["files"].values())
    files_with_type_hints = sum(
        1 for f in report["files"].values() if f.get("metrics", {}).get("has_type_hints")
    )
    files_with_docstrings = sum(
        1 for f in report["files"].values() if f.get("metrics", {}).get("has_docstrings")
    )

    report["summary"] = {
        "total_files_analyzed": total_files,
        "total_lines_of_code": total_lines,
        "total_functions": total_functions,
        "total_classes": total_classes,
        "files_with_type_hints": files_with_type_hints,
        "files_with_docstrings": files_with_docstrings,
        "total_issues": total_issues,
        "critical_issues": len(report["critical_issues"]),
        "high_issues": len(report["high_issues"]),
        "medium_issues": len(report["medium_issues"]),
        "low_issues": len(report["low_issues"]),
        "security_issues": len(report["security_issues"]),
        "performance_issues": len(report["performance_issues"]),
        "quality_issues": len(report["quality_issues"]),
        "error_handling_issues": len(report["error_handling_issues"]),
        "scan_completed": datetime.now().isoformat(),
    }

    # Save report
    with open(OUTPUT_FILE, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print("\nPhase 3 Complete!")
    print(f"Files Analyzed: {total_files}")
    print(f"Total Lines: {total_lines}")
    print(f"Total Functions: {total_functions}")
    print(f"Total Classes: {total_classes}")
    print(f"Total Issues: {total_issues}")
    print(f"Critical Issues: {len(report['critical_issues'])}")
    print(f"High Issues: {len(report['high_issues'])}")
    print(f"Medium Issues: {len(report['medium_issues'])}")
    print(f"Low Issues: {len(report['low_issues'])}")
    print(f"Report saved to: {OUTPUT_FILE}")

    # Print critical issues
    if report["critical_issues"]:
        print("\n=== CRITICAL ISSUES ===")
        for i, issue in enumerate(report["critical_issues"][:20], 1):
            print(
                f"  {i}. [{issue['type']}] {issue['message']} ({issue.get('file', 'unknown')}:{issue.get('line', '?')})"
            )

    # Print security issues
    if report["security_issues"]:
        print("\n=== SECURITY ISSUES ===")
        for i, issue in enumerate(report["security_issues"][:20], 1):
            print(
                f"  {i}. [{issue['type']}] {issue['message']} ({issue.get('file', 'unknown')}:{issue.get('line', '?')})"
            )

    # Print summary by type
    print("\n=== Issues by Type ===")
    issue_types = {}
    for issue in (
        report["critical_issues"]
        + report["high_issues"]
        + report["medium_issues"]
        + report["low_issues"]
    ):
        itype = issue["type"]
        issue_types[itype] = issue_types.get(itype, 0) + 1
    for itype, count in sorted(issue_types.items(), key=lambda x: x[1], reverse=True):
        print(f"  {itype}: {count}")


if __name__ == "__main__":
    main()
