# SudoBrain — Enhancement Roadmap

## Priority: High

### 1. Local LLM (Ollama)
Run AI models directly on your Mac. No internet needed, no API costs.
- Use for quick tasks: classification, summarization, simple extraction
- Keep a configurable local CLI model for complex reasoning
- Works in airplane mode
- **Options:** Ollama, LM Studio, MLX

### 2. Graph Database (Neo4j)
Store knowledge as a connected network instead of flat tables.
- Every person, project, decision, promise becomes a node
- Relationships become edges: "Alex promised Taylor", "Decision belongs to Project X"
- Ask questions like "who is the bottleneck across all my projects?"
- Visual knowledge map in Neo4j browser
- **Options:** Neo4j Community (Docker), Kuzu (embedded), Apache AGE

### 3. Document Ingestion
Feed PDFs, Word docs, text files, and web pages into the knowledge base.
- Not just audio — knowledge can come from anywhere
- Drop a document, SudoBrain extracts and connects it to people and projects
- **Options:** PyMuPDF, python-docx, Trafilatura

### 4. Calendar Intelligence (Pre-Meeting Prep)
Auto-prepare you before every meeting using your knowledge base.
- 10 minutes before a meeting: pop up context about attendees
- Show last discussion, pending promises, open decisions
- Uses Apple EventKit + existing MCP Calendar integration

### 5. ReACT Chat Agent
Multi-step reasoning instead of single-shot answers.
- Chat agent decides: search transcripts, check promises, look up person, then synthesize
- Handles complex questions like "Am I falling behind on commitments this month?"
- Based on MiroFish's report agent pattern

---

## Priority: Medium

### 6. Local Vector Database
Replace basic numpy similarity search with a proper vector engine.
- Faster semantic search as knowledge grows
- Filter by date, person, project during search
- **Options:** ChromaDB, LanceDB, Qdrant

### 7. Local Speech-to-Text (Whisper)
Run transcription on-device instead of calling Sarvam API.
- Free, offline, supports 99 languages
- Keep Sarvam for Tamil-specific accuracy
- **Options:** Whisper.cpp, MLX Whisper, Faster-Whisper

### 8. Real-Time Transcription
See words appear as people speak in meetings.
- Live action item and promise detection
- "Promise detected" the moment someone says "I'll send that by Friday"
- **Options:** Whisper streaming, Vosk, macOS Speech Recognition

### 9. Smart Search (InsightForge Pattern)
Auto-decompose a question into sub-queries for richer answers.
- "How is Project X going?" generates sub-queries: decisions, blockers, timeline, people
- Run each through FTS + semantic search, merge results
- Based on MiroFish's InsightForge search

### 10. Email Draft Generation
Auto-draft follow-up emails after meetings.
- Summarize decisions and action items
- Draft addressed to attendees
- Review and export from the email draft workflow

### 11. Automated Workflows / Triggers
"When X happens, do Y" — set rules once, run forever.
- Promise 2 days from due date → send reminder
- Meeting ends → auto-generate minutes
- Action item unassigned for 24 hours → flag in inbox
- **Options:** APScheduler (already in project), n8n (self-hosted)

### 12. Weekly/Monthly Intelligence Reports
Auto-generated personal reports showing patterns and trends.
- Meeting count, decisions made, tasks completed, promises kept/broken
- Most discussed topics, most frequent contacts
- Recommendations: "You're over-committed on Project X"

---

## Priority: Lower (Nice to Have)

### 13. Sentiment & Emotion Tracking
Track emotional tone of meetings and interactions over time.
- Detect when conversations got tense
- Trend analysis: "Meetings with engineering team are increasingly frustrated"
- **Options:** Local transformer models, TextBlob, local CLI model

### 14. Personal CRM (Relationship Intelligence)
Upgrade people graph into full relationship management.
- "You haven't talked to Maya in 45 days"
- Top contacts this quarter
- Full history before meeting someone senior
- Relationship health reminders

### 15. Task Dependency Tracking
Understand which tasks block which, and who is blocking whom.
- "4 tasks are blocked by a single unmade decision"
- Critical path visibility across all work
- Works best with graph database

### 16. Voice Commands
Control SudoBrain by speaking.
- "What's on my plate today?"
- "Add a task: review proposal by Thursday"
- Uses macOS Speech Recognition API (free, built-in)

### 17. Clipboard Intelligence
Watch clipboard and offer to capture relevant content.
- Copy a Slack message → "Save as decision for Project X?"
- Copy a phone number → "Add to Ravi's profile?"
- Passive capture, no manual effort

### 18. Meeting Scoring & Trends
Rate meeting effectiveness and track over time.
- Partially built already (meeting_score.py)
- Add trend tracking: "Standups dropped from 72 to 58 this month"
- Data-driven meeting management

### 19. Browser Extension
Capture content from web pages into SudoBrain.
- Highlight text, click "Send to SudoBrain"
- Auto-link to relevant projects and people
- **Options:** Safari Web Extension, Chrome Extension

### 20. Habit & Health Correlation
Connect health data to productivity patterns.
- "Days with 7+ hours sleep → 40% more decisions made"
- Uses Apple HealthKit (sleep, steps, heart rate)

### 21. Multi-Device Sync (iPhone Companion)
Access knowledge and capture on the go.
- Quick voice capture from phone
- Morning briefing on iPhone
- Check promises before meetings away from Mac
- **Options:** iCloud CloudKit, SQLite + iCloud Drive

---

## Already Completed

- [x] Audio recording (mic + system)
- [x] Sarvam AI transcription (Tamil/English/mixed)
- [x] Local model knowledge extraction
- [x] People graph with interaction tracking
- [x] Decision journal with calibration
- [x] Promise tracking and accountability
- [x] Cross-reference and contradiction detection
- [x] Habits, expenses, ideas tracking
- [x] Morning briefing generated from the local knowledge base
- [x] Heartbeat engine (15-min checks, persisted notifications)
- [x] Chat with FTS + semantic search
- [x] Fathom meeting integration (webhook + sync)
- [x] Guardrails and permission tiers
- [x] Structured logging and error handling
- [x] API authentication middleware
- [x] Database connection safety and indexes
- [x] Backup with 7-day retention
- [x] App logo and branding
- [x] Local LLM via Ollama (classify, summarize, extract entities, sentiment)
- [x] Neo4j knowledge graph (nodes, edges, entity relationships, graph queries)
- [x] Document ingestion (PDF, DOCX, TXT, MD → knowledge extraction → graph)
- [x] ReACT chat agent (multi-step reasoning with tool invocation)
- [x] Pre-meeting preparation (attendee context, promises, action items)
- [x] All hardcoded paths replaced with environment variable references
- [x] Neo4j installed and configured via Homebrew
- [x] All Python dependencies installed (30+ new packages)
- [x] Backend API tested with mock data (20+ endpoints verified)
- [x] Tiered model routing (model_router.py) — gemma4:e4b for fast, qwen3:14b for extract, deepseek-r1 for reasoning
- [x] Gmail integration (backend/gmail/) — read-only, knowledge extraction, Postgres storage
- [x] Google Calendar integration (backend/calendar/) — today's events, upcoming meetings, pre-meeting prep, briefing context
- [x] Calendar alerts in heartbeat — 15-min upcoming meeting notification
- [x] Slack view (SlackView.swift) — channels, messages, pending items, engagement stats
- [x] Knowledge Graph view (GraphView.swift) — Neo4j network, bottlenecks, orphaned items, person/project drill-down
- [x] ReACT chat mode toggle in ChatView — brain icon = deep reasoning, magnifying glass = simple search
- [x] AppState extended with slack, graph sections + Integrations group
- [x] Keyboard shortcuts Cmd+0 (Slack), Cmd+Shift+G (Graph)
- [x] Postgres migration — full SQLite → Postgres (psycopg2 wrapper, tsvector FTS, pg_dump backup)
- [x] /models/status and /models/refresh endpoints for runtime model management
- [x] /gmail/status, /gmail/sync, /gmail/pending, /gmail/search endpoints
- [x] /calendar/status, /calendar/today, /calendar/upcoming, /calendar/next-meeting endpoints
- [x] ChromaDB vector store with metadata filtering (#6)
- [x] Local Whisper transcription via faster-whisper (#7)
- [x] Real-time transcription via macOS Speech framework (#8)
- [x] InsightForge smart search with sub-query decomposition (#9)
- [x] Email draft generation from meeting recordings (#10)
- [x] Automated workflows/triggers engine with default rules (#11)
- [x] Weekly/monthly intelligence reports with narrative (#12)
- [x] Sentiment & emotion tracking per meeting (#13)
- [x] Personal CRM with health scoring and stale contact alerts (#14)
- [x] Task dependency tracking with critical path analysis (#15)
- [x] Voice commands via macOS Speech Recognition (#16)
- [x] Clipboard intelligence monitor (#17)
- [x] Meeting scoring trends and worst meeting analysis (#18)
- [x] Chrome browser extension for web capture (#19)
- [x] Habit & health correlation with productivity insights (#20)
- [x] 42 API endpoints tested — 40 passed (2 first-load timeouts)
