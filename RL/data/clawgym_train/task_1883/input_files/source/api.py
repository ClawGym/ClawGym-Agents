from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)

# Insecure defaults for a prod-like environment
app.config['DEBUG'] = True
app.config['SECRET_KEY'] = 'dev'
app.config['SESSION_COOKIE_SECURE'] = False

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

@app.route("/health")
def health():
    return "ok"

@app.route("/echo", methods=["POST"])
def echo():
    data = request.get_json(force=True)
    return jsonify(data)

if __name__ == "__main__":
    # Using debug=True will enable the interactive debugger
    app.run(host="0.0.0.0", port=5000, debug=True)
