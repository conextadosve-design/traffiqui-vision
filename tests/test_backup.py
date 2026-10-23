"""Copias de seguridad: copia en caliente de las bases, zip y rotación."""
import sqlite3
import zipfile
from datetime import date, timedelta

from app.backup import KEEP_DAILY, BackupManager, rotate


def test_copia_y_carpeta_extra(tmp_path):
    data = tmp_path / "datos"
    data.mkdir()
    con = sqlite3.connect(data / "traffiqui.db")
    con.execute("CREATE TABLE t (x)"); con.execute("INSERT INTO t VALUES (42)"); con.commit()   # sigue abierta
    (data / "modo.json").write_text('{"modo": "tienda"}')
    bm = BackupManager(data)
    assert bm.due()
    extra = tmp_path / "usb"
    bm.set_extra_dir(str(extra))
    zip_path = bm.run_now()
    assert not bm.due()
    with zipfile.ZipFile(zip_path) as z:
        assert {"traffiqui.db", "modo.json", "LEEME.txt"} <= set(z.namelist())
        z.extract("traffiqui.db", tmp_path / "rest")
    assert sqlite3.connect(tmp_path / "rest" / "traffiqui.db").execute("SELECT x FROM t").fetchone() == (42,)
    assert (extra / zip_path.name).exists()
    st = bm.status()
    assert st["last_ok"] and st["copies"][0]["name"] == zip_path.name and st["extra_dir"] == str(extra)
    con.close()


def test_rotacion(tmp_path):
    today = date(2026, 10, 23)
    for i in range(40):
        (tmp_path / f"traffiqui-{(today - timedelta(days=i)).isoformat()}.zip").write_text("x")
    rotate(tmp_path, today)
    left = sorted(p.name for p in tmp_path.glob("*.zip"))
    assert len(left) <= KEEP_DAILY + 4
    assert f"traffiqui-{today.isoformat()}.zip" in left
    assert all(date.fromisoformat(n[10:20]) >= today - timedelta(weeks=5) for n in left)


def test_carpeta_extra_invalida(tmp_path):
    bm = BackupManager(tmp_path)
    blocker = tmp_path / "archivo"
    blocker.write_text("no soy carpeta")
    try:
        bm.set_extra_dir(str(blocker / "sub"))
    except ValueError as e:
        assert "No se puede escribir" in str(e)
    else:
        raise AssertionError("debía fallar")
