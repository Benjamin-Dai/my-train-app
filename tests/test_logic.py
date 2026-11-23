import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'api'))

import index  # 不需要任何環境變數；沒有 Redis 時只會印警告

TW = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=TW)


def train(no="123", type_zh="區間車", dep="12:30", arr="13:10", flag=0, dep_flag=0, arr_flag=0):
    return {
        "TrainInfo": {"TrainNo": no, "TrainTypeName": {"Zh_tw": type_zh}, "SuspendedFlag": flag},
        "StopTimes": [
            {"StationID": "1000", "DepartureTime": dep, "SuspendedFlag": dep_flag},
            {"StationID": "1210", "ArrivalTime": arr, "SuspendedFlag": arr_flag},
        ],
    }


def process(raw, delays=None, now=NOW, date="2026-10-28", **kw):
    ctx = types.SimpleNamespace()
    out = index.handler.process_daily_list(ctx, raw, date, "1000", "1210", delays or {}, now, **kw)
    return out, getattr(ctx, 'suspended_count', 0)


class SuspendedTests(unittest.TestCase):
    def test_normal(self):
        self.assertFalse(index.is_suspended({"SuspendedFlag": 0}, {}, {}))

    def test_missing_or_garbage_flag_is_normal(self):
        self.assertFalse(index.is_suspended({}, {}, {}))
        self.assertFalse(index.is_suspended({"SuspendedFlag": "abc"}, {}, {}))

    def test_full_suspension(self):
        self.assertTrue(index.is_suspended({"SuspendedFlag": 1}, {}, {}))

    def test_partial_only_hides_when_our_stops_are_affected(self):
        info = {"SuspendedFlag": 2}
        self.assertFalse(index.is_suspended(info, {"SuspendedFlag": 0}, {"SuspendedFlag": 0}))
        self.assertTrue(index.is_suspended(info, {"SuspendedFlag": 1}, {"SuspendedFlag": 0}))
        self.assertTrue(index.is_suspended(info, {"SuspendedFlag": 0}, {"SuspendedFlag": 1}))


class AlertTests(unittest.TestCase):
    def test_normal_status_not_shown(self):
        data = {"Alerts": [{"Title": "全線營運正常", "Status": 1}]}
        self.assertEqual(index.parse_alerts(data, NOW), [])

    def test_title_says_normal_not_shown(self):
        self.assertEqual(index.parse_alerts([{"Title": "營運正常", "Status": 2}], NOW), [])

    def test_abnormal_shown(self):
        out = index.parse_alerts({"Alerts": [{"Title": "颱風停駛", "Description": "花東線", "Status": 2}]}, NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "颱風停駛")

    def test_expired_hidden(self):
        a = {"Title": "舊公告", "Status": 2, "EndTime": "2026-10-27T00:00:00+08:00"}
        self.assertEqual(index.parse_alerts([a], NOW), [])

    def test_unknown_format_is_empty(self):
        self.assertEqual(index.parse_alerts({"Alerts": "oops"}, NOW), [])
        self.assertEqual(index.parse_alerts(None, NOW), [])
        self.assertEqual(index.parse_alerts([None, 5, {}], NOW), [])

    def test_text_as_dict(self):
        out = index.parse_alerts([{"Title": {"Zh_tw": "事故", "En": "x"}, "Status": 2}], NOW)
        self.assertEqual(out[0]["title"], "事故")

    def test_only_http_urls(self):
        out = index.parse_alerts([{"Title": "t", "Status": 2, "AlertURL": "javascript:alert(1)"}], NOW)
        self.assertEqual(out[0]["url"], "")

    def test_max_five(self):
        items = [{"Title": f"t{i}", "Status": 2} for i in range(9)]
        self.assertEqual(len(index.parse_alerts(items, NOW)), 5)


class ProcessTests(unittest.TestCase):
    def test_on_time(self):
        out, _ = process([train()])
        self.assertEqual(out[0]["delay"], 0)
        self.assertEqual((out[0]["act_dep"], out[0]["act_arr"]), ("12:30", "13:10"))

    def test_delay_shifts_both_times_and_keeps_scheduled(self):
        out, _ = process([train()], {"123": 15})
        t = out[0]
        self.assertEqual((t["act_dep"], t["act_arr"]), ("12:45", "13:25"))
        self.assertEqual((t["sch_dep"], t["sch_arr"]), ("12:30", "13:10"))
        self.assertEqual(t["delay"], 15)

    def test_delay_ignored_when_more_than_six_hours_away(self):
        out, _ = process([train(dep="20:00", arr="21:00")], {"123": 30})
        self.assertEqual(out[0]["delay"], 0)

    def test_suspended_filtered_and_counted(self):
        out, n = process([train(no="1", flag=1), train(no="2")])
        self.assertEqual([t["no"] for t in out], ["2"])
        self.assertEqual(n, 1)

    def test_train_missing_a_stop_is_skipped(self):
        t = train()
        t["StopTimes"] = t["StopTimes"][:1]
        self.assertEqual(process([t])[0], [])

    def test_past_train(self):
        out, _ = process([train(dep="11:00", arr="11:40"), train(dep="11:55", arr="12:30")])
        by = {t["sch_dep"]: t["is_past"] for t in out}
        self.assertTrue(by["11:00"])
        self.assertFalse(by["11:55"])  # 10 分鐘內剛開走的還保留

    def test_delay_can_bring_a_past_train_back(self):
        out, _ = process([train(dep="11:00", arr="11:40")], {"123": 65})
        self.assertFalse(out[0]["is_past"])

    def test_arrival_after_midnight_rolls_to_next_day(self):
        now = datetime(2026, 10, 28, 23, 0, tzinfo=TW)
        out, _ = process([train(dep="23:30", arr="00:20")], now=now)
        self.assertEqual(out[0]["arr_date"], "2026-10-29")
        self.assertEqual(out[0]["dep_date"], "2026-10-28")

    def test_delay_across_midnight_changes_date(self):
        now = datetime(2026, 10, 28, 23, 0, tzinfo=TW)
        out, _ = process([train(dep="23:50", arr="23:59")], {"123": 20}, now=now)
        self.assertEqual(out[0]["act_dep"], "00:10")
        self.assertEqual(out[0]["dep_date"], "2026-10-29")

    def test_next_day_list_morning_times_belong_to_tomorrow(self):
        out, _ = process([train(dep="06:00", arr="07:00")], date="2026-10-28", fix_crossing_night=True)
        self.assertEqual(out[0]["dep_date"], "2026-10-29")

    def test_train_types(self):
        cases = {"區間快": "區間快", "區間車": "區間車", "普悠瑪": "普悠瑪", "自強3000": "自強3000",
                 "自強": "自強號", "太魯閣": "太魯閣", "莒光": "莒光號"}
        for raw, shown in cases.items():
            out, _ = process([train(type_zh=raw)])
            self.assertEqual(out[0]["type"], shown, raw)

    def test_fast_local_is_not_plain_local(self):
        self.assertEqual(process([train(type_zh="區間快")])[0][0]["type"], "區間快")


class RouteKeyTests(unittest.TestCase):
    def test_route_key_distinguishes_inputs(self):
        k = index.route_key("1000", "1210", "2026-10-28")
        self.assertNotEqual(k, index.route_key("1210", "1000", "2026-10-28"))
        self.assertNotEqual(k, index.route_key("1000", "1210", "2026-10-29"))


if __name__ == '__main__':
    unittest.main()


class EmptyRouteCacheTests(unittest.TestCase):
    """TDX 回空的時刻表不能快取 2 小時（彰化→板橋顯示「沒有直達車」）。"""

    def setUp(self):
        self.saved = []
        self._orig = (index.tdx_get, index.redis_set)
        index.redis_set = lambda k, v, ex: self.saved.append((k, v, ex))

    def tearDown(self):
        index.tdx_get, index.redis_set = self._orig

    def fake_tdx(self, body):
        calls = []
        def get(url, headers):
            calls.append(url)
            return types.SimpleNamespace(status_code=200, headers={}, json=lambda: body)
        index.tdx_get = get
        return calls

    def get(self, cached):
        ctx = types.SimpleNamespace(get_header_info=lambda res: "API", general_fallback=lambda *a: ([], None))
        return index.handler.get_route_timetable(ctx, "3360", "1020", "2026-11-23", cached, lambda: {})

    def test_empty_response_cached_short(self):
        self.fake_tdx({"TrainTimetables": []})
        raw, _ = self.get(None)
        self.assertEqual(raw, [])
        self.assertEqual(self.saved[0][2], index.EMPTY_ROUTE_CACHE_TTL)

    def test_missing_key_or_null_is_empty(self):
        self.fake_tdx({"TrainTimetables": None})
        raw, _ = self.get(None)
        self.assertEqual(raw, [])

    def test_normal_response_cached_long(self):
        self.fake_tdx({"TrainTimetables": [train()]})
        raw, _ = self.get(None)
        self.assertEqual(len(raw), 1)
        self.assertEqual(self.saved[0][2], index.ROUTE_CACHE_TTL)

    def test_old_empty_list_cache_is_ignored(self):
        calls = self.fake_tdx({"TrainTimetables": [train()]})
        raw, src = self.get(b"[]")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(raw), 1)

    def test_new_empty_marker_is_used(self):
        calls = self.fake_tdx({"TrainTimetables": [train()]})
        raw, src = self.get(b'{"empty": true}')
        self.assertEqual((raw, src, calls), ([], "Redis", []))

    def test_cached_trains_used(self):
        calls = self.fake_tdx({})
        raw, src = self.get(index.json.dumps([train()]).encode())
        self.assertEqual((len(raw), src, calls), (1, "Redis", []))


class GeneralFallbackTests(unittest.TestCase):
    """TDX 每日時刻表空掉時改用定期時刻表。"""

    def gen(self, no, stops, days=None):
        item = {"TrainInfo": {"TrainNo": no, "TrainTypeName": {"Zh_tw": "自強(推拉式自強號)"}},
                "StopTimes": [{"StationID": sid, "ArrivalTime": a, "DepartureTime": d} for sid, a, d in stops]}
        if days is not None:
            item["ServiceDay"] = days
        return item

    def test_direction_weekday_and_format(self):
        everyday = {d: 1 for d in index.WEEKDAYS}
        no_monday = dict(everyday, Monday=0)
        raw = [
            self.gen("101", [("4400", "", "08:00"), ("3360", "10:00", "10:02"), ("1020", "12:00", "12:01"), ("1000", "12:10", "")], everyday),
            self.gen("102", [("1000", "", "09:00"), ("1020", "09:08", "09:09"), ("3360", "11:00", "11:02")], everyday),  # 反方向
            self.gen("103", [("3360", "", "13:00"), ("1020", "15:00", "15:01")], no_monday),  # 週一停開
            self.gen("104", [("3360", "", "14:00"), ("1020", "16:00", "")]),  # 沒有 ServiceDay 當成每天
        ]
        packed = index.compact_general(raw)
        out = index.general_route(packed, "3360", "1020", "2026-11-23")  # 週一
        self.assertEqual([t["TrainInfo"]["TrainNo"] for t in out], ["101", "104"])
        self.assertEqual(out[0]["StopTimes"][0]["DepartureTime"], "10:02")
        self.assertEqual(out[0]["StopTimes"][1]["ArrivalTime"], "12:00")
        # 起站是始發站時沒有 ArrivalTime 也要有出發時間
        self.assertEqual(out[1]["StopTimes"][0]["DepartureTime"], "14:00")
        procd, _ = (lambda c: (index.handler.process_daily_list(c, out, "2026-11-23", "3360", "1020", {}, NOW), 0))(types.SimpleNamespace())
        self.assertEqual(len(procd), 2)

    def test_empty_daily_uses_general(self):
        saved = []
        orig = (index.tdx_get, index.redis_set)
        everyday = {d: 1 for d in index.WEEKDAYS}
        general = {"TrainTimetables": [self.gen("101", [("3360", "", "10:02"), ("1020", "12:00", "")], everyday)]}
        def get(url, headers):
            body = general if "GeneralTrainTimetable" in url else {"TrainTimetables": []}  # 起訖站和當天全部都空
            return types.SimpleNamespace(status_code=200, headers={}, json=lambda: body)
        index.tdx_get = get
        index.redis_set = lambda k, v, ex: saved.append((k, ex))
        try:
            ctx = types.SimpleNamespace(get_header_info=lambda r: "API")
            ctx.packed_timetable = lambda *a: index.handler.packed_timetable(ctx, *a)
            ctx.general_fallback = lambda *a: index.handler.general_fallback(ctx, *a)
            raw, src = index.handler.get_route_timetable(ctx, "3360", "1020", "2026-11-23", None, lambda: {})
            self.assertEqual((len(raw), src, ctx.used_general), (1, "General", True))
            self.assertIn((index.route_key("3360", "1020", "2026-11-23"), index.GENERAL_ROUTE_TTL), saved)
            # 當天全部班次也是空的：記 5 分鐘，下一條路線不用再打一次
            self.assertIn((index.DAY_ALL_KEY + "2026-11-23", index.EMPTY_PACKED_TTL), saved)
            # 快取讀回來也要標記是定期時刻表
            ctx2 = types.SimpleNamespace()
            raw2, src2 = index.handler.get_route_timetable(ctx2, "3360", "1020", "2026-11-23", index.json.dumps({"general": raw}).encode(), lambda: {})
            self.assertEqual((len(raw2), src2, ctx2.used_general), (1, "Redis/General", True))
        finally:
            index.tdx_get, index.redis_set = orig


class PackedEmptyCacheTests(unittest.TestCase):
    def test_empty_mark_skips_tdx(self):
        orig = (index.tdx_get, index.redis_client)
        index.tdx_get = lambda *a: self.fail("不該打 TDX")
        index.redis_client = types.SimpleNamespace(get=lambda k: index.EMPTY_MARK.encode())
        try:
            self.assertIsNone(index.handler.packed_timetable(types.SimpleNamespace(), "k", "u", 1, lambda: {}))
        finally:
            index.tdx_get, index.redis_client = orig

    def test_429_not_marked_empty(self):
        saved = []
        orig = (index.tdx_get, index.redis_set)
        index.tdx_get = lambda *a: types.SimpleNamespace(status_code=429, headers={})
        index.redis_set = lambda k, v, ex: saved.append(k)
        try:
            self.assertIsNone(index.handler.packed_timetable(types.SimpleNamespace(), "k", "u", 1, lambda: {}))
            self.assertEqual(saved, [])
        finally:
            index.tdx_get, index.redis_set = orig

    def test_route_key_not_shared_with_old_version(self):
        # 正式站舊版讀 v3_route_*，讀到 {"general": …} 會 500；新版不能寫到同一個 key
        self.assertFalse(index.route_key("1000", "3300", "2026-11-23").startswith("v3_route_"))


class DelayCacheTests(unittest.TestCase):
    def test_cached_delays_used_without_tdx(self):
        orig = index.tdx_get
        index.tdx_get = lambda *a: self.fail("不該打 TDX")
        try:
            d, src = index.handler.get_delays(types.SimpleNamespace(), b'{"123": 5}', lambda: {})
            self.assertEqual((d, src), ({"123": 5}, "Redis"))
        finally:
            index.tdx_get = orig


class DayAllFallbackTests(unittest.TestCase):
    def test_empty_od_uses_full_day_list_first(self):
        saved, calls = [], []
        orig = (index.tdx_get, index.redis_set)
        day = {"TrainTimetables": [
            {"TrainInfo": {"TrainNo": "111", "TrainTypeName": {"Zh_tw": "自強"}, "SuspendedFlag": 0},
             "StopTimes": [{"StationID": "3360", "DepartureTime": "10:02"}, {"StationID": "1020", "ArrivalTime": "12:00"}]},
            {"TrainInfo": {"TrainNo": "222", "TrainTypeName": {"Zh_tw": "自強"}, "SuspendedFlag": 1},
             "StopTimes": [{"StationID": "3360", "DepartureTime": "11:02"}, {"StationID": "1020", "ArrivalTime": "13:00"}]},
        ]}
        def get(url, headers):
            calls.append(url)
            body = day if "/TrainDate/" in url else {"TrainTimetables": []}
            return types.SimpleNamespace(status_code=200, headers={}, json=lambda: body)
        index.tdx_get = get
        index.redis_set = lambda k, v, ex: saved.append((k, ex))
        try:
            ctx = types.SimpleNamespace(get_header_info=lambda r: "API")
            ctx.packed_timetable = lambda *a: index.handler.packed_timetable(ctx, *a)
            ctx.general_fallback = lambda *a: index.handler.general_fallback(ctx, *a)
            raw, src = index.handler.get_route_timetable(ctx, "3360", "1020", "2026-11-23", None, lambda: {})
            self.assertEqual(([t["TrainInfo"]["TrainNo"] for t in raw], src), (["111"], "API/Daily"))
            self.assertFalse(getattr(ctx, "used_general", False))
            self.assertFalse(any("GeneralTrainTimetable" in u for u in calls))
            self.assertIn((index.route_key("3360", "1020", "2026-11-23"), index.ROUTE_CACHE_TTL), saved)
        finally:
            index.tdx_get, index.redis_set = orig
