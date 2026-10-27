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

# ==============================================================================
# コンソールカラー定義（ANSI Escape Code）
# Windows標準コマンドプロンプト用のVT100エスケープシーケンス有効化
# ==============================================================================
os.system('')  # Windows環境でのANSIエスケープシーケンスを有効化

COLOR_BLUE = "\033[94m"   # 土曜日用（明るい青）
COLOR_RED = "\033[91m"    # 日曜日用（明るい赤）
COLOR_RESET = "\033[0m"   # 色リセット

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

    print("＋--------------------------------------------------＋")
    print(f"  バンテリンドーム ナゴヤ イベントスケジュール")
    print(f"  対象期間: {range_start_str} 〜 {range_end_str}")
    if HIDE_PRIVATE_EVENTS:
        print("  ※関係者イベントは除外して表示中")
    print("＋--------------------------------------------------＋\n")

    events_by_date = {}
    years_months = set((d.year, d.month) for d in target_dates)

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    }

    for y, m in years_months:
        target_url = f"{BASE_URL}?year={y}&month={m:02d}"
        
        try:
            req = urllib.request.Request(target_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15, context=ssl_context) as resp:
                    raw_bytes = resp.read()
                    try:
                        html_text = raw_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        html_text = raw_bytes.decode('shift_jis', errors='ignore')

                    html_text = html.unescape(html_text)
                    cells = re.findall(r'<td[^>]*>(.*?)</td>', html_text, flags=re.DOTALL | re.IGNORECASE)

                    for cell in cells:
                        date_match = re.search(r'(\d{1,2})[/\u6708](\d{1,2})[\u65e5]?', cell)
                        if not date_match:
                            continue

                        found_m = int(date_match.group(1))
                        found_d = int(date_match.group(2))

                        if found_m != m:
                            continue

                        date_key = (m, found_d)
                        if date_key not in events_by_date:
                            events_by_date[date_key] = []

                        lines = re.split(r'<br\s*/?>', cell, flags=re.IGNORECASE)
                        for line in lines:
                            clean_text = re.sub(r'<[^>]+>', ' ', line).strip()
                            clean_text = re.sub(r'\s+', ' ', clean_text)

                            if not clean_text:
                                continue

                            if re.search(r'(TOUR|LIVE|フェス|マラソン|トップ|カレンダー|HOME|インフォメーション|2026年|2027年)', clean_text):
                                continue
                            if any(kw in clean_text for kw in ["Anniversary", "トライアウト", "WORLD TOUR", "BLOOD SAGA", "Romantic Tour", "No.III", "愛知2027"]):
                                continue

                            if not re.search(r'^\d{1,2}[/\u6708]\d{1,2}[\u65e5]?$', clean_text):
                                if clean_text not in events_by_date[date_key]:
                                    events_by_date[date_key].append(clean_text)

            except urllib.error.HTTPError as e:
                # 404などのHTTPエラー時は該当月にデータ（ページ）が無いものとして静かにスキップ
                if e.code == 404:
                    continue
                else:
                    print(f"[通信注意] {y}年{m}月のデータ取得に失敗しました (HTTP Error {e.code})")
            except Exception as e:
                print(f"[通信注意] {y}年{m}月のデータ取得エラー: {e}")

        except Exception as err:
            print(f"[通信注意] {y}年{m}月の処理に失敗しました ({err})")

    total_event_count = 0

    # 対象期間の日付順に出力
    for current_date in target_dates:
        key = (current_date.month, current_date.day)
        raw_items = events_by_date.get(key, [])

        if raw_items:
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
                formatted_date_raw = current_date.strftime(f"%Y年%m月%d日({weekday_kanji})")

                if weekday_num == 5:
                    display_date = f"{COLOR_BLUE}{formatted_date_raw}{COLOR_RESET}"
                elif weekday_num == 6:
                    display_date = f"{COLOR_RED}{formatted_date_raw}{COLOR_RESET}"
                else:
                    display_date = formatted_date_raw

                print(f"■ {display_date}")

                for title, time_info in valid_events:
                    if title:
                        print(f"   │")
                        print(f"   └─ {title}")
                    if time_info:
                        print(f"   │")
                        print(f"   └─ {time_info}")
                    
                    total_event_count += 1
                print()

    print("----------------------------------------------------")
    if total_event_count == 0:
        print(" 対象期間中に該当する一般イベントはありません。")
    else:
        print(f" 該当イベント数: 計 {total_event_count} 件")
    print("----------------------------------------------------")

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
        print(f"\nエラーが発生しました: {e}")
    finally:
        print("\n")
        input("Enterキーを押すと終了します...")
