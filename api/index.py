from http.server import BaseHTTPRequestHandler
from urllib import parse
import json
import os
import time
from datetime import datetime, timedelta, timezone
import urllib.request
import urllib.error

# === 1. 車站代碼對照表 (修正版) ===
STATION_MAP = {
    # === 縱貫線北段 ===
    "基隆": "0900", "三坑": "0910", "八堵": "0920", "七堵": "0930", "百福": "0940",
    "五堵": "0950", "汐止": "0960", "汐科": "0970", "南港": "0980", "松山": "0990",
    "臺北": "1000", "萬華": "1010", "板橋": "1020", "浮洲": "1030", "樹林": "1040",
    "南樹林": "1050", "山佳": "1060", "鶯歌": "1070", "鳳鳴": "1075", "桃園": "1080", 
    "內壢": "1090", "中壢": "1100", "埔心": "1110", "楊梅": "1120", "富岡": "1130", 
    "新富": "1140", "北湖": "1150", "湖口": "1160", "新豐": "1170", "竹北": "1180", 
    "北新竹": "1190", "新竹": "1210", "三姓橋": "1220", "香山": "1230", "崎頂": "1240", 
    "竹南": "1250",

    # === 海線 ===
    "談文": "2110", "大山": "2120", "後龍": "2130", "龍港": "2140", "白沙屯": "2150",
    "新埔": "2160", "通霄": "2170", "苑裡": "2180", "日南": "2190", "大甲": "2200",
    "臺中港": "2210", "清水": "2220", "沙鹿": "2230", "龍井": "2240", "大肚": "2250",
    "追分": "2260",

    # === 山線 ===
    "造橋": "3140", "豐富": "3150", "苗栗": "3160", "南勢": "3170", "銅鑼": "3180",
    "三義": "3190", "泰安": "3210", "后里": "3220", "豐原": "3230", "栗林": "3240",
    "潭子": "3250", "頭家厝": "3260", "松竹": "3270", "太原": "3280", "精武": "3290",
    "臺中": "3300", "五權": "3310", "大慶": "3320", "烏日": "3330", "新烏日": "3340",
    "成功": "3350",

    # === 縱貫線南段 ===
    "彰化": "3360", "花壇": "3370", "大村": "3380", "員林": "3390", "永靖": "3400",
    "社頭": "3410", "田中": "3420", "二水": "3430", "林內": "3450", "石榴": "3460",
    "斗六": "3470", "斗南": "3480", "石龜": "3490", "大林": "4050", "民雄": "4060",
    "嘉北": "4070", "嘉義": "4080", "水上": "4090", "南靖": "4100", "後壁": "4110",
    "新營": "4120", "柳營": "4130", "林鳳營": "4140", "隆田": "4150", "拔林": "4160",
    "善化": "4170", "南科": "4180", "新市": "4190", "永康": "4200", "大橋": "4210",
    "臺南": "4220", "保安": "4250", "仁德": "4260", "中洲": "4270", 
    "大湖": "4280", "路竹": "4290", "岡山": "4300", "橋頭": "4310", "楠梓": "4320", 
    "新左營": "4330", "左營": "4340", "內惟": "4350", "美術館": "4360", "鼓山": "4370", 
    "三塊厝": "4380", "高雄": "4400",

    # === 屏東線 ===
    "民族": "4410", "科工館": "4420", "正義": "4430", "鳳山": "4440", "後庄": "4450", 
    "九曲堂": "4460", "六塊厝": "4470", "屏東": "5000", "歸來": "5010", "麟洛": "5020", 
    "西勢": "5030", "竹田": "5040", "潮州": "5050", "崁頂": "5060", "南州": "5070", 
    "鎮安": "5080", "林邊": "5090", "佳冬": "5100", "東海": "5110", "枋寮": "5120",

    # === 南迴線 ===
    "加祿": "5130", "內獅": "5140", "枋山": "5160", "大武": "5190", "瀧溪": "5200",
    "金崙": "5210", "太麻里": "5220", "知本": "5230", "康樂": "5240", "臺東": "6000",

    # === 臺東線 ===
    "山里": "6010", "鹿野": "6020", "瑞源": "6030", "瑞和": "6040", "關山": "6050",
    "海端": "6060", "池上": "6070", "富里": "6080", "東竹": "6090", "東里": "6100",
    "玉里": "6110", "三民": "6120", "瑞穗": "6130", "富源": "6140", "大富": "6150",
    "光復": "6160", "萬榮": "6170", "鳳林": "6180", "南平": "6190", "林榮新光": "6200",
    "豐田": "6210", "壽豐": "6220", "平和": "6230", "志學": "6240", "吉安": "6250",

    # === 北迴線/宜蘭線 ===
    "花蓮": "7000", "北埔": "7010", "景美": "7020", "新城": "7030", "崇德": "7040",
    "和仁": "7050", "和平": "7060", "漢本": "7070", "武塔": "7080", "南澳": "7090",
    "東澳": "7100", "永樂": "7110", "蘇澳": "7120", "蘇澳新": "7130", "冬山": "7140",
    "羅東": "7150", "中里": "7160", "二結": "7170", "宜蘭": "7180", "四城": "7190",
    "礁溪": "7200", "頂埔": "7210", "頭城": "7220", "外澳": "7230", "龜山": "7240",
    "大溪": "7250", "大里": "7260", "石城": "7270", "福隆": "7280", "貢寮": "7290",
    "雙溪": "7300", "牡丹": "7310", "三貂嶺": "7320", 
    "暖暖": "7390", "四腳亭": "7380", 
    "侯硐": "7350", "瑞芳": "7360", 

    # === 支線 ===
    "大華": "7331", "十分": "7332", "望古": "7333", "嶺腳": "7334", "平溪": "7335",
    "菁桐": "7336", "海科館": "7361", "八斗子": "7362",
    "千甲": "1191", "新莊": "1192", "六家": "1193", "竹中": "1194", 
    "上員": "1203", "榮華": "1204", "竹東": "1205", "橫山": "1206", "九讚頭": "1207", 
    "合興": "1208", "富貴": "1209", "內灣": "1210",
    "源泉": "3431", "濁水": "3432", "龍泉": "3433", "集集": "3434", "水里": "3435", "車埕": "3436",
    "長榮大學": "4271", "沙崙": "4272"
}

# === 2. TDX Token 管理 ===
class TDXToken:
    def __init__(self):
        self.access_token = None
        self.expires_at = 0
        # 🔴 這裡修正了：改成讀取您 Vercel 設定的環境變數名稱
        self.client_id = os.environ.get("TDX_ID")
        self.client_secret = os.environ.get("TDX_SECRET")

    def get_token(self):
        now = time.time()
        if self.access_token and now < self.expires_at - 60:
            return self.access_token

        url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        data = parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }).encode()

        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req) as response:
                resp_json = json.loads(response.read().decode())
                self.access_token = resp_json.get("access_token")
                self.expires_at = now + resp_json.get("expires_in", 86400)
                return self.access_token
        except Exception as e:
            print(f"Token Error: {e}")
            return None

token_manager = TDXToken()

# === 3. Vercel Serverless Handler ===
class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        # 1. 處理參數
        try:
            query = parse.urlparse(self.path).query
            params = parse.parse_qs(query)
            start_name = params.get('start', [''])[0]
            end_name = params.get('end', [''])[0]

            if not start_name or not end_name:
                raise ValueError("Missing start/end station")

            start_id = STATION_MAP.get(start_name)
            end_id = STATION_MAP.get(end_name)

            if not start_id or not end_id:
                raise ValueError("Invalid Station Name")

            # 2. 取得 Token
            token = token_manager.get_token()
            if not token:
                raise ConnectionError("TDX Token Failed")

            # 3. 準備時間與 API
            tz = timezone(timedelta(hours=8))
            now = datetime.now(tz)
            today_str = now.strftime('%Y-%m-%d')
            
            headers = {"Authorization": f"Bearer {token}", "Accept-Encoding": "gzip"}

            # API 1: 時刻表 (OD)
            # 抓取該區間今日所有班次
            url_schedule = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{today_str}?%24format=JSON"
            
            # API 2: 即時動態 (Live Board) - 用於取得誤點資訊
            # 針對「起點站」查詢電子看板，效率較高
            url_live = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/TrainLiveBoard/Station/{start_id}?%24format=JSON"

            # 4. 抓取資料 (平行處理概念，但 Python http.server 是同步的，依序抓取)
            schedule_data = []
            delay_map = {} # {車次號: 誤點分鐘}
            delay_failed = False

            # (A) 抓時刻表
            try:
                req = urllib.request.Request(url_schedule, headers=headers)
                with urllib.request.urlopen(req) as res:
                    schedule_data = json.loads(res.read().decode())
                    if 'TrainTimetables' in schedule_data:
                        schedule_data = schedule_data['TrainTimetables']
            except Exception as e:
                raise ConnectionError(f"Schedule API Error: {e}")

            # (B) 抓誤點資訊
            try:
                req = urllib.request.Request(url_live, headers=headers)
                with urllib.request.urlopen(req) as res:
                    live_data = json.loads(res.read().decode())
                    if 'TrainLiveBoards' in live_data:
                        for item in live_data['TrainLiveBoards']:
                            delay_map[item['TrainNo']] = item.get('DelayTime', 0)
            except Exception:
                delay_failed = True # 誤點抓失敗不應卡死，顯示時刻表即可

            # 5. 資料整合與過濾
            final_trains = []
            
            # 定義車種顏色
            def get_color(train_type_name):
                t = train_type_name
                if '普悠瑪' in t: return '#FF4081' # 粉紅
                if '太魯閣' in t: return '#FF9800' # 橘
                if '自強' in t or 'EMU3000' in t: return '#FF5722' # 深橘紅
                if '莒光' in t: return '#FFC107' # 黃
                if '區間快' in t: return '#4CAF50' # 綠
                return '#2196F3' # 區間車藍

            for train in schedule_data:
                info = train['TrainInfo']
                stop_times = train['StopTimes']
                
                # 找出起點與終點時間
                # API 回傳的 StopTimes[0] 通常就是起點，但為了保險起見還是對應一下 StationID
                dep_time_str = ""
                arr_time_str = ""
                
                for st in stop_times:
                    if st['StationID'] == start_id:
                        dep_time_str = st['DepartureTime']
                    elif st['StationID'] == end_id:
                        arr_time_str = st['ArrivalTime']
                
                if not dep_time_str or not arr_time_str:
                    continue

                train_no = info['TrainNo']
                delay = int(delay_map.get(train_no, 0))
                
                # 計算實際時間
                # 處理跨日 (雖少見但預防萬一)
                dep_dt = datetime.strptime(f"{today_str} {dep_time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                arr_dt = datetime.strptime(f"{today_str} {arr_time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                
                # 如果終點時間比起點早，代表跨日，終點加一天
                if arr_dt < dep_dt:
                    arr_dt += timedelta(days=1)

                real_dep = dep_dt + timedelta(minutes=delay)
                real_arr = arr_dt + timedelta(minutes=delay)

                # === 核心邏輯：過濾過期車次 ===
                # 規則：只保留「現在時間 - 10分鐘」之後的車
                # 例如現在 10:00，只顯示 09:50 之後發車的 (09:50 算是剛走)
                cutoff_time = now - timedelta(minutes=10)
                
                if real_dep < cutoff_time:
                    continue # 太舊了，跳過

                # 標記是否已駛離 (但還在10分鐘緩衝期內)
                is_past = real_dep < now

                # 簡化車種名稱 (去掉 (3000) 之類的雜訊)
                t_type = info['TrainTypeName']['Zh_tw'].split('(')[0]

                final_trains.append({
                    "no": train_no,
                    "type": t_type,
                    "color": get_color(t_type),
                    "delay": delay,
                    "sch_dep": dep_time_str,
                    "sch_arr": arr_time_str,
                    "act_dep": real_dep.strftime("%H:%M"),
                    "act_arr": real_arr.strftime("%H:%M"),
                    "is_past": is_past,
                    "sort_ts": real_dep.timestamp() # 用於排序
                })

            # 6. 排序 (依實際發車時間)
            final_trains.sort(key=lambda x: x['sort_ts'])

            # 7. 回傳結果
            response_data = {
                "update_time": now.strftime("%H:%M:%S"),
                "trains": final_trains,
                "delay_failed": delay_failed,
                "stats": {
                    "original_count": len(schedule_data),
                    "display_count": len(final_trains)
                },
                "diagnostics": {
                    "route_status": "API OK",
                    "delay_status": "API OK" if not delay_failed else "API Failed"
                }
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 's-maxage=10, stale-while-revalidate=59') # Vercel 快取設定
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))