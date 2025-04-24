import subprocess
import tempfile
import os
import shlex

from flask import Flask, jsonify, request, render_template

from rust import run_rust_code

app = Flask(__name__)

INITIAL_RUST_CODE = """
fn main() {
    println!("Hello from Rust inside Flask!");
    let sum = 5 + 10;
    println!("5 + 10 = {}", sum);
}
"""


@app.route('/')
def index():
    """Serves the main HTML page with the code editor."""
    # Pass the initial Rust code to the template
    return render_template('index.html', initial_code=INITIAL_RUST_CODE)


@app.route('/execute', methods=['POST'])
def execute_code():
    """Receives Rust code, executes it, and returns the output."""
    if not request.is_json:
        return jsonify({"error": "Invalid request: Content-Type must be application/json"}), 400

    data = request.get_json()
    code = data.get('code')

    if code is None:
        return jsonify({"error": "Missing 'code' field in JSON payload"}), 400

    if not isinstance(code, str):
        return jsonify({"error": "'code' field must be a string"}), 400

    # ** SECURITY WARNING **: Directly running code received from the request.
    execution_result = run_rust_code(code)
    return jsonify(execution_result)


# --- Add shutil import ---
import shutil  # Needed for shutil.which

if __name__ == '__main__':

    app.run(host='0.0.0.0', port=5000, debug=True)
