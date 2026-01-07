import requests
import json
import os
from datetime import datetime, timedelta

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
# 為了避免 ID 錯誤，我們還是用最保險的屏東站 ID
START_STATION_ID = '5000' 
END_STATION_NAME = '潮州'
# =========================================

class TrainApp:
    def __init__(self, cid, csecret):
        self.cid = cid
        self.csecret = csecret
        self.token = self.get_token()

    def get_token(self):
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        try:
            res = requests.post(auth_url, data={
                'grant_type': 'client_credentials',
                'client_id': self.cid,
                'client_secret': self.csecret
            })
            if res.status_code != 200:
                print("Token 取得失敗")
                return None
            return res.json().get('access_token')
        except:
            return None

    def fetch_data(self):
        if not self.token: return []
        
        headers = {'authorization': f'Bearer {self.token}'}
        
        # --- 手動校正時間 (最穩定的寫法) ---
        # GitHub 伺服器是 UTC，我們直接 +8 小時變台灣時間
        utc_now = datetime.utcnow()
        taiwan_now = utc_now + timedelta(hours=8)
        today_str = taiwan_now.strftime('%Y-%m-%d')
        current_time_str = taiwan_now.strftime('%H:%M')
        
        print(f"DEBUG: 系統時間(UTC): {utc_now}")
        print(f"DEBUG: 台灣時間: {taiwan_now}")
        
        # 抓時刻表
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today_str}"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"

        try:
            res = requests.get(url, headers=headers).json()
            delay_res = requests.get(delay_url, headers=headers).json()
            
            delays = {}
            if isinstance(delay_res, list):
                for t in delay_res:
                    delays[t.get('TrainNo')] = t.get('DelayTime', 0)

            processed = []
            
            # 確保有抓到資料
            if not isinstance(res, list):
                print("API 回傳異常")
                return []
            
            print(f"DEBUG: 原始資料共 {len(res)} 筆")

            for t in res:
                stop_times = t.get('StopTimes', [])
                # 簡化站名提取
                stations = []
                for s in stop_times:
                    stations.append(s['StationName']['Zh_tw'])
                
                if END_STATION_NAME in stations:
                    idx_start = stations.index('屏東') # 直接用中文名稱比較保險
                    idx_end = stations.index(END_STATION_NAME)

                    # 往潮州方向
                    if idx_start < idx_end:
                        no = t['DailyTrainInfo']['TrainNo']
                        dep_time_str = stop_times[idx_start]['DepartureTime'] # 格式 "13:00"
                        delay = delays.get(no, 0)
                        
                        # --- 最單純的時間比較邏輯 ---
                        # 因為都在同一天，我們直接比對 "HH:MM" 字串即可 (字串比對 "13:00" > "12:00" 是成立的)
                        # 但為了加上誤點，還是轉成 datetime
                        
                        train_dt = datetime.strptime(f"{today_str} {dep_time_str}", "%Y-%m-%d %H:%M")
                        actual_dt = train_dt + timedelta(minutes=delay)
                        
                        # 這裡使用台灣時間的 datetime 物件直接比較
                        # 顯示標準：只要是「現在」之後的車，全部顯示 (不設 3 小時限制，確保有車)
                        # 多減 20 分鐘當緩衝，避免剛開走的車消失
                        if actual_dt > taiwan_now - timedelta(minutes=20):
                            
                            raw_type = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                            arr_time_str = stop_times[idx_end]['ArrivalTime']
                            
                            # 簡單計算抵達時間
                            arr_dt = datetime.strptime(f"{today_str} {arr_time_str}", "%Y-%m-%d %H:%M") + timedelta(minutes=delay)

                            color = "#ffffff"
                            if "區間" in raw_type: color = "#0076B2"
                            elif "3000" in raw_type: color = "#85a38f"
                            elif "自強" in raw_type: color = "#DF3F1F"
                            elif "普悠瑪" in raw_type: color = "#9C1637"

                            processed.append({
                                "no": no, 
                                "type": raw_type.replace("自強(3000)", "自強3000"), 
                                "delay": delay, 
                                "color": color,
                                "act_dep": actual_dt.strftime("%H:%M"),
                                "act_arr": arr_dt.strftime("%H:%M"),
                                "sch_dep": dep_time_str, 
                                "sch_arr": arr_time_str,
                                "sort_key": actual_dt
                            })
            
            print(f"DEBUG: 符合條件共 {len(processed)} 筆")
            return sorted(processed, key=lambda x: x['sort_key'])
        except Exception as e:
            print(f"Error: {e}")
            return []

    def generate_html(self, data):
        # 顯示台灣時間
        utc_now = datetime.utcnow()
        taiwan_now = utc_now + timedelta(hours=8)
        update_time = taiwan_now.strftime("%H:%M:%S")

        html_template = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <meta http-equiv="refresh" content="60">
            <title>列車時刻</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .update-time { color: #999999; font-size: 0.65rem; text-align: right; margin-bottom: 8px; }
                .header { padding: 0 5px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
                .card { background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; position: relative; }
                .delay-badge { position: absolute; top: 12px; right: 16px; border: 1px solid #f2a900; color: #f2a900; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; }
                .train-info { font-size: 0.82rem; font-weight: 700; margin-bottom: 2px; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 700; padding: 4px 0; }
                .arrow { margin: 0 12px; color: #999999; font-size: 0.8rem; }
                .sub-time { text-align: center; color: #999999; font-size: 0.7rem; }
                a { text-decoration: none; color: inherit; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="update-time">最後更新：""" + update_time + """</div>
                <div class="header">
                    <h1 style="margin:0; font-size:1.3rem;">""" + "屏東" + """ ➔ """ + END_STATION_NAME + """</h1>
                </div>
                {% CARDS %}
            </div>
        </body>
        </html>
        """
        cards_html
