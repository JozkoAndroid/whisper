from hlas.hotkey import HotkeyMachine, parse_combo, win_vk_tokens


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def make():
    log = []
    clock = Clock()
    m = HotkeyMachine(
        parse_combo("ctrl+win"),
        on_start=lambda: log.append("start"),
        on_stop=lambda: log.append("stop"),
        on_cancel=lambda: log.append("cancel"),
        on_lang=lambda l: log.append(f"lang:{l}"),
        on_lock=lambda: log.append("lock"),
        clock=clock,
    )
    return m, log, clock


CTRL, WIN = {"ctrl", "ctrl_l"}, {"cmd", "cmd_l"}


def test_parse_combo():
    assert parse_combo("Ctrl+Win") == ["ctrl", "cmd"]
    assert parse_combo("") == ["ctrl", "cmd"]
    assert parse_combo("f9") == ["f9"]


def test_hold_to_talk():
    m, log, _ = make()
    m.down(CTRL)
    assert log == []
    m.down(WIN)
    m.down(WIN)  # auto-repeat ignored
    assert log == ["start"]
    m.up(WIN)
    assert log == ["start", "stop"]
    m.up(CTRL)
    assert log == ["start", "stop"]


def test_lock_then_tap_to_stop():
    m, log, clock = make()
    m.down(CTRL); m.down(WIN)
    assert m.down({"space"}) is True  # swallowed
    assert m.up({"space"}) is True
    m.up(WIN); m.up(CTRL)
    assert log == ["start", "lock"]
    clock.t = 5
    m.down(CTRL); m.down(WIN)  # pressing the combo again while locked
    m.down({"2"})  # language switch, not a stop
    m.up({"2"}); m.up(WIN); m.up(CTRL)
    assert log == ["start", "lock", "lang:de"]
    m.down(CTRL); m.down(WIN); m.up(WIN); m.up(CTRL)
    assert log[-1] == "stop"


def test_language_keys_while_holding():
    m, log, clock = make()
    m.down(CTRL); m.down(WIN)
    clock.t = 2
    assert m.down({"1"}) is True
    m.up({"1"})
    m.down({"3"}); m.up({"3"})
    m.down({"0"}); m.up({"0"})
    m.up(WIN)
    assert log == ["start", "lang:sk", "lang:en", "lang:auto", "stop"]


def test_other_shortcut_cancels_fresh_recording():
    m, log, clock = make()
    m.down(CTRL); m.down(WIN)
    clock.t = 0.2
    assert m.down({"d"}) is False  # Ctrl+Win+D passes through
    assert log == ["start", "cancel"]
    m.up({"d"}); m.up(WIN); m.up(CTRL)
    assert log == ["start", "cancel"]


def test_escape_cancels():
    m, log, clock = make()
    m.down(CTRL); m.down(WIN); m.down({"space"}); m.up({"space"}); m.up(WIN); m.up(CTRL)
    m.down({"esc"})
    assert log == ["start", "lock", "cancel"]


def test_plain_digits_pass_through_when_idle():
    m, log, _ = make()
    assert m.down({"1"}) is False
    assert log == []


def test_win_vk_tokens():
    assert win_vk_tokens(0xA2) == {"ctrl", "ctrl_l"}
    assert win_vk_tokens(0x32) == {"2"}
    assert win_vk_tokens(0x62) == {"2"}
    assert win_vk_tokens(0x44) == {"d"}
    assert win_vk_tokens(0x78) == {"f9"}
