"""Тесты универсального коннектора. Запуск: python -m pytest connectors/tests -q (сервер не нужен)."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lawdesk_connect as lc  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "примеры"


@pytest.fixture(autouse=True)
def no_retry_pauses(monkeypatch):
    import lawdesk_client
    monkeypatch.setattr(lc, "RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(lawdesk_client, "RETRY_DELAYS", (0, 0))


# --- шаблоны и фильтры ---------------------------------------------------------------------

@pytest.mark.parametrize("tpl,row,expected", [
    ("{a}", {"a": " x "}, "x"),
    ("{a|money}", {"a": "1 200 000,50 руб."}, "1200000.50"),
    ("{a|kopecks}", {"a": "12345"}, "123.45"),
    ("{a|date}", {"a": "15.03.2027"}, "2027-03-15"),
    ("{a|date}", {"a": "0001-01-01T00:00:00"}, ""),
    ("{a|date:%Y%m%d}", {"a": "20270315"}, "2027-03-15"),
    ("{a|upper|trim}", {"a": " ab "}, "AB"),
    ("{a|default:нет}", {"a": ""}, "нет"),
    ("{нет такой|default:—}", {}, "—"),
    ("{a|first}", {"a": "Иванов; Петров"}, "Иванов"),
    ("{a|digits}", {"a": "№ 2-101/27"}, "210127"),
    ("{a|replace:АВт=>АВТ}", {"a": "АВт401"}, "АВТ401"),
    ("{a|bool}", {"a": "Да"}, "true"),
    ("{суд.код}", {"суд": {"код": "123"}}, "123"),
    ("{СУД.Код}", {"суд": {"код": "123"}}, "123"),
    ("{a} / {b}", {"a": "1", "b": "2"}, "1 / 2"),
    ("{a|map:m}", {"a": "x"}, "икс"),
    ("{a|map:m}", {"a": "y"}, "прочее"),
])
def test_render(tpl, row, expected):
    assert lc.render(tpl, row, {"m": {"x": "икс", "*": "прочее"}}) == expected


def test_render_errors():
    with pytest.raises(KeyError):
        lc.render("{нет}", {}, {})
    assert lc.render("{нет}", {}, {}, strict=False) == ""
    with pytest.raises(ValueError):
        lc.render("{a|money}", {"a": "много"}, {})
    with pytest.raises(lc.ConfigError):
        lc.render("{a|неизвестный}", {"a": "1"}, {})


# --- файл настроек -------------------------------------------------------------------------

def write(tmp_path, text, name="n.toml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_config_errors(tmp_path):
    base = '[connector]\nname = "x"\n'
    with pytest.raises(lc.ConfigError, match="delimiter"):
        lc.load_config(write(tmp_path, base + '[source]\ntype = "csv"\npath = "a"\ndelimeter = ";"\n[cases]\nuid = "{a}"\n'))
    with pytest.raises(lc.ConfigError, match="неизвестный раздел"):
        lc.load_config(write(tmp_path, base + "[sorce]\n"))
    with pytest.raises(lc.ConfigError, match="что делать с данными"):
        lc.load_config(write(tmp_path, base + '[source]\ntype = "csv"\npath = "a"\n'))
    with pytest.raises(lc.ConfigError, match="ошибка в записи"):
        lc.load_config(write(tmp_path, base + "[maps.юрлица]\n"))
    with pytest.raises(lc.ConfigError, match="name"):
        lc.load_config(write(tmp_path, "[connector]\n"))


@pytest.mark.parametrize("example", sorted(p.name for p in EXAMPLES.glob("*.toml")))
def test_examples_are_valid(example):
    """Все примеры из папки «примеры» читаются без ошибок — их копируют как образец."""
    lc.load_config(EXAMPLES / example)


# --- источники -----------------------------------------------------------------------------

def test_csv_example_maps_rows():
    cfg = lc.load_config(EXAMPLES / "csv.toml")
    rows = list(lc.read_rows(cfg["source"], EXAMPLES))
    assert len(rows) == 2  # черновик отфильтрован only_if
    m = lc.map_row(cfg, rows[0])
    assert m["case"]["legal_entity"] == "ГС-Саввино" and m["case"]["aliases"] == ["М-55/2027"]
    assert m["case"]["responsible"] == "ivanova"
    obs = {o["field"]: o["value"] for o in m["observations"]}
    assert obs["claim_total"] == "900000.00" and obs["decision_date"] == "2027-03-15"
    m2 = lc.map_row(cfg, rows[1])
    assert "uid" not in m2["case"] and m2["observations"][0]["case_number"] == "2-202/2027"
    assert "amount_penalty" not in {o["field"] for o in m2["observations"]}  # пустые не отправляются


def test_xlsx_json_folder_calendar_examples():
    for name in ("xlsx", "json", "папка_документов", "календарь_csv"):
        cfg = lc.load_config(EXAMPLES / f"{name}.toml")
        lc.check_templates(cfg, EXAMPLES)
        rows = list(lc.read_rows(cfg["source"], EXAMPLES))
        assert rows, name
        lc.map_row(cfg, rows[0])
    xr = list(lc.read_rows(lc.load_config(EXAMPLES / "xlsx.toml")["source"], EXAMPLES))
    assert xr[0]["Дата решения"] == "2027-03-15"
    doc = lc.map_row(lc.load_config(EXAMPLES / "папка_документов.toml"),
                     next(lc.read_rows({"type": "folder", "path": "данные/документы", "pattern": "*.pdf"}, EXAMPLES)))["document"]
    assert doc["act_type"] == "решение" and doc["case"] == {"uid": "50RS0010-01-2027-000101-11"} and doc["_file"].endswith(".pdf")


def test_sqlite(tmp_path):
    import sqlite3
    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    con.execute("create table t(uid, judge)")
    con.execute("insert into t values ('U1', 'Иванова')")
    con.commit()
    con.close()
    rows = list(lc.read_rows({"type": "sqlite", "path": str(db), "query": "select * from t"}, tmp_path))
    assert rows == [{"uid": "U1", "judge": "Иванова"}]


@pytest.fixture
def mock_server():
    """Эмулятор: OData с постраничной выдачей и HTTP-сервис с next; запоминает POST."""
    received = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            from urllib.parse import parse_qsl, unquote, urlparse
            u = urlparse(self.path)
            q = dict(parse_qsl(u.query))
            if self.headers.get("Authorization") is None:
                return self._send({"e": 1}, 401)
            if unquote(u.path).endswith("/Catalog_Дела"):
                data = [{"Ref_Key": str(i)} for i in range(5)]
                top, skip = int(q["$top"]), int(q["$skip"])
                return self._send({"value": data[skip:skip + top]})
            page = int(q.get("page", 1))
            nxt = f"http://127.0.0.1:{self.server.server_port}/x?page={page + 1}" if page < 3 else None
            return self._send({"items": [{"n": page}], "next": nxt})

        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self._send({"ok": True})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", received
    srv.shutdown()


def test_odata_and_http_paging(mock_server, monkeypatch):
    url, _ = mock_server
    monkeypatch.setenv("PW", "p")
    rows = list(lc.read_rows({"type": "odata", "url": url, "entity": "Catalog_Дела", "page_size": 2,
                              "user": "u", "password_env": "PW"}, Path(".")))
    assert [r["Ref_Key"] for r in rows] == ["0", "1", "2", "3", "4"]
    rows = list(lc.read_rows({"type": "http_json", "url": url + "/x", "items_path": "items", "next_path": "next",
                              "user": "u", "password_env": "PW"}, Path(".")))
    assert [r["n"] for r in rows] == [1, 2, 3]
    with pytest.raises(lc.LinkError, match="401"):
        list(lc.read_rows({"type": "odata", "url": url, "entity": "Catalog_Дела"}, Path(".")))


# --- выгрузка наружу ----------------------------------------------------------------------

class FakeLawdesk:
    """Лента из трёх событий, одна страница; дело с УИД."""

    def __init__(self):
        self.events = [{"id": i, "feed_seq": i, "action": "value_resolved", "case_id": 7, "actor": "ivanova", "ts": "2027-01-0%dT10:00:00Z" % i,
                        "data": {"field": "judge", "after": {"value": f"Судья {i}"}, "before": {"value": None}, "note": "н"}} for i in (1, 2, 3)]
        self.events.append({"id": 4, "feed_seq": 4, "action": "task_done", "case_id": None, "actor": "svc", "ts": "2027-01-05T00:00:00Z", "data": {}})

    def request(self, method, path, *a, **k):
        return [{"key": "judge", "label": "Судья"}]

    def changes(self, after, actions, limit=500):
        items = [e for e in self.events if e["feed_seq"] > after]
        return {"items": items, "next_cursor": items[-1]["feed_seq"] if items else after}

    def get_case(self, cid):
        return {"uid": "U7", "case_number": "2-7/27"}


def test_out_csv_and_cursor(tmp_path):
    cfg = lc.load_config(write(tmp_path, """
[connector]
name = "т"
direction = "out"
[feed]
state_file = "курсор.txt"
[sink]
type = "csv"
path = "out.csv"
mode = "append"
[sink.columns]
"УИД" = "{case.uid}"
"Поле" = "{field_label}"
"Значение" = "{value}"
"Кто" = "{actor}"
"""))
    ld = FakeLawdesk()
    lc.run_out(cfg, tmp_path, ld, None, dry=False)
    lines = (tmp_path / "out.csv").read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "УИД;Поле;Значение;Кто" and lines[1] == "U7;Судья;Судья 1;ivanova"
    assert lines[4] == ";;;svc"  # событие без дела — пустые ячейки, не ошибка
    assert (tmp_path / "курсор.txt").read_text() == "4"
    lc.run_out(cfg, tmp_path, ld, None, dry=False)  # повтор — без новых строк
    assert len((tmp_path / "out.csv").read_text(encoding="utf-8-sig").splitlines()) == 5


def test_out_http_failure_keeps_cursor(tmp_path, mock_server):
    url, received = mock_server
    text = f"""
[connector]
name = "т"
direction = "out"
[feed]
state_file = "к.txt"
[sink]
type = "http"
url = "{url}/in"
"""
    cfg = lc.load_config(write(tmp_path, text))
    lc.run_out(cfg, tmp_path, FakeLawdesk(), None, dry=False)
    assert len(received[0]["items"]) == 4 and received[0]["source"] == "lawdesk"
    bad = lc.load_config(write(tmp_path, text.replace(url, "http://127.0.0.1:1").replace("к.txt", "плохой.txt"), "b.toml"))
    with pytest.raises(lc.LinkError):
        lc.run_out(bad, tmp_path, FakeLawdesk(), None, dry=False)
    assert not (tmp_path / "плохой.txt").exists()


# --- надёжность (аудит) ------------------------------------------------------------------

def test_csv_cp1251_and_datetime(tmp_path):
    (tmp_path / "a.csv").write_bytes("Дата;Сумма\n2027-01-01 00:00:00;1 234,5\n".encode("cp1251"))
    rows = list(lc.read_rows({"type": "csv", "path": "a.csv"}, tmp_path))
    assert rows[0]["Дата"] == "2027-01-01 00:00:00"
    assert lc.render("{Дата|date}", rows[0], {}) == "2027-01-01"
    assert lc.render("{Сумма|money}", rows[0], {}) == "1234.50"
    with pytest.raises(lc.ConfigError, match="кодировке"):
        list(lc.read_rows({"type": "csv", "path": "a.csv", "encoding": "utf-8"}, tmp_path))


def test_empty_reference_message():
    with pytest.raises(KeyError, match="не заполнено"):
        lc.render("{Суд.Code}", {"Суд": None}, {})


def test_cursor_file_corrupt_is_error(tmp_path):
    (tmp_path / "к.txt").write_text("")
    cfg = lc.load_config(write(tmp_path, OUT_CSV))
    with pytest.raises(lc.ConfigError, match="испорчен"):
        lc.run_out(cfg, tmp_path, FakeLawdesk(), None, dry=False)


OUT_CSV = """
[connector]
name = "т"
direction = "out"
[feed]
state_file = "к.txt"
[sink]
type = "csv"
path = "out.csv"
[sink.columns]
"Значение" = "{value}"
"""


def test_csv_new_does_not_overwrite_unclaimed_file(tmp_path):
    (tmp_path / "out.csv").write_text("вчерашнее", encoding="utf-8")
    cfg = lc.load_config(write(tmp_path, OUT_CSV))
    lc.run_out(cfg, tmp_path, FakeLawdesk(), None, dry=False)
    assert (tmp_path / "out.csv").read_text(encoding="utf-8") == "вчерашнее"
    assert len(list(tmp_path.glob("out_*.csv"))) == 1


def test_out_cursor_saved_per_portion(tmp_path):
    class Paged(FakeLawdesk):
        def changes(self, after, actions, limit=500):
            items = [e for e in self.events if e["feed_seq"] > after][:2]  # по 2 события
            return {"items": items, "next_cursor": items[-1]["feed_seq"] if items else after}

    calls = []

    class Broken(lc.SinkWriter):
        def write(self, rows, ids):
            calls.append(ids)
            if len(calls) == 2:
                raise lc.LinkError("обрыв")
            super().write(rows, ids)

    cfg = lc.load_config(write(tmp_path, OUT_CSV))
    orig, lc.SinkWriter = lc.SinkWriter, Broken
    try:
        with pytest.raises(lc.LinkError):
            lc.run_out(cfg, tmp_path, Paged(), None, dry=False)
    finally:
        lc.SinkWriter = orig
    assert (tmp_path / "к.txt").read_text() == "2"  # первая порция записана и учтена, вторая — нет
    lc.run_out(cfg, tmp_path, Paged(), None, dry=False)
    assert (tmp_path / "к.txt").read_text() == "4"


def test_temporary_case_error_does_not_move_cursor(tmp_path):
    class Flaky(FakeLawdesk):
        def get_case(self, cid):
            raise lc.LawdeskError(503, "перезапуск")

    cfg = lc.load_config(write(tmp_path, OUT_CSV))
    with pytest.raises(lc.LawdeskError):
        lc.run_out(cfg, tmp_path, Flaky(), None, dry=False)
    assert not (tmp_path / "к.txt").exists()


def test_http_sink_sends_event_ids(tmp_path, mock_server):
    url, received = mock_server
    cfg = lc.load_config(write(tmp_path, f"""
[connector]
name = "т"
direction = "out"
[sink]
type = "http"
url = "{url}/in"
"""))
    lc.run_out(cfg, tmp_path, FakeLawdesk(), None, dry=False)
    assert received[-1]["ids"] == [1, 2, 3, 4]


def test_run_lock(tmp_path):
    with lc.RunLock(tmp_path / "x.замок"):
        with pytest.raises(lc.AlreadyRunning):
            with lc.RunLock(tmp_path / "x.замок"):
                pass
    with lc.RunLock(tmp_path / "x.замок"):  # после выхода замок свободен
        pass


def test_batch_with_bad_item_is_split(monkeypatch):
    import lawdesk_client as cl
    sent = []

    def fake(self, method, path, body=None, **kw):
        sent.append(len(body))
        if any(x.get("bad") for x in body):
            raise cl.LawdeskError(422, [{"loc": ["body", 0, "act_date"], "msg": "Input should be a valid date", "input": "01.02.2027"}])
        return [{"index": i, "ok": True} for i in range(len(body))]

    monkeypatch.setattr(cl.Lawdesk, "request", fake)
    ld = cl.Lawdesk("http://x", "k")
    res = ld.documents([{"n": i, "bad": i == 5} for i in range(8)])
    assert [r["ok"] for r in res] == [True] * 5 + [False] + [True] * 2
    assert "act_date" in res[5]["error"] and "01.02.2027" in res[5]["error"]


def test_unexpected_error_exit_code(tmp_path):
    (tmp_path / "a.json").write_text("{ сломано", encoding="utf-8")
    write(tmp_path, """
[connector]
name = "т"
[source]
type = "json"
path = "a.json"
[cases]
uid = "{uid}"
""", "c.toml")
    assert lc.main(["x", "проверить", str(tmp_path / "c.toml")]) == lc.EXIT_UNEXPECTED
    assert lc.main(["x", "проверить", str(tmp_path / "c.toml"), "--limit"]) == lc.EXIT_CONFIG


def test_connector_timeout_batch_retry_settings(tmp_path, monkeypatch):
    base = '[connector]\nname = "т"\ndirection = "out"\n[sink]\ntype = "csv"\npath = "o.csv"\n'
    cfg = lc.load_config(write(tmp_path, base.replace('direction', 'timeout = 300\nbatch = 50\nretry_delays = [1, 2]\ndirection')))
    monkeypatch.setenv("LAWDESK_KEY", "ldk_x_y")
    monkeypatch.delenv("LAWDESK_URL", raising=False)
    ld = lc.client({**cfg, "connector": {**cfg["connector"], "api_url": "http://127.0.0.1:1"}}, tmp_path)
    assert ld.batch == 50 and ld.timeout == 300
    with pytest.raises(lc.ConfigError, match="положительное число"):
        lc.load_config(write(tmp_path, base.replace('direction', 'timeout = "300"\ndirection'), "b.toml"))
    with pytest.raises(lc.ConfigError, match="retry_delays"):
        lc.load_config(write(tmp_path, base.replace('direction', 'retry_delays = 5\ndirection'), "c.toml"))
