# SQL Guardrail Module

Version: 1.1
Date: May 8, 2025 (Documentation Date)

A Python module to analyze string parameters within the WHERE clauses of an SQL query and suggest the closest valid or intended matches from predefined reference datasets.

## Features

* Parses SQL WHERE clauses to identify parameters.
* Compares parameters against reference lists using multiple similarity/distance metrics.
* Supports Levenshtein distance, Semantic Similarity (via sentence-transformers), and FuzzyWuzzy-like matching.
* Extensible design for adding custom distance metrics.
* Structured JSON output for analysis results.

## Installation

```bash
pip install sql_guardrail # Assuming you publish it
# Or from source:
# pip install .