# Extract Knowledge from Transcript

Extract all structured knowledge from this meeting transcript or voice note. Return valid JSON only.

## Rules
- Only extract items explicitly stated or clearly implied in the transcript
- For Tamil text, provide extracted items in English
- Convert relative dates to absolute dates based on the transcript date provided
- "I'll look into it" = action item for the speaker
- "Can you review this?" = action item for the addressee
- "We decided..." or "Let's go with..." = decision
- "I'll send you..." or "I'll get back to you" = promise

## Output Format

Return ONLY this JSON structure, no markdown code blocks, no other text:

{
  "summary": "2-3 sentence summary of what was discussed",
  "action_items": [
    {
      "text": "what needs to be done",
      "assignee": "person who should do it (use speaker name)",
      "assigned_by": "person who assigned it",
      "due_date": "YYYY-MM-DD if mentioned, null otherwise",
      "priority": "high or normal or low"
    }
  ],
  "decisions": [
    {
      "text": "what was decided",
      "made_by": "who made or proposed the decision",
      "context": "brief context for why this decision was made"
    }
  ],
  "promises": [
    {
      "text": "what was promised",
      "promised_by": "who made the promise",
      "promised_to": "who it was promised to",
      "due_date": "YYYY-MM-DD if mentioned, null otherwise"
    }
  ],
  "topics": [
    {
      "title": "short topic name",
      "summary": "one sentence summary of discussion on this topic"
    }
  ],
  "project": "project name if identifiable from context, null otherwise"
}
