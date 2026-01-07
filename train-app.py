import requests
import json
import os
from datetime import datetime, timedelta

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_NAME = '屏東'
START_STATION_ID = '3300'  # 屏東站代碼
END_STATION_NAME = '潮州'
# =========================================

class TrainApp:
    def __init__(self, cid, csecret):
        self.cid = cid
        self.csecret = csecret
        self.token = self.get_token()

    def get_token(self):
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        res = requests.post(auth_url, data={
            'grant_type': 'client_credentials',
            'client_id': self.cid,
            'client_secret': self.csecret
        })
        return res.json().get('access_token')

    def fetch_data(self):
        headers = {'authorization': f'Bearer {self.token}'}
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        
        # --- 優化 1：只抓取屏東站的當日時刻表 ---
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today}"
        # 即時誤點還是需要全台資料，因為它是單一 API
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"

        try:
            res = requests.get(url, headers=headers).json()
            delay_res = requests.get(delay_url, headers=headers).json()
            delays = {t['TrainNo']: t.get('DelayTime', 0) for t in delay_res}

            processed = []
            for t in res:
                # --- 優化 2：提前過濾方向 ---
                # 檢查這班車的終點站方向是否包含潮州
                # (由於已經是屏東出發，只需確認後續站點有潮州)
                stop_times = t['StopTimes']
                stations = [s['StationName']['Zh_tw'].strip() for s in stop_times]

                if END_STATION_NAME in stations:
                    idx_start = stations.index(START_STATION_NAME)
                    idx_end = stations.index(END_STATION_NAME)

                    # 確保是往南（潮州方向）
                    if idx_start < idx_end:
                        no = t['DailyTrainInfo']['TrainNo']
                        
                        # --- 優化 3：時間過濾提前 ---
                        dep_s = stop_times[idx_start]['DepartureTime']
                        delay = delays.get(no, 0)
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M")
                        real_dep = dep_dt + timedelta(minutes=delay)

                        # 如果車子已經開走超過 10 分鐘，就不浪費效能處理它
                        if real_dep < now - timedelta(minutes=10):
                            continue

                        # 通過所有過濾後，才處理剩餘的 UI 邏輯
                        raw_type = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                        type_code = t['DailyTrainInfo'].get('TrainTypeCode', '6')
                        arr_s = stop_times[idx_end]['ArrivalTime']
                        
                        # 配色邏輯 (保持原樣)
                        type_color = self.get_color(raw_type)
                        display_type = self.simplify_type(raw_type)

                        processed.append({
                            "no": no, "type": display_type, "type_code": type_code, 
                            "delay": delay, "color": type_color,
                            "act_dep": real_dep.strftime("%H:%M"),
                            "act_arr": (datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M") + timedelta(minutes=delay)).strftime("%H:%M"),
                            "sch_dep": dep_s, "sch_arr": arr_s,
                            "sort_key": real_dep
                        })
            return sorted(processed, key=lambda x: x['sort_key'])
        except Exception as e:
            print(f"發生異常: {e}")
            return []

    def get_color(self, raw_type):
        if "區間" in raw_type: return "#0076B2"
        if "自強3000" in raw_type: return "#85a38f"
        if "自強" in raw_type: return "#DF3F1F"
        if "普悠瑪" in raw_type or "太魯閣" in raw_type: return "#9C1637"
        return "#ffffff"

    def simplify_type(self, raw_type):
        if "區間快" in raw_type: return "區間快"
        if "區間" in raw_type: return "區間車"
        if "3000" in raw_type: return "自強3000"
        if "自強" in raw_type: return "自強號"
        return raw_type

    def generate_html(self, data):
        # (與先前 generate_html 邏輯相同，使用您指定的 /live 連結)
        # ... (省略重複的 HTML 模板部分以節省空間) ...
        pass # 此處請保留您之前的完整 generate_html 代碼
