from pathlib import Path
import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "test_config.yaml"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def test_login():
    cfg = load_config()

    chrome_options = Options()
    for arg in cfg.get("chromeOptions", []):
        chrome_options.add_argument(arg)

    # Insecure: pass through capability from config
    chrome_options.set_capability(
        "acceptInsecureCerts",
        cfg.get("capabilities", {}).get("acceptInsecureCerts", False)
    )

    driver = webdriver.Remote(
        command_executor=cfg["remoteWebDriverUrl"],
        options=chrome_options
    )

    base = cfg["baseUrl"]
    username = cfg["credentials"]["username"]
    password = cfg["credentials"]["password"]

    # Insecure: printing credentials
    print(f"[debug] Attempting login with credentials: {username}:{password}")

    driver.get(base + "/login")
    driver.find_element("css selector", "#username").send_keys(username)
    driver.find_element("css selector", "#password").send_keys(password)
    driver.find_element("css selector", "button[type='submit']").click()

    driver.quit()
