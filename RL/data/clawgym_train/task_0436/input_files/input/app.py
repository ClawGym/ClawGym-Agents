import yaml
import os
import logging

with open('config/app.yaml') as f:
    cfg = yaml.load(f, Loader=None)  # insecure YAML load

log_path = cfg['debug']['log_path']
logging.basicConfig(filename=log_path, level=logging.DEBUG)
token = cfg['secrets']['api_token'] or os.environ.get('HG_TOKEN', '')
logging.debug(f"Auth-Token: {token}")  # logs secret
if cfg.get('export_private_notes_to_public'):
    os.system('cp -r notes/private public/notes/')  # exports private notes to public

print("HarmonyNotes app initialized")
