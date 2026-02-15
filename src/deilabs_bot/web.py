"""Flask web dashboard for current DeiLabs presence status."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template_string

from .db import list_current_status_snapshot

PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{{ refresh_seconds }}">
  <title>{{ title }}</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --card: #ffffff;
      --text: #1b2430;
      --muted: #6b7280;
      --online: #0d9488;
      --offline: #ef4444;
      --border: #dbe2ea;
      --shadow: 0 8px 24px rgba(23, 34, 52, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
      background: radial-gradient(circle at 10% 10%, #e9f5ff 0%, var(--bg) 55%);
      color: var(--text);
    }
    .container {
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 18px 40px;
    }
    .header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 20px;
    }
    .title {
      margin: 0;
      font-size: clamp(1.4rem, 2.5vw, 2rem);
      letter-spacing: 0.2px;
    }
    .subtitle {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .summary {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .pill {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 8px 12px;
      font-weight: 600;
      box-shadow: var(--shadow);
      font-size: 0.9rem;
    }
    .pill.online { color: var(--online); }
    .pill.offline { color: var(--offline); }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .panel {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      box-shadow: var(--shadow);
      overflow: hidden;
      min-height: 240px;
    }
    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      font-weight: 700;
    }
    .panel-header.online { color: var(--online); background: #ebfffc; }
    .panel-header.offline { color: var(--offline); background: #fff2f2; }
    .list {
      padding: 10px;
      display: grid;
      gap: 10px;
    }
    .user-card {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px;
      background: #ffffff;
    }
    .user-name {
      margin: 0 0 6px;
      font-size: 1rem;
      font-weight: 700;
    }
    .meta {
      margin: 0;
      color: var(--muted);
      font-size: 0.85rem;
      line-height: 1.4;
    }
    .empty {
      padding: 18px;
      color: var(--muted);
      font-style: italic;
    }
    @media (max-width: 900px) {
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h1 class="title">{{ title }}</h1>
        <p class="subtitle">Last refresh: {{ generated_at }} UTC</p>
      </div>
      <div class="summary">
        <div class="pill">Total: {{ total_count }}</div>
        <div class="pill online">Online: {{ online_count }}</div>
        <div class="pill offline">Offline: {{ offline_count }}</div>
      </div>
    </div>

    <div class="grid">
      <section class="panel">
        <div class="panel-header online">
          <span>Online</span>
          <span>{{ online_count }}</span>
        </div>
        {% if online %}
        <div class="list">
          {% for user in online %}
          <article class="user-card">
            <h3 class="user-name">{{ user.display_name }}</h3>
            <p class="meta">UID: {{ user.user_id }}</p>
            <p class="meta">Lab: {{ user.lab_name or '-' }}</p>
            <p class="meta">Entered: {{ user.last_entered_at or '-' }}</p>
            <p class="meta">Updated: {{ user.updated_at or '-' }}</p>
          </article>
          {% endfor %}
        </div>
        {% else %}
        <p class="empty">No one is currently marked as online.</p>
        {% endif %}
      </section>

      <section class="panel">
        <div class="panel-header offline">
          <span>Offline</span>
          <span>{{ offline_count }}</span>
        </div>
        {% if offline %}
        <div class="list">
          {% for user in offline %}
          <article class="user-card">
            <h3 class="user-name">{{ user.display_name }}</h3>
            <p class="meta">UID: {{ user.user_id }}</p>
            <p class="meta">State: {{ user.status }}</p>
            <p class="meta">Lab: {{ user.lab_name or '-' }}</p>
            <p class="meta">Updated: {{ user.updated_at or '-' }}</p>
          </article>
          {% endfor %}
        </div>
        {% else %}
        <p class="empty">No users are currently marked as offline.</p>
        {% endif %}
      </section>
    </div>
  </div>
</body>
</html>
"""


def _normalize_rows() -> List[Dict[str, Any]]:
    rows = list_current_status_snapshot()
    normalized: List[Dict[str, Any]] = []
    for user_id, username, status, lab_name, last_entered_at, updated_at in rows:
        display_name = username if username else f"user_{user_id}"
        normalized.append(
            {
                "user_id": user_id,
                "username": username,
                "display_name": display_name,
                "status": status or "unknown",
                "lab_name": lab_name or "",
                "last_entered_at": last_entered_at,
                "updated_at": updated_at,
            }
        )

    normalized.sort(key=lambda row: (row["display_name"].lower(), row["user_id"]))
    return normalized


def _split_online_offline(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    online = [row for row in rows if row["status"] == "inside"]
    offline = [row for row in rows if row["status"] != "inside"]
    return {"online": online, "offline": offline}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["DEILABS_WEB_TITLE"] = os.getenv(
        "DEILABS_WEB_TITLE",
        "DeiLabs Presence Dashboard",
    )
    app.config["DEILABS_WEB_REFRESH_SECONDS"] = int(
        os.getenv("DEILABS_WEB_REFRESH_SECONDS", "30")
    )

    @app.get("/")
    def index():
        rows = _normalize_rows()
        split = _split_online_offline(rows)
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return render_template_string(
            PAGE_TEMPLATE,
            title=app.config["DEILABS_WEB_TITLE"],
            refresh_seconds=app.config["DEILABS_WEB_REFRESH_SECONDS"],
            generated_at=generated_at,
            total_count=len(rows),
            online=split["online"],
            offline=split["offline"],
            online_count=len(split["online"]),
            offline_count=len(split["offline"]),
        )

    @app.get("/api/status")
    def api_status():
        rows = _normalize_rows()
        split = _split_online_offline(rows)
        return jsonify(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total": len(rows),
                "online_count": len(split["online"]),
                "offline_count": len(split["offline"]),
                "online": split["online"],
                "offline": split["offline"],
            }
        )

    @app.get("/health")
    def health():
        return jsonify({"ok": True}), 200

    return app


def main() -> None:
    app = create_app()
    host = os.getenv("DEILABS_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("DEILABS_WEB_PORT", "8080"))
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
