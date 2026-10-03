from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    timezone: str = 'Asia/Shanghai'
    user_name: str = '你'
    assistant_name: str = '你的 AI'

    def __post_init__(self):
        ZoneInfo(self.timezone)


def load_settings() -> Settings:
    return Settings(Path(os.environ.get('PET_NEST_DATA_DIR', Path.home() / '.local/share/cove-pet-nest')).expanduser(),
                    os.environ.get('PET_NEST_TIMEZONE', 'Asia/Shanghai'),
                    os.environ.get('PET_NEST_USER_NAME', '你'),
                    os.environ.get('PET_NEST_ASSISTANT_NAME', '你的 AI'))
