from flask import Flask, request, jsonify
import requests
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

TARGET_BASE_URL = "https://FreeSoraGenerator.com/api"

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Proxy is running! Accepts client API Key."})

def forward_request(endpoint):
    # 1. Extract the API Key sent from the App (in Headers)
    client_auth = request.headers.get("Authorization")
    
    if not client_auth:
        return jsonify({"code": -1, "message": "Missing Authorization header from client app."}), 401

    payload = request.json
    url = f"{TARGET_BASE_URL}{endpoint}"
    
    # 2. Forward the SAME key to the real Sora API
    headers = {
        "Authorization": client_auth,
        "Content-Type": "application/json"
    }
    
    try:
        if request.method == 'POST':
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        else:
            response = requests.get(url, headers=headers, timeout=120)
            
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"code": -1, "message": f"Proxy Error: {str(e)}"}), 500

@app.route('/v1/video/sora-video', methods=['POST'])
def proxy_create_video():
    return forward_request('/v1/video/sora-video')

@app.route('/video-generations/check-result', methods=['POST'])
def proxy_check_result():
    return forward_request('/video-generations/check-result')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)