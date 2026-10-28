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
