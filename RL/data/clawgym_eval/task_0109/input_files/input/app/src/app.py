from flask import Flask, request
import yaml
import subprocess

app = Flask(__name__)
app.config['DEBUG'] = True
app.config['SECRET_KEY'] = 'dev-secret'  # hard-coded secret

@app.route('/hello')
def hello():
    name = request.args.get('name', 'world')
    # Insecure: shell=True with untrusted input
    subprocess.call(f"echo Hello {name}", shell=True)
    return 'ok'

@app.route('/load')
def load():
    data = request.args.get('data', 'foo: bar')
    # Unsafe YAML load (should use safe_load)
    cfg = yaml.load(data, Loader=yaml.Loader)
    return str(cfg)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
