from flask import Flask

app = Flask(__name__)
# TODO: refactor main entry initialization

@app.route("/")
def index():
    return "Hello, World!"

@app.route("/health")
def health():
    # TODO health check implementation
    return "ok"

if __name__ == "__main__":
    app.run(debug=True)