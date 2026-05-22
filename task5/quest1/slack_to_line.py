"""Slackチャンネルのメッセージを取得し、Claudeで要約してLINEに送信するプロトタイプ。

使い方:
    python slack_to_line.py

環境変数(.env)で設定する項目は .env.example を参照。
"""

import os
import sys
import time

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_TO = os.environ["LINE_TO"]
# ANTHROPIC_API_KEY は anthropic SDK が環境変数から自動で読み込む

SUMMARY_HOURS = float(os.environ.get("SUMMARY_HOURS", "24"))
LINE_TEXT_LIMIT = 5000  # LINEのテキストメッセージ上限


def fetch_slack_messages(channel_id: str, hours: float) -> list[dict]:
    """指定チャンネルの直近 hours 時間のメッセージを取得する。"""
    oldest = time.time() - hours * 3600
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    messages: list[dict] = []
    cursor = None

    while True:
        params = {"channel": channel_id, "oldest": oldest, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(
            "https://slack.com/api/conversations.history",
            headers=headers,
            params=params,
            timeout=30,
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")

        messages.extend(data.get("messages", []))

        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    # 古い順に並べ替え、テキストのある通常メッセージのみ残す
    messages.sort(key=lambda m: float(m["ts"]))
    return [m for m in messages if m.get("text") and m.get("type") == "message"]


def resolve_user_names(messages: list[dict]) -> dict[str, str]:
    """メッセージに登場するユーザーIDを表示名に解決する。"""
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    names: dict[str, str] = {}
    for user_id in {m.get("user") for m in messages if m.get("user")}:
        resp = requests.get(
            "https://slack.com/api/users.info",
            headers=headers,
            params={"user": user_id},
            timeout=30,
        )
        data = resp.json()
        if data.get("ok"):
            profile = data["user"]["profile"]
            names[user_id] = (
                profile.get("display_name") or profile.get("real_name") or user_id
            )
        else:
            names[user_id] = user_id
    return names


def format_transcript(messages: list[dict], names: dict[str, str]) -> str:
    """メッセージ一覧を「名前: 本文」形式のテキストに整形する。"""
    lines = []
    for m in messages:
        name = names.get(m.get("user", ""), m.get("user", "不明"))
        lines.append(f"{name}: {m['text']}")
    return "\n".join(lines)


def summarize(transcript: str) -> str:
    """Claudeで会話を要約する。"""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2000,
        system=(
            "あなたはSlackチャンネルの会話を要約するアシスタントです。"
            "日本語で、要点を箇条書きで簡潔にまとめてください。"
            "決定事項・TODO・重要な議論があれば優先的に拾ってください。"
        ),
        messages=[
            {
                "role": "user",
                "content": f"以下のSlackの会話を要約してください。\n\n{transcript}",
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def send_line(text: str) -> None:
    """LINE Messaging APIでテキストをpush送信する。"""
    if len(text) > LINE_TEXT_LIMIT:
        text = text[: LINE_TEXT_LIMIT - 1] + "…"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {"to": LINE_TO, "messages": [{"type": "text", "text": text}]}
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=headers,
        json=body,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"LINE API error: {resp.status_code} {resp.text}")


def main() -> None:
    print(f"Slackから直近{SUMMARY_HOURS}時間のメッセージを取得中...")
    messages = fetch_slack_messages(SLACK_CHANNEL_ID, SUMMARY_HOURS)
    if not messages:
        print("対象メッセージがありませんでした。")
        send_line(f"直近{SUMMARY_HOURS:.0f}時間の新着メッセージはありませんでした。")
        return

    print(f"{len(messages)}件のメッセージを取得。ユーザー名を解決中...")
    names = resolve_user_names(messages)
    transcript = format_transcript(messages, names)

    print("Claudeで要約中...")
    summary = summarize(transcript)

    print("LINEに送信中...")
    send_line(f"【Slackまとめ（直近{SUMMARY_HOURS:.0f}時間）】\n\n{summary}")
    print("完了しました。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
