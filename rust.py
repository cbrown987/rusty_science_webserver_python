import os
import subprocess
import tempfile
import docker # Import the docker library
import shlex # Useful for potential command splitting if needed, though less so here
import shutil

# Define the sandbox image name
SANDBOX_IMAGE_NAME = "rust-runner-sandbox:latest" 
# Execution timeouts (adjust as needed)
COMPILE_TIMEOUT_SECONDS = 15
RUN_TIMEOUT_SECONDS = 10 
# Resource Limits (adjust as needed)
MEM_LIMIT = "128m" # e.g., 128 megabytes
# CPU_SHARES = 512 # Relative weight, 1024 is default. Lower numbers get less CPU time under contention.

# --- Helper function to parse combined output ---
def parse_docker_output(output: str) -> dict:
    """Parses the structured output from the sandbox container."""
    parsed = {"compile_stdout": "", "compile_stderr": "", "run_stdout": "", "run_stderr": "", "exit_codes": None}
    
    try:
        # Simple parsing based on markers. Robust parsing might use regex.
        c_stdout_start = output.find("---COMPILE_STDOUT_START---")
        c_stdout_end = output.find("---COMPILE_STDOUT_END---")
        c_stderr_start = output.find("---COMPILE_STDERR_START---")
        c_stderr_end = output.find("---COMPILE_STDERR_END---")
        r_stdout_start = output.find("---RUN_STDOUT_START---")
        r_stdout_end = output.find("---RUN_STDOUT_END---")
        r_stderr_start = output.find("---RUN_STDERR_START---")
        r_stderr_end = output.find("---RUN_STDERR_END---")
        exit_code_start = output.find("---EXIT_CODE---{")
        exit_code_end = output.find("}")

        if c_stdout_start != -1 and c_stdout_end != -1:
            parsed["compile_stdout"] = output[c_stdout_start + len("---COMPILE_STDOUT_START---"):c_stdout_end].strip()
        if c_stderr_start != -1 and c_stderr_end != -1:
            parsed["compile_stderr"] = output[c_stderr_start + len("---COMPILE_STDERR_START---"):c_stderr_end].strip()
        if r_stdout_start != -1 and r_stdout_end != -1:
            parsed["run_stdout"] = output[r_stdout_start + len("---RUN_STDOUT_START---"):r_stdout_end].strip()
        if r_stderr_start != -1 and r_stderr_end != -1:
             parsed["run_stderr"] = output[r_stderr_start + len("---RUN_STDERR_START---"):r_stderr_end].strip()
        if exit_code_start != -1 and exit_code_end != -1:
             parsed["exit_codes"] = output[exit_code_start + len("---EXIT_CODE---{"):exit_code_end]

    except Exception as e:
        print(f"Error parsing docker output: {e}\nOutput was:\n{output}")
        # Return partial results if possible, or indicate parsing error
        
    return parsed


def run_rust_code(code: str) -> dict:
    """Compiles and runs a Rust code string inside a restricted Docker container."""
    result = {"compile_stdout": "", "compile_stderr": "", "run_stdout": "", "run_stderr": "", "error": None}
    
    try:
        client = docker.from_env()
        try:
             client.images.get(SANDBOX_IMAGE_NAME)
        except docker.errors.ImageNotFound:
             result["error"] = f"Sandbox image '{SANDBOX_IMAGE_NAME}' not found. Please build it first."
             return result
             
        # Create a temporary directory on the host system
        with tempfile.TemporaryDirectory() as tempdir:
            source_filename = "main.rs"
            source_path_host = os.path.join(tempdir, source_filename)
            
            # Write the user's code to the temp file
            with open(source_path_host, "w") as f:
                f.write(code)

            # Define the command to run inside the container
            # This script compiles, runs (if compile succeeds), and prints output with markers
            # It uses intermediate files inside the container's /tmp for stderr capture
            container_command = [
                "/bin/sh", "-c",
                """
                # Ensure /tmp is writable if needed
                # Compile step
                echo "---COMPILE_STDOUT_START---"
                rustc main.rs -o main_exec 2> /tmp/compile.stderr
                COMPILE_EXIT_CODE=$?
                echo "---COMPILE_STDOUT_END---"
                
                echo "---COMPILE_STDERR_START---"
                cat /tmp/compile.stderr || echo "" # Output stderr, or nothing if file doesn't exist
                echo "---COMPILE_STDERR_END---"

                # Execution step (only if compile succeeded)
                RUN_EXIT_CODE=-1 # Default value if not run
                if [ $COMPILE_EXIT_CODE -eq 0 ]; then
                    echo "---RUN_STDOUT_START---"
                    # Use timeout command if available in the container image, otherwise run directly
                    # Note: Coreutils timeout might not be in rust:slim, needs checking/installation
                    # For simplicity, relying on Docker's overall timeout here.
                    ./main_exec 2> /tmp/run.stderr 
                    RUN_EXIT_CODE=$?
                    echo "---RUN_STDOUT_END---"

                    echo "---RUN_STDERR_START---"
                    cat /tmp/run.stderr || echo "" # Output stderr, or nothing
                    echo "---RUN_STDERR_END---"
                fi
                
                # Report exit codes
                echo "---EXIT_CODE---{$COMPILE_EXIT_CODE:$RUN_EXIT_CODE}"
                
                # Optional: cleanup (container is removed anyway)
                # rm -f /tmp/compile.stderr /tmp/run.stderr main.rs main_exec
                """
            ]
            
            # Define the volume mount
            volumes = {
                tempdir: {'bind': '/sandbox', 'mode': 'rw'} # Mount temp dir to /sandbox inside container
            }

            try:
                container = client.containers.run(
                    image=SANDBOX_IMAGE_NAME,
                    command=container_command,
                    volumes=volumes,
                    working_dir="/sandbox", # Work inside the mounted directory
                    network_mode="none",    # Disable networking
                    mem_limit=MEM_LIMIT,    # Apply memory limit
                    # cpu_shares=CPU_SHARES,  # Apply CPU limit (optional)
                    remove=True,            # Automatically remove container on exit
                    detach=False,           # Run attached (block until completion) - simpler for getting logs
                    stdout=True,            # Capture stdout
                    stderr=True             # Capture stderr (both go to logs)
                    # user=1001             # If using non-root user in sandbox image
                )
                
                # The 'run' command blocks, logs are available after completion for attached runs
                # For detached runs, you'd use container.wait() and then container.logs()
                output = container.decode('utf-8') # Logs are bytes
                
                # Parse the combined output
                parsed_output = parse_docker_output(output)
                
                result["compile_stdout"] = parsed_output["compile_stdout"]
                result["compile_stderr"] = parsed_output["compile_stderr"]
                result["run_stdout"] = parsed_output["run_stdout"]
                result["run_stderr"] = parsed_output["run_stderr"]
                
                # Interpret exit codes
                exit_codes = parsed_output.get("exit_codes", None)
                compile_ec, run_ec = -1, -1
                if exit_codes:
                    try:
                       c_ec_str, r_ec_str = exit_codes.split(':')
                       compile_ec = int(c_ec_str)
                       run_ec = int(r_ec_str) # Will be -1 if execution didn't happen
                    except ValueError:
                       result["error"] = "Failed to parse exit codes from container."

                if compile_ec != 0:
                     result["error"] = f"Compilation failed with exit code {compile_ec}"
                elif run_ec != 0 and run_ec != -1: # Check run error only if compilation succeeded
                     # Append run error to any existing compile error message (shouldn't happen here)
                     run_error = f"Execution failed with exit code {run_ec}"
                     result["error"] = f"{result.get('error', '')} | {run_error}".strip(" | ")


            except docker.errors.ContainerError as e:
                # This catches errors reported by the container itself (e.g., non-zero exit code if not handled in script)
                # but our script above tries to handle exit codes explicitly.
                # We capture logs anyway.
                output = e.container.logs().decode('utf-8')
                parsed_output = parse_docker_output(output) # Try parsing even on error
                result.update(parsed_output) # Update with whatever could be parsed
                result["error"] = f"Container execution error: {e.stderr.decode('utf-8', errors='ignore')}"
                # You might want to refine error reporting based on exit code and stderr from e
                
            # Note: The docker SDK's blocking run doesn't have a direct timeout param. 
            # For strict timeouts, you'd run detached=True, then use container.wait(timeout=...)
            # and handle the Timeout exception from docker.errors.
            # Or rely on Docker daemon timeouts if configured globally.

    # Catch potential errors from Docker client (daemon down, image pull issues etc.)
    except docker.errors.APIError as e:
        result["error"] = f"Docker API error: {str(e)}"
    except Exception as e:
        # Catch-all for other unexpected errors (e.g., temp dir issues)
        result["error"] = f"An unexpected error occurred in run_rust_code: {str(e)}"
        # Log the exception traceback for debugging
        import traceback
        traceback.print_exc() 

    return result