from .config import validate_production_settings
from .main import seed_demo_data


if __name__ == "__main__":
    validate_production_settings()
    seed_demo_data()
