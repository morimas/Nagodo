import sys
import re
import ssl
import html
from datetime import datetime, timedelta, timezone
import urllib.request
import os

# ==============================================================================
# 設定項目
# ==============================================================================
BASE_URL = "https://www.nagoya-dome.co.jp/sp/eventcalen.php"

# 関係者イベントを非表示にする場合は True、表示する場合は False
HIDE_PRIVATE_EVENTS = True

# 日本時間（JST）の定義
JST = timezone(timedelta(hours=9))

# ==============================================================================
# 日付計算ロジック
# ==============================================================================
def get_target_date_range(base_date):
    """
    軸となる日(base_date)当日から「2回目の日曜日」までの日付リストを計算します。
    - 実行日が日曜日の場合：当日の日曜日(1回目) ＋ 7日後(2回目)
    - 実行日が月〜土曜日の場合：直近の日曜日(1回目) ＋ 7日後(2回目)
    """
    start_date = base_date

    # 1回目の日曜日までの日数を計算
    days_to_first_sunday = (6 - start_date.weekday()) % 7

    # 1回目の日曜日に 7日 を加えて「2回目の日曜日」の到達日を算出
    days_to_second_sunday = days_to_first_sunday + 7
    end_date = start_date + timedelta(days=days_to_second_sunday)

    target_dates = []
    curr = start_date
    while curr <= end_date:
        target_dates.append(curr)
        curr += timedelta(days=1)
    return target_dates

# ==============================================================================
# データ取得・解析処理
# ==============================================================================
def collect_schedule_data(base_date):
    """
    対象期間のイベントデータを取得し、日付ごとに整理したリストを返す。
    サイト側がyear/monthパラメータを無視して常に約1年分の全期間データを
    一括で返却する仕様であるため、リクエストは1回のみとし、取得した全データの
    中から対象期間分のみを(月,日)一致で抽出する方式としている。
    """
    target_dates = get_target_date_range(base_date)
    events_by_date = {}
    target_md_set = set((d.month, d.day) for d in target_dates)

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    }

    target_url = f"{BASE_URL}?year={base_date.year}&month={base_date.month:02d}"
    fetch_error = None

    try:
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=ssl_context) as resp:
            raw_bytes = resp.read()
            try:
                html_text = raw_bytes.decode('utf-8')
            except UnicodeDecodeError:
                html_text = raw_bytes.decode('shift_jis', errors='ignore')

            # &nbsp; 等のHTML実体参照を通常テキストに変換
            html_text = html.unescape(html_text)

            compact_html = html_text.replace('\r', '').replace('\n', '')
            cell_blocks = re.split(r'<(?:tr|td|li|div)[^>]*>', compact_html, flags=re.IGNORECASE)

            current_key = None

            for block in cell_blocks:
                text_content = re.sub(r'<[^>]+>', ' ', block).strip()
                text_content = re.sub(r'\s+', ' ', text_content)

                if not text_content:
                    continue

                # 日付の検出（例: 9/9, 9月9日 など）
                date_match = re.search(r'(\d{1,2})[/\u6708](\d{1,2})', text_content)

                if date_match:
                    found_m = int(date_match.group(1))
                    found_d = int(date_match.group(2))

                    if (found_m, found_d) in target_md_set:
                        current_key = (found_m, found_d)
                        if current_key not in events_by_date:
                            events_by_date[current_key] = []

                        after_date_text = text_content[date_match.end():].strip()
                        after_date_text = re.sub(r'^\s*[\(（]\s*[月火水木金土日]\s*[\)）]', '', after_date_text).strip()

                        if len(after_date_text) > 2 and not re.search(r'^(トップ|カレンダー|HOME)', after_date_text):
                            events_by_date[current_key].append(after_date_text)
                    else:
                        # 対象期間外の日付が見つかった場合はcurrent_keyを解除する
                        current_key = None

                elif current_key is not None:
                    # 「◯月は予定がありません」等の月境界メッセージは日付を持たないため
                    # ここで明示的に除外しないと、直前の対象日に誤って吸着してしまう
                    if re.search(r'予定がありません', text_content):
                        continue

                    # システムナビゲーション要素を除外して同日のテキストをすべて配列に格納
                    if len(text_content) > 1 and not re.search(r'^(トップ|カレンダー|HOME|pagetop|次へ|前へ|戻る|イベント|バンテリン|URL)', text_content, re.IGNORECASE):
                        if text_content not in events_by_date[current_key]:
                            events_by_date[current_key].append(text_content)

    except Exception as err:
        fetch_error = str(err)

    schedule_list = []
    for current_date in target_dates:
        key = (current_date.month, current_date.day)
        raw_items = events_by_date.get(key, [])

        if not raw_items:
            continue

        times = [item for item in raw_items if "開場" in item or "開始" in item]
        titles = [item for item in raw_items if "開場" not in item and "開始" not in item]

        valid_events = []
        max_len = max(len(titles), len(times))
        for i in range(max_len):
            title = titles[i] if i < len(titles) else ""
            time_info = times[i] if i < len(times) else ""

            if HIDE_PRIVATE_EVENTS and "関係者イベント" in title:
                continue

            if title or time_info:
                valid_events.append((title, time_info))

        if valid_events:
            weekday_num = current_date.weekday()
            weekday_kanji = ["月", "火", "水", "木", "金", "土", "日"][weekday_num]
            schedule_list.append((current_date, weekday_num, weekday_kanji, valid_events))

    return schedule_list, target_dates, fetch_error

# ==============================================================================
# コンソール出力（クラウド実行ログ確認用）
# ==============================================================================
def print_console(schedule_list, target_dates, fetch_error):
    range_start_str = target_dates[0].strftime("%Y/%m/%d")
    range_end_str = target_dates[-1].strftime("%Y/%m/%d")

    print(f"バンテリンドーム ナゴヤ イベントスケジュール 対象期間: {range_start_str} 〜 {range_end_str}")

    if fetch_error:
        print(f"通信注意: イベントデータ取得に失敗しました ({fetch_error})")

    total_event_count = 0
    for current_date, weekday_num, weekday_kanji, valid_events in schedule_list:
        formatted_date = current_date.strftime(f"%Y年%m月%d日({weekday_kanji})")
        print(f"{formatted_date}")
        for title, time_info in valid_events:
            if title:
                print(f"  - {title}")
            if time_info:
                print(f"  - {time_info}")
            total_event_count += 1

    print(f"該当イベント数: 計 {total_event_count} 件")

# ==============================================================================
# HTML出力（GitHub Pages公開用）
# ==============================================================================
def generate_html(schedule_list, target_dates, fetch_error):
    """
    Android等のスマートフォンブラウザで閲覧しやすい、レスポンシブな単一HTMLファイルを生成する。
    リポジトリ直下に index.html として出力し、GitHub Pagesがそのまま公開する。
    """
    range_start_str = target_dates[0].strftime("%Y/%m/%d")
    range_end_str = target_dates[-1].strftime("%Y/%m/%d")
    generated_at = datetime.now(JST).strftime("%Y/%m/%d %H:%M")

    rows_html = ""
    total_event_count = 0

    for current_date, weekday_num, weekday_kanji, valid_events in schedule_list:
        formatted_date_raw = current_date.strftime(f"%Y年%m月%d日({weekday_kanji})")

        if weekday_num == 5:
            date_class = "sat"
        elif weekday_num == 6:
            date_class = "sun"
        else:
            date_class = "normal"

        items_html = ""
        for title, time_info in valid_events:
            if title:
                items_html += f"<li>{html.escape(title)}</li>"
            if time_info:
                items_html += f"<li class=\"time\">{html.escape(time_info)}</li>"
            total_event_count += 1

        rows_html += (
            f"<section class=\"day\">"
            f"<h2 class=\"{date_class}\">{formatted_date_raw}</h2>"
            f"<ul>{items_html}</ul>"
            f"</section>"
        )

    error_html = ""
    if fetch_error:
        error_html = f"<p class=\"error\">通信注意: イベントデータ取得に失敗しました ({html.escape(fetch_error)})</p>"

    if total_event_count == 0:
        rows_html = "<p class=\"empty\">対象期間中に該当する一般イベントはありません。</p>"

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>バンテリンドーム ナゴヤ イベントスケジュール</title>
<style>
body {{ font-family: sans-serif; margin: 0; padding: 16px; background: #f5f5f5; color: #222; }}
h1 {{ font-size: 1.3em; margin-bottom: 4px; }}
.range {{ color: #555; font-size: 0.9em; margin-bottom: 16px; }}
.day {{ background: #fff; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.day h2 {{ font-size: 1.05em; margin: 0 0 8px 0; }}
.day h2.sat {{ color: #1565c0; }}
.day h2.sun {{ color: #c62828; }}
.day ul {{ margin: 0; padding-left: 1.2em; }}
.day li.time {{ color: #666; font-size: 0.9em; }}
.error {{ color: #c62828; }}
.empty {{ color: #555; }}
.footer {{ color: #999; font-size: 0.8em; margin-top: 20px; text-align: center; }}
</style>
</head>
<body>
<h1>バンテリンドーム ナゴヤ イベントスケジュール</h1>
<div class="range">対象期間: {range_start_str} 〜 {range_end_str}</div>
{error_html}
{rows_html}
<div class="footer">最終更新: {generated_at}</div>
</body>
</html>
"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)

# ==============================================================================
# 実行部
# ==============================================================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            base_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            base_date = datetime.now(JST).date()
    else:
        base_date = datetime.now(JST).date()

    schedule_list, target_dates, fetch_error = collect_schedule_data(base_date)
    print_console(schedule_list, target_dates, fetch_error)
    generate_html(schedule_list, target_dates, fetch_error)
