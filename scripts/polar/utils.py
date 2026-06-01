from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass
class Belt:
    name: str
    id: str
    address: str
    heart_rate_service: str
    service_0: str


@dataclass
class Settings:
    ROOT: Path
    duration: int
    belt_1: Belt


def config_loader() -> Settings:
    ROOT = Path(__file__).resolve().parent.parent
    SETTINGS = ROOT / "scripts/config.yaml"

    with open(SETTINGS, "r") as f:
        data = yaml.safe_load(f)

    return Settings(
        ROOT=ROOT,
        duration=data["duration"],
        belt_1=Belt(**data["belt_1"]),
    )