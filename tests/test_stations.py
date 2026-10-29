import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'api'))

from stations import STATION_MAP


def load_station_data():
    """從 public/stations.js 取出 STATION_DATA（縣市 → 車站清單）。"""
    with open(os.path.join(ROOT, 'public', 'stations.js'), encoding='utf-8') as f:
        html = f.read()
    m = re.search(r"const STATION_DATA\s*=\s*\{(.*?)\n\s*\};", html, re.S)
    assert m, "找不到 STATION_DATA"
    data = {}
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(',')
        if not line:
            continue
        region, names = line.split(':', 1)
        data[json.loads(region)] = json.loads(names)
    return data


class StationTests(unittest.TestCase):
    def test_ids_are_four_digits(self):
        for name, sid in STATION_MAP.items():
            self.assertRegex(sid, r"^\d{4}$", name)

    def test_ids_are_unique(self):
        seen = {}
        for name, sid in STATION_MAP.items():
            self.assertNotIn(sid, seen, f"{name} 和 {seen.get(sid)} 站碼重複：{sid}")
            seen[sid] = name

    def test_frontend_and_backend_stations_match(self):
        front = {s for stations in load_station_data().values() for s in stations}
        back = set(STATION_MAP)
        self.assertEqual(sorted(front - back), [], "前端有、stations.py 沒有")
        self.assertEqual(sorted(back - front), [], "stations.py 有、前端沒有")

    def test_no_station_listed_twice_in_frontend(self):
        seen = set()
        for region, stations in load_station_data().items():
            for s in stations:
                self.assertNotIn(s, seen, f"{s} 在前端出現不只一次（{region}）")
                seen.add(s)

    def test_known_ids(self):
        # 曾經錯位過的站，用官方站碼釘住
        self.assertEqual(STATION_MAP['臺北'], '1000')
        self.assertEqual(STATION_MAP['新左營'], '4340')
        self.assertEqual(STATION_MAP['新馬'], '7140')


if __name__ == '__main__':
    unittest.main()
