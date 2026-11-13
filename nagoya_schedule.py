import sys
import re
import ssl
import html
from datetime import datetime, timedelta
import urllib.request
import os

# ==============================================================================
# 設定項目
# ==============================================================================
BASE_URL = "https://www.nagoya-dome.co.jp/sp/eventcalen.php"

# 関係者イベントを非表示にする場合は True、表示する場合は False
HIDE_PRIVATE_EVENTS = True

# 出力ファイル名（GitHub Pages等の公開ファイル）
OUTPUT_FILENAME = "index.html"

# ==============================================================================
# コンソールカラー定義（ANSI Escape Code）
# ==============================================================================
os.system('')  # Windows環境でのANSIエスケープシーケンスを有効化

COLOR_BLUE = "\033[94m"   # 土曜日用（明るい青）
COLOR_RED = "\033[91m"    # 日曜日・祝日用（明るい赤）
COLOR_RESET = "\033[0m"   # 色リセット

# ==============================================================================
# ノイズ（不要な会社名・電話番号・入庫案内等）のクレンジング処理
# ==============================================================================
def clean_noise(text):
    if not text:
        return ""
    
    # 電話番号の削除
    text = re.sub(r'\d{2,4}-\d{2,4}-\d{4}', '', text)
    text = re.sub(r'0570-\d{3}-\d{3}', '', text)
    
    # 入庫情報の削除
    text = re.sub(r'※\s*\d{1,2}:\d{2}\s*入庫開始', '', text)
    
    # 営業時間やナビダイヤルの削除
    text = re.sub(r'（全日[^）]+）', '', text)
    text = re.sub(r'（ナビダイヤル）', '', text)
    
    # プロモーション会社名等の削除
    ignore_phrases = [
        "サンデーフォークプロモーション",
        "中日ドラゴンズコールセンター",
    ]
    for p in ignore_phrases:
        text = text.replace(p, '')
        
    return text.strip()

# ==============================================================================
# 除外対象のシステム文字列判定
# ==============================================================================
def is_system_text(text):
    exact_ignore_words = {
        "トップ", "カレンダー", "HOME", "pagetop", "次へ", "前へ", "戻る", 
        "イベント", "バンテリン", "URL", "インフォメーション", "ニュース＆トピックス",
        "フロアマップ", "売店検索", "ドラゴンズ観戦チケット", "SNS応援メッセージ",
        "草野球", "交通アクセス", "ご来場の皆様へ", "ページ上部へ", "PCサイト",
        "メニュー", "ホーム", "プライバシーポリシー", "サイトマップ"
    }
    if text in exact_ignore_words:
        return True
    if re.search(r'予定がありません', text):
        return True
    return False

# ==============================================================================
# 日付計算ロジック
# ==============================================================================
def get_target_date_range(base_date):
    start_date = base_date
    days_to_first_sunday = (6 - start_date.weekday()) % 7
    days_to_second_sunday = days_to_first_sunday + 7
    end_date = start_date + timedelta(days=days_to_second_sunday)
    
    target_dates = []
    curr = start_date
    while curr <= end_date:
        target_dates.append(curr)
        curr += timedelta(days=1)
    return target_dates

# ==============================================================================
# メイン処理
# ==============================================================================
def fetch_schedule(base_date):
    target_dates = get_target_date_range(base_date)
    if not target_dates:
        return

    range_start_str = target_dates[0].strftime("%Y/%m/%d")
    range_end_str = target_dates[-1].strftime("%Y/%m/%d")

    console_lines = []
    html_lines = []

    def log(message="", html_message=None):
        print(message)
        console_lines.append(message)
        html_lines.append(html_message if html_message is not None else html.escape(message))

    # 冒頭はシンプルに対象期間の1行のみ
    log(f"対象期間: {range_start_str} 〜 {range_end_str}", f"対象期間: {range_start_str} 〜 {range_end_str}")
    log("", "")

    events_by_date = {}
    years_months = set((d.year, d.month) for d in target_dates)

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    }

    for y, m in years_months:
        target_url = f"{BASE_URL}?year={y}&month={m:02d}"
        
        try:
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15, context=ssl_context) as resp:
                raw_bytes = resp.read()
                try:
                    html_text = raw_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    html_text = raw_bytes.decode('shift_jis', errors='ignore')

                html_text = html.unescape(html_text)
                
                cells = re.findall(r'<td[^>]*>(.*?)</td>', html_text, flags=re.DOTALL | re.IGNORECASE)
                if not cells:
                    cells = re.findall(r'<(?:div|li|p)[^>]*>(.*?)<\/(?:div|li|p)>', html_text, flags=re.DOTALL | re.IGNORECASE)

                current_key = None

                for cell in cells:
                    text_content = re.sub(r'<[^>]+>', ' ', cell).strip()
                    text_content = re.sub(r'\s+', ' ', text_content)

                    if not text_content:
                        continue

                    date_match = re.search(r'(\d{1,2})[/\u6708](\d{1,2})[\u65e5]?', text_content)
                    if date_match:
                        found_m = int(date_match.group(1))
                        found_d = int(date_match.group(2))

                        if found_m == m:
                            current_key = (m, found_d)
                            if current_key not in events_by_date:
                                events_by_date[current_key] = []

                            after_text = text_content[date_match.end():].strip()
                            after_text = re.sub(r'^\s*[\(（]\s*[月火水木金土日祝・・/]+\s*[\)）]', '', after_text).strip()
                            
                            cleaned_after = clean_noise(after_text)
                            if len(cleaned_after) > 1 and not is_system_text(cleaned_after):
                                if cleaned_after not in events_by_date[current_key]:
                                    events_by_date[current_key].append(cleaned_after)
                            continue

                    if current_key is not None:
                        lines = re.split(r'<br\s*/?>', cell, flags=re.IGNORECASE)
                        for line in lines:
                            clean_line = re.sub(r'<[^>]+>', ' ', line).strip()
                            clean_line = re.sub(r'\s+', ' ', clean_line)

                            if not clean_line:
                                continue
                            if is_system_text(clean_line):
                                continue
                            if re.search(r'^\d{1,2}[/\u6708](\d{1,2})[\u65e5]?$', clean_line):
                                continue

                            cleaned_text = clean_noise(clean_line)
                            if cleaned_text and len(cleaned_text) > 1:
                                if cleaned_text not in events_by_date[current_key]:
                                    events_by_date[current_key].append(cleaned_text)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            else:
                log(f"[通信注意] {y}年{m}月のデータ取得に失敗しました (HTTP Error {e.code})")
        except Exception as e:
            log(f"[通信注意] {y}年{m}月のデータ取得エラー: {e}")

    total_event_count = 0

    for current_date in target_dates:
        key = (current_date.month, current_date.day)
        raw_items = events_by_date.get(key, [])

        if raw_items:
            times = []
            titles = []
            
            for item in raw_items:
                found_times = re.findall(r'\d{1,2}:\d{2}', item)
                for t in found_times:
                    if t not in times:
                        times.append(t)
                
                pure_title = re.sub(r'\d{1,2}:\d{2}', '', item).strip()
                pure_title = re.sub(r'[／〜～]', ' ', pure_title).strip()
                pure_title = re.sub(r'\s+', ' ', pure_title)
                
                if pure_title in ["開場", "開始", "／", "開場 開始", ""] or re.match(r'^[開場開始\s／]+$', pure_title):
                    continue
                
                if pure_title and len(pure_title) > 1:
                    if not is_system_text(pure_title):
                        if HIDE_PRIVATE_EVENTS and "関係者イベント" in pure_title:
                            continue
                        if pure_title not in titles:
                            titles.append(pure_title)

            time_str = ""
            if len(times) >= 2:
                time_str = f"開始 {times[1]}（開場 {times[0]}）"
            elif len(times) == 1:
                time_str = f"開始 {times[0]}"

            valid_events = []
            seen_titles = set()
            for title in titles:
                if title not in seen_titles:
                    seen_titles.add(title)
                    valid_events.append(title)

            if valid_events or time_str:
                weekday_num = current_date.weekday()
                weekday_kanji = ["月", "火", "水", "木", "金", "土", "日"][weekday_num]
                
                is_holiday = any("祝" in str(item) for item in raw_items) or (weekday_num == 6)
                is_saturday = (weekday_num == 5)

                formatted_date_raw = current_date.strftime(f"%Y年%m月%d日({weekday_kanji})")

                # コンソール用カラー
                if is_saturday:
                    display_date_con = f"{COLOR_BLUE}{formatted_date_raw}{COLOR_RESET}"
                elif is_holiday:
                    display_date_con = f"{COLOR_RED}{formatted_date_raw}{COLOR_RESET}"
                else:
                    display_date_con = formatted_date_raw

                # HTML用カラー（土曜:青、日曜祝日:赤）
                if is_saturday:
                    display_date_html = f'<span style="color: #0066cc; font-weight: bold;">{html.escape(formatted_date_raw)}</span>'
                elif is_holiday:
                    display_date_html = f'<span style="color: #cc0000; font-weight: bold;">{html.escape(formatted_date_raw)}</span>'
                else:
                    display_date_html = f'<span style="font-weight: bold;">{html.escape(formatted_date_raw)}</span>'

                log(f"{display_date_con}", f"{display_date_html}")

                for title in valid_events:
                    log(f"   └─ {title}", f"   └─ {html.escape(title)}")
                    total_event_count += 1
                
                if time_str:
                    log(f"   └─ {time_str}", f"   └─ {html.escape(time_str)}")
                
                log("", "")

    log("----------------------------------------------------", "----------------------------------------------------")
    if total_event_count == 0:
        log("対象期間中に該当する一般イベントはありません。", "対象期間中に該当する一般イベントはありません。")
    else:
        log(f"該当イベント数: 計 {total_event_count} 件", f"該当イベント数: 計 {total_event_count} 件")
    log(f"最終更新: {datetime.now().strftime('%Y/%m/%d %H:%M')}", f"最終更新: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    log("----------------------------------------------------", "----------------------------------------------------")

    joined_html_lines = '\n'.join(html_lines)
    
    html_output = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>バンテリンドーム ナゴヤ イベントスケジュール</title>
    <style>
        body {{ font-family: monospace, sans-serif; background: #f4f4f4; padding: 20px; color: #333; }}
        pre {{ background: #fff; padding: 15px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); font-size: 14px; line-height: 1.5; }}
    </style>
</head>
<body>
    <pre>{joined_html_lines}</pre>
</body>
</html>
"""

    with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
        f.write(html_output)
    
    print(f"\n[情報] 結果を {OUTPUT_FILENAME} に正常に書き出しました。")

# ==============================================================================
# 実行部
# ==============================================================================
if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            try:
                base_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
            except ValueError:
                base_date = datetime.now().date()
        else:
            base_date = datetime.now().date()

        fetch_schedule(base_date)
    except Exception as e:
        print(f"\nエラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if not os.getenv("CI"):
            try:
                print("\n")
                input("Enterキーを押すと終了します...")
            except (KeyboardInterrupt, EOFError):
                pass
