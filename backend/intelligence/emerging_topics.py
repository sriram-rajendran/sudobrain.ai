"""Topic emergence detector.

Compares token/phrase frequency in the last N days vs the prior 4×N days
to find topics with big jumps — the "what's new this week".

Uses simple TF-based delta, filtered by stop words and minimum length.
"""

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection


STOPWORDS = {
    "the","a","an","and","or","but","is","are","was","were","to","of","in","for","on","at","by",
    "with","from","that","this","it","as","be","have","has","had","do","does","did","will","would",
    "can","could","should","may","might","there","their","they","we","you","i","me","my","our",
    "us","your","he","she","him","her","its","if","then","so","not","no","yes","ok","okay","like",
    "just","get","got","go","gone","also","here","now","hi","hello","please","thanks","thank","let",
    "know","make","made","take","took","see","seen","look","looking","what","who","how","when","why",
    "which","these","those","up","down","out","back","over","all","any","some","one","two","three",
    "about","after","before","into","than","too","very","really","also","only","even","per","via",
    "via","ive","im","dont","didnt","wasnt","isnt","wont","youre","weve","theres","thats","wasnt",
    "something","someone","anything","everyone","lets","cant","wont","didnt","havent","hasnt",
    "amp","gt","lt","http","https","com","www","cc","bcc","re","fwd","linear","slack","gmail",
    "message","channel","thread","email","app","page","update","need","add","added","show","side",
    "actually","still","would","could","should","may","might","check","checked","check","run","good",
    "issue","bug","fix","fixed","work","working","works","worked","code","ticket","user","users",
    "team","teams","call","calling","talk","talked","time","day","week","today","tomorrow","yesterday",
}


def _tokens(text: str) -> list[str]:
    if not text:
        return []
    # simple alphanumeric tokens, min length 4
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]{3,}", text.lower())
    return [w for w in words if w not in STOPWORDS]


def _ngrams(tokens: list[str], n: int = 2) -> list[str]:
    return [" ".join(tokens[i:i+n]) for i in range(len(tokens) - n + 1)]


def compute_emerging_topics(window_days: int = 7, min_count: int = 3) -> dict:
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=window_days)
    baseline_start = now - timedelta(days=window_days * 5)
    baseline_end = recent_start

    conn = get_connection()
    try:
        recent_rows = conn.execute(
            "SELECT text FROM slack_messages "
            "WHERE message_at >= ? AND message_at < ? "
            "  AND is_bot_message = FALSE AND length(text) > 20",
            (recent_start, now),
        ).fetchall()
        baseline_rows = conn.execute(
            "SELECT text FROM slack_messages "
            "WHERE message_at >= ? AND message_at < ? "
            "  AND is_bot_message = FALSE AND length(text) > 20",
            (baseline_start, baseline_end),
        ).fetchall()
    finally:
        conn.close()

    def count_all(rows):
        c1, c2 = Counter(), Counter()
        for r in rows:
            toks = _tokens(r["text"])
            c1.update(toks)
            c2.update(_ngrams(toks, 2))
        return c1, c2

    r_uni, r_bi = count_all(recent_rows)
    b_uni, b_bi = count_all(baseline_rows)

    recent_days = window_days
    baseline_days = window_days * 4  # ratio normalization

    def compute_emerging(recent: Counter, baseline: Counter) -> list[dict]:
        items = []
        for term, rc in recent.items():
            if rc < min_count:
                continue
            bc = baseline.get(term, 0)
            # Normalize by window length (baseline is 4x as long)
            baseline_rate = bc / baseline_days if baseline_days else 0
            recent_rate = rc / recent_days
            if baseline_rate == 0:
                ratio = float("inf") if rc >= min_count else 0
            else:
                ratio = recent_rate / baseline_rate
            if ratio < 2.0:
                continue
            items.append({
                "term": term,
                "recent_count": rc,
                "baseline_count": bc,
                "ratio": round(ratio, 2) if ratio != float("inf") else "new",
            })
        items.sort(key=lambda d: (d["ratio"] == "new", -d["recent_count"]), reverse=False)
        return items

    unigrams = compute_emerging(r_uni, b_uni)[:25]
    bigrams = compute_emerging(r_bi, b_bi)[:25]

    return {
        "window_days": window_days,
        "recent_messages": len(recent_rows),
        "baseline_messages": len(baseline_rows),
        "emerging_terms": unigrams,
        "emerging_phrases": bigrams,
    }
