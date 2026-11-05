import io
import zipfile

from copytrading.actualizar import apply_zip


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Blockchain_IOT-rama/", "")
        for k, v in files.items():
            zf.writestr(f"Blockchain_IOT-rama/{k}", v)
    return buf.getvalue()


def test_updates_code_but_never_data(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "hft_flujo.csv").write_text("mis datos")
    (tmp_path / "copytrading").mkdir()
    (tmp_path / "copytrading" / "escucha.py").write_text("vieja")
    data = _zip({"copytrading/escucha.py": b"nueva", "copytrading/nuevo.py": b"x",
                 "data/hft_flujo.csv": b"BORRADO", "windows/escuchar_hft.bat": b"bat nuevo",
                 "windows/LEEME_ESCUCHA.md": b"guia", "docs/x.md": b"no"})
    changed = apply_zip(data, tmp_path)
    assert sorted(changed) == ["copytrading/escucha.py", "copytrading/nuevo.py", "windows/LEEME_ESCUCHA.md"]
    assert (tmp_path / "data" / "hft_flujo.csv").read_text() == "mis datos"
    assert not (tmp_path / "windows" / "escuchar_hft.bat").exists()
    assert apply_zip(data, tmp_path) == []          # segunda vez: ya al día
