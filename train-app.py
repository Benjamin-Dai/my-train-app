        # 取得今天日期並格式化為 YYYY/MM/DD
        ride_date = datetime.now().strftime("%Y/%m/%d")

        for t in data:
            delay_tag = f'<div class="delay-badge">誤點 {t["delay"]} 分</div>' if t['delay'] > 0 else ""
            
            # 修正後的台鐵查詢連結：加入 rideDate 參數
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
