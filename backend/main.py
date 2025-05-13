from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uuid
from backend.services.executor import cancel_execution, run_script
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from backend.llms.claude_llm import ClaudeLLM

app = FastAPI()

# Enable CORS to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow requests from any frontend (can get restricted later)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (POST, GET, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Claude API client
claude = ClaudeLLM()

# Store task statuses and LLM output
task_status = {}
llm_outputs = {}  # Dictionary to store LLM outputs


class UserRequest(BaseModel):
    user_input: str
    repo_name: str  # Added field for repository name


@app.post("/run-automation")
async def run_automation(request: UserRequest):
    """Uses Claude to determine which automation to run and streams logs."""
    user_input = request.user_input
    repo_name = request.repo_name.strip()

    if not user_input or not repo_name:
        raise HTTPException(
            status_code=400, detail="User input and repo name are required"
        )

    # Build Claude-compatible prompt
    intent_prompt = [
        {
            "role": "system",
            "content": (
                "You are an AI assistant responsible for classifying automation tasks.\n"
                "Based on the user request, return **only one** of these exact options:\n"
                "- `GitHub Actions`\n"
                "- `Docker`\n"
                "- `GitLab CI/CD`\n"
                "- `Kubernetes`\n"
                "- `Cloud`\n\n"
                "**Rules:**\n"
                "- If the user mentions **GitHub Actions**, return **GitHub Actions**.\n"
                "- If the user mentions **Docker**, return **Docker**.\n"
                "- If the user mentions **GitLab pipeline** or **GitLab CI/CD**, return **GitLab CI/CD**.\n"
                "- If the request involves **Kubernetes**, **k8s**, **kubectl**, or **Minikube**, return **Kubernetes**.\n"
                "- If the request involves **AWS**, **EC2**, **Pulumi**, or **cloud deployment**, return **Cloud**.\n"
                "- Do **not** return explanations or any extra text — **only** the exact option."
            ),
        },
        {"role": "user", "content": user_input},
    ]

    # Query Claude
    try:
        response = await claude.chat(intent_prompt)
        intent = response.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude API error: {e}")

    if intent not in [
        "GitHub Actions",
        "Docker",
        "GitLab CI/CD",
        "Kubernetes",
        "Cloud",
    ]:
        return {"error": "LLM returned an unrecognized intent.", "llm_output": intent}

    # Store LLM response
    task_id = str(uuid.uuid4())
    task_status[task_id] = "Running"
    llm_outputs[task_id] = intent

    async def log_stream():
        """Streams logs dynamically to the UI with real-time output."""
        if intent == "GitHub Actions":
            script_name = "setup_github_actions.py"
        elif intent == "Docker":
            script_name = "dockerize_app.py"
        elif intent == "GitLab CI/CD":
            script_name = "setup_gitlab_ci.py"
        elif intent == "Kubernetes":
            script_name = "setup_kubernetes.py"
        elif intent == "Cloud":
            script_name = "deploy_to_cloud.py"
        else:
            script_name = "setup_github_actions.py"

        process = run_script(script_name, repo_name, user_input)

        for log in process:
            yield log  # 🔄 Immediately send logs to the UI

        task_status[task_id] = "Completed"

        yield "✅ Task Completed!"

    return StreamingResponse(log_stream(), media_type="text/event-stream")


@app.get("/get-llm-output/{task_id}")
async def get_llm_output(task_id: str):
    """Fetches the stored LLM output for the given task ID."""
    if task_id not in llm_outputs:
        raise HTTPException(
            status_code=404, detail="Task ID not found or no LLM output available."
        )
    return {"llm_output": llm_outputs[task_id]}


@app.post("/cancel-automation")
async def cancel_automation():
    """Immediately stops any running automation task."""
    cancel_execution()  # Call function to stop execution
    return {"message": "Automation cancelled"}
