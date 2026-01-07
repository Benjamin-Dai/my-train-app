import requests
import json
import os
import sys
from datetime import datetime, timedelta

# ================= 設定區 =================
# 為了方便偵錯，我們強制輸出緩衝區，確保 Log 即時顯示
sys.stdout.reconfigure(encoding='utf-8')

CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_NAME = '屏東'
END_STATION_NAME = '潮州'

# TDX V3 API URL 基礎
API_BASE_URL = "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA"
# =========================================

def log(msg):
    """加上時間戳記的 Log 函式"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

class TrainApp:
    def __init__(self, cid, csecret):
        self.cid = cid
        self.csecret = csecret
        self.token = None
        self.station_map = {} # 儲存 { '屏東': '5000', ... }

    def get_token(self):
        log("正在取得 Access Token...")
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        try:
            res = requests.post(auth_url, data={
                'grant_type': 'client_credentials',
                'client_id': self.cid,
                'client_secret': self.csecret
            })
            if res.status_code == 200:
                self.token = res.json().get('access_token')
                log("Token 取得成功")
                return self.token
            else:
                log(f"Token 取得失敗: {res.text}")
                return None
        except Exception as e:
            log(f"Token 請求發生例外: {e}")
            return None

    def get_station_ids(self):
        """
        V3 查詢通常需要 StationID，這裡先抓一次車站列表來做名稱對應
        """
        log("正在下載車站列表以取得 StationID...")
        url = f"{API_BASE_URL}/Station"
        headers = {'authorization': f'Bearer {self.token}'}
        
        try:
            res = requests.get(url, headers=headers)
            if res.status_code != 200:
                log(f"車站列表下載失敗: {res.status_code} - {res.text}")
                return False
            
            stations = res.json()
            # 建立 名稱 -> ID 的對應表
            for s in stations:
                name = s['StationName']['Zh_tw']
                sid = s['StationID']
                self.station_map[name] = sid
            
            start_id = self.station_map.get(START_STATION_NAME)
            end_id = self.station_map.get(END_STATION_NAME)
            
            log(f"車站對應結果: {START_STATION_NAME}->{start_id}, {END_STATION_NAME}->{end_id}")
            
            if not start_id or not end_id:
                log("❌ 找不到起點或終點的 StationID，請檢查站名設定")
                return False
                
            return True
        except Exception as e:
            log(f"取得車站列表時發生例外: {e}")
            return False

    def fetch_data(self):
        if not self.token and not self.get_token():
            return []
        
        # 步驟 1: 取得車站 ID
        if not self.get_station_ids():
            return []

        start_id = self.station_map.get(START_STATION_NAME)
        end_id = self.station_map.get(END_STATION_NAME)
        
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        
        headers = {'authorization': f'Bearer {self.token}'}

        # 步驟 2: 使用 OD (起訖) 查詢 API (這是 V3 的精華，直接抓兩站之間的車)
        # 格式: /DailyTrainTimetable/OD/{OriginStationID}/to/{DestinationStationID}/{TrainDate}
        timetable_url = f"{API_BASE_URL}/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{today_str}"
        
        # 步驟 3: 取得即時誤點資訊
        delay_url = f"{API_BASE_URL}/LiveTrainDelay"

        try:
            log(f"正在抓取時刻表 (V3 OD): {timetable_url}")
            res = requests.get(timetable_url, headers=headers)
            
            if res.status_code != 200:
                log(f"❌ 時刻表請求失敗: {res.status_code}")
                log(f"回應內容: {res.text[:500]}") # 印出前500字錯誤訊息
                return []
            
            timetable_data = res.json()
            trains_count = len(timetable_data.get('TrainTimetables', [])) # V3 結構通常包在 TrainTimetables 裡
            log(f"時刻表下載成功，共找到 {trains_count} 班次")

            # --- DEBUG: 印出第一筆資料的結構，讓我們確認 V3 的欄位名稱 ---
            if trains_count > 0:
                first_train = timetable_data['TrainTimetables'][0]
                log("--- DEBUG: 第一筆列車資料結構 ---")
                log(json.dumps(first_train, indent=2, ensure_ascii=False))
                log("--------------------------------")
            # -----------------------------------------------------

            log(f"正在抓取誤點資訊 (V3): {delay_url}")
            delay_res = requests.get(delay_url, headers=headers)
            if delay_res.status_code != 200:
                log(f"❌ 誤點資訊請求失敗: {res.status_code}")
                return []
            
            delay_data = delay_res.json()
            # V3 的誤點資料結構可能也不同，我們這裡做個保護
            delays = {}
            if 'LiveTrainDelay' in delay_data: # 有時候會包一層
                delay_list = delay_data['LiveTrainDelay']
            else:
                delay_list = delay_data # 有時候是直接 List

            for t in delay_list:
                delays[t['TrainNo']] = t.get('DelayTime', 0)
            
            log(f"誤點資訊下載成功，共 {len(delays)} 筆")

            processed = []
            
            # 開始處理資料
            # V3 OD 介面回傳的結構通常是: { "TrainTimetables": [ { "TrainInfo": {...}, "StopTimes": [...] } ] }
            raw_list = timetable_data.get('TrainTimetables', [])
            
            for item in raw_list:
                # V3 欄位名稱防呆處理
                info = item.get('TrainInfo', {})
                no = info.get('TrainNo')
                raw_type = info.get('TrainTypeName', {}).get('Zh_tw', '')
                
                # 找出出發和抵達時間
                # OD API 回傳的 StopTimes 通常只有起點和終點兩個，或者包含中間站
                # 我們需要找到符合 start_id 和 end_id 的時間
                stop_times = item.get('StopTimes', [])
                
                dep_time = None
                arr_time = None
                
                for stop in stop_times:
                    s_id = stop.get('StationID')
                    if s_id == start_id:
                        dep_time = stop.get('DepartureTime')
                    elif s_id == end_id:
                        arr_time = stop.get('ArrivalTime')
                
                if not dep_time or not arr_time:
                    continue # 找不到時間就跳過

                # --- 名稱簡化與顏色 (沿用你的邏輯) ---
                display_type = raw_type
                type_color = "#ffffff" 
                if "區間快" in raw_type: display_type, type_color = "區間快", "#0076B2"
                elif "區間" in raw_type: display_type, type_color = "區間車", "#0076B2"
                elif "普悠瑪" in raw_type: display_type, type_color = "普悠瑪", "#9C1637"
                elif "3000" in raw_type: display_type, type_color = "自強3000", "#85a38f"
                elif "自強" in raw_type: display_type, type_color = "自強號", "#DF3F1F"
                elif "太魯閣" in raw_type: display_type, type_color = "太魯閣", "#9C1637"

                delay = delays.get(no, 0)

                dep_dt = datetime.strptime(f"{today_str} {dep_time}", "%Y-%m-%d %H:%M")
                arr_dt = datetime.strptime(f"{today_str} {arr_time}", "%Y-%m-%d %H:%M")
                real_dep = dep_dt + timedelta(minutes=delay)
                real_arr = arr_dt + timedelta(minutes=delay)

                # 顯示 10 分鐘前到今天的車
                if real_dep > now - timedelta(minutes=10):
                    processed.append({
                        "no": no, "type": display_type, "delay": delay, "color": type_color,
                        "act_dep": real_dep.strftime("%H:%M"),
                        "act_arr": real_arr.strftime("%H:%M"),
                        "sch_dep": dep_time, "sch_arr": arr_time,
                        "sort_key": real_dep
                    })
            
            result = sorted(processed, key=lambda x: x['sort_key'])
            log(f"資料處理完成，共有 {len(result)} 班符合條件的列車")
            return result

        except Exception as e:
            log(f"❌ 發生異常: {e}")
            import traceback
            traceback.print_exc() # 印出詳細錯誤位置
            return []

    def generate_html(self, data):
        log("正在產生 HTML...")
        html_template = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
            <meta http-equiv="Pragma" content="no-cache">
            <meta http-equiv="Expires" content="0">
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <meta http-equiv="refresh" content="10">
            <title>列車時刻 (V3測試)</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .update-time { color: #999999; font-size: 0.65rem; text-align: right; margin-bottom: 8px; }
                .header { padding: 0 5px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
                .card { background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; position: relative; transition: transform 0.1s; }
                .card:active { background: #1c1c1e; transform: scale(0.97); }
                .delay-badge { position: absolute; top: 12px; right: 16px; border: 1px solid hsl(40, 100%, 50%); color: hsl(40, 100%, 50%); padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; }
                .train-info { font-size: 0.82rem; font-weight: 700; margin-bottom: 2px; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 700; padding: 4px 0; }
                .arrow { margin: 0 12px; color: #999999; font-size: 0.8rem; }
                .sub-time { text-align: center; color: #999999; font-size: 0.7rem; }
                a { text-decoration: none; color: inherit; -webkit-tap-highlight-color: transparent; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="update-time">上次更新時間：""" + datetime.now().strftime("%H:%M:%S") + """</div>
                <div class="header">
                    <h1 style="margin:0; font-size:1.3rem;">""" + START_STATION_NAME + """ ➔ """ + END_STATION_NAME + """</h1>
                    <span style="color: #444; font-size: 0.7rem;">V3 Test</span>
                </div>
                {% CARDS %}
            </div>
        </body>
        </html>
        """
        cards_html = ""
        for t in data:
            delay_tag = f'<div class="delay-badge">誤點 {t["delay"]} 分</div>' if t['delay'] > 0 else ""
            train_url = f"https://railway.chienwen.net/taiwan/train/TRA-{t['no']}/live"
            
            cards_html += f"""
            <a href="{train_url}" target="_blank">
                <div class="card" style="border-left-color: {t['color']};">
                    {delay_tag}
                    <div class="train-info" style="color: {t['color']};">{t['type']} {t['no']} 次</div>
                    <div class="main-time"><span>{t['act_dep']}</span><span class="arrow">➔</span><span>{t['act_arr']}</span></div>
                    <div class="sub-time">原定 {t['sch_dep']} ➔ {t['sch_arr']}</div>
                </div>
            </a>
            """
        if not data:
            cards_html = '<div style="text-align:center; padding:50px; color:#444;">目前無符合班次 (或 API 錯誤)</div>'
        
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template.replace("{% CARDS %}", cards_html))
        log("HTML 產生完成")

if __name__ == "__main__":
    app = TrainApp(CLIENT_ID, CLIENT_SECRET)
    data = app.fetch_data()
    app.generate_html(data)
