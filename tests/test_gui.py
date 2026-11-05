"""
Desktop app tests. They need a screen, so they only run when RUN_GUI_TESTS=1
(GitHub Actions runs them on Linux with a virtual display).
"""

import os
import time

import pytest

if os.environ.get("RUN_GUI_TESTS") != "1":
    pytest.skip("set RUN_GUI_TESTS=1 to run the desktop app tests", allow_module_level=True)

tk = pytest.importorskip("tkinter")

from conftest import oem_text  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    from tkinter import messagebox
    import converter_gui
    messages = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(messagebox, "showerror", lambda t, m: messages.append(m))
    monkeypatch.setattr(messagebox, "showwarning", lambda t, m: messages.append(m))
    monkeypatch.setattr(converter_gui.updater, "is_configured", lambda: False)  # no startup check
    root = tk.Tk()
    a = converter_gui.ConverterApp(root)
    a.messages_shown = messages
    root.update()
    yield a
    root.destroy()


def run(app):
    app._start()
    start = time.time()
    while (app.worker is not None and app.worker.is_alive()) or \
            str(app.convert_button["state"]) == "disabled":
        app.root.update()
        time.sleep(0.02)
        assert time.time() - start < 60, "conversion did not finish"
    app.root.update()
    return app.status.get()


def test_suggested_name_follows_typing_and_format(app, tmp_path):
    path = str(tmp_path / "orbit data.oem")
    for i in range(1, len(path) + 1):                 # typed one character at a time
        app.input_path.set(path[:i])
    assert app.output_path.get() == str(tmp_path / "orbit data_lla.csv")
    app.separator.set("space")
    assert app.output_path.get().endswith("_lla.txt")
    app.separator.set("nairas")
    assert app.output_path.get() == str(tmp_path / "orbit_data_nairas.txt")


def test_user_chosen_name_is_kept(app, tmp_path):
    app.input_path.set(str(tmp_path / "a.oem"))
    app.output_path.set(str(tmp_path / "mine.csv"))     # typed by the user
    app.input_path.set(str(tmp_path / "b.oem"))
    assert app.output_path.get() == str(tmp_path / "mine.csv")


def test_nairas_conversion(app, tmp_path):
    src = tmp_path / "orbit.oem"
    src.write_text(oem_text([({}, [f"2026-01-01T00:{i:02d}:00 6778.137 0 0" for i in range(10)])]))
    app.input_path.set(str(src))
    app.separator.set("nairas")
    app.step.set("120")
    assert all(w.instate(["disabled"]) for w in app.epoch_widgets)
    assert run(app).startswith("Done. Wrote 5 points")
    rows = [r for r in open(app.output_path.get()) if not r.startswith("#")]
    assert len(rows) == 5


def test_csv_input_disables_nairas(app):
    app.input_type.set("oem")
    app.separator.set("nairas")
    app.input_type.set("csv")
    app.root.update()
    assert app.separator.get() == "space"
    assert app.format_buttons["nairas"].instate(["disabled"])


def test_error_is_shown_and_no_file_written(app, tmp_path):
    src = tmp_path / "bad.csv"
    src.write_text("x,y,z\n1,abc,3\n")
    app.input_type.set("csv")
    app.input_path.set(str(src))
    assert run(app) == "Conversion failed."
    assert "not a number" in app.messages_shown[-1]
    assert not os.path.exists(app.output_path.get())


def test_output_that_is_the_input_under_another_name_is_refused(app, tmp_path):
    # The app used to compare paths as text, so on Windows and macOS "Orbit.oem"
    # and "orbit.oem" could overwrite the input. A hard link shows the same thing.
    src = tmp_path / "orbit.csv"
    src.write_text("x,y,z\n6378137,0,0\n")
    link = tmp_path / "same_file.csv"
    os.link(src, link)
    app.input_type.set("csv")
    app.input_path.set(str(src))
    app.output_path.set(str(link))
    app._start()
    assert app.worker is None
    assert "different" in app.messages_shown[-1]
    assert src.read_text() == "x,y,z\n6378137,0,0\n"


def test_folder_as_output_is_refused(app, tmp_path):
    src = tmp_path / "orbit.csv"
    src.write_text("x,y,z\n6378137,0,0\n")
    app.input_type.set("csv")
    app.input_path.set(str(src))
    app.output_path.set(str(tmp_path))
    app._start()
    assert app.worker is None
    assert "is a folder" in app.messages_shown[-1]


@pytest.mark.parametrize("step", ["nan", "inf", "-5", "abc"])
def test_bad_nairas_step_is_refused_before_starting(app, tmp_path, step):
    src = tmp_path / "orbit.oem"
    src.write_text(oem_text([({}, ["2026-01-01T00:00:00 6778.137 0 0"])]))
    app.input_path.set(str(src))
    app.separator.set("nairas")
    app.step.set(step)
    app._start()
    assert app.worker is None
    assert "time step" in app.messages_shown[-1]
