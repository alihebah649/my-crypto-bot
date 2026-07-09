import hashlib
import json
import time
import uuid
import platform
import numpy as np
import pandas as pd
from dataclasses import dataclass, asdict

@dataclass
class StrictRunMetadata:
    run_id: str
    config_hash: str
    dataset_name: str
    dataset_hash: str            
    environment_env: dict        
    termination_reason: str      
    strategy_version: str = "V18.9-PROD"
    seed: int = 42

class MetaAuditOrchestrator:
    def __init__(self, strategy_config: dict, dataset_path: str, seed: int = 42):
        self.config = strategy_config
        self.dataset_path = dataset_path
        self.seed = seed
        self.run_id = f"RUN_{uuid.uuid4().hex[:8].upper()}"

    def generate_config_hash(self) -> str:
        config_string = json.dumps(self.config, sort_keys=True)
        return hashlib.sha256(config_string.encode('utf-8')).hexdigest()[:12]

    def capture_environment_dna(self) -> dict:
        sha256_hash = hashlib.sha256()
        with open(self.dataset_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        data_hash = sha256_hash.hexdigest()[:16]
        
        env_dna = {
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "pandas_version": pd.__version__,
            "os": platform.system()
        }
        
        return {
            "run_id": self.run_id,
            "config_hash": self.generate_config_hash(),
            "dataset_name": self.dataset_path.split("/")[-1],
            "dataset_hash": data_hash,
            "environment_env": env_dna,
            "termination_reason": "RUNNING"
        }

    def write_baseline_header(self, file_path: str = "data/decision_audit.jsonl") -> str:
        dna = self.capture_environment_dna()
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"METADATA_HEADER": dna}) + "\n")
        return self.run_id
