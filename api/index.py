// 修改前端 renderCards 函式
function renderCards(data) {
    if (data.trains && data.trains.length > 0) {
        let html = `<div class="click-hint">👆 點擊卡片查看「列車即時位置」與「完整停靠站」</div>`;
        let has = false;
        let hasShownNextDayDivider = false; // 新增標記

        const nowSec = Math.floor(Date.now() / 1000);

        // 取得台灣時間的「明天凌晨 00:00」的時間戳記，用來畫分隔線
        // 這裡簡單用本地時間估算，或是比較相鄰兩班車的時間差
        let lastTrainTs = 0;

        data.trains.forEach(t => {
            const diffSec = t.sort_key - nowSec;
            const diffMin = Math.floor(diffSec / 60);

            let isDeparted = diffSec < 0; 
            let isArriving = !isDeparted && diffMin <= 10;

            if (!isShowAll && diffMin < -10) return;
            
            // === 新增：跨日分隔線 ===
            // 如果這班車的時間 比 上一班車 晚了超過 4 小時 (且不是第一筆)，視為隔日
            // 或者簡單點：如果上一班是 23:xx，這班是 00:xx ~ 06:xx
            if (has && !hasShownNextDayDivider) {
                const thisDate = new Date(t.sort_key * 1000);
                const lastDate = new Date(lastTrainTs * 1000);
                if (thisDate.getDate() !== lastDate.getDate()) {
                     html += `<div style="text-align:center; padding:10px 0; color:#4d7f5e; font-size:0.8rem; font-weight:bold; border-top:1px dashed #333; margin-top:10px;">⬇ 次日班次 ⬇</div>`;
                     hasShownNextDayDivider = true;
                }
            }
            lastTrainTs = t.sort_key;
            // ======================

            has = true;

            // ... (後面產生卡片的程式碼維持不變) ...