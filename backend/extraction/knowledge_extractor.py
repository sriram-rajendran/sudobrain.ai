"""Extract structured knowledge from transcripts using the configured local model."""

import json
from typing import Optional

from dotenv import load_dotenv

from backend.ai.local_llm_engine import ask

load_dotenv()


EXTRACTION_PROMPT = """You are analyzing a transcript from a meeting or voice note. Extract structured information.

The transcript has speaker labels and timestamps. Speakers may use English, Tamil, or a mix of both.

Extract the following as JSON:

{
  "summary": "2-3 sentence summary of the conversation",
  "action_items": [
    {
      "text": "what needs to be done",
      "assignee": "who should do it (use speaker label)",
      "due_date": "YYYY-MM-DD if mentioned, null otherwise"
    }
  ],
  "decisions": [
    {
      "text": "what was decided",
      "made_by": "who made the decision",
      "context": "brief context for why"
    }
  ],
  "topics": [
    {
      "title": "topic name",
      "summary": "brief summary of discussion on this topic"
    }
  ],
  "reminders": [
    {
      "text": "reminder text",
      "urgency": "low | normal | high"
    }
  ],
  "project": "project name if identifiable, null otherwise"
}

Rules:
- Only extract items that are explicitly stated or clearly implied
- For Tamil text, provide the extracted items in English for consistency
- If a due date is mentioned relatively (e.g., "by Friday", "next week"), convert to absolute date based on the transcript date
- If no items exist for a category, return an empty array
- Be concise but precise

Return ONLY the JSON, no other text."""


def extract_knowledge(transcript: dict, transcript_date: Optional[str] = None) -> dict:
    """Extract action items, decisions, topics, and reminders from a transcript."""
    formatted = _format_transcript_for_llm(transcript)

    date_context = ""
    if transcript_date:
        date_context = f"\n\nThis transcript is from: {transcript_date}"

    response_text = ask(
        f"{EXTRACTION_PROMPT}{date_context}\n\n--- TRANSCRIPT ---\n{formatted}",
        max_wait=180,
    ).strip()

    # Handle potential markdown code blocks in response
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

    return json.loads(response_text)


def _format_transcript_for_llm(transcript: dict) -> str:
    """Format unified transcript into readable text for an LLM."""
    lines = []

    for seg in transcript.get("segments", []):
        speaker = seg.get("speaker_id", "Unknown")

        # Use participant label if available
        for p in transcript.get("participants", []):
            if p["speaker_id"] == speaker:
                speaker = p["label"]
                break

        timestamp = _format_time(seg.get("start_seconds", 0))
        lines.append(f"[{timestamp}] {speaker}: {seg['text']}")

    return "\n".join(lines)


def _format_time(seconds: float) -> str:
    """Format seconds into MM:SS."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def extract_and_store(transcript: dict, db_module=None):
    """Extract knowledge and save to database."""
    if db_module is None:
        from backend.storage.database import (
            save_action_item,
            save_decision,
            save_reminder,
        )
    else:
        save_action_item = db_module.save_action_item
        save_decision = db_module.save_decision
        save_reminder = db_module.save_reminder

    knowledge = extract_knowledge(transcript, transcript.get("created_at"))
    transcript_id = transcript["id"]
    project = knowledge.get("project")

    for item in knowledge.get("action_items", []):
        save_action_item(
            transcript_id=transcript_id,
            text=item["text"],
            assignee=item.get("assignee"),
            project=project,
            due_date=item.get("due_date"),
        )

    for item in knowledge.get("decisions", []):
        save_decision(
            transcript_id=transcript_id,
            text=item["text"],
            made_by=item.get("made_by"),
            context=item.get("context"),
            project=project,
        )

    for item in knowledge.get("reminders", []):
        save_reminder(
            transcript_id=transcript_id,
            text=item["text"],
            urgency=item.get("urgency", "normal"),
        )

    return knowledge


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python knowledge_extractor.py <transcript.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        transcript = json.load(f)

    result = extract_knowledge(transcript)
    print(json.dumps(result, indent=2, ensure_ascii=False))
