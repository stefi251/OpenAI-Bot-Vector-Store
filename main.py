from dotenv import load_dotenv
load_dotenv()
import asyncio
import csv
import html
import json
import os
import time
import openai
from datetime import datetime

from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('regadam.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

REGADAM_ID = "asst_No" # change for RegAdam ID
VECTOR_STORE_ID = "vs_ID" # change for ReAdam_VS ID
LOG_FILE = "chat_metrics.csv"
FEEDBACK_LOG_FILE = "feedback_metrics.csv"

openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise RuntimeError("Please set OPENAI_API_KEY (in your environment or a .env file)")

app = FastAPI()

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def html_form():
    return """
    <html><body style="font-family:sans-serif">
    <h2>Regada Valve Assistant</h2>
    <form action="/ask" method="post">
    <textarea name="question" rows="4" cols="50" placeholder="Describe your issue/question"></textarea><br>
    <input type="hidden" name="thread_id" value="">
    <input type="submit" value="Ask">
    </form>
    </body></html>
    """

@app.post("/ask")
async def ask(
    question: str = Form(...),
    thread_id: str = Form(None),
):  # noqa: PLR0912  # endpoint has several validation branches
    if question is None:
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Question is required.</p>"
                "<a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )

    cleaned_question = question.strip()
    if not cleaned_question:
        logger.warning("Blank question submitted")
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Please enter a question or code.</p>"
                "<a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )
    if len(cleaned_question) < 3 and not thread_id:
        logger.warning("Initial question too short submitted")
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Please provide at least three "
                "characters for the first question.</p><a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )
    if len(cleaned_question) > 2000:
        logger.warning("Question too long submitted")
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Please limit the question to "
                "2000 characters.</p><a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )
    question = cleaned_question
    try:
        if not thread_id:
            run = openai.beta.threads.create_and_run(
                assistant_id=REGADAM_ID,
                thread={"messages": [{"role": "user", "content": question}]},
                tool_resources={"file_search": {"vector_store_ids": [VECTOR_STORE_ID]}},
            )
            thread_id = run.thread_id
        else:
            openai.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=question
            )
            run = openai.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=REGADAM_ID
            )
    except openai.APIError as exc:
        logger.error(f"OpenAI API error: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ Service Temporarily Unavailable</h3>
            <p>We're experiencing connectivity issues with our AI service.</p>
            <p>Please try again in a few moments or contact support.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=503,
        )
    except Exception as exc:
        logger.error(f"Unexpected error starting assistant run: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ System Error</h3>
            <p>An unexpected error occurred. Our team has been notified.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=500,
        )

    start_time = time.time()
    timeout = 60
    try:
        while True:
            status = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id).status
            if status in ("completed", "failed"):
                break
            if time.time() - start_time > timeout:
                return HTMLResponse(content="Assistant response timeout. Please try again later.", status_code=504)
            await asyncio.sleep(1)
    except openai.APIError as exc:
        logger.error(f"OpenAI API error while polling: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ Service Temporarily Unavailable</h3>
            <p>We're experiencing connectivity issues with our AI service.</p>
            <p>Please try again in a few moments or contact support.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=503,
        )
    except Exception as exc:
        logger.error(f"Unexpected polling error: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ System Error</h3>
            <p>An unexpected error occurred. Our team has been notified.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=500,
        )

    try:
        msgs = openai.beta.threads.messages.list(thread_id)
        msgs_sorted = sorted(msgs.data, key=lambda m: m.created_at)
    except openai.APIError as exc:
        logger.error(f"OpenAI API error while fetching messages: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ Service Temporarily Unavailable</h3>
            <p>We're experiencing connectivity issues with our AI service.</p>
            <p>Please try again in a few moments or contact support.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=503,
        )
    except Exception as exc:
        logger.error(f"Unexpected message retrieval error: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ System Error</h3>
            <p>An unexpected error occurred. Our team has been notified.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=500,
        )

    def safe_message_text(msg):
        return (msg.content and hasattr(msg.content[0], "text") and getattr(msg.content[0].text, 'value', None))

    answer_msg = next((m for m in reversed(msgs_sorted) if m.role == "assistant" and safe_message_text(m)), None)
    answer_text = (
        answer_msg.content[0].text.value if answer_msg and answer_msg.content and hasattr(answer_msg.content[0], "text") and hasattr(answer_msg.content[0].text, "value")
        else "[No answer returned]"
    )

    citations_html = ""
    if answer_msg and answer_msg.content:
        file_citations = set()
        for part in answer_msg.content:
            if hasattr(part, "text") and hasattr(part.text, "annotations") and part.text.annotations:
                for ann in part.text.annotations:
                    if getattr(ann, 'type', None) == "file_citation":
                        file_id = ann.file_citation.file_id
                        try:
                            file_info = openai.files.retrieve(file_id)
                            filename = file_info.filename
                        except Exception:
                            filename = f"File ID {file_id}"
                        quote_part = getattr(ann.file_citation, "quote", "") or ""
                        filename_safe = html.escape(str(filename))
                        quote_safe = html.escape(quote_part)
                        citation_text = (
                            f"{filename_safe}" + (f" (\"{quote_safe}\")" if quote_safe else "")
                        )
                        file_citations.add(citation_text)
        if file_citations:
            citations_html = "<h4>References:</h4><ul>" + "".join(
                f"<li>{c}</li>" for c in file_citations
            ) + "</ul>"

    def _sanitize_csv_value(value: str) -> str:
        if value is None:
            return ""
        value = value.replace("\r", " ").replace("\n", " ")
        value = value.strip()
        if value.startswith(("=", "+", "-", "@")):
            return f"'{value}"
        return value

    log_row = [
        datetime.now().isoformat(),
        _sanitize_csv_value(thread_id or ""),
        _sanitize_csv_value(question),
        _sanitize_csv_value(answer_text),
    ]
    try:
        file_exists = os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["datetime", "thread_id", "question", "answer"])
            writer.writerow(log_row)
    except Exception as e:
        logger.error(f"Failed to log chat: {e}")

    chat_html = ""
    for m in msgs_sorted:
        if m.content and hasattr(m.content[0], "text") and hasattr(m.content[0].text, "value"):
            who = m.role.title()
            text = m.content[0].text.value
            chat_html += f"<b>{html.escape(who)}:</b> {html.escape(text)}<br>"

    safe_question = html.escape(question)
    safe_answer = html.escape(answer_text)
    safe_citations = citations_html
    safe_thread_id = html.escape(str(thread_id)) if thread_id else ""
    thread_id_js = json.dumps(thread_id or "")

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Regada Valve Assistant</title>
        <style>
            body {{ font-family: sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
            .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .chat-history {{ background: #f8f9fa; padding: 20px; border-radius: 6px; margin: 20px 0; }}
            .response-box {{ background: #e3f2fd; padding: 20px; border-radius: 6px; margin: 20px 0; border-left: 4px solid #2196f3; }}
            .feedback-section {{ background: #fff3e0; padding: 15px; border-radius: 6px; margin: 15px 0; text-align: center; }}
            .btn {{ padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-block; margin: 5px; }}
            .btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
            .btn-primary {{ background: #007bff; color: white; }}
            .btn-success {{ background: #28a745; color: white; }}
            .btn-danger {{ background: #dc3545; color: white; }}
            .btn-warning {{ background: #ffc107; color: #212529; }}
            textarea {{ width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Regada Valve Assistant</h2>
            <h3>Conversation History:</h3>
            <div class="chat-history">{chat_html}</div>
            <hr>
            <h3>Your Question:</h3>
            <p><strong>{safe_question}</strong></p>
            <h3>Assistant Response:</h3>
            <div class="response-box">{safe_answer}</div>
            {safe_citations}
            <div class="feedback-section">
                <h4>Was this response helpful?</h4>
                <button onclick="submitFeedback({thread_id_js}, 1)" class="btn btn-success" id="btn-helpful">Helpful</button>
                <button onclick="submitFeedback({thread_id_js}, -1)" class="btn btn-danger" id="btn-not-helpful">Not Helpful</button>
                <div id="feedback-result"></div>
            </div>
            <h3>Continue Conversation:</h3>
            <form action="/ask" method="post">
                <textarea name="question" rows="4" placeholder="Ask another question..." required></textarea><br><br>
                <input type="hidden" name="thread_id" value="{safe_thread_id}">
                <button type="submit" class="btn btn-primary">Ask Question</button>
            </form>
            <div style="margin-top:20px;">
                <form action="/escalate" method="post" style="display:inline;">
                    <input type="hidden" name="thread_id" value="{safe_thread_id}">
                    <button type="submit" class="btn btn-warning">Escalate to Human Support</button>
                </form>
                <a href="/" class="btn btn-primary">New Conversation</a>
                <a href="/stats" class="btn" style="background:#6c757d;color:white;">Admin Stats</a>
            </div>
        </div>
        <script>
            function submitFeedback(threadId, rating) {{
                document.getElementById('btn-helpful').disabled = true;
                document.getElementById('btn-not-helpful').disabled = true;
                const formData = new FormData();
                formData.append('thread_id', threadId);
                formData.append('rating', rating);
                formData.append('comment', rating > 0 ? 'helpful' : 'not-helpful');
                fetch('/feedback', {{method: 'POST', body: formData}})
                .then(response => response.text())
                .then(html => {{
                    document.getElementById('feedback-result').innerHTML = '<div style="background:#d4edda;color:#155724;padding:10px;border-radius:4px;margin-top:10px;">Thank you for your feedback!</div>';
                }})
                .catch(error => {{
                    document.getElementById('feedback-result').innerHTML = '<div style="background:#f8d7da;color:#721c24;padding:10px;border-radius:4px;margin-top:10px;">Error submitting feedback.</div>';
                    document.getElementById('btn-helpful').disabled = false;
                    document.getElementById('btn-not-helpful').disabled = false;
                }});
            }}
        </script>
    </body>
    </html>
    """)

@app.post("/feedback")
async def feedback(thread_id: str = Form(...), rating: int = Form(...), comment: str = Form(None)):
    def _sanitize_csv_value(value: str) -> str:
        if value is None:
            return ""
        value = value.replace("\r", " ").replace("\n", " ")
        value = value.strip()
        if value.startswith(("=", "+", "-", "@")):
            return f"'{value}"
        return value

    feedback_row = [
        datetime.now().isoformat(),
        _sanitize_csv_value(thread_id),
        rating,
        _sanitize_csv_value(comment or ""),
    ]
    try:
        file_exists = os.path.exists(FEEDBACK_LOG_FILE)
        with open(FEEDBACK_LOG_FILE, "a", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["datetime", "thread_id", "rating", "comment"])
            writer.writerow(feedback_row)
        logger.info(f"Feedback received: Thread {thread_id}, Rating {rating}")
        return HTMLResponse(content="OK")
    except Exception as exc:
        logger.error(f"Feedback error: {exc}")
        return HTMLResponse(content="ERROR", status_code=500)

@app.post("/escalate")
async def escalate(thread_id: str = Form(...)):
    try:
        msgs = openai.beta.threads.messages.list(thread_id)
        msgs_sorted = sorted(msgs.data, key=lambda m: m.created_at)
    except Exception as exc:
        logger.error(f"Escalation retrieval error: {exc}")
        return HTMLResponse(
            content="<p>Unable to retrieve conversation right now. Please try again later.</p>",
            status_code=500,
        )
    
    chat_history_lines = []
    for m in msgs_sorted:
        if m.content and hasattr(m.content[0], "text") and hasattr(m.content[0].text, "value"):
            role = html.escape(m.role.title())
            text = html.escape(m.content[0].text.value)
            chat_history_lines.append(f"{role}: {text}")
    thread_text = "\n".join(chat_history_lines)

    return HTMLResponse(content=f"""
    <html><body style="font-family:sans-serif;padding:20px;">
    <h2>Escalation Submitted</h2>
    <h4>Chat History:</h4>
    <pre style="background:#f1f1f1;padding:10px">{thread_text}</pre>
    <a href='/'>Start new conversation</a>
    </body></html>
    """)

@app.get("/stats")
async def stats():
    try:
        import pandas as pd

        chat_stats = {"n_chats": 0, "n_questions": 0}
        feedback_stats = {"total": 0, "positive": 0, "negative": 0, "rate": 0}

        if os.path.exists(LOG_FILE):
            df = pd.read_csv(LOG_FILE, encoding="utf-8")
            if "thread_id" not in df.columns and df.shape[1] >= 4:
                df = pd.read_csv(
                    LOG_FILE,
                    encoding="utf-8",
                    names=["datetime", "thread_id", "question", "answer"],
                    header=None,
                )
            if not df.empty and "thread_id" in df.columns:
                chat_stats["n_chats"] = df["thread_id"].nunique()
                chat_stats["n_questions"] = len(df)
            elif not df.empty:
                chat_stats["n_questions"] = len(df)

        if os.path.exists(FEEDBACK_LOG_FILE):
            fb_df = pd.read_csv(FEEDBACK_LOG_FILE, encoding="utf-8")
            if "thread_id" not in fb_df.columns and fb_df.shape[1] >= 4:
                fb_df = pd.read_csv(
                    FEEDBACK_LOG_FILE,
                    encoding="utf-8",
                    names=["datetime", "thread_id", "rating", "comment"],
                    header=None,
                )
            if not fb_df.empty:
                feedback_stats["total"] = len(fb_df)
                if "rating" in fb_df.columns:
                    feedback_stats["positive"] = len(fb_df[fb_df["rating"] > 0])
                    feedback_stats["negative"] = len(fb_df[fb_df["rating"] < 0])
                    if feedback_stats["total"] > 0:
                        feedback_stats["rate"] = (
                            feedback_stats["positive"] / feedback_stats["total"]
                        ) * 100

        return HTMLResponse(content=f"""
        <html><body style="font-family:sans-serif;padding:20px;">
        <h1>RegAdam Analytics</h1>
        <p><b>Total Conversations:</b> {chat_stats["n_chats"]}</p>
        <p><b>Total Questions:</b> {chat_stats["n_questions"]}</p>
        <p><b>Total Feedback:</b> {feedback_stats["total"]}</p>
        <p><b>Satisfaction Rate:</b> {feedback_stats["rate"]:.1f}% ({feedback_stats["positive"]} positive / {feedback_stats["negative"]} negative)</p>
        <a href="/">Back to Assistant</a>
        </body></html>
        """)
    except Exception as exc:
        logger.error(f"Stats error: {exc}")
        return HTMLResponse(
            content="<p>Unable to load statistics right now. Please try again later.</p>",
            status_code=500,
        )

@app.get("/health")
async def health_check():
    try:
        openai.models.list()
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
