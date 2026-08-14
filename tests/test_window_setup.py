"""Drive DeskPetApp._build with a stub Tk — asserts always-on-top and default whale."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class _FakeCanvas:
    def __init__(self, _master, **_kwargs) -> None:
        self.ops = []

    def pack(self, **_kwargs) -> None:
        return None

    def bind(self, *_args, **_kwargs) -> None:
        return None

    def delete(self, *_args) -> None:
        self.ops.append("delete")

    def create_rectangle(self, *args, **kwargs) -> None:
        self.ops.append(("rect", args, kwargs))

    def create_oval(self, *args, **kwargs) -> None:
        self.ops.append(("oval", args, kwargs))

    def create_polygon(self, *args, **kwargs) -> None:
        self.ops.append(("poly", args, kwargs))

    def create_line(self, *args, **kwargs) -> None:
        self.ops.append(("line", args, kwargs))


class _FakeTk:
    TclError = RuntimeError

    def __init__(self) -> None:
        self._attrs = {}
        self.overridden = False
        self.bound = []
        self.geometry_value = ""
        self.title_value = ""

    def title(self, value: str) -> None:
        self.title_value = value

    def geometry(self, value: str) -> None:
        self.geometry_value = value

    def overrideredirect(self, value: bool) -> None:
        self.overridden = bool(value)

    def attributes(self, key, value=None):
        if value is None:
            return self._attrs.get(key, 0)
        self._attrs[key] = value
        return value

    def configure(self, **_kwargs) -> None:
        return None

    def bind(self, seq, _fn) -> None:
        self.bound.append(seq)

    def update_idletasks(self) -> None:
        return None

    def update(self) -> None:
        return None

    def winfo_width(self) -> int:
        return 168

    def winfo_height(self) -> int:
        return 188

    def winfo_x(self) -> int:
        return 80

    def winfo_y(self) -> int:
        return 80

    def destroy(self) -> None:
        return None


class WindowSetupTests(unittest.TestCase):
    def test_build_is_topmost_borderless_default_whale(self) -> None:
        fake_tk = types.ModuleType("tkinter")
        fake_root = _FakeTk()

        def _tk_ctor() -> _FakeTk:
            return fake_root

        fake_tk.Tk = _tk_ctor  # type: ignore[attr-defined]
        fake_tk.TclError = RuntimeError  # type: ignore[attr-defined]
        fake_tk.Canvas = _FakeCanvas  # type: ignore[attr-defined]
        sys.modules["tkinter"] = fake_tk

        from dsh_desk_pet.app import DeskPetApp
        from dsh_desk_pet.runtime import PetRuntime

        app = DeskPetApp(PetRuntime())
        app._build()
        self.assertTrue(fake_root.overridden)
        self.assertEqual(int(fake_root.attributes("-topmost")), 1)
        self.assertTrue(app.always_on_top())
        self.assertEqual(app.painted_skin, "whale")
        self.assertEqual(app.painted_state, "idle")
        self.assertGreater(len(fake_root.geometry_value), 0)

        state = app.select_skin("nautilus")
        self.assertEqual(state, "idle")
        self.assertEqual(app.painted_skin, "nautilus")
        self.assertEqual(app.painted_state, "idle")


if __name__ == "__main__":
    unittest.main()
