    def generate_html(self, data):
        # 這裡不能有空格在最前面，要跟下面的 html_template 對齊
        ride_date = datetime.now().strftime("%Y/%m/%d")
        
        html_template = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
            <meta http-equiv="Pragma" content="no-cache">
            <meta http-equiv="Expires" content="0">
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <meta http-equiv="refresh" content="30">
            <title>列車時刻</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .update-time { color: #999999; font-size: 0.65rem; text-align: right; margin-bottom: 8px; }
                .header { padding: 0 5px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
                .card { background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; position: relative; transition: transform 0.1s, background 0.1s; }
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
                    <span style="color: #444; font-size: 0.7rem;">by Benjamin Dai</span>
                </div>
                {% CARDS %}
            </div>
        </body>
        </html>
        """
        cards_html = ""
        for t in data:
            delay_tag = f'<div class="delay-badge">誤點 {t["delay"]} 分</div>' if t['delay'] > 0 else ""
            # 這裡會帶入上面定義好的 ride_date
            train_url = f"https://www.railway.gov.tw/tra-tip-web/tip/tip001/tip112/querybytrainno?trainNo={t['no']}&rideDate={ride_date}"
            
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
            cards_html = '<div style="text-align:center; padding:50px; color:#444;">目前無符合班次</div>'
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template.replace("{% CARDS %}", cards_html))
