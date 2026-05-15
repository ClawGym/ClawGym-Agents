from pathlib import Path
import yaml
import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "test_config.yaml"

@pytest.fixture
def driver():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    opts = Options()
    for arg in cfg.get("chromeOptions", []):
        opts.add_argument(arg)

    # Insecure: verbose logging and remote over HTTP
    opts.add_argument("--log-level=0")

    drv = webdriver.Remote(
        command_executor=cfg["remoteWebDriverUrl"],
        options=opts
    )
    try:
        yield drv
    finally:
        drv.quit()
