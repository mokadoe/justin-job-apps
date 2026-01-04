"""
Aggregators package - discover companies from external sources.

Usage:
    python -m src.discovery.aggregators.run simplify
    python -m src.discovery.aggregators.run yc --check 100
    python -m src.discovery.aggregators.run --list
"""

from .types import CompanyLead, JobLead, AggregatorResult
from .simplify_aggregator import SimplifyAggregator
from .yc_aggregator import YCAggregator
from .a16z_aggregator import A16ZAggregator
from .manual_aggregator import ManualAggregator

__all__ = [
    'CompanyLead',
    'JobLead',
    'AggregatorResult',
    'SimplifyAggregator',
    'YCAggregator',
    'A16ZAggregator',
    'ManualAggregator',
]
