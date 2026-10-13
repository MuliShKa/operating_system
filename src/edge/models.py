"""Data models for sensor readings, edge decisions, and process health. TODO."""

from dataclasses import dataclass


@dataclass
class SensorEvent:
    sensor_id: str
    value: float
    unit: str
    timestamp: float


@dataclass
class EdgeDecision:
    action: str
    value: float
    reason: str
    timestamp: float


@dataclass
class ProcessHealth:
    process_name: str
    pid: int
    status: str
    cpu_percent: float
    memory_mb: float
